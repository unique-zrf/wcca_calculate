import contextlib
import hashlib
import io
import shutil
import tempfile
import unittest
from pathlib import Path

from wcca_cli.cli import main
from wcca_cli.docgen import build_document_package
from wcca_cli.docgen import validate_document_package
from wcca_cli.engine import calculate_document
from wcca_cli.io import read_json, read_yaml, write_json
from wcca_cli.knowledge_providers import query_knowledge
from wcca_cli.report_export import export_report_documents


SAMPLE_INPUT = Path("examples/project_sample/work/wcca_input.yaml")


class DocumentGenerationTest(unittest.TestCase):
    def test_local_knowledge_provider_returns_model_card_hits(self):
        hits = query_knowledge("resistor_divider", {"provider": "local"}, limit=3)

        self.assertTrue(hits)
        self.assertEqual(hits[0].provider, "local")
        self.assertTrue(any("resistor_divider" in hit.title or "resistor_divider" in hit.content for hit in hits))

    def test_document_package_writes_traceable_outputs(self):
        input_document = read_yaml(SAMPLE_INPUT)
        results_document = calculate_document(input_document, input_path=SAMPLE_INPUT)

        output_dir = Path("examples/project_sample/output/test_document_generation/package")
        manifest = build_document_package(
            input_document,
            results_document,
            output_dir,
            knowledge_config={"provider": "local"},
            citation_limit=2,
            input_path=SAMPLE_INPUT,
            results_path=Path("examples/project_sample/output/calculation/results.json"),
        )

        document_path = Path(manifest["document"])
        references_path = Path(manifest["source_references"])
        traceability_path = Path(manifest["traceability_matrix"])
        evidence_path = Path(manifest["evidence_candidates"])
        self.assertTrue(document_path.exists())
        self.assertTrue(references_path.exists())
        self.assertTrue(traceability_path.exists())
        self.assertTrue(evidence_path.exists())
        self.assertEqual(manifest["input_sha256"], read_json(output_dir / "docgen_manifest.json")["input_sha256"])
        self.assertIn("Calculation Results", document_path.read_text(encoding="utf-8"))
        self.assertIn("requirement_id", traceability_path.read_text(encoding="utf-8").splitlines()[0])

    def test_cli_document_build_generates_manifest(self):
        output_dir = Path("examples/project_sample/output/test_document_generation/cli")
        results_path = output_dir / "results.json"
        input_document = read_yaml(SAMPLE_INPUT)
        results_document = calculate_document(input_document, input_path=SAMPLE_INPUT)
        write_json(results_path, results_document)

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "document-build",
                "--input",
                str(SAMPLE_INPUT),
                "--results",
                str(results_path),
                "--output",
                str(output_dir),
                "--knowledge-config",
                "examples/knowledge_local.yaml",
            ])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        self.assertTrue((output_dir / "docgen_manifest.json").exists())
        manifest = read_json(output_dir / "docgen_manifest.json")
        self.assertIsNotNone(manifest["input_sha256"])
        self.assertIsNotNone(manifest["results_sha256"])

    def test_cli_validate_document_rejects_tampered_document(self):
        output_dir = Path("examples/project_sample/output/document")
        input_document = read_yaml(SAMPLE_INPUT)
        results_document = read_json("examples/project_sample/output/calculation/results.json")
        build_document_package(
            input_document,
            results_document,
            output_dir,
            knowledge_config={"provider": "local"},
            input_path=SAMPLE_INPUT,
            results_path="examples/project_sample/output/calculation/results.json",
        )
        document_path = output_dir / "wcca_document.md"
        original = document_path.read_text(encoding="utf-8")
        try:
            document_path.write_text(original + "\nTampered.\n", encoding="utf-8")
            issues = validate_document_package("examples/project_sample")
            self.assertTrue(any("hash mismatch" in issue["message"] for issue in issues), issues)
        finally:
            document_path.write_text(original, encoding="utf-8")

    def test_cli_kb_query_uses_configured_provider(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "kb",
                "query",
                "resistor_divider",
                "--config",
                "examples/knowledge_local.yaml",
            ])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        self.assertIn("local", stdout.getvalue())

    def test_cli_extract_parameters_writes_review_required_candidates(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "extract-parameters",
                "--project",
                "examples/project_sample",
                "--knowledge-config",
                "examples/knowledge_local.yaml",
            ])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        candidates = read_yaml("examples/project_sample/work/extracted/parameter_candidates.yaml")
        self.assertEqual(candidates["summary"]["release_ready_count"], 0)
        self.assertTrue(all(item["review_status"] == "knowledge_extracted" for item in candidates["candidates"]))

    def test_cli_simulate_writes_skipped_summary_when_not_configured(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "simulate",
                "--project",
                "examples/project_sample",
            ])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        summary = read_json("examples/project_sample/output/simulation/simulation_summary.json")
        self.assertEqual(summary["status"], "skipped")
        self.assertGreater(summary["block_count"], 0)

    def test_report_export_writes_docx_and_pdf(self):
        input_document = read_yaml(SAMPLE_INPUT)
        results_document = calculate_document(input_document, input_path=SAMPLE_INPUT)
        output_dir = Path("examples/project_sample/output/test_report_export")
        exported = export_report_documents("examples/project_sample", input_document, results_document, output_dir)

        self.assertTrue(Path(exported["docx"]).exists())
        self.assertTrue(Path(exported["pdf"]).exists())
        self.assertTrue((output_dir / "wcca_report.md").exists())
        self.assertIn("WCCA Report Draft", (output_dir / "wcca_report.md").read_text(encoding="utf-8"))

    def test_cli_report_export_generates_artifacts(self):
        output_dir = Path("examples/project_sample/output/test_report_export_cli")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            exit_code = main([
                "report-export",
                "--input",
                str(SAMPLE_INPUT),
                "--results",
                "examples/project_sample/output/calculation/results.json",
                "--output",
                str(output_dir),
            ])

        self.assertEqual(exit_code, 0, stdout.getvalue())
        self.assertTrue((output_dir / "wcca_report.docx").exists())
        self.assertTrue((output_dir / "wcca_report.pdf").exists())

    def test_cli_agent_plan_writes_guardrailed_plan_without_llm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _prepare_agent_project(Path(temp_dir))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "agent-plan",
                    "--project",
                    str(project),
                    "--llm-config",
                    "examples/llm_none.yaml",
                ])

            self.assertEqual(exit_code, 0, stdout.getvalue())
            workplan = read_yaml(project / "work" / "agents" / "agent_workplan.yaml")
            self.assertEqual(workplan["llm_assistance"]["status"], "skipped")
            self.assertTrue(any("must not approve" in item for item in workplan["guardrails"]))
            self.assertEqual(workplan["llm_assistance"]["prompt_path"], "work/agents/llm_prompt.md")
            self.assertEqual(workplan["llm_assistance"]["call_record_path"], "work/agents/llm_call.json")
            prompt_path = project / "work" / "agents" / "llm_prompt.md"
            call_record = read_json(project / "work" / "agents" / "llm_call.json")
            self.assertTrue(prompt_path.exists())
            self.assertIn("Guardrails", prompt_path.read_text(encoding="utf-8"))
            self.assertEqual(
                call_record["prompt_sha256"],
                hashlib.sha256(prompt_path.read_text(encoding="utf-8").rstrip("\n").encode("utf-8")).hexdigest(),
            )
            self.assertEqual(call_record["status"], "skipped")

    def test_cli_agent_run_writes_role_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _prepare_agent_project(Path(temp_dir))

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "agent-run",
                    "--project",
                    str(project),
                    "--llm-config",
                    "examples/llm_none.yaml",
                    "--knowledge-config",
                    "examples/knowledge_local.yaml",
                ])

            self.assertEqual(exit_code, 0, stdout.getvalue())
            manifest = read_json(project / "work" / "agents" / "agent_run.json")
            self.assertEqual(manifest["artifact_count"], 6)
            self.assertTrue((project / "work" / "agents" / "planner.md").exists())
            self.assertTrue((project / "work" / "agents" / "compliance_reviewer.md").exists())

    def test_cli_review_flow_and_integration_dispatch(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _prepare_agent_project(Path(temp_dir))

            flow_stdout = io.StringIO()
            with contextlib.redirect_stdout(flow_stdout):
                flow_status = main([
                    "review-flow",
                    "--project",
                    str(project),
                    "--action",
                    "start",
                    "--reviewer",
                    "workflow_tester",
                ])

            self.assertEqual(flow_status, 0, flow_stdout.getvalue())
            workflow = read_json(project / "review" / "workflow.json")
            self.assertEqual(workflow["state"], "in_review")
            self.assertTrue(workflow["readiness"]["release_ready"])

            integration_stdout = io.StringIO()
            with contextlib.redirect_stdout(integration_stdout):
                integration_status = main([
                    "integration-dispatch",
                    "--project",
                    str(project),
                ])

            self.assertEqual(integration_status, 0, integration_stdout.getvalue())
            self.assertTrue((project / "output" / "integration" / "integration_manifest.json").exists())
            self.assertTrue((project / "output" / "integration" / "integration_payload.json").exists())

    def test_cli_agent_plan_records_llm_command_failure_without_blocking_plan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _prepare_agent_project(Path(temp_dir))
            output_path = project / "work" / "agents" / "llm_review.md"

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "agent-plan",
                    "--project",
                    str(project),
                    "--llm-config",
                    "examples/llm_claude_cli.yaml",
                ])

            self.assertEqual(exit_code, 0, stdout.getvalue())
            workplan = read_yaml(project / "work" / "agents" / "agent_workplan.yaml")
            self.assertIn(workplan["llm_assistance"]["status"], {"completed", "failed"})
            self.assertTrue((project / "work" / "agents" / "llm_call.json").exists())
            self.assertFalse(output_path.exists() and workplan["llm_assistance"]["status"] == "failed")

def _prepare_agent_project(parent: Path) -> Path:
    project = parent / "agent_project"
    (project / "work").mkdir(parents=True)
    (project / "output" / "calculation").mkdir(parents=True)
    (project / "review").mkdir(parents=True)
    shutil.copyfile(SAMPLE_INPUT, project / "work" / "wcca_input.yaml")
    shutil.copyfile("examples/project_sample/output/calculation/results.json", project / "output" / "calculation" / "results.json")
    input_index = Path("examples/project_sample/work/input_index.yaml")
    if input_index.exists():
        shutil.copyfile(input_index, project / "work" / "input_index.yaml")
    return project


if __name__ == "__main__":
    unittest.main()
