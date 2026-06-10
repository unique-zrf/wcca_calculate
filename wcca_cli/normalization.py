from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_yaml, write_yaml
from .units import canonical_unit


CANONICAL_UNITS = {
    "ohm": "ohm",
    "\u03a9": "ohm",
    "%": "%",
    "percent": "%",
    "F": "F",
    "farad": "F",
    "V": "V",
    "volt": "V",
}


def normalize_project(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    components_path = root / "work" / "extracted" / "components.yaml"
    draft_path = root / "work" / "extracted" / "parameter_draft.yaml"
    netlist_path = root / "work" / "extracted" / "netlist.yaml"
    if not draft_path.exists():
        raise FileNotFoundError(f"Missing parameter draft: {draft_path}")
    draft = read_yaml(draft_path)
    components = read_yaml(components_path) if components_path.exists() else {"components": []}
    netlist = read_yaml(netlist_path) if netlist_path.exists() else {"topology_hints": []}
    normalized_parameters = [_normalize_parameter(item) for item in draft.get("parameters", [])]
    output = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "parameters": normalized_parameters,
        "parameter_index": sorted(item["parameter_id"] for item in normalized_parameters),
        "summary": {
            "parameter_count": len(normalized_parameters),
            "confirmed_count": sum(1 for item in normalized_parameters if item["review_status"] == "confirmed"),
            "trial_only_count": sum(1 for item in normalized_parameters if item["review_status"] in {"rule_extracted", "ai_extracted"}),
            "release_ready_count": sum(1 for item in normalized_parameters if item["release_ready"]),
        },
    }
    candidates = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "candidates": _model_candidates(components.get("components", []), netlist.get("topology_hints", [])),
    }
    write_yaml(root / "work" / "normalized" / "parameters.yaml", output)
    write_yaml(root / "work" / "normalized" / "model_candidates.yaml", candidates)
    return {"parameters": output, "model_candidates": candidates}


def _normalize_parameter(item: dict[str, Any]) -> dict[str, Any]:
    unit = _canonical_unit(item.get("unit", ""))
    review_status = item.get("review_status", "missing")
    parameter_id = f"{item.get('component_ref')}.{item.get('parameter')}"
    issues = []
    if not item.get("source"):
        issues.append("missing_source")
    if review_status in {"rule_extracted", "ai_extracted"}:
        issues.append("requires_engineer_confirmation")
    return {
        "parameter_id": parameter_id,
        "component_ref": item.get("component_ref"),
        "component_type": item.get("component_type"),
        "parameter": item.get("parameter"),
        "parameter_type": item.get("parameter"),
        "value": item.get("value"),
        "unit": unit,
        "source": item.get("source"),
        "extraction_method": "rule",
        "review_status": review_status,
        "release_ready": review_status in {"confirmed", "risk_accepted", "not_applicable"} and not issues,
        "issues": issues,
    }


def _canonical_unit(unit: str) -> str:
    return canonical_unit(unit)


def _model_candidates(components: list[dict[str, Any]], topology_hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    resistors = [item for item in components if item.get("component_type") == "resistor"]
    capacitors = [item for item in components if item.get("component_type") == "capacitor"]
    ics = [item for item in components if item.get("component_type") == "ic"]
    component_by_ref = {item.get("reference"): item for item in components if item.get("reference")}

    used_pairs = set()
    used_rc_refs = set()
    for hint in topology_hints:
        refs = hint.get("component_refs", [])
        pair_key = tuple(sorted(refs))
        if hint.get("candidate_type") == "resistor_pair" and len(refs) == 2:
            used_pairs.add(pair_key)
            top = component_by_ref.get(refs[0], {"reference": refs[0]})
            bottom = component_by_ref.get(refs[1], {"reference": refs[1]})
            description = f"{top.get('description', '')} {bottom.get('description', '')}".lower()
            if "comparator" in description:
                candidates.append(_candidate(
                    "comparator_threshold",
                    refs,
                    0.82,
                    f"Netlist shows resistor pair sharing {', '.join(hint.get('shared_nets', []))}; descriptions indicate comparator threshold.",
                    evidence={"topology_hint": hint},
                ))
            else:
                candidates.append(_candidate(
                    "resistor_divider",
                    refs,
                    0.80,
                    f"Netlist shows resistor pair sharing {', '.join(hint.get('shared_nets', []))}.",
                    evidence={"topology_hint": hint},
                ))
        elif hint.get("candidate_type") == "rc_pair" and len(refs) == 2:
            used_rc_refs.update(refs)
            candidates.append(_candidate(
                "rc_delay",
                refs,
                0.72,
                f"Netlist shows RC pair sharing {', '.join(hint.get('shared_nets', []))}.",
                required_confirmations=["threshold_min", "threshold_max", "initial_voltage_range"],
                evidence={"topology_hint": hint},
            ))

    for top, bottom in _paired_resistors(resistors):
        if tuple(sorted([top["reference"], bottom["reference"]])) in used_pairs:
            continue
        description = f"{top.get('description', '')} {bottom.get('description', '')}".lower()
        if "comparator" in description:
            candidates.append(_candidate(
                "comparator_threshold",
                [top["reference"], bottom["reference"]],
                0.72,
                "Two comparator-related resistors may define a comparator threshold.",
            ))
        else:
            candidates.append(_candidate(
                "resistor_divider",
                [top["reference"], bottom["reference"]],
                0.68,
                "Two related resistors may form a divider network.",
            ))

    for ic in ics:
        haystack = f"{ic.get('description', '')} {ic.get('part_number', '')}".lower()
        if "ldo" in haystack:
            candidates.append(_candidate(
                "ldo_power_rail",
                [ic["reference"]],
                0.65,
                "IC description or part number indicates an LDO regulator.",
            ))

    for capacitor in capacitors:
        if capacitor["reference"] in used_rc_refs:
            continue
        haystack = f"{capacitor.get('description', '')} {capacitor.get('reference', '')}".lower()
        if "delay" in haystack or "reset" in haystack or "timing" in haystack:
            candidates.append(_candidate(
                "rc_delay",
                [capacitor["reference"]],
                0.55,
                "Timing capacitor may participate in an RC delay; paired resistor requires engineer confirmation.",
                required_confirmations=["paired_resistor", "threshold_min", "threshold_max", "initial_voltage_range"],
            ))
    return candidates


def _paired_resistors(resistors: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    sorted_resistors = sorted(resistors, key=lambda item: item.get("reference", ""))
    return [
        (sorted_resistors[index], sorted_resistors[index + 1])
        for index in range(0, len(sorted_resistors) - 1, 2)
    ]


def _candidate(
    model_id: str,
    component_refs: list[str],
    confidence: float,
    reason: str,
    required_confirmations: list[str] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "model_id": model_id,
        "model_version": "1.0.0",
        "component_refs": component_refs,
        "confidence": confidence,
        "selection_status": "requires_engineer_confirmation",
        "reason": reason,
        "required_confirmations": required_confirmations or ["model_selection", "boundary_conditions", "requirements"],
        "evidence": evidence or {},
    }
