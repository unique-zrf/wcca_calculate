from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_yaml, write_json
from .reporting import validate_results
from .validation import has_errors, validate_input_document


WORKFLOW_PATH = Path("review") / "workflow.json"


def load_review_workflow(project_dir: str | Path) -> dict[str, Any]:
    root = Path(project_dir)
    path = root / WORKFLOW_PATH
    if path.exists():
        return read_json(path)
    return _default_workflow(root)


def summarize_review_readiness(
    input_document: dict[str, Any] | None,
    results_document: dict[str, Any] | None,
) -> dict[str, Any]:
    input_issues = validate_input_document(input_document, release=True) if input_document else []
    result_issues = validate_results(input_document, results_document) if input_document and results_document else []
    combined = input_issues + result_issues
    return {
        "input_issue_count": len(input_issues),
        "result_issue_count": len(result_issues),
        "error_count": sum(1 for item in combined if item.get("level") == "error"),
        "warning_count": sum(1 for item in combined if item.get("level") == "warning"),
        "release_ready": not has_errors(combined),
        "input_status": "passed" if not has_errors(input_issues) else "failed",
        "result_status": "passed" if not has_errors(result_issues) else "failed",
    }


def transition_review_workflow(
    project_dir: str | Path,
    action: str,
    reviewer: str | None = None,
    comment: str = "",
    input_document: dict[str, Any] | None = None,
    results_document: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_dir)
    input_document = input_document if input_document is not None else _read_yaml_if_exists(root / "work" / "wcca_input.yaml")
    results_document = results_document if results_document is not None else _read_json_if_exists(root / "output" / "calculation" / "results.json")
    readiness = summarize_review_readiness(input_document, results_document)
    current = load_review_workflow(root)
    current_state = str(current.get("state", "draft"))
    next_state = _next_state(current_state, action, readiness)
    event = {
        "at": _now(),
        "action": action,
        "from_state": current_state,
        "to_state": next_state,
        "actor": reviewer or "system",
        "comment": comment,
        "input_status": readiness["input_status"],
        "result_status": readiness["result_status"],
        "release_ready": readiness["release_ready"],
    }
    if input_document is not None:
        event["input_sha256"] = _sha256_json_like(input_document)
    if results_document is not None:
        event["results_sha256"] = _sha256_json_like(results_document)

    workflow = dict(current)
    workflow.update({
        "project_dir": str(root),
        "updated_at": event["at"],
        "state": next_state,
        "readiness": readiness,
    })
    history = list(current.get("history", []))
    history.append(event)
    workflow["history"] = history
    workflow.setdefault("generated_at", event["at"])
    write_json(root / WORKFLOW_PATH, workflow)
    return workflow


def workflow_status(project_dir: str | Path) -> dict[str, Any]:
    workflow = load_review_workflow(project_dir)
    return {
        "state": workflow.get("state", "draft"),
        "generated_at": workflow.get("generated_at"),
        "updated_at": workflow.get("updated_at"),
        "history_count": len(workflow.get("history", [])),
        "readiness": workflow.get("readiness", {}),
    }


def _default_workflow(root: Path) -> dict[str, Any]:
    return {
        "project_dir": str(root),
        "generated_at": _now(),
        "updated_at": None,
        "state": "draft",
        "readiness": {
            "input_issue_count": 0,
            "result_issue_count": 0,
            "error_count": 0,
            "warning_count": 0,
            "release_ready": False,
            "input_status": "unknown",
            "result_status": "unknown",
        },
        "history": [],
    }


def _next_state(current_state: str, action: str, readiness: dict[str, Any]) -> str:
    normalized = action.lower().strip()
    if normalized == "start":
        return "in_review" if readiness["release_ready"] else "blocked"
    if normalized == "approve":
        if not readiness["release_ready"]:
            raise ValueError("Cannot approve workflow while validation has errors")
        return "approved"
    if normalized == "reject":
        return "rejected"
    if normalized == "archive":
        if current_state not in {"approved", "rejected"}:
            raise ValueError("Workflow can only be archived after approval or rejection")
        return "archived"
    if normalized == "refresh":
        return current_state
    raise ValueError(f"Unsupported workflow action: {action}")


def _read_yaml_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_yaml(path)


def _read_json_if_exists(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return read_json(path)


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_json_like(value: Any) -> str:
    import hashlib
    import json

    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
