from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_yaml, write_json
from .registry import file_sha256
from .reporting import validate_results
from .validation import has_errors, validate_input_document


def generate_review_checklist(
    input_path: str | Path,
    output_dir: str | Path | None = None,
    results_path: str | Path | None = None,
) -> dict[str, Any]:
    input_document = read_yaml(input_path)
    results_document = read_json(results_path) if results_path else None
    input_issues = validate_input_document(input_document, release=True)
    result_issues = validate_results(input_document, results_document) if results_document else []
    items = _input_review_items(input_document)
    if results_document:
        items.extend(_result_review_items(results_document))
    items.extend(_issue_review_items(input_issues + result_issues))
    checklist = {
        "generated_at": _now(),
        "input_path": str(input_path),
        "results_path": str(results_path) if results_path else None,
        "summary": {
            "item_count": len(items),
            "blocking_issue_count": sum(1 for item in items if item["severity"] == "blocker"),
            "warning_count": sum(1 for item in items if item["severity"] == "warning"),
        },
        "items": items,
    }
    if output_dir:
        target = Path(output_dir)
        target.mkdir(parents=True, exist_ok=True)
        write_json(target / "review_checklist.json", checklist)
        _write_markdown_checklist(target / "review_checklist.md", checklist)
    return checklist


def approve_project(
    input_path: str | Path,
    results_path: str | Path,
    output_dir: str | Path,
    reviewer: str,
    decision: str,
    comment: str = "",
) -> dict[str, Any]:
    input_document = read_yaml(input_path)
    results_document = read_json(results_path)
    input_issues = validate_input_document(input_document, release=True)
    result_issues = validate_results(input_document, results_document)
    all_issues = input_issues + result_issues
    if decision == "approved" and has_errors(all_issues):
        raise ValueError("Cannot approve project while release validation has errors")
    record = {
        "approved_at": _now(),
        "reviewer": reviewer,
        "decision": decision,
        "comment": comment,
        "input_path": str(input_path),
        "input_sha256": file_sha256(input_path),
        "results_path": str(results_path),
        "results_sha256": file_sha256(results_path),
        "validation_status": "passed" if not has_errors(all_issues) else "failed",
        "issues": all_issues,
    }
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    write_json(target / "approval_record.json", record)
    _write_markdown_approval(target / "approval_record.md", record)
    return record


def _input_review_items(input_document: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in input_document.get("circuit_blocks", []):
        block_id = block.get("id")
        selected = block.get("selected_model", {})
        items.append(_item(
            block_id,
            "model_selection",
            "blocker" if selected.get("selection_status") != "engineer_confirmed" else "info",
            f"Confirm selected model {selected.get('model_id')} {selected.get('model_version')}.",
        ))
        for requirement in block.get("requirements", []):
            severity = "blocker" if requirement.get("min_value") is None or requirement.get("max_value") is None else "info"
            items.append(_item(
                block_id,
                "requirement_limits",
                severity,
                f"Confirm requirement {requirement.get('id')} limits and unit.",
            ))
        _collect_parameter_review_items(block.get("inputs", {}), block_id, "", items)
    return items


def _collect_parameter_review_items(node: Any, block_id: str | None, path: str, items: list[dict[str, Any]]) -> None:
    if isinstance(node, dict) and "value" in node:
        review_status = node.get("review_status")
        if review_status in {"missing", "rule_extracted", "ai_extracted"}:
            items.append(_item(
                block_id,
                "parameter_confirmation",
                "blocker",
                f"Confirm parameter {path}; current review_status={review_status}.",
            ))
        elif review_status == "risk_accepted":
            items.append(_item(
                block_id,
                "risk_acceptance",
                "warning",
                f"Review accepted risk for parameter {path}.",
            ))
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            _collect_parameter_review_items(value, block_id, child_path, items)


def _result_review_items(results_document: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for result in results_document.get("results", []):
        summary = result.get("summary_result", {})
        block_id = result.get("circuit_block_id")
        pass_fail = summary.get("pass_fail")
        margin_min = summary.get("margin_min")
        margin_max = summary.get("margin_max")
        severity = "blocker" if pass_fail != "pass" else "info"
        items.append(_item(block_id, "pass_fail", severity, f"Review Pass/Fail result: {pass_fail}."))
        for margin_name, margin_value in (("margin_min", margin_min), ("margin_max", margin_max)):
            if isinstance(margin_value, (int, float)) and margin_value < 5:
                items.append(_item(
                    block_id,
                    "low_margin",
                    "warning",
                    f"Review low {margin_name}: {margin_value}%.",
                ))
    return items


def _issue_review_items(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _item(issue.get("path"), "validation_issue", "blocker" if issue.get("level") == "error" else "warning", issue.get("message", ""))
        for issue in issues
    ]


def _item(scope: str | None, category: str, severity: str, description: str) -> dict[str, Any]:
    return {
        "scope": scope,
        "category": category,
        "severity": severity,
        "description": description,
        "status": "open",
    }


def _write_markdown_checklist(path: Path, checklist: dict[str, Any]) -> None:
    lines = ["# WCCA Review Checklist", ""]
    lines.append(f"Generated: {checklist['generated_at']}")
    lines.append("")
    lines.append("| Scope | Category | Severity | Description | Status |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in checklist["items"]:
        lines.append(
            f"| {item.get('scope')} | {item['category']} | {item['severity']} | {item['description']} | {item['status']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown_approval(path: Path, record: dict[str, Any]) -> None:
    lines = ["# WCCA Approval Record", ""]
    lines.append(f"- Reviewer: {record['reviewer']}")
    lines.append(f"- Decision: {record['decision']}")
    lines.append(f"- Validation Status: {record['validation_status']}")
    lines.append(f"- Input SHA256: {record['input_sha256']}")
    lines.append(f"- Results SHA256: {record['results_sha256']}")
    if record.get("comment"):
        lines.append(f"- Comment: {record['comment']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

