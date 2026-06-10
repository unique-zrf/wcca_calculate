from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
import zipfile
from pathlib import Path

from .agents import build_agent_workplan
from .agent_runtime import run_agent_automation
from .audit import audit_project
from .docgen import build_document_package
from .docgen import validate_document_package
from .engine import calculate_document, write_calculation_outputs
from .enterprise_integration import dispatch_enterprise_integration
from .extraction import extract_project
from .input_builder import build_input_draft
from .io import read_json, read_yaml, write_json
from .knowledge import search_knowledge, show_knowledge, validate_knowledge_cards
from .knowledge_providers import load_knowledge_config, query_knowledge
from .llm import load_llm_config
from .normalization import normalize_project
from .parameter_extraction import extract_parameter_candidates
from .project import ingest_project, init_project
from .report_export import export_report_documents
from .registry import get_model, iter_models
from .reporting import result_status, validate_results, write_markdown_report
from .review import approve_project, generate_review_checklist
from .simulation import run_simulation_interface
from .validation import has_errors, validate_input_document
from .workflow import transition_review_workflow, workflow_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wcca", description="WCCA Core CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    model_parser = subparsers.add_parser("model", help="Inspect calculation models")
    model_subparsers = model_parser.add_subparsers(dest="model_command", required=True)
    model_list = model_subparsers.add_parser("list", help="List models")
    model_list.add_argument("--status")
    model_show = model_subparsers.add_parser("show", help="Show one model")
    model_show.add_argument("model_id")
    model_show.add_argument("--version")
    model_diff = model_subparsers.add_parser("diff", help="Diff two model metadata versions")
    model_diff.add_argument("model_id")
    model_diff.add_argument("--from-version", required=True)
    model_diff.add_argument("--to-version", required=True)

    init = subparsers.add_parser("init", help="Create a WCCA project directory")
    init.add_argument("--project", required=True)
    init.add_argument("--name")

    ingest = subparsers.add_parser("ingest", help="Index project input files")
    ingest.add_argument("--project", required=True)

    extract = subparsers.add_parser("extract", help="Extract structured BOM components")
    extract.add_argument("--project", required=True)

    normalize = subparsers.add_parser("normalize", help="Normalize extracted parameters")
    normalize.add_argument("--project", required=True)

    input_build = subparsers.add_parser("input-build", help="Build draft wcca_input.yaml from normalized data")
    input_build.add_argument("--project", required=True)

    extract_parameters = subparsers.add_parser("extract-parameters", help="Extract parameter candidates from configured knowledge provider")
    extract_parameters.add_argument("--project", required=True)
    extract_parameters.add_argument("--input")
    extract_parameters.add_argument("--knowledge-config")
    extract_parameters.add_argument("--limit", type=int, default=3)

    validate_input = subparsers.add_parser("validate-input", help="Validate wcca_input.yaml")
    validate_input.add_argument("--input", required=True)
    validate_input.add_argument("--release", action="store_true")

    validate_kb = subparsers.add_parser("validate-kb", help="Validate knowledge model cards and hashes")

    kb_parser = subparsers.add_parser("kb", help="Search local knowledge base")
    kb_subparsers = kb_parser.add_subparsers(dest="kb_command", required=True)
    kb_search = kb_subparsers.add_parser("search", help="Search knowledge base")
    kb_search.add_argument("query")
    kb_search.add_argument("--limit", type=int, default=10)
    kb_show = kb_subparsers.add_parser("show", help="Show a knowledge item")
    kb_show.add_argument("identifier")
    kb_query = kb_subparsers.add_parser("query", help="Query configured local/RAG knowledge provider")
    kb_query.add_argument("query")
    kb_query.add_argument("--config")
    kb_query.add_argument("--limit", type=int, default=5)

    calculate = subparsers.add_parser("calculate", help="Run calculations")
    calculate.add_argument("--input", required=True)
    calculate.add_argument("--output", required=True)

    simulate = subparsers.add_parser("simulate", help="Run or summarize configured circuit simulations")
    simulate.add_argument("--project", required=True)
    simulate.add_argument("--input")
    simulate.add_argument("--output")
    simulate.add_argument("--simulator", default="not_configured")

    agent_plan = subparsers.add_parser("agent-plan", help="Build deterministic WCCA agent workplan with optional LLM suggestions")
    agent_plan.add_argument("--project", required=True)
    agent_plan.add_argument("--llm-config")

    agent_run = subparsers.add_parser("agent-run", help="Run deterministic multi-agent automation and write role artifacts")
    agent_run.add_argument("--project", required=True)
    agent_run.add_argument("--llm-config")
    agent_run.add_argument("--knowledge-config")

    validate = subparsers.add_parser("validate", help="Validate calculation results")
    validate.add_argument("--input", required=True)
    validate.add_argument("--results", required=True)

    report = subparsers.add_parser("report", help="Generate report draft")
    report.add_argument("--input", required=True)
    report.add_argument("--results", required=True)
    report.add_argument("--output", required=True)

    report_export = subparsers.add_parser("report-export", help="Export report draft to DOCX and PDF")
    report_export.add_argument("--input", required=True)
    report_export.add_argument("--results", required=True)
    report_export.add_argument("--output", required=True)

    document_build = subparsers.add_parser("document-build", help="Generate WCCA document package with traceability")
    document_build.add_argument("--input", required=True)
    document_build.add_argument("--results", required=True)
    document_build.add_argument("--output", required=True)
    document_build.add_argument("--knowledge-config")
    document_build.add_argument("--citation-limit", type=int, default=3)

    validate_document = subparsers.add_parser("validate-document", help="Validate WCCA document package")
    validate_document.add_argument("--project", required=True)

    review = subparsers.add_parser("review-checklist", help="Generate engineering review checklist")
    review.add_argument("--input", required=True)
    review.add_argument("--results")
    review.add_argument("--output", required=True)

    approve = subparsers.add_parser("approve", help="Write approval record after release validation")
    approve.add_argument("--input", required=True)
    approve.add_argument("--results", required=True)
    approve.add_argument("--output", required=True)
    approve.add_argument("--reviewer", required=True)
    approve.add_argument("--decision", choices=["approved", "rejected"], required=True)
    approve.add_argument("--comment", default="")

    review_flow = subparsers.add_parser("review-flow", help="Advance or inspect the platform approval workflow state")
    review_flow.add_argument("--project", required=True)
    review_flow.add_argument("--action", choices=["status", "refresh", "start", "approve", "reject", "archive"], default="status")
    review_flow.add_argument("--reviewer")
    review_flow.add_argument("--comment", default="")

    integration = subparsers.add_parser("integration-dispatch", help="Export release payload to enterprise integration targets")
    integration.add_argument("--project", required=True)
    integration.add_argument("--config")

    audit = subparsers.add_parser("audit", help="Audit project traceability and release package")
    audit.add_argument("--project", required=True)

    package = subparsers.add_parser("package", help="Create archive package")
    package.add_argument("--project", required=True)
    package.add_argument("--output", required=True)

    web = subparsers.add_parser("web", help="Run the local WCCA web platform")
    web.add_argument("--project", default="examples/project_sample")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)

    args = parser.parse_args(argv)

    if args.command == "model":
        return _model(args)
    if args.command == "init":
        project = init_project(args.project, args.name)
        print(f"project={project.resolve()}")
        print(f"input={Path(args.project, 'work', 'wcca_input.yaml').resolve()}")
        return 0
    if args.command == "ingest":
        index = ingest_project(args.project)
        print(f"indexed_documents={len(index['documents'])}")
        print(f"index={Path(args.project, 'work', 'input_index.yaml').resolve()}")
        return 0
    if args.command == "extract":
        extracted = extract_project(args.project)
        print(f"component_count={extracted['summary']['component_count']}")
        print(f"components={Path(args.project, 'work', 'extracted', 'components.yaml').resolve()}")
        print(f"parameter_draft={Path(args.project, 'work', 'extracted', 'parameter_draft.yaml').resolve()}")
        return 0
    if args.command == "normalize":
        normalized = normalize_project(args.project)
        print(f"parameter_count={normalized['parameters']['summary']['parameter_count']}")
        print(f"candidate_count={len(normalized['model_candidates']['candidates'])}")
        print(f"parameters={Path(args.project, 'work', 'normalized', 'parameters.yaml').resolve()}")
        print(f"model_candidates={Path(args.project, 'work', 'normalized', 'model_candidates.yaml').resolve()}")
        return 0
    if args.command == "input-build":
        draft = build_input_draft(args.project)
        print(f"draft_blocks={len(draft['circuit_blocks'])}")
        print(f"draft={Path(args.project, 'work', 'wcca_input_draft.yaml').resolve()}")
        return 0
    if args.command == "extract-parameters":
        input_path = args.input or str(Path(args.project, "work", "wcca_input.yaml"))
        document = read_yaml(input_path)
        knowledge_config = load_knowledge_config(args.knowledge_config)
        extracted = extract_parameter_candidates(args.project, document, knowledge_config=knowledge_config, limit=args.limit)
        print(f"candidate_count={extracted['summary']['candidate_count']}")
        print(f"review_required_count={extracted['summary']['review_required_count']}")
        print(f"candidates={Path(args.project, 'work', 'extracted', 'parameter_candidates.yaml').resolve()}")
        return 0
    if args.command == "validate-input":
        document = read_yaml(args.input)
        issues = validate_input_document(document, release=args.release)
        _print_issues(issues)
        return 1 if has_errors(issues) else 0
    if args.command == "validate-kb":
        issues = validate_knowledge_cards()
        _print_issues(issues)
        return 1 if has_errors(issues) else 0
    if args.command == "kb":
        return _kb(args)
    if args.command == "calculate":
        document = read_yaml(args.input)
        calculation = calculate_document(document, input_path=args.input)
        write_calculation_outputs(args.output, calculation)
        print(f"calculation_status={calculation['status']}")
        print(f"output={Path(args.output).resolve()}")
        return 1 if calculation["status"] != "calculated" else 0
    if args.command == "simulate":
        input_path = args.input or str(Path(args.project, "work", "wcca_input.yaml"))
        document = read_yaml(input_path)
        summary = run_simulation_interface(args.project, document, output_dir=args.output, simulator=args.simulator)
        print(f"simulation_status={summary['status']}")
        print(f"block_count={summary['block_count']}")
        print(f"output={Path(args.output or Path(args.project, 'output', 'simulation')).resolve()}")
        return 0
    if args.command == "agent-plan":
        llm_config = load_llm_config(args.llm_config)
        workplan = build_agent_workplan(args.project, llm_config=llm_config)
        print(f"roles={len(workplan['roles'])}")
        print(f"llm_status={workplan['llm_assistance']['status']}")
        print(f"workplan={Path(args.project, 'work', 'agents', 'agent_workplan.yaml').resolve()}")
        return 0
    if args.command == "agent-run":
        llm_config = load_llm_config(args.llm_config)
        knowledge_config = load_knowledge_config(args.knowledge_config)
        run = run_agent_automation(args.project, llm_config=llm_config, knowledge_config=knowledge_config)
        print(f"agent_run_status=completed")
        print(f"artifact_count={run['artifact_count']}")
        print(f"release_ready={run['readiness']['release_ready']}")
        print(f"manifest={Path(args.project, 'work', 'agents', 'agent_run.json').resolve()}")
        return 0
    if args.command == "validate":
        input_document = read_yaml(args.input)
        results_document = read_json(args.results)
        issues = validate_results(input_document, results_document)
        _print_issues(issues)
        status = result_status(issues)
        print(f"validation_status={status}")
        return 1 if status == "failed" else 0
    if args.command == "report":
        input_document = read_yaml(args.input)
        results_document = read_json(args.results)
        report_path = write_markdown_report(args.output, input_document, results_document)
        print(f"report={report_path.resolve()}")
        return 0
    if args.command == "report-export":
        input_document = read_yaml(args.input)
        results_document = read_json(args.results)
        exported = export_report_documents(Path(args.input).parent.parent, input_document, results_document, args.output)
        print(f"markdown={Path(exported['markdown']).resolve()}")
        print(f"docx={Path(exported['docx']).resolve()}")
        print(f"pdf={Path(exported['pdf']).resolve()}")
        return 0
    if args.command == "document-build":
        input_document = read_yaml(args.input)
        results_document = read_json(args.results)
        knowledge_config = load_knowledge_config(args.knowledge_config)
        manifest = build_document_package(
            input_document,
            results_document,
            args.output,
            knowledge_config=knowledge_config,
            citation_limit=args.citation_limit,
            input_path=args.input,
            results_path=args.results,
        )
        print(f"document={Path(manifest['document']).resolve()}")
        print(f"traceability_matrix={Path(manifest['traceability_matrix']).resolve()}")
        print(f"citation_count={manifest['citation_count']}")
        return 0
    if args.command == "validate-document":
        issues = validate_document_package(args.project)
        _print_issues(issues)
        status = "failed" if has_errors(issues) else "passed"
        print(f"document_validation_status={status}")
        return 1 if status == "failed" else 0
    if args.command == "review-checklist":
        checklist = generate_review_checklist(args.input, args.output, args.results)
        print(f"review_items={checklist['summary']['item_count']}")
        print(f"blocking_issues={checklist['summary']['blocking_issue_count']}")
        print(f"checklist={Path(args.output, 'review_checklist.md').resolve()}")
        return 0
    if args.command == "approve":
        try:
            record = approve_project(args.input, args.results, args.output, args.reviewer, args.decision, args.comment)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        project_dir = Path(args.output).parent.parent
        if project_dir.name == "review":
            project_dir = project_dir.parent
        try:
            transition_review_workflow(
                project_dir,
                "approve" if args.decision == "approved" else "reject",
                reviewer=args.reviewer,
                comment=args.comment,
            )
        except ValueError:
            pass
        print(f"decision={record['decision']}")
        print(f"validation_status={record['validation_status']}")
        print(f"approval={Path(args.output, 'approval_record.md').resolve()}")
        return 0
    if args.command == "review-flow":
        if args.action == "status":
            status = workflow_status(args.project)
            print(f"workflow_state={status['state']}")
            print(f"history_count={status['history_count']}")
            return 0
        try:
            workflow = transition_review_workflow(args.project, args.action, reviewer=args.reviewer, comment=args.comment)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"workflow_state={workflow['state']}")
        print(f"release_ready={workflow['readiness']['release_ready']}")
        print(f"workflow={Path(args.project, 'review', 'workflow.json').resolve()}")
        return 0
    if args.command == "integration-dispatch":
        config = read_yaml(args.config) if args.config else None
        try:
            manifest = dispatch_enterprise_integration(args.project, config)
        except ValueError as exc:
            print(f"error: {exc}")
            return 1
        print(f"integration_status=completed")
        print(f"target_count={len(manifest['targets'])}")
        print(f"manifest={Path(args.project, 'output', 'integration', 'integration_manifest.json').resolve()}")
        return 0
    if args.command == "audit":
        audit_result = audit_project(args.project)
        for issue in audit_result["issues"]:
            print(f"{issue.get('level')}: {issue.get('path')}: {issue.get('message')}")
        print(f"audit_status={audit_result['status']}")
        print(f"errors={audit_result['summary']['error_count']}")
        return 1 if audit_result["status"] == "failed" else 0
    if args.command == "package":
        return _package(args.project, args.output)
    if args.command == "web":
        from .webapp import main as web_main

        return web_main([
            "--project",
            args.project,
            "--host",
            args.host,
            "--port",
            str(args.port),
        ])
    return 2


def _model(args: argparse.Namespace) -> int:
    if args.model_command == "list":
        for model in iter_models(status=args.status):
            print(f"{model.model_id}\t{model.version}\t{model.metadata.get('status')}\t{model.metadata.get('kb_card_id')}")
        return 0
    if args.model_command == "show":
        model = get_model(args.model_id, args.version)
        print(f"model_id: {model.model_id}")
        print(f"version: {model.version}")
        print(f"status: {model.metadata.get('status')}")
        print(f"kb_card_id: {model.metadata.get('kb_card_id')}")
        print("inputs:")
        for item in model.metadata.get("inputs", []):
            print(f"  - {item['name']}")
        return 0
    if args.model_command == "diff":
        before = get_model(args.model_id, args.from_version)
        after = get_model(args.model_id, args.to_version)
        before_text = _model_yaml_text(before.path)
        after_text = _model_yaml_text(after.path)
        diff = list(difflib.unified_diff(
            before_text,
            after_text,
            fromfile=f"{before.model_id}:{before.version}",
            tofile=f"{after.model_id}:{after.version}",
            lineterm="",
        ))
        if not diff:
            print("no differences")
            return 0
        for line in diff:
            print(line)
        return 1
    return 2


def _kb(args: argparse.Namespace) -> int:
    if args.kb_command == "search":
        results = search_knowledge(args.query, limit=args.limit)
        for result in results:
            print(f"{result['id']}\t{result['doc_type']}\t{result['score']}\t{result['title']}\t{result['path']}")
        if not results:
            print("no matches")
        return 0
    if args.kb_command == "show":
        result = show_knowledge(args.identifier)
        if result is None:
            print(f"not found: {args.identifier}")
            return 1
        print(f"id: {result['id']}")
        print(f"doc_type: {result['doc_type']}")
        print(f"title: {result['title']}")
        print(f"path: {result['path']}")
        print(f"summary: {result['summary']}")
        return 0
    if args.kb_command == "query":
        try:
            config = load_knowledge_config(args.config)
            results = query_knowledge(args.query, config, limit=args.limit)
        except Exception as exc:
            print(f"error: {exc}")
            return 1
        for result in results:
            excerpt = " ".join(result.content.split())[:240]
            print(_console_safe(f"{result.provider}\t{result.score}\t{result.title}\t{result.source}\t{excerpt}"))
        if not results:
            print("no matches")
        return 0
    return 2


def _print_issues(issues: list[dict[str, str]]) -> None:
    if not issues:
        print("no issues")
        return
    for issue in issues:
        print(f"{issue.get('level')}: {issue.get('path')}: {issue.get('message')}")


def _console_safe(text: str) -> str:
    encoding = sys.stdout.encoding or "utf-8"
    return text.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _model_yaml_text(model_path: Path) -> list[str]:
    return (model_path / "model.yaml").read_text(encoding="utf-8").splitlines()


def _package(project_dir: str, output_path: str) -> int:
    project = Path(project_dir)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in project.rglob("*"):
            if path.is_file() and path.resolve() != target.resolve():
                arcname = path.relative_to(project)
                archive.write(path, arcname)
                manifest.append({
                    "path": str(arcname).replace("\\", "/"),
                    "sha256": _file_sha256(path),
                })
        manifest.sort(key=lambda item: item["path"])
        archive.writestr("archive_manifest.json", json.dumps({"files": manifest}, indent=2))
    print(f"package={target.resolve()}")
    return 0


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
