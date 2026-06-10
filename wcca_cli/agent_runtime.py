from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .docgen import build_document_package
from .extraction import extract_project
from .io import read_json, read_yaml, write_json, write_yaml
from .knowledge_providers import load_knowledge_config
from .parameter_extraction import extract_parameter_candidates
from .reporting import write_markdown_report
from .validation import validate_input_document
from .workflow import summarize_review_readiness
from .agents import build_agent_workplan


def run_agent_automation(
    project_dir: str | Path,
    llm_config: dict[str, Any] | None = None,
    knowledge_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(project_dir)
    knowledge_config = knowledge_config or {"provider": "local"}
    workplan = build_agent_workplan(root, llm_config=llm_config)
    input_document = _load_yaml(root / "work" / "wcca_input.yaml")
    results_document = _load_json(root / "output" / "calculation" / "results.json")
    input_index = _load_yaml(root / "work" / "input_index.yaml")
    readiness = summarize_review_readiness(input_document, results_document)

    if input_document:
        extract_parameter_candidates(root, input_document, knowledge_config=knowledge_config, limit=3)
        parameter_candidates = _load_yaml(root / "work" / "extracted" / "parameter_candidates.yaml")
    else:
        parameter_candidates = {}

    artifacts: list[dict[str, Any]] = []
    artifacts.append(_write_role_report(root, "planner", _planner_section(input_index, input_document)))
    artifacts.append(_write_role_report(root, "parameter_extractor", _parameter_section(parameter_candidates, knowledge_config)))
    artifacts.append(_write_role_report(root, "circuit_analysis", _circuit_section(input_document)))
    artifacts.append(_write_role_report(root, "calculation_reviewer", _calculation_section(results_document)))
    artifacts.append(_write_role_report(root, "report_writer", _report_section(root, input_document, results_document)))
    artifacts.append(_write_role_report(root, "compliance_reviewer", _compliance_section(root, input_document, results_document, readiness)))

    manifest = {
        "generated_at": _now(),
        "project_dir": str(root),
        "mode": "multi_agent_automation",
        "knowledge_provider": knowledge_config.get("provider", "local"),
        "llm_provider": workplan.get("llm_assistance", {}).get("provider"),
        "readiness": readiness,
        "artifacts": artifacts,
        "workplan_path": "work/agents/agent_workplan.yaml",
    }
    manifest["artifact_count"] = len(artifacts)
    manifest["artifact_sha256"] = _sha256_json(artifacts)
    write_json(root / "work" / "agents" / "agent_run.json", manifest)
    return manifest


def _planner_section(input_index: dict[str, Any], input_document: dict[str, Any]) -> dict[str, Any]:
    missing = input_index.get("missing_input_categories", [])
    blocks = input_document.get("circuit_blocks", [])
    return {
        "title": "Planner",
        "findings": [
            f"missing_input_categories={len(missing)}",
            f"circuit_block_count={len(blocks)}",
        ],
        "next_actions": [
            "Confirm project scope and missing source documents.",
            "Confirm selected models and requirement limits for each circuit block.",
        ],
        "files": [],
    }


def _parameter_section(parameter_candidates: dict[str, Any], knowledge_config: dict[str, Any]) -> dict[str, Any]:
    summary = parameter_candidates.get("summary", {})
    files = [
        "work/extracted/parameter_candidates.yaml",
        "work/extracted/evidence_candidates.csv",
    ] if parameter_candidates else []
    return {
        "title": "Parameter Extractor",
        "findings": [
            f"candidate_count={summary.get('candidate_count', 0)}",
            f"review_required_count={summary.get('review_required_count', 0)}",
            f"knowledge_provider={knowledge_config.get('provider', 'local')}",
        ],
        "next_actions": [
            "Review candidate parameters and promote only engineer-confirmed values.",
        ],
        "files": files,
    }


def _circuit_section(input_document: dict[str, Any]) -> dict[str, Any]:
    lines = []
    for block in input_document.get("circuit_blocks", []):
        selected = block.get("selected_model", {})
        issues = validate_input_document({"circuit_blocks": [block]}, release=False)
        lines.append(
            f"{block.get('id')}: {selected.get('model_id')} {selected.get('model_version')} "
            f"issues={sum(1 for item in issues if item.get('level') == 'error')}"
        )
    return {
        "title": "Circuit Analysis",
        "findings": lines or ["No circuit blocks available."],
        "next_actions": [
            "Verify each selected model is compatible with the circuit block type.",
        ],
        "files": [],
    }


def _calculation_section(results_document: dict[str, Any]) -> dict[str, Any]:
    results = results_document.get("results", [])
    findings = []
    for item in results:
        summary = item.get("summary_result", {})
        findings.append(
            f"{item.get('circuit_block_id')}: {summary.get('pass_fail')} "
            f"margin_min={summary.get('margin_min')} margin_max={summary.get('margin_max')}"
        )
    low_margin = [
        item.get("circuit_block_id")
        for item in results
        if any(
            isinstance(item.get("summary_result", {}).get(field), (int, float))
            and item.get("summary_result", {}).get(field) < 5
            for field in ("margin_min", "margin_max")
        )
    ]
    return {
        "title": "Calculation Reviewer",
        "findings": findings or ["No calculation results available."],
        "next_actions": [
            "Escalate any low-margin or failing blocks to engineering review.",
        ] + ([f"Low margin blocks: {', '.join(low_margin)}"] if low_margin else []),
        "files": ["output/calculation/results.json"] if results else [],
    }


def _report_section(root: Path, input_document: dict[str, Any], results_document: dict[str, Any]) -> dict[str, Any]:
    report_path = root / "output" / "report" / "wcca_report.md"
    if not report_path.exists() and input_document and results_document:
        write_markdown_report(root / "output" / "report", input_document, results_document)
    return {
        "title": "Report Writer",
        "findings": [
            f"report_exists={report_path.exists()}",
            "Use deterministic calculation outputs and approved source references only.",
        ],
        "next_actions": [
            "Populate report narrative from validated calculation outputs.",
        ],
        "files": [str(report_path.relative_to(root)).replace("\\", "/")] if report_path.exists() else [],
    }


def _compliance_section(
    root: Path,
    input_document: dict[str, Any],
    results_document: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    blockers = []
    if not readiness["release_ready"]:
        blockers.append("Release validation has unresolved errors.")
    if results_document and results_document.get("release_status") == "not_for_release":
        blockers.append("Results are marked not_for_release.")
    if input_document:
        blockers.append(f"block_count={len(input_document.get('circuit_blocks', []))}")
    return {
        "title": "Compliance Reviewer",
        "findings": blockers or ["No compliance blockers detected."],
        "next_actions": [
            "Confirm source references, approval state, and release package completeness.",
        ],
        "files": [
            path for path in [
                "review/approvals/approval_record.json",
                "review/workflow.json",
                "output/document/docgen_manifest.json",
            ]
            if (root / path).exists()
        ],
    }


def _write_role_report(root: Path, role: str, payload: dict[str, Any]) -> dict[str, Any]:
    path = root / "work" / "agents" / f"{role}.md"
    lines = [f"# {payload['title']}", ""]
    lines.append("## Findings")
    lines.extend(f"- {item}" for item in payload.get("findings", []))
    lines.append("")
    lines.append("## Next Actions")
    lines.extend(f"- {item}" for item in payload.get("next_actions", []))
    lines.append("")
    if payload.get("files"):
        lines.append("## Related Files")
        lines.extend(f"- `{item}`" for item in payload["files"])
        lines.append("")
    text = "\n".join(lines) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {
        "role": role,
        "path": str(path.relative_to(root)).replace("\\", "/"),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "finding_count": len(payload.get("findings", [])),
    }


def _load_yaml(path: Path) -> dict[str, Any]:
    return read_yaml(path) if path.exists() else {}


def _load_json(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_json(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
