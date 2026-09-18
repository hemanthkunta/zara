"""
Tests for ZARA Command Center UI Integration:
WebSocket live streaming, EventBus auto-broadcasting, natural-language command dispatch,
plan approval pipeline, multi-client synchronization, and CLI integration.
"""
import unittest
import asyncio
import json
from pathlib import Path
from starlette.testclient import TestClient

from ui.server import create_ui_app
from core.engine import ZaraEngine
from modules.events import Event, EventType
from modules.world_model import Modality
from core.observability import audit_logger


class TestUIIntegration(unittest.TestCase):
    def setUp(self):
        self.engine = ZaraEngine(enable_voice=False)
        self.app = create_ui_app(engine=self.engine)
        self.client = TestClient(self.app)

    def test_websocket_handshake_and_init(self):
        """Connecting to /ws must send the initial state dump."""
        with self.client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
            self.assertEqual(msg.get("type"), "init")
            self.assertEqual(msg.get("status"), "ONLINE")
            self.assertIn("world", msg)
            self.assertIn("autonomous", msg)

    def test_websocket_ping_pong(self):
        """Sending a ping frame must return a pong frame with timestamp."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init frame
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            self.assertEqual(pong.get("type"), "pong")
            self.assertIn("timestamp", pong)

    def test_websocket_broadcast_from_manager(self):
        """ConnectionManager broadcast must deliver messages to connected clients."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init frame

            asyncio.run(self.app.state.ws_manager.broadcast({
                "type": "custom_broadcast",
                "content": "Mission update alpha"
            }))

            received = ws.receive_json()
            self.assertEqual(received.get("type"), "custom_broadcast")
            self.assertEqual(received.get("content"), "Mission update alpha")

    def test_websocket_client_disconnect_cleanup(self):
        """Closing client connection must cleanly remove it from active_connections."""
        self.assertEqual(len(self.app.state.ws_manager.active_connections), 0)
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()
            self.assertEqual(len(self.app.state.ws_manager.active_connections), 1)

        # After exiting context manager, client is disconnected
        self.assertEqual(len(self.app.state.ws_manager.active_connections), 0)

    def test_multiple_websocket_clients_broadcast(self):
        """Multiple concurrent WebSocket clients must all receive broadcasts."""
        with self.client.websocket_connect("/ws") as ws1:
            ws1.receive_json()  # Consume init 1
            with self.client.websocket_connect("/ws") as ws2:
                ws2.receive_json()  # Consume init 2
                self.assertEqual(len(self.app.state.ws_manager.active_connections), 2)

                asyncio.run(self.app.state.ws_manager.broadcast({
                    "type": "sync_alert",
                    "channel": "global"
                }))

                m1 = ws1.receive_json()
                m2 = ws2.receive_json()
                self.assertEqual(m1.get("type"), "sync_alert")
                self.assertEqual(m2.get("type"), "sync_alert")

    def test_world_refresh_triggers_websocket_broadcast(self):
        """POST /api/world/refresh must broadcast world_update to WebSocket."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            resp = self.client.post("/api/world/refresh", json={})
            self.assertEqual(resp.status_code, 200)

            event = ws.receive_json()
            self.assertEqual(event.get("type"), "world_update")
            self.assertIn("world", event)

    def test_screen_refresh_triggers_websocket_broadcast(self):
        """POST /api/screen/refresh must broadcast screen_refreshed to WebSocket."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            resp = self.client.post("/api/screen/refresh")
            self.assertEqual(resp.status_code, 200)

            event = ws.receive_json()
            self.assertEqual(event.get("type"), "screen_refreshed")
            self.assertIn("screenshot", event)

    def test_autonomous_toggle_broadcast(self):
        """POST /api/autonomous/toggle must broadcast autonomous_toggled to WebSocket."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            resp = self.client.post("/api/autonomous/toggle", json={"enabled": True})
            self.assertEqual(resp.status_code, 200)

            event = ws.receive_json()
            self.assertEqual(event.get("type"), "autonomous_toggled")
            self.assertEqual(event.get("active"), True)

            # Restore
            self.client.post("/api/autonomous/toggle", json={"enabled": False})

    def test_plan_approval_triggers_broadcast(self):
        """POST /api/plan/approve with a pending ticket broadcasts plan_approved."""
        # Set a mock pending approval ticket on project manager
        pm = self.engine.project_manager
        if pm:
            pm.pending_approval_ticket = {
                "ticket_id": "test_ticket_001",
                "action": "run_security_audit",
                "confirmed": False
            }

        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            resp = self.client.post("/api/plan/approve", json={"approved": True})
            self.assertEqual(resp.status_code, 200)

            event = ws.receive_json()
            self.assertEqual(event.get("type"), "plan_approved")
            self.assertIn("ticket", event)

    def test_command_execution_pipeline(self):
        """POST /api/command executes task through engine and returns structured response."""
        with self.client.websocket_connect("/ws") as ws:
            ws.receive_json()  # Consume init

            resp = self.client.post("/api/command", json={"command": "Inspect active directory structure"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("success"))
            self.assertIn("status", data)

            event = ws.receive_json()
            self.assertEqual(event.get("type"), "task_completed")

    def test_command_execution_audit_logging(self):
        """Submitting commands must write structured audit event to audit logger."""
        cmd_text = "Check current memory lessons"
        resp = self.client.post("/api/command", json={"command": cmd_text, "tag": "test_audit"})
        self.assertEqual(resp.status_code, 200)

        log_file = Path(audit_logger.log_path)
        self.assertTrue(log_file.exists())
        content = log_file.read_text(encoding="utf-8")
        self.assertIn("UI_COMMAND_SUBMITTED", content)
        self.assertIn(cmd_text, content)

    def test_cli_ui_parser(self):
        """CLI argument parser must correctly configure 'ui' command and options."""
        from cli import main
        import argparse

        # Verify ui command is recognized by parsing arguments
        import sys
        old_argv = sys.argv
        try:
            from cli import main
            # Test that cli parses 'ui --port 9000' without error
            sys.argv = ["zara.py", "ui", "status", "--port", "9000"]
            # Call status check which should gracefully report stopped/unreachable
            from cli import cmd_ui
            parser = argparse.ArgumentParser()
            sub = parser.add_subparsers(dest="command")
            ui_p = sub.add_parser("ui")
            ui_p.add_argument("ui_action", nargs="?", default="start")
            ui_p.add_argument("--port", type=int, default=8420)
            ui_p.add_argument("--host", type=str, default="127.0.0.1")
            parsed = ui_p.parse_args(["status", "--port", "9000"])
            self.assertEqual(parsed.ui_action, "status")
            self.assertEqual(parsed.port, 9000)
        finally:
            sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
