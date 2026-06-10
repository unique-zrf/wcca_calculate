from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml


def build_input_draft(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    parameters_path = root / "work" / "normalized" / "parameters.yaml"
    candidates_path = root / "work" / "normalized" / "model_candidates.yaml"
    requirements_path = root / "work" / "extracted" / "requirements.yaml"
    if not parameters_path.exists():
        raise FileNotFoundError(f"Missing normalized parameters: {parameters_path}")
    if not candidates_path.exists():
        raise FileNotFoundError(f"Missing model candidates: {candidates_path}")
    parameters = read_yaml(parameters_path).get("parameters", [])
    candidates = read_yaml(candidates_path).get("candidates", [])
    requirements = read_yaml(requirements_path).get("requirements", []) if requirements_path.exists() else []
    parameter_map = {item["parameter_id"]: item for item in parameters}
    requirements_by_model = _requirements_by_model(requirements)
    draft = {
        "project": {
            "name": root.name,
            "document_type": "WCCA",
            "draft_generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "draft_status": "requires_engineer_completion",
        },
        "circuit_blocks": [
            _block_from_candidate(candidate, parameter_map, requirements_by_model, index)
            for index, candidate in enumerate(candidates, start=1)
        ],
        "draft_notes": [
            "This draft is generated from normalized BOM-derived parameters.",
            "Requirements, operating boundaries, datasheet-only parameters, and model selections require engineer confirmation.",
            "Do not use this draft for release until validate-input --release passes after engineering review.",
        ],
    }
    write_yaml(root / "work" / "wcca_input_draft.yaml", draft)
    return draft


def _block_from_candidate(
    candidate: dict[str, Any],
    parameter_map: dict[str, dict[str, Any]],
    requirements_by_model: dict[str, list[dict[str, Any]]],
    index: int,
) -> dict[str, Any]:
    model_id = candidate["model_id"]
    requirements = requirements_by_model.get(model_id) or [_missing_requirement(model_id)]
    block = {
        "id": f"DRAFT_{index:03d}_{model_id.upper()}",
        "name": f"Draft {model_id} analysis",
        "type": model_id,
        "component_refs": candidate.get("component_refs", []),
        "selected_model": {
            "model_id": model_id,
            "model_version": candidate.get("model_version", "1.0.0"),
            "selection_status": "requires_engineer_confirmation",
            "confidence": candidate.get("confidence"),
            "reason": candidate.get("reason"),
        },
        "requirements": requirements,
        "inputs": _inputs_for_model(model_id, candidate.get("component_refs", []), parameter_map),
        "draft_warnings": [
            "Generated from BOM-derived parameters only.",
            "Boundary conditions and datasheet parameters may be missing.",
        ],
    }
    return block


def _missing_requirement(model_id: str) -> dict[str, Any]:
    return {
        "id": f"REQ-DRAFT-{model_id}",
        "description": "Engineer must provide requirement limits before release.",
        "min_value": None,
        "max_value": None,
        "unit": None,
        "review_status": "missing",
    }


def _requirements_by_model(requirements: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    mapped: dict[str, list[dict[str, Any]]] = {}
    for requirement in requirements:
        model_id = requirement.get("model_id")
        if not model_id:
            continue
        mapped.setdefault(model_id, []).append({
            "id": requirement.get("id"),
            "description": requirement.get("description"),
            "min_value": requirement.get("min_value"),
            "max_value": requirement.get("max_value"),
            "unit": requirement.get("unit"),
            "source": requirement.get("source"),
            "review_status": requirement.get("review_status", "rule_extracted"),
        })
    return mapped


def _inputs_for_model(model_id: str, refs: list[str], parameter_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    if model_id == "resistor_divider":
        return {
            "vin_min": _missing_input("V", "requirement"),
            "vin_max": _missing_input("V", "requirement"),
            "r_top": _resistor_input(refs[0], parameter_map) if len(refs) >= 1 else {},
            "r_bottom": _resistor_input(refs[1], parameter_map) if len(refs) >= 2 else {},
        }
    if model_id == "comparator_threshold":
        return {
            "vref_min": _missing_input("V", "datasheet"),
            "vref_max": _missing_input("V", "datasheet"),
            "input_offset": _missing_input("V", "datasheet"),
            "r_top": _resistor_input(refs[0], parameter_map) if len(refs) >= 1 else {},
            "r_bottom": _resistor_input(refs[1], parameter_map) if len(refs) >= 2 else {},
        }
    if model_id == "ldo_power_rail":
        return {
            "vout_nominal": _missing_input("V", "schematic_or_requirement"),
            "output_accuracy": _missing_input("%", "datasheet"),
            "load_regulation": _missing_input("%", "datasheet"),
            "line_regulation": _missing_input("%", "datasheet"),
        }
    if model_id == "rc_delay":
        resistor_ref = next((ref for ref in refs if ref.upper().startswith("R")), "")
        cap_ref = next((ref for ref in refs if ref.upper().startswith("C")), "")
        return {
            "r": _resistor_input(resistor_ref, parameter_map) if resistor_ref else {
                "nominal": _missing_input("ohm", "bom_or_schematic"),
                "tolerance": _missing_input("%", "datasheet_or_bom"),
            },
            "c": _capacitor_input(cap_ref, parameter_map) if cap_ref else {},
            "v_initial_min": _missing_input("V", "requirement"),
            "v_initial_max": _missing_input("V", "requirement"),
            "threshold_min": _missing_input("V", "datasheet"),
            "threshold_max": _missing_input("V", "datasheet"),
        }
    return {}


def _resistor_input(ref: str, parameter_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "nominal": _parameter_record(parameter_map, f"{ref}.nominal", "ohm"),
        "tolerance": _parameter_record(parameter_map, f"{ref}.tolerance", "%"),
    }


def _capacitor_input(ref: str, parameter_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "nominal": _parameter_record(parameter_map, f"{ref}.nominal", "F"),
        "tolerance": _parameter_record(parameter_map, f"{ref}.tolerance", "%"),
    }


def _parameter_record(parameter_map: dict[str, dict[str, Any]], parameter_id: str, unit: str) -> dict[str, Any]:
    parameter = parameter_map.get(parameter_id)
    if not parameter:
        return _missing_input(unit, "bom")
    return {
        "value": parameter.get("value"),
        "unit": parameter.get("unit"),
        "parameter_type": parameter.get("parameter_type"),
        "source": parameter.get("source"),
        "review_status": parameter.get("review_status"),
        "extraction_method": parameter.get("extraction_method"),
        "issues": parameter.get("issues", []),
    }


def _missing_input(unit: str, expected_source: str) -> dict[str, Any]:
    return {
        "value": None,
        "unit": unit,
        "parameter_type": "missing",
        "source": {"type": expected_source, "status": "missing"},
        "review_status": "missing",
        "issues": ["missing_value", "requires_engineer_confirmation"],
    }
