import json
import shutil
import tempfile
import unittest
from pathlib import Path

from wcca_cli.webapp import WccaWebApp, STATIC_ROOT


class WebAppTest(unittest.TestCase):
    def test_state_and_models_api(self):
        app = WccaWebApp("examples/project_sample")

        status, state = app.handle_get("/api/state", {})
        self.assertEqual(status, 200)
        self.assertEqual(state["project_name"], "Phase1Sample")
        self.assertGreaterEqual(state["summary"]["result_count"], 4)

        status, models = app.handle_get("/api/models", {})
        self.assertEqual(status, 200)
        self.assertTrue(any(model["model_id"] == "dcdc_feedback" for model in models["models"]))

    def test_agent_workflow_and_integration_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = _prepare_project(Path(temp_dir))
            app = WccaWebApp(project)

            status, agent = app.handle_post("/api/actions/agent-run", {
                "llm_config": "examples/llm_none.yaml",
                "knowledge_config": "examples/knowledge_local.yaml",
            })
            self.assertEqual(status, 200, agent)
            self.assertTrue((project / "work" / "agents" / "agent_run.json").exists())

            status, workflow = app.handle_post("/api/actions/review-flow", {
                "action": "start",
                "reviewer": "web_test",
            })
            self.assertEqual(status, 200, workflow)
            self.assertEqual(workflow["result"]["state"], "in_review")

            status, integration = app.handle_post("/api/actions/integration-dispatch", {})
            self.assertEqual(status, 200, integration)
            self.assertTrue((project / "output" / "integration" / "integration_manifest.json").exists())

    def test_file_api_and_static_assets(self):
        app = WccaWebApp("examples/project_sample")

        status, payload = app.handle_get("/api/file", {"path": ["output/calculation/results.json"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["content_type"], "json")
        self.assertEqual(payload["content"]["status"], "calculated")

        self.assertTrue((STATIC_ROOT / "index.html").exists())
        self.assertIn("WCCA Platform", (STATIC_ROOT / "index.html").read_text(encoding="utf-8"))


def _prepare_project(parent: Path) -> Path:
    project = parent / "web_project"
    (project / "work").mkdir(parents=True)
    (project / "output" / "calculation").mkdir(parents=True)
    shutil.copyfile("examples/project_sample/work/wcca_input.yaml", project / "work" / "wcca_input.yaml")
    shutil.copyfile("examples/project_sample/output/calculation/results.json", project / "output" / "calculation" / "results.json")
    return project


if __name__ == "__main__":
    unittest.main()
