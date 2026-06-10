from __future__ import annotations

from pathlib import Path
from typing import Any

from .model_api import margin_percent
from .registry import get_model
from .units import normalize_document_units
from .validation import expected_units_for_model, has_errors, validate_input_document


def validate_results(input_document: dict[str, Any], results_document: dict[str, Any]) -> list[dict[str, Any]]:
    issues = validate_input_document(input_document, release=True)
    if results_document.get("release_status") == "not_for_release":
        issues.append({
            "level": "error",
            "path": "results.release_status",
            "message": "Trial calculation results cannot be used for release",
        })
    expected_blocks = {block.get("id") for block in input_document.get("circuit_blocks", [])}
    result_blocks = {item.get("circuit_block_id") for item in results_document.get("results", [])}
    for missing in sorted(expected_blocks - result_blocks):
        issues.append({"level": "error", "path": "results", "message": f"Missing result for {missing}"})

    for item in results_document.get("results", []):
        if item.get("release_status") != "release_candidate":
            issues.append({
                "level": "error",
                "path": f"results.{item.get('circuit_block_id')}.release_status",
                "message": f"Result release_status must be release_candidate, got {item.get('release_status')}",
            })
        summary = item.get("summary_result", {})
        pass_fail = summary.get("pass_fail")
        worst_min = summary.get("worst_min")
        worst_max = summary.get("worst_max")
        req_min = summary.get("requirement_min")
        req_max = summary.get("requirement_max")
        if None not in (worst_min, worst_max, req_min, req_max):
            expected = "pass" if worst_min >= req_min and worst_max <= req_max else "fail"
            if pass_fail != expected:
                issues.append({
                    "level": "error",
                    "path": f"results.{item.get('circuit_block_id')}.summary_result.pass_fail",
                    "message": f"Pass/Fail should be {expected}",
                })
            issues.extend(_validate_margins(item, worst_min, worst_max, req_min, req_max))
    issues.extend(_validate_parameter_risk_coverage(input_document, results_document))
    issues.extend(_validate_requirements_coverage(input_document, results_document))
    issues.extend(_validate_parameter_sources(input_document, results_document))
    return issues


def _validate_parameter_sources(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    actual = {
        (item.get("circuit_block_id"), item.get("parameter")): item
        for item in results_document.get("parameter_sources", [])
    }
    expected_rows = _expected_parameter_sources(input_document)
    for expected in expected_rows:
        key = (expected["circuit_block_id"], expected["parameter"])
        actual_row = actual.get(key)
        if actual_row is None:
            issues.append({
                "level": "error",
                "path": f"results.parameter_sources.{key[0]}.{key[1]}",
                "message": "Missing parameter source row",
            })
            continue
        for field, expected_value in expected.items():
            actual_value = actual_row.get(field)
            if _coverage_value_mismatch(actual_value, expected_value):
                issues.append({
                    "level": "error",
                    "path": f"results.parameter_sources.{key[0]}.{key[1]}.{field}",
                    "message": f"Parameter source {field} should be {expected_value}, got {actual_value}",
                })
    expected_keys = {
        (item["circuit_block_id"], item["parameter"])
        for item in expected_rows
    }
    for extra_key in sorted(set(actual) - expected_keys):
        issues.append({
            "level": "error",
            "path": f"results.parameter_sources.{extra_key[0]}.{extra_key[1]}",
            "message": "Unexpected parameter source row",
        })
    return issues


def _expected_parameter_sources(input_document: dict[str, Any]) -> list[dict[str, Any]]:
    input_document, _ = normalize_document_units(input_document, _expected_units_by_block(input_document))
    rows: list[dict[str, Any]] = []
    for block in input_document.get("circuit_blocks", []):
        _collect_expected_parameter_sources(block.get("inputs", {}), block, "", rows)
    return rows


def _collect_expected_parameter_sources(
    node: Any,
    block: dict[str, Any],
    path: str,
    rows: list[dict[str, Any]],
) -> None:
    if isinstance(node, dict) and "value" in node:
        source = node.get("source") or {}
        selected = block.get("selected_model", {})
        rows.append({
            "circuit_block_id": block.get("id"),
            "circuit_block_name": block.get("name"),
            "model_id": selected.get("model_id"),
            "model_version": selected.get("model_version"),
            "parameter": path,
            "value": node.get("value"),
            "unit": node.get("unit"),
            "parameter_type": node.get("parameter_type"),
            "source_type": source.get("type") if isinstance(source, dict) else None,
            "document_id": source.get("document_id") if isinstance(source, dict) else None,
            "source_detail": _source_detail(source),
            "review_status": node.get("review_status"),
            "risk_reason": node.get("risk_reason"),
        })
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            _collect_expected_parameter_sources(value, block, child_path, rows)


def _validate_requirements_coverage(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    actual = {
        (item.get("requirement_id"), item.get("circuit_block_id")): item
        for item in results_document.get("requirements_coverage", [])
    }
    expected_rows = _expected_requirements_coverage(input_document, results_document)
    for expected in expected_rows:
        key = (expected["requirement_id"], expected["circuit_block_id"])
        actual_row = actual.get(key)
        if actual_row is None:
            issues.append({
                "level": "error",
                "path": f"results.requirements_coverage.{key[0]}",
                "message": "Missing requirements coverage row",
            })
            continue
        for field, expected_value in expected.items():
            actual_value = actual_row.get(field)
            if _coverage_value_mismatch(actual_value, expected_value):
                issues.append({
                    "level": "error",
                    "path": f"results.requirements_coverage.{key[0]}.{field}",
                    "message": f"Coverage {field} should be {expected_value}, got {actual_value}",
                })
    expected_keys = {
        (item["requirement_id"], item["circuit_block_id"])
        for item in expected_rows
    }
    for extra_key in sorted(set(actual) - expected_keys):
        issues.append({
            "level": "error",
            "path": f"results.requirements_coverage.{extra_key[0]}",
            "message": "Unexpected requirements coverage row",
        })
    return issues


def _expected_requirements_coverage(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
) -> list[dict[str, Any]]:
    result_by_block = {
        item.get("circuit_block_id"): item
        for item in results_document.get("results", [])
    }
    rows: list[dict[str, Any]] = []
    for block in input_document.get("circuit_blocks", []):
        result = result_by_block.get(block.get("id"), {})
        summary = result.get("summary_result", {})
        selected = block.get("selected_model", {})
        for requirement in block.get("requirements", []):
            rows.append({
                "requirement_id": requirement.get("id"),
                "circuit_block_id": block.get("id"),
                "model_id": selected.get("model_id"),
                "model_version": selected.get("model_version"),
                "requirement_min": requirement.get("min_value"),
                "requirement_max": requirement.get("max_value"),
                "worst_min": summary.get("worst_min"),
                "worst_max": summary.get("worst_max"),
                "pass_fail": summary.get("pass_fail"),
            })
    return rows


def _coverage_value_mismatch(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (int, float)):
        try:
            return abs(float(actual) - float(expected)) > 1e-9
        except (TypeError, ValueError):
            return True
    return actual != expected


def _source_detail(source: Any) -> str:
    if not isinstance(source, dict):
        return ""
    details = [
        f"{key}={value}"
        for key, value in source.items()
        if key not in {"type", "document_id"} and value not in (None, "")
    ]
    return "; ".join(details)


def _expected_units_by_block(document: dict[str, Any]) -> dict[str | None, dict[str, str]]:
    expected: dict[str | None, dict[str, str]] = {}
    for block in document.get("circuit_blocks", []):
        selected = block.get("selected_model", {})
        try:
            model = get_model(selected.get("model_id"), selected.get("model_version"))
        except KeyError:
            continue
        expected[block.get("id")] = expected_units_for_model(model.metadata)
    return expected


def _validate_parameter_risk_coverage(
    input_document: dict[str, Any],
    results_document: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    required = _required_parameter_risks(input_document)
    present = {
        (
            item.get("circuit_block_id"),
            item.get("parameter"),
        )
        for item in results_document.get("risk_items", [])
        if item.get("risk_type") == "parameter_risk"
    }
    for risk in required:
        key = (risk["circuit_block_id"], risk["parameter"])
        if key not in present:
            issues.append({
                "level": "error",
                "path": f"results.risk_items.{risk['circuit_block_id']}.{risk['parameter']}",
                "message": "Missing parameter_risk item for risk_accepted or typical parameter",
            })
    return issues


def _required_parameter_risks(input_document: dict[str, Any]) -> list[dict[str, str | None]]:
    risks: list[dict[str, str | None]] = []
    for block in input_document.get("circuit_blocks", []):
        _collect_required_parameter_risks(block.get("inputs", {}), block.get("id"), "", risks)
    return risks


def _collect_required_parameter_risks(
    node: Any,
    block_id: str | None,
    path: str,
    risks: list[dict[str, str | None]],
) -> None:
    if isinstance(node, dict) and "value" in node:
        if node.get("review_status") == "risk_accepted" or node.get("parameter_type") == "typical":
            risks.append({"circuit_block_id": block_id, "parameter": path})
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            _collect_required_parameter_risks(value, block_id, child_path, risks)


def _validate_margins(
    result: dict[str, Any],
    worst_min: float,
    worst_max: float,
    req_min: float,
    req_max: float,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    summary = result.get("summary_result", {})
    try:
        expected_margin_min, expected_margin_max = margin_percent(worst_min, worst_max, req_min, req_max)
    except ValueError as exc:
        return [{
            "level": "error",
            "path": f"results.{result.get('circuit_block_id')}.summary_result",
            "message": str(exc),
        }]
    expected = {
        "margin_min": round(expected_margin_min, 3),
        "margin_max": round(expected_margin_max, 3),
    }
    for field, expected_value in expected.items():
        actual = summary.get(field)
        if not isinstance(actual, (int, float)) or abs(float(actual) - expected_value) > 0.001:
            issues.append({
                "level": "error",
                "path": f"results.{result.get('circuit_block_id')}.summary_result.{field}",
                "message": f"{field} should be {expected_value}, got {actual}",
            })
    return issues


def write_markdown_report(output_dir: str | Path, input_document: dict[str, Any], results_document: dict[str, Any]) -> Path:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / "wcca_report.md"
    lines: list[str] = []
    project = input_document.get("project", {})
    lines.append(f"# {project.get('name', 'WCCA Project')} WCCA Report Draft")
    lines.append("")
    lines.append("## Calculation Summary")
    lines.append("")
    lines.append("| Circuit Block | Model | Worst Min | Worst Max | Requirement | Margin Min | Margin Max | Result |")
    lines.append("| --- | --- | ---: | ---: | --- | ---: | ---: | --- |")
    for item in results_document.get("results", []):
        summary = item.get("summary_result", {})
        requirement = f"{summary.get('requirement_min')} to {summary.get('requirement_max')}"
        lines.append(
            f"| {item.get('circuit_block_id')} | {item.get('model_id')} {item.get('model_version')} | "
            f"{summary.get('worst_min')} | {summary.get('worst_max')} | {requirement} | "
            f"{summary.get('margin_min')} | {summary.get('margin_max')} | {summary.get('pass_fail')} |"
        )
    lines.append("")
    lines.append("## Review Notes")
    lines.append("")
    lines.append("- Confirm all boundary conditions and parameter sources before release.")
    lines.append("- Confirm any `risk_accepted` parameter appears in the risk item list.")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def result_status(issues: list[dict[str, Any]]) -> str:
    return "failed" if has_errors(issues) else "passed"
