from __future__ import annotations

import argparse
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .agent_runtime import run_agent_automation
from .audit import audit_project
from .docgen import build_document_package, validate_document_package
from .engine import calculate_document, write_calculation_outputs
from .enterprise_integration import dispatch_enterprise_integration
from .extraction import extract_project
from .input_builder import build_input_draft
from .io import read_json, read_yaml
from .knowledge import search_knowledge
from .knowledge_providers import load_knowledge_config
from .llm import load_llm_config
from .normalization import normalize_project
from .project import ingest_project, init_project
from .registry import iter_models
from .report_export import export_report_documents
from .reporting import validate_results
from .review import approve_project, generate_review_checklist
from .simulation import run_simulation_interface
from .validation import has_errors, validate_input_document
from .workflow import transition_review_workflow, workflow_status


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = Path(__file__).resolve().parent / "web_static"


class WccaWebApp:
    def __init__(self, project_dir: str | Path = "examples/project_sample") -> None:
        self.project_dir = Path(project_dir)

    def handle_get(self, path: str, query: dict[str, list[str]]) -> tuple[int, Any]:
        if path == "/api/state":
            return 200, self._state()
        if path == "/api/models":
            return 200, {"models": [_model_record(model) for model in iter_models()]}
        if path == "/api/knowledge/search":
            q = query.get("q", [""])[0]
            return 200, {"query": q, "results": search_knowledge(q, limit=10)}
        if path == "/api/file":
            rel_path = query.get("path", [""])[0]
            return self._read_project_file(rel_path)
        return 404, {"error": f"Unknown API route: {path}"}

    def handle_post(self, path: str, body: dict[str, Any]) -> tuple[int, Any]:
        actions = {
            "/api/actions/init": self._action_init,
            "/api/actions/ingest": self._action_ingest,
            "/api/actions/extract": self._action_extract,
            "/api/actions/normalize": self._action_normalize,
            "/api/actions/input-build": self._action_input_build,
            "/api/actions/validate-input": self._action_validate_input,
            "/api/actions/calculate": self._action_calculate,
            "/api/actions/validate": self._action_validate_results,
            "/api/actions/report-export": self._action_report_export,
            "/api/actions/document-build": self._action_document_build,
            "/api/actions/validate-document": self._action_validate_document,
            "/api/actions/simulate": self._action_simulate,
            "/api/actions/agent-run": self._action_agent_run,
            "/api/actions/review-checklist": self._action_review_checklist,
            "/api/actions/review-flow": self._action_review_flow,
            "/api/actions/approve": self._action_approve,
            "/api/actions/integration-dispatch": self._action_integration,
            "/api/actions/package": self._action_package,
            "/api/actions/audit": self._action_audit,
        }
        action = actions.get(path)
        if action is None:
            return 404, {"error": f"Unknown API route: {path}"}
        try:
            result = action(body)
        except Exception as exc:
            return 500, {"error": str(exc), "state": self._state()}
        if isinstance(result, tuple):
            return result
        return 200, {"result": result, "state": self._state()}

    def _state(self) -> dict[str, Any]:
        project = self.project_dir
        input_path = project / "work" / "wcca_input.yaml"
        results_path = project / "output" / "calculation" / "results.json"
        input_document = _read_yaml_or_empty(input_path)
        results_document = _read_json_or_empty(results_path)
        validation_issues = validate_input_document(input_document, release=True) if input_document else []
        result_issues = validate_results(input_document, results_document) if input_document and results_document else []
        if (project / "release" / "wcca_package.zip").exists():
            audit_result = audit_project(project)
        else:
            audit_result = {
                "status": "not_run",
                "summary": {"error_count": 0, "warning_count": 0},
                "issues": [],
            }
        workflow = workflow_status(project)
        return {
            "project_dir": str(project),
            "project_name": input_document.get("project", {}).get("name", project.name),
            "files": _file_status(project),
            "summary": _result_summary(results_document),
            "validation": {
                "input_status": "failed" if has_errors(validation_issues) else "passed",
                "input_issue_count": len(validation_issues),
                "result_status": "failed" if has_errors(result_issues) else "passed",
                "result_issue_count": len(result_issues),
            },
            "workflow": workflow,
            "audit": audit_result,
            "blocks": _block_rows(input_document, results_document),
            "risks": results_document.get("risk_items", []),
            "artifacts": _artifact_links(project),
        }

    def _read_project_file(self, rel_path: str) -> tuple[int, Any]:
        target = _resolve_project_path(self.project_dir, rel_path)
        if target is None or not target.exists() or not target.is_file():
            return 404, {"error": "File not found"}
        suffix = target.suffix.lower()
        if suffix in {".json"}:
            return 200, {"path": rel_path, "content_type": "json", "content": read_json(target)}
        if suffix in {".yaml", ".yml"}:
            return 200, {"path": rel_path, "content_type": "yaml", "content": read_yaml(target)}
        if suffix in {".md", ".txt", ".csv"}:
            return 200, {"path": rel_path, "content_type": "text", "content": target.read_text(encoding="utf-8")}
        return 200, {"path": rel_path, "content_type": "binary", "size_bytes": target.stat().st_size}

    def _action_init(self, body: dict[str, Any]) -> dict[str, Any]:
        project = body.get("project_dir") or str(self.project_dir)
        name = body.get("name")
        self.project_dir = init_project(project, name)
        return {"project_dir": str(self.project_dir)}

    def _action_ingest(self, body: dict[str, Any]) -> dict[str, Any]:
        return ingest_project(self.project_dir)

    def _action_extract(self, body: dict[str, Any]) -> dict[str, Any]:
        return extract_project(self.project_dir)

    def _action_normalize(self, body: dict[str, Any]) -> dict[str, Any]:
        return normalize_project(self.project_dir)

    def _action_input_build(self, body: dict[str, Any]) -> dict[str, Any]:
        return build_input_draft(self.project_dir)

    def _action_validate_input(self, body: dict[str, Any]) -> dict[str, Any]:
        document = read_yaml(self.project_dir / "work" / "wcca_input.yaml")
        issues = validate_input_document(document, release=bool(body.get("release", True)))
        return {"status": "failed" if has_errors(issues) else "passed", "issues": issues}

    def _action_calculate(self, body: dict[str, Any]) -> dict[str, Any]:
        input_path = self.project_dir / "work" / "wcca_input.yaml"
        document = read_yaml(input_path)
        calculation = calculate_document(document, input_path=input_path)
        write_calculation_outputs(self.project_dir / "output" / "calculation", calculation)
        return {"status": calculation.get("status"), "result_count": len(calculation.get("results", []))}

    def _action_validate_results(self, body: dict[str, Any]) -> dict[str, Any]:
        document = read_yaml(self.project_dir / "work" / "wcca_input.yaml")
        results = read_json(self.project_dir / "output" / "calculation" / "results.json")
        issues = validate_results(document, results)
        return {"status": "failed" if has_errors(issues) else "passed", "issues": issues}

    def _action_report_export(self, body: dict[str, Any]) -> dict[str, Any]:
        document = read_yaml(self.project_dir / "work" / "wcca_input.yaml")
        results = read_json(self.project_dir / "output" / "calculation" / "results.json")
        return export_report_documents(self.project_dir, document, results, self.project_dir / "output" / "report")

    def _action_document_build(self, body: dict[str, Any]) -> dict[str, Any]:
        input_path = self.project_dir / "work" / "wcca_input.yaml"
        results_path = self.project_dir / "output" / "calculation" / "results.json"
        knowledge_config = load_knowledge_config(body.get("knowledge_config") or "examples/knowledge_local.yaml")
        return build_document_package(
            read_yaml(input_path),
            read_json(results_path),
            self.project_dir / "output" / "document",
            knowledge_config=knowledge_config,
            input_path=input_path,
            results_path=results_path,
        )

    def _action_validate_document(self, body: dict[str, Any]) -> dict[str, Any]:
        issues = validate_document_package(self.project_dir)
        return {"status": "failed" if has_errors(issues) else "passed", "issues": issues}

    def _action_simulate(self, body: dict[str, Any]) -> dict[str, Any]:
        document = read_yaml(self.project_dir / "work" / "wcca_input.yaml")
        return run_simulation_interface(self.project_dir, document, simulator=body.get("simulator", "not_configured"))

    def _action_agent_run(self, body: dict[str, Any]) -> dict[str, Any]:
        return run_agent_automation(
            self.project_dir,
            llm_config=load_llm_config(body.get("llm_config") or "examples/llm_none.yaml"),
            knowledge_config=load_knowledge_config(body.get("knowledge_config") or "examples/knowledge_local.yaml"),
        )

    def _action_review_checklist(self, body: dict[str, Any]) -> dict[str, Any]:
        return generate_review_checklist(
            self.project_dir / "work" / "wcca_input.yaml",
            self.project_dir / "review" / "comments",
            self.project_dir / "output" / "calculation" / "results.json",
        )

    def _action_review_flow(self, body: dict[str, Any]) -> dict[str, Any]:
        action = body.get("action", "start")
        return transition_review_workflow(
            self.project_dir,
            action,
            reviewer=body.get("reviewer") or "web_user",
            comment=body.get("comment", ""),
        )

    def _action_approve(self, body: dict[str, Any]) -> dict[str, Any]:
        reviewer = body.get("reviewer") or "web_user"
        decision = body.get("decision") or "approved"
        record = approve_project(
            self.project_dir / "work" / "wcca_input.yaml",
            self.project_dir / "output" / "calculation" / "results.json",
            self.project_dir / "review" / "approvals",
            reviewer=reviewer,
            decision=decision,
            comment=body.get("comment", ""),
        )
        transition_review_workflow(self.project_dir, "approve" if decision == "approved" else "reject", reviewer=reviewer)
        return record

    def _action_integration(self, body: dict[str, Any]) -> dict[str, Any]:
        config_path = body.get("config") or "examples/integration_filesystem.yaml"
        return dispatch_enterprise_integration(self.project_dir, read_yaml(config_path))

    def _action_package(self, body: dict[str, Any]) -> dict[str, Any]:
        from .cli import _package

        output = self.project_dir / "release" / "wcca_package.zip"
        status = _package(str(self.project_dir), str(output))
        return {"status": status, "package": str(output)}

    def _action_audit(self, body: dict[str, Any]) -> dict[str, Any]:
        return audit_project(self.project_dir)


class WccaRequestHandler(BaseHTTPRequestHandler):
    app: WccaWebApp

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            status, payload = self.app.handle_get(parsed.path, parse_qs(parsed.query))
            self._send_json(status, payload)
            return
        self._send_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json(404, {"error": "Not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8") if length else "{}"
            body = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            self._send_json(400, {"error": f"Invalid JSON: {exc}"})
            return
        status, payload = self.app.handle_post(parsed.path, body)
        self._send_json(status, payload)

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_static(self, request_path: str) -> None:
        rel = unquote(request_path.lstrip("/")) or "index.html"
        if rel == "app":
            rel = "index.html"
        target = (STATIC_ROOT / rel).resolve()
        if not str(target).startswith(str(STATIC_ROOT.resolve())) or not target.exists() or target.is_dir():
            target = STATIC_ROOT / "index.html"
        data = target.read_bytes()
        mime = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def create_server(host: str = "127.0.0.1", port: int = 8765, project_dir: str | Path = "examples/project_sample") -> ThreadingHTTPServer:
    app = WccaWebApp(project_dir)

    class Handler(WccaRequestHandler):
        pass

    Handler.app = app
    return ThreadingHTTPServer((host, port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wcca-web", description="WCCA Web Platform")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--project", default="examples/project_sample")
    args = parser.parse_args(argv)
    server = create_server(args.host, args.port, args.project)
    print(f"WCCA Web Platform running at http://{args.host}:{args.port}/")
    print(f"project={Path(args.project).resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def _read_yaml_or_empty(path: Path) -> dict[str, Any]:
    return read_yaml(path) if path.exists() else {}


def _read_json_or_empty(path: Path) -> dict[str, Any]:
    return read_json(path) if path.exists() else {}


def _file_status(project: Path) -> dict[str, bool]:
    return {
        "input": (project / "work" / "wcca_input.yaml").exists(),
        "results": (project / "output" / "calculation" / "results.json").exists(),
        "report": (project / "output" / "report" / "wcca_report.md").exists(),
        "document": (project / "output" / "document" / "wcca_document.md").exists(),
        "agent_run": (project / "work" / "agents" / "agent_run.json").exists(),
        "workflow": (project / "review" / "workflow.json").exists(),
        "integration": (project / "output" / "integration" / "integration_manifest.json").exists(),
        "package": (project / "release" / "wcca_package.zip").exists(),
    }


def _result_summary(results: dict[str, Any]) -> dict[str, Any]:
    rows = results.get("results", [])
    pass_count = sum(1 for item in rows if item.get("summary_result", {}).get("pass_fail") == "pass")
    fail_count = sum(1 for item in rows if item.get("summary_result", {}).get("pass_fail") == "fail")
    margins = [
        item.get("summary_result", {}).get(field)
        for item in rows
        for field in ("margin_min", "margin_max")
        if isinstance(item.get("summary_result", {}).get(field), (int, float))
    ]
    return {
        "status": results.get("status", "not_run"),
        "release_status": results.get("release_status", "unknown"),
        "result_count": len(rows),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "min_margin": min(margins) if margins else None,
    }


def _block_rows(input_document: dict[str, Any], results_document: dict[str, Any]) -> list[dict[str, Any]]:
    result_by_block = {item.get("circuit_block_id"): item for item in results_document.get("results", [])}
    rows = []
    for block in input_document.get("circuit_blocks", []):
        result = result_by_block.get(block.get("id"), {})
        summary = result.get("summary_result", {})
        rows.append({
            "id": block.get("id"),
            "name": block.get("name"),
            "type": block.get("type"),
            "model": block.get("selected_model", {}).get("model_id"),
            "pass_fail": summary.get("pass_fail"),
            "worst_min": summary.get("worst_min"),
            "worst_max": summary.get("worst_max"),
            "margin_min": summary.get("margin_min"),
            "margin_max": summary.get("margin_max"),
        })
    return rows


def _artifact_links(project: Path) -> list[dict[str, str]]:
    candidates = [
        "work/wcca_input.yaml",
        "output/calculation/results.json",
        "output/calculation/risk_items.md",
        "output/document/wcca_document.md",
        "output/document/source_references.md",
        "work/agents/agent_run.json",
        "work/agents/compliance_reviewer.md",
        "review/workflow.json",
        "output/integration/integration_manifest.json",
    ]
    return [
        {"path": rel, "label": rel}
        for rel in candidates
        if (project / rel).exists()
    ]


def _resolve_project_path(project: Path, rel_path: str) -> Path | None:
    if not rel_path:
        return None
    target = (project / rel_path).resolve()
    try:
        target.relative_to(project.resolve())
    except ValueError:
        return None
    return target


def _model_record(model: Any) -> dict[str, Any]:
    return {
        "model_id": model.model_id,
        "version": model.version,
        "status": model.metadata.get("status"),
        "kb_card_id": model.metadata.get("kb_card_id"),
        "circuit_types": model.metadata.get("circuit_types", []),
        "inputs": model.metadata.get("inputs", []),
    }


if __name__ == "__main__":
    raise SystemExit(main())
