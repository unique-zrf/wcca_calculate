from __future__ import annotations

from typing import Any

from .io import read_yaml
from .registry import ROOT, get_model
from .units import can_convert_unit


RELEASE_ALLOWED_STATUSES = {"confirmed", "risk_accepted", "not_applicable"}
TRIAL_ONLY_STATUSES = {"ai_extracted", "rule_extracted"}


def _walk(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _required_parameter_paths(model_metadata: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    for item in model_metadata.get("inputs", []):
        if not item.get("required", False):
            continue
        name = item["name"]
        fields = item.get("fields")
        if fields:
            for field in fields:
                paths.append(f"{name}.{field}")
        else:
            paths.append(name)
    return paths


def _expected_unit(model_metadata: dict[str, Any], dotted_path: str) -> str | None:
    head, _, tail = dotted_path.partition(".")
    for item in model_metadata.get("inputs", []):
        if item.get("name") != head:
            continue
        if not tail:
            return item.get("unit")
        if tail == "nominal":
            return item.get("unit")
        if tail in {"tolerance", "aging"}:
            return "%"
        if tail == "tempco":
            return "ppm/C"
    return None


def expected_units_for_model(model_metadata: dict[str, Any]) -> dict[str, str]:
    expected_units: dict[str, str] = {}
    for param_path in _required_parameter_paths(model_metadata):
        unit = _expected_unit(model_metadata, param_path)
        if unit:
            expected_units[param_path] = unit
    for item in model_metadata.get("inputs", []):
        name = item.get("name")
        if not name:
            continue
        unit = item.get("unit")
        fields = item.get("fields")
        if fields:
            for field in fields:
                expected_units.setdefault(f"{name}.{field}", _expected_unit(model_metadata, f"{name}.{field}") or unit)
        elif unit:
            expected_units.setdefault(name, unit)
    return {key: value for key, value in expected_units.items() if value}


def validate_input_document(document: dict[str, Any], release: bool = False) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    known_document_ids = _known_document_ids() if release else set()
    blocks = document.get("circuit_blocks") or []
    if not blocks:
        return [{"level": "error", "path": "circuit_blocks", "message": "No circuit blocks defined"}]

    for block_index, block in enumerate(blocks):
        block_path = f"circuit_blocks[{block_index}]"
        selected = block.get("selected_model") or {}
        model_id = selected.get("model_id")
        model_version = selected.get("model_version")
        if not model_id:
            issues.append({"level": "error", "path": f"{block_path}.selected_model", "message": "Missing model_id"})
            continue
        try:
            model = get_model(model_id, model_version)
        except KeyError as exc:
            issues.append({"level": "error", "path": f"{block_path}.selected_model", "message": str(exc)})
            continue

        block_type = block.get("type")
        circuit_types = model.metadata.get("circuit_types") or []
        if release:
            if not block_type:
                issues.append({
                    "level": "error",
                    "path": f"{block_path}.type",
                    "message": "Missing circuit block type for release",
                })
            elif circuit_types and block_type not in circuit_types:
                issues.append({
                    "level": "error",
                    "path": f"{block_path}.type",
                    "message": f"Circuit type {block_type} is not supported by model {model.model_id}; allowed: {', '.join(circuit_types)}",
                })

        status = model.metadata.get("status")
        if release and status != "approved":
            issues.append({
                "level": "error",
                "path": f"{block_path}.selected_model",
                "message": f"Model status must be approved for release, got {status}",
            })
        selection_status = selected.get("selection_status")
        if release and selection_status != "engineer_confirmed":
            issues.append({
                "level": "error",
                "path": f"{block_path}.selected_model.selection_status",
                "message": f"Model selection must be engineer_confirmed for release, got {selection_status}",
            })

        requirements = block.get("requirements") or []
        if not requirements:
            issues.append({"level": "error", "path": f"{block_path}.requirements", "message": "Missing requirement"})
        for req_index, req in enumerate(requirements):
            req_path = f"{block_path}.requirements[{req_index}]"
            if "min_value" not in req or "max_value" not in req:
                issues.append({
                    "level": "error",
                    "path": req_path,
                    "message": "Requirement needs min_value and max_value",
                })
            elif req.get("min_value") is None or req.get("max_value") is None:
                issues.append({
                    "level": "error",
                    "path": req_path,
                    "message": "Requirement min_value and max_value must be filled before release",
                })
            if release:
                source = req.get("source")
                if source in (None, {}, ""):
                    issues.append({"level": "error", "path": req_path, "message": "Missing requirement source"})
                else:
                    document_id = source.get("document_id") if isinstance(source, dict) else None
                    if not document_id:
                        issues.append({
                            "level": "error",
                            "path": f"{req_path}.source",
                            "message": "Missing requirement source document_id",
                        })
                    elif document_id not in known_document_ids:
                        issues.append({
                            "level": "error",
                            "path": f"{req_path}.source.document_id",
                            "message": f"Unknown requirement source document_id: {document_id}",
                        })
                review_status = req.get("review_status")
                if not review_status:
                    issues.append({"level": "error", "path": req_path, "message": "Missing requirement review_status"})
                elif review_status not in RELEASE_ALLOWED_STATUSES:
                    issues.append({
                        "level": "error",
                        "path": req_path,
                        "message": f"Requirement review_status {review_status} is not allowed for release",
                    })

        inputs = block.get("inputs") or {}
        for param_path in _required_parameter_paths(model.metadata):
            record = _walk(inputs, param_path)
            full_path = f"{block_path}.inputs.{param_path}"
            if record is None:
                issues.append({"level": "error", "path": full_path, "message": "Missing required parameter"})
                continue
            if not isinstance(record, dict) or "value" not in record:
                issues.append({"level": "error", "path": full_path, "message": "Parameter must contain value"})
                continue
            expected_unit = _expected_unit(model.metadata, param_path)
            actual_unit = record.get("unit")
            if expected_unit and actual_unit and not can_convert_unit(actual_unit, expected_unit):
                issues.append({
                    "level": "error",
                    "path": full_path,
                    "message": f"Unit must be convertible to {expected_unit}, got {actual_unit}",
                })
            source = record.get("source")
            if source in (None, {}, ""):
                issues.append({"level": "error", "path": full_path, "message": "Missing parameter source"})
            elif release:
                document_id = source.get("document_id") if isinstance(source, dict) else None
                if not document_id:
                    issues.append({"level": "error", "path": f"{full_path}.source", "message": "Missing source document_id"})
                elif document_id not in known_document_ids:
                    issues.append({
                        "level": "error",
                        "path": f"{full_path}.source.document_id",
                        "message": f"Unknown source document_id: {document_id}",
                    })
            review_status = record.get("review_status")
            if not review_status:
                issues.append({"level": "error", "path": full_path, "message": "Missing review_status"})
            elif release and review_status not in RELEASE_ALLOWED_STATUSES:
                issues.append({
                    "level": "error",
                    "path": full_path,
                    "message": f"review_status {review_status} is not allowed for release",
                })
            elif review_status in TRIAL_ONLY_STATUSES:
                issues.append({
                    "level": "warning",
                    "path": full_path,
                    "message": f"review_status {review_status} is trial-only",
                })
            if record.get("parameter_type") == "typical" and review_status != "risk_accepted":
                issues.append({
                    "level": "error",
                    "path": full_path,
                    "message": "Typical value must be risk_accepted",
                })
    return issues


def _known_document_ids() -> set[str]:
    path = ROOT / "wcca_knowledge_base" / "index" / "documents_index.yaml"
    if not path.exists():
        return set()
    data = read_yaml(path)
    return {
        str(document.get("document_id"))
        for document in data.get("documents", [])
        if document.get("document_id")
    }


def has_errors(issues: list[dict[str, Any]]) -> bool:
    return any(issue.get("level") == "error" for issue in issues)
