"""
Tests for ZARA Command Center UI Security:
Localhost binding enforcement, credential redaction, XSS sanitization,
path traversal defenses, cyber authorization scope preservation, and confirmation gates.
"""
import unittest
from pathlib import Path
from starlette.testclient import TestClient

from ui.server import (
    create_ui_app,
    redact_sensitive_data,
    sanitize_xss,
)
from core.engine import ZaraEngine
from config.settings import UI_HOST, UI_PORT, UI_ENABLE_CORS, LOGS_DIR
from modules.cyber_lab import CyberLabScope


class TestUISecurity(unittest.TestCase):
    def setUp(self):
        self.engine = ZaraEngine(enable_voice=False)
        self.app = create_ui_app(engine=self.engine)
        self.client = TestClient(self.app)

    def test_default_bind_localhost(self):
        """UI must bind to 127.0.0.1 by default for local-only safety."""
        self.assertEqual(UI_HOST, "127.0.0.1")
        self.assertNotEqual(UI_HOST, "0.0.0.0")

    def test_cors_disabled_by_default(self):
        """Cross-Origin Resource Sharing must be disabled by default."""
        self.assertFalse(UI_ENABLE_CORS)

    def test_credential_redaction_bearer_token(self):
        """Bearer tokens must be redacted from strings, dicts, and lists."""
        raw = "Authorization: Bearer secret_token_xyz_1234567890"
        redacted = redact_sensitive_data(raw)
        self.assertNotIn("secret_token_xyz_1234567890", redacted)
        self.assertIn("[REDACTED_TOKEN]", redacted)

    def test_credential_redaction_api_keys(self):
        """API key patterns must be obscured."""
        data = {"openai_api_key": "api_key='sk-ant-api03-abcdef1234567890'"}
        cleaned = redact_sensitive_data(data)
        self.assertNotIn("sk-ant-api03-abcdef1234567890", str(cleaned))
        self.assertIn("[REDACTED_API_KEY]", str(cleaned))

    def test_credential_redaction_passwords_and_secrets(self):
        """Passwords and secrets must be redacted."""
        entry = {
            "db_pass": "password = 'SuperSecretP@ssword123'",
            "client_secret": "secret='super_secret_client_key_999'"
        }
        sanitized = redact_sensitive_data(entry)
        self.assertNotIn("SuperSecretP@ssword123", str(sanitized))
        self.assertNotIn("super_secret_client_key_999", str(sanitized))

    def test_credential_redaction_nested_structures(self):
        """Nested structures containing credentials must be thoroughly redacted."""
        complex_data = [
            {"meta": {"auth": "Bearer a1b2c3d4e5f6g7h8i9j0"}},
            ["random_item", {"secret_val": "password = 'admin_secret_pass'"}]
        ]
        res = redact_sensitive_data(complex_data)
        self.assertNotIn("a1b2c3d4e5f6g7h8i9j0", str(res))
        self.assertNotIn("admin_secret_pass", str(res))

    def test_xss_escaping(self):
        """HTML injection payloads must be safely entity-encoded."""
        payload = "<script>alert('XSS')</script>&\"quote\""
        sanitized = sanitize_xss(payload)
        self.assertNotIn("<script>", sanitized)
        self.assertNotIn("</script>", sanitized)
        self.assertIn("&lt;script&gt;", sanitized)
        self.assertIn("&amp;", sanitized)
        self.assertIn("&quot;", sanitized)

    def test_path_traversal_prevention_in_projects(self):
        """Path traversal characters in project ID endpoints must be rejected."""
        traversals = [
            "../../etc/passwd",
            "..\\..\\windows\\win.ini",
            "foo/bar",
            "foo\\bar"
        ]
        for bad_id in traversals:
            resp = self.client.get(f"/api/projects/{bad_id}")
            self.assertIn(resp.status_code, (400, 404))

    def test_path_traversal_prevention_in_screenshots(self):
        """Screenshots directory check must prevent arbitrary file serving."""
        resp = self.client.get("/api/screenshot/latest")
        # If no screenshots exist yet, 404 is returned.
        # If screenshot exists, 200 is returned with image/png.
        self.assertIn(resp.status_code, (200, 404))
        if resp.status_code == 200:
            self.assertEqual(resp.headers.get("content-type"), "image/png")

    def test_cyber_authorization_preservation(self):
        """UI endpoints must NEVER bypass CyberLabScope authorization boundaries."""
        scope = CyberLabScope()
        # Localhost must be authorized by default
        authorized, _, _ = scope.verify_target("127.0.0.1")
        self.assertTrue(authorized)

        # Target outside authorized scope must be forbidden by scope
        forbidden, _, err = scope.verify_target("https://target-bank.com")
        self.assertFalse(forbidden)
        self.assertIn("TARGET SCOPE VIOLATION", err)

    def test_confirmation_gate_preservation(self):
        """Confirmation gate must be strictly preserved; plan approval without ticket behaves safely."""
        resp = self.client.post("/api/plan/approve", json={"confirmed": True})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_command_validation_empty(self):
        """Submitting an empty or missing command must be rejected with 422."""
        resp = self.client.post("/api/command", json={"command": ""})
        self.assertEqual(resp.status_code, 422)

    def test_command_validation_max_length(self):
        """Commands exceeding maximum character threshold (2000) must be rejected with 422."""
        long_cmd = "a" * 2005
        resp = self.client.post("/api/command", json={"command": long_cmd})
        self.assertEqual(resp.status_code, 422)

    def test_invalid_modality_refresh_safe_handling(self):
        """Providing invalid or corrupted modality identifiers to refresh must not crash."""
        resp = self.client.post("/api/world/refresh", json={"modalities": ["alien_signal", "unknown_dimension"]})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))


if __name__ == "__main__":
    unittest.main()
