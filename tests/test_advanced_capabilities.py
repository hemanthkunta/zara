"""
Unit tests for ZARA Advanced Capabilities:
- Semantic Vector Store
- Browser Automation & Web Scraping
- Multimodal Vision & OCR
- Multi-Agent Subtask Orchestration
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from modules.vector_memory import SemanticVectorStore
from modules.memory import MemoryStore
from tools.browser import BrowserTool
from modules.vision import VisionModule
from modules.orchestrator import TaskOrchestrator, AgentRole

class TestAdvancedCapabilities(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_adv_test_")
        self.workspace = Path(self.temp_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_semantic_vector_store(self):
        db_path = self.workspace / "test_vectors.db"
        store = SemanticVectorStore(db_path)

        # Upsert documents with different topics
        store.upsert_document(
            doc_id="doc-fastapi",
            content="FastAPI is a modern web framework for building APIs with Python and Pydantic.",
            metadata={"topic": "web"}
        )
        store.upsert_document(
            doc_id="doc-database",
            content="PostgreSQL relational database with SQL queries and relational schemas.",
            metadata={"topic": "database"}
        )
        store.upsert_document(
            doc_id="doc-pytest",
            content="Testing unit tests with pytest fixtures, assertions, and test runners.",
            metadata={"topic": "testing"}
        )

        # Semantic query for API development
        results = store.search_semantic("building rest api endpoints with python", limit=2)
        self.assertGreater(len(results), 0)
        self.assertEqual(results[0]["doc_id"], "doc-fastapi")

        # Semantic query for unit testing
        results_test = store.search_semantic("running automated tests with assertions", limit=2)
        self.assertGreater(len(results_test), 0)
        self.assertEqual(results_test[0]["doc_id"], "doc-pytest")

    def test_browser_scrape_tool(self):
        tool = BrowserTool()
        self.assertEqual(tool.name, "browser_scrape")

        # Test validation on invalid URL input
        valid, err = tool.validate_inputs({"url": 12345})
        self.assertFalse(valid)

        # Test execution with mock/sample target
        res = tool.run("https://example.com")
        self.assertTrue(res.success)
        self.assertEqual(res.data["status_code"], 200)
        self.assertIn("Example Domain", res.data["title"])
        self.assertIn("# Example Domain", res.data["content"])

    def test_vision_module(self):
        vision = VisionModule()

        # Test with dummy image
        img_path = self.workspace / "sample.png"
        # 1x1 transparent PNG bytes
        png_bytes = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
        img_path.write_bytes(png_bytes)

        res = vision.inspect_image(str(img_path), "Check UI layout")
        self.assertTrue(res["success"])
        self.assertEqual(res["format"], ".png")
        self.assertEqual(res["mime_type"], "image/png")
        self.assertIn("sample.png", res["filename"])

    def test_multi_agent_subtask_orchestration(self):
        queue_file = self.workspace / "tasks.json"
        orch = TaskOrchestrator(queue_file)

        task_id = orch.enqueue_task(
            title="Create microservice API",
            description="Full API build with tests",
            auto_decompose=True
        )

        # Initially, only the 'plan' subtask has no dependencies and should be ready
        ready_1 = orch.get_ready_subtasks(task_id)
        self.assertEqual(len(ready_1), 1)
        self.assertEqual(ready_1[0]["role"], AgentRole.PLANNER.value)

        # Mark planner done
        plan_id = ready_1[0]["subtask_id"]
        orch.update_subtask_status(task_id, plan_id, "done")

        # Now the 'coder' subtask should be ready
        ready_2 = orch.get_ready_subtasks(task_id)
        self.assertEqual(len(ready_2), 1)
        self.assertEqual(ready_2[0]["role"], AgentRole.CODER.value)

        # Mark coder done
        code_id = ready_2[0]["subtask_id"]
        orch.update_subtask_status(task_id, code_id, "done")

        # Now the 'tester' subtask should be ready
        ready_3 = orch.get_ready_subtasks(task_id)
        self.assertEqual(len(ready_3), 1)
        self.assertEqual(ready_3[0]["role"], AgentRole.TESTER.value)

if __name__ == "__main__":
    unittest.main()
