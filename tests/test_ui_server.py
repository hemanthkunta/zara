"""
Tests for ZARA Command Center UI Server:
REST API endpoints, static asset delivery, health checks, and subsystem inspection.
"""
import unittest
import json
from pathlib import Path
from starlette.testclient import TestClient

from ui.server import create_ui_app
from core.engine import ZaraEngine
from modules.world_model import WorldModel, Modality, Observation
from modules.workspace import ProjectManager
from config.settings import LOGS_DIR


class TestUIServer(unittest.TestCase):
    def setUp(self):
        self.engine = ZaraEngine(enable_voice=False)
        self.app = create_ui_app(engine=self.engine)
        self.client = TestClient(self.app)

    def tearDown(self):
        pass

    def test_root_index_html(self):
        """GET / should serve the Command Center HTML dashboard."""
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers.get("content-type", ""))
        self.assertIn("ZARA — Unified Command Center", resp.text)
        self.assertIn("command-input", resp.text)

    def test_static_css_and_js(self):
        """GET /static/styles.css and /static/app.js should return assets with 200 OK."""
        css_resp = self.client.get("/static/styles.css")
        self.assertEqual(css_resp.status_code, 200)
        self.assertIn("text/css", css_resp.headers.get("content-type", ""))
        self.assertIn("--accent-cyan", css_resp.text)

        js_resp = self.client.get("/static/app.js")
        self.assertEqual(js_resp.status_code, 200)
        self.assertIn("javascript", js_resp.headers.get("content-type", ""))
        self.assertIn("connectWebSocket", js_resp.text)

    def test_api_health(self):
        """GET /api/health should report operational status of all core subsystems."""
        resp = self.client.get("/api/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "healthy")
        components = data.get("components", {})
        self.assertEqual(components.get("engine"), "ONLINE")
        self.assertEqual(components.get("world_model"), "ONLINE")
        self.assertEqual(components.get("planner"), "ONLINE")
        self.assertEqual(components.get("event_bus"), "ONLINE")
        self.assertEqual(components.get("workspace"), "READY")
        self.assertEqual(components.get("scheduler"), "ONLINE")

    def test_api_status(self):
        """GET /api/status should report host system resources and active engine state."""
        resp = self.client.get("/api/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cpu_percent", data)
        self.assertIn("memory_percent", data)
        self.assertIn("autonomous_mode", data)
        self.assertIn("voice_speaking", data)

    def test_api_world_state(self):
        """GET /api/world should return normalized multimodal state, freshness, and graph counts."""
        resp = self.client.get("/api/world")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("world_state", data)
        self.assertIn("freshness", data)
        self.assertIn("entities_count", data)
        self.assertIn("relationships_count", data)
        self.assertIn("confidence", data)

    def test_api_world_diff(self):
        """GET /api/world/diff should return diff structure between states."""
        resp = self.client.get("/api/world/diff")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("has_changes", data)
        self.assertIn("changes", data)

    def test_api_world_refresh_all(self):
        """POST /api/world/refresh should refresh multimodal perceptions and return success."""
        resp = self.client.post("/api/world/refresh", json={})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("refreshed_at", data)

    def test_api_world_refresh_specific_modalities(self):
        """POST /api/world/refresh with selective modalities."""
        resp = self.client.post("/api/world/refresh", json={"modalities": ["screen", "terminal"]})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_api_screen_refresh(self):
        """POST /api/screen/refresh should trigger screenshot tool and observe screen state."""
        resp = self.client.post("/api/screen/refresh")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertIn("screenshot", data)

    def test_api_tasks(self):
        """GET /api/tasks should return task DAG queue and planning state."""
        resp = self.client.get("/api/tasks")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("tasks", data)
        self.assertIn("total_tasks", data)
        self.assertIn("completed_tasks", data)
        self.assertIn("status", data)

    def test_api_plan_approve(self):
        """POST /api/plan/approve should accept approval payload."""
        resp = self.client.post("/api/plan/approve", json={"approved": True, "notes": "Approved by unit test"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("status"), "approved")

    def test_api_projects_list(self):
        """GET /api/projects should return persistent workspace projects."""
        resp = self.client.get("/api/projects")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("projects", data)
        self.assertIsInstance(data["projects"], list)

    def test_api_project_get_not_found(self):
        """GET /api/projects/{id} should return 404 for nonexistent project."""
        resp = self.client.get("/api/projects/non_existent_project_99999")
        self.assertEqual(resp.status_code, 404)

    def test_api_project_pause_resume_cancel(self):
        """POST /api/project/pause, resume, and cancel should handle active project state safely."""
        pause_resp = self.client.post("/api/project/pause")
        self.assertEqual(pause_resp.status_code, 200)

        resume_resp = self.client.post("/api/project/resume")
        self.assertEqual(resume_resp.status_code, 200)

        cancel_resp = self.client.post("/api/project/cancel")
        self.assertEqual(cancel_resp.status_code, 200)

    def test_api_events(self):
        """GET /api/events should return chronological event bus audit records."""
        resp = self.client.get("/api/events?limit=10")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("events", data)
        self.assertIsInstance(data["events"], list)

    def test_api_notifications_and_clear(self):
        """GET /api/notifications and POST /api/notifications/clear."""
        resp = self.client.get("/api/notifications")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("notifications", data)

        clear_resp = self.client.post("/api/notifications/clear")
        self.assertEqual(clear_resp.status_code, 200)
        self.assertTrue(clear_resp.json().get("success"))

    def test_api_memory(self):
        """GET /api/memory should return memory lessons and statistics."""
        resp = self.client.get("/api/memory")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("lessons_count", data)
        self.assertIn("recent_lessons", data)

    def test_api_schedules(self):
        """GET /api/schedules should list registered proactive scheduled jobs."""
        resp = self.client.get("/api/schedules")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("jobs", data)
        self.assertIn("autonomous_enabled", data)

    def test_api_autonomous_toggle(self):
        """POST /api/autonomous/toggle should toggle autonomous mode on/off."""
        orig_resp = self.client.get("/api/status")
        orig_state = orig_resp.json().get("autonomous_mode", False)

        toggle_resp = self.client.post("/api/autonomous/toggle", json={"enabled": not orig_state})
        self.assertEqual(toggle_resp.status_code, 200)
        self.assertEqual(toggle_resp.json().get("autonomous_mode"), not orig_state)

        # Restore original state
        self.client.post("/api/autonomous/toggle", json={"enabled": orig_state})

    def test_api_voice_interrupt(self):
        """POST /api/voice/interrupt should signal TTS synthesizer to stop playback."""
        resp = self.client.post("/api/voice/interrupt")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))
        self.assertEqual(data.get("voice_speaking"), False)


if __name__ == "__main__":
    unittest.main()
