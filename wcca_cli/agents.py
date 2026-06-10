from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io import read_json, read_yaml, write_json, write_yaml
from .llm import generate_text


AGENT_ROLES = [
    "planner",
    "parameter_extractor",
    "circuit_analysis",
    "calculation_reviewer",
    "report_writer",
    "compliance_reviewer",
]

AGENT_PACKAGE_FILES = [
    "work/agents/agent_workplan.yaml",
    "work/agents/llm_prompt.md",
    "work/agents/llm_call.json",
    "work/agents/agent_run.json",
    "work/agents/planner.md",
    "work/agents/parameter_extractor.md",
    "work/agents/circuit_analysis.md",
    "work/agents/calculation_reviewer.md",
    "work/agents/report_writer.md",
    "work/agents/compliance_reviewer.md",
]


def build_agent_workplan(project_dir: str | Path, llm_config: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(project_dir)
    agents_dir = root / "work" / "agents"
    input_path = root / "work" / "wcca_input.yaml"
    results_path = root / "output" / "calculation" / "results.json"
    input_index_path = root / "work" / "input_index.yaml"
    document = read_yaml(input_path) if input_path.exists() else {}
    results = read_json(results_path) if results_path.exists() else {}
    input_index = read_yaml(input_index_path) if input_index_path.exists() else {}
    workplan = {
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "mode": "deterministic_agent_plan",
        "llm_required": False,
        "roles": [
            _planner_role(input_index, document),
            _parameter_extractor_role(document),
            _circuit_analysis_role(document),
            _calculation_reviewer_role(results),
            _report_writer_role(results),
            _compliance_reviewer_role(document, results),
        ],
        "guardrails": [
            "Agents may create suggestions and review items only.",
            "Agents must not approve parameters or release decisions.",
            "All numerical conclusions must reference deterministic calculation outputs.",
        ],
    }
    prompt = _agent_prompt(workplan)
    prompt_path = agents_dir / "llm_prompt.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(prompt + "\n", encoding="utf-8")
    llm_result = generate_text(prompt, llm_config)
    llm_call = {
        "generated_at": workplan["generated_at"],
        "provider": llm_result.provider,
        "status": llm_result.status,
        "error": llm_result.error,
        "prompt_path": "work/agents/llm_prompt.md",
        "prompt_sha256": _sha256_text(prompt),
        "response_path": "work/agents/llm_review.md" if llm_result.text else None,
        "response_sha256": _sha256_text(llm_result.text) if llm_result.text else None,
    }
    workplan["llm_assistance"] = {
        "provider": llm_result.provider,
        "status": llm_result.status,
        "error": llm_result.error,
        "prompt_path": "work/agents/llm_prompt.md",
        "call_record_path": "work/agents/llm_call.json",
        "output_path": "work/agents/llm_review.md" if llm_result.text else None,
    }
    write_yaml(agents_dir / "agent_workplan.yaml", workplan)
    write_json(agents_dir / "llm_call.json", llm_call)
    if llm_result.text:
        review_path = agents_dir / "llm_review.md"
        review_path.write_text(llm_result.text + "\n", encoding="utf-8")
    return workplan


def validate_agent_package(project_dir: str | Path) -> list[dict[str, str]]:
    root = Path(project_dir)
    issues: list[dict[str, str]] = []
    for rel_path in AGENT_PACKAGE_FILES:
        if not (root / rel_path).exists():
            issues.append({"level": "error", "path": rel_path, "message": "Required agent file is missing"})
    workplan_path = root / "work" / "agents" / "agent_workplan.yaml"
    prompt_path = root / "work" / "agents" / "llm_prompt.md"
    call_path = root / "work" / "agents" / "llm_call.json"
    if not workplan_path.exists() or not prompt_path.exists() or not call_path.exists():
        return issues

    workplan = read_yaml(workplan_path)
    call_record = read_json(call_path)
    llm_assistance = workplan.get("llm_assistance", {})
    if llm_assistance.get("prompt_path") != "work/agents/llm_prompt.md":
        issues.append({
            "level": "error",
            "path": "work/agents/agent_workplan.yaml:llm_assistance.prompt_path",
            "message": "Agent workplan prompt_path must reference work/agents/llm_prompt.md",
        })
    if llm_assistance.get("call_record_path") != "work/agents/llm_call.json":
        issues.append({
            "level": "error",
            "path": "work/agents/agent_workplan.yaml:llm_assistance.call_record_path",
            "message": "Agent workplan call_record_path must reference work/agents/llm_call.json",
        })
    if not any("must not approve" in item for item in workplan.get("guardrails", [])):
        issues.append({
            "level": "error",
            "path": "work/agents/agent_workplan.yaml:guardrails",
            "message": "Agent guardrails must prohibit approval actions",
        })

    prompt_text = prompt_path.read_text(encoding="utf-8").rstrip("\n")
    if call_record.get("prompt_sha256") != _sha256_text(prompt_text):
        issues.append({
            "level": "error",
            "path": "work/agents/llm_call.json:prompt_sha256",
            "message": "LLM prompt hash does not match llm_prompt.md",
        })

    response_path = call_record.get("response_path")
    response_hash = call_record.get("response_sha256")
    if response_path:
        resolved_response = root / str(response_path)
        if not resolved_response.exists():
            issues.append({"level": "error", "path": response_path, "message": "LLM response file is missing"})
        elif response_hash != _sha256_text(resolved_response.read_text(encoding="utf-8").rstrip("\n")):
            issues.append({
                "level": "error",
                "path": "work/agents/llm_call.json:response_sha256",
                "message": "LLM response hash does not match response file",
            })
    elif response_hash:
        issues.append({
            "level": "error",
            "path": "work/agents/llm_call.json:response_sha256",
            "message": "LLM response hash is set without a response_path",
        })
    agent_run_path = root / "work" / "agents" / "agent_run.json"
    if agent_run_path.exists():
        _audit_agent_run(root, read_json(agent_run_path), issues)
    return issues


def _audit_agent_run(root: Path, manifest: dict[str, Any], issues: list[dict[str, str]]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        issues.append({
            "level": "error",
            "path": "work/agents/agent_run.json:artifacts",
            "message": "Agent run artifacts must be a list",
        })
        return
    for item in artifacts:
        rel_path = item.get("path") if isinstance(item, dict) else None
        expected_hash = item.get("sha256") if isinstance(item, dict) else None
        if not rel_path or not expected_hash:
            issues.append({
                "level": "error",
                "path": "work/agents/agent_run.json:artifacts",
                "message": "Agent artifact entries need path and sha256",
            })
            continue
        path = root / rel_path
        if not path.exists():
            issues.append({"level": "error", "path": rel_path, "message": "Agent artifact is missing"})
            continue
        actual_hash = _sha256_text(path.read_text(encoding="utf-8"))
        if actual_hash != expected_hash:
            issues.append({
                "level": "error",
                "path": rel_path,
                "message": "Agent artifact hash does not match agent_run.json",
            })


def _planner_role(input_index: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    missing = input_index.get("missing_input_categories", [])
    blocks = document.get("circuit_blocks", [])
    tasks = ["Confirm analysis scope and required project inputs."]
    if missing:
        tasks.append(f"Resolve missing input categories: {', '.join(missing)}.")
    if not blocks:
        tasks.append("Define circuit blocks before calculation.")
    return {"role": "planner", "tasks": tasks, "outputs": ["scope_review", "missing_inputs"]}


def _parameter_extractor_role(document: dict[str, Any]) -> dict[str, Any]:
    unconfirmed = []
    for block in document.get("circuit_blocks", []):
        _collect_unconfirmed(block.get("inputs", {}), block.get("id"), "", unconfirmed)
    tasks = ["Generate parameter candidates from knowledge evidence."]
    if unconfirmed:
        tasks.append(f"Engineer confirmation required for {len(unconfirmed)} parameter records.")
    return {"role": "parameter_extractor", "tasks": tasks, "outputs": ["parameter_candidates", "source_evidence"]}


def _circuit_analysis_role(document: dict[str, Any]) -> dict[str, Any]:
    tasks = ["Verify selected model applicability for each circuit block."]
    for block in document.get("circuit_blocks", []):
        selected = block.get("selected_model", {})
        tasks.append(f"Check {block.get('id')} uses {selected.get('model_id')} {selected.get('model_version')}.")
    return {"role": "circuit_analysis", "tasks": tasks, "outputs": ["model_selection_review"]}


def _calculation_reviewer_role(results: dict[str, Any]) -> dict[str, Any]:
    tasks = ["Review calculation status, margins, and failed or low-margin items."]
    for item in results.get("results", []):
        summary = item.get("summary_result", {})
        tasks.append(
            f"{item.get('circuit_block_id')}: {summary.get('pass_fail')} "
            f"margin_min={summary.get('margin_min')} margin_max={summary.get('margin_max')}."
        )
    return {"role": "calculation_reviewer", "tasks": tasks, "outputs": ["calculation_review_notes"]}


def _report_writer_role(results: dict[str, Any]) -> dict[str, Any]:
    status = results.get("release_status", "unknown")
    return {
        "role": "report_writer",
        "tasks": [
            "Generate report narrative from template variables only.",
            f"Use release status from calculation output: {status}.",
        ],
        "outputs": ["wcca_document_draft", "review_summary"],
    }


def _compliance_reviewer_role(document: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    requirement_count = sum(len(block.get("requirements", [])) for block in document.get("circuit_blocks", []))
    coverage_count = len(results.get("requirements_coverage", []))
    return {
        "role": "compliance_reviewer",
        "tasks": [
            "Check source references, risk items, requirements coverage, approval state, and release package.",
            f"Requirement rows={requirement_count}; coverage rows={coverage_count}.",
        ],
        "outputs": ["compliance_review", "release_blockers"],
    }


def _collect_unconfirmed(node: Any, block_id: str | None, path: str, rows: list[dict[str, str | None]]) -> None:
    if isinstance(node, dict) and "value" in node:
        if node.get("review_status") != "confirmed":
            rows.append({"circuit_block_id": block_id, "parameter": path})
        return
    if isinstance(node, dict):
        for key, value in node.items():
            child_path = f"{path}.{key}" if path else key
            _collect_unconfirmed(value, block_id, child_path, rows)


def _agent_prompt(workplan: dict[str, Any]) -> str:
    lines = [
        "Review this WCCA automation workplan and produce concise engineering review suggestions.",
        "Guardrails:",
    ]
    lines.extend(f"- {item}" for item in workplan.get("guardrails", []))
    lines.append("")
    lines.append("Roles and tasks:")
    for role in workplan.get("roles", []):
        lines.append(f"## {role.get('role')}")
        for task in role.get("tasks", []):
            lines.append(f"- {task}")
    lines.append("")
    lines.append("Return only suggestions, blockers, and review questions. Do not invent numerical values.")
    return "\n".join(lines)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
