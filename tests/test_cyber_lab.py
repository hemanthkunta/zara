"""
Tests for ZARA Phase 9: Autonomous Cybersecurity Lab Subsystem.
Strict allowlist scoping, command injection defense, tool adapters,
Metasploit confirmation gate, vulnerability normalization, credential scrubbing,
and executive report generation.
"""
import unittest
import json
import tempfile
from pathlib import Path
from typing import Dict, Any

from modules.cyber_lab import (
    CyberLabTarget,
    CyberLabScope,
    ScopeViolationError,
    NmapScanRequest,
    NmapAdapter,
    ZAPScanRequest,
    ZAPAdapter,
    SQLInjectionTestRequest,
    SQLMapAdapter,
    MetasploitRequest,
    MetasploitAdapter,
    VulnerabilitySeverity,
    VulnerabilityRecord,
    VulnerabilityNormalizer,
    CyberSecurityReport,
    CyberLabManager,
    scrub_credentials
)
from tools.cyber_tools import (
    CyberLabScanTool,
    CyberWebAuditTool,
    CyberSQLTestTool,
    CyberExploitCheckTool
)
from modules.workspace import ProjectManager, ProjectType
from core.engine import ZaraEngine


class TestCyberLabScope(unittest.TestCase):
    """Verify strict scope boundaries and injection defenses."""

    def setUp(self):
        self.scope = CyberLabScope()

    def test_01_localhost_allowed(self):
        allowed, target, msg = self.scope.verify_target("127.0.0.1")
        self.assertTrue(allowed)
        self.assertIsNotNone(target)
        self.assertEqual(target.host, "127.0.0.1")

    def test_02_rfc1918_192_168_allowed(self):
        allowed, target, msg = self.scope.verify_target("192.168.1.50")
        self.assertTrue(allowed)
        self.assertIsNotNone(target)

    def test_03_rfc1918_10_0_allowed(self):
        allowed, target, msg = self.scope.verify_target("10.0.2.15")
        self.assertTrue(allowed)
        self.assertIsNotNone(target)

    def test_04_rfc1918_172_16_allowed(self):
        allowed, target, msg = self.scope.verify_target("172.16.5.1")
        self.assertTrue(allowed)
        self.assertIsNotNone(target)

    def test_05_preapproved_lab_domain_allowed(self):
        allowed, target, msg = self.scope.verify_target("dvwa.local")
        self.assertTrue(allowed)
        self.assertIsNotNone(target)
        self.assertEqual(target.name, "Damn Vulnerable Web App")

    def test_06_juice_shop_allowed(self):
        allowed, target, msg = self.scope.verify_target("juice-shop.local")
        self.assertTrue(allowed)

    def test_07_public_ip_blocked(self):
        allowed, target, msg = self.scope.verify_target("8.8.8.8")
        self.assertFalse(allowed)
        self.assertIn("Public or unapproved target '8.8.8.8' is STRICTLY FORBIDDEN", msg)

    def test_08_public_domain_blocked(self):
        allowed, target, msg = self.scope.verify_target("google.com")
        self.assertFalse(allowed)
        self.assertIn("STRICTLY FORBIDDEN", msg)

    def test_09_command_injection_semicolon_blocked(self):
        allowed, target, msg = self.scope.verify_target("127.0.0.1; cat /etc/passwd")
        self.assertFalse(allowed)
        self.assertIn("disallowed characters", msg)

    def test_10_command_injection_pipe_blocked(self):
        allowed, target, msg = self.scope.verify_target("127.0.0.1 | rm -rf /")
        self.assertFalse(allowed)
        self.assertIn("disallowed characters", msg)

    def test_11_command_injection_backtick_blocked(self):
        allowed, target, msg = self.scope.verify_target("127.0.0.1`whoami`")
        self.assertFalse(allowed)
        self.assertIn("disallowed characters", msg)


class TestCyberAdaptersAndSafety(unittest.TestCase):
    """Verify scanning adapters, Metasploit human confirmation gates, and sanitization."""

    def setUp(self):
        self.mgr = CyberLabManager()
        self.target = CyberLabTarget(
            target_id="test-dvwa",
            name="Test DVWA",
            host="127.0.0.1",
            allowed_ports=[80, 443, 3306],
            description="Local container"
        )

    def test_12_nmap_adapter_quick_scan(self):
        req = NmapScanRequest(target_id="test-dvwa", scan_profile="quick", ports="80,443")
        res = self.mgr.nmap.execute(req, self.target)
        self.assertTrue(res.get("success"))
        self.assertEqual(res.get("target"), "127.0.0.1")
        self.assertIn("open_ports", res)

    def test_13_nmap_disallowed_port_string_rejected(self):
        req = NmapScanRequest(target_id="test-dvwa", scan_profile="quick", ports="80; rm -rf")
        res = self.mgr.nmap.execute(req, self.target)
        self.assertFalse(res.get("success"))
        self.assertIn("Invalid port specification", res.get("error", ""))

    def test_14_zap_adapter_web_audit(self):
        req = ZAPScanRequest(target_id="test-dvwa", base_url="http://127.0.0.1:8080")
        res = self.mgr.zap.execute(req, self.target)
        self.assertTrue(res.get("success"))
        self.assertIn("alerts", res)
        self.assertGreaterEqual(len(res["alerts"]), 1)

    def test_15_sqlmap_adapter_test(self):
        req = SQLInjectionTestRequest(
            target_id="test-dvwa",
            url="http://127.0.0.1:8080/vulnerabilities/sqli/?id=1&Submit=Submit",
            parameter="id"
        )
        res = self.mgr.sqlmap.execute(req, self.target)
        self.assertTrue(res.get("success"))
        self.assertIn("is_vulnerable", res)
        self.assertTrue(res.get("is_vulnerable"))
        self.assertEqual(res.get("parameter"), "id")

    def test_16_metasploit_check_only_succeeds(self):
        req = MetasploitRequest(
            target_id="test-dvwa",
            module_path="exploit/unix/webapp/wp_admin_shell_upload",
            check_only=True,
            is_confirmed=False
        )
        res = self.mgr.metasploit.execute(req, self.target)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("check_only"))
        self.assertEqual(res.get("check_result"), "Appears vulnerable")

    def test_17_metasploit_exploit_blocked_without_confirmation(self):
        req = MetasploitRequest(
            target_id="test-dvwa",
            module_path="exploit/unix/webapp/wp_admin_shell_upload",
            check_only=False,
            is_confirmed=False  # Gate not unlocked
        )
        with self.assertRaises(ScopeViolationError) as ctx:
            self.mgr.metasploit.execute(req, self.target)
        self.assertIn("REQUIRES HUMAN CONFIRMATION", str(ctx.exception))

    def test_18_metasploit_exploit_allowed_when_confirmed(self):
        req = MetasploitRequest(
            target_id="test-dvwa",
            module_path="exploit/unix/webapp/wp_admin_shell_upload",
            check_only=False,
            is_confirmed=True  # Human confirmed
        )
        res = self.mgr.metasploit.execute(req, self.target)
        self.assertTrue(res.get("success"))
        self.assertTrue(res.get("exploit_simulated"))

    def test_19_credential_scrubbing(self):
        raw_text = "Target leak: password=SecretAdminPass123! token=ghp_ABC123xyz456 bearer_token=eyJhbGciOiJIUzI1NiIn"
        scrubbed = scrub_credentials(raw_text)
        self.assertNotIn("SecretAdminPass123!", scrubbed)
        self.assertNotIn("ghp_ABC123xyz456", scrubbed)
        self.assertIn("[REDACTED]", scrubbed)

    def test_20_vulnerability_normalizer_and_report(self):
        norm = VulnerabilityNormalizer()
        vulns = [
            norm.normalize_nmap("127.0.0.1", 21, "vsftpd 2.3.4 (Backdoor)", "CRITICAL"),
            norm.normalize_zap("SQL Injection vulnerability in login form", "HIGH", "http://127.0.0.1/login", "cwe-89"),
            norm.normalize_sqlmap("http://127.0.0.1/vulnerable.php", "id", ["boolean-based blind", "UNION query"])
        ]
        self.assertEqual(len(vulns), 3)
        self.assertEqual(vulns[0].severity, VulnerabilitySeverity.CRITICAL)
        self.assertEqual(vulns[1].severity, VulnerabilitySeverity.HIGH)
        self.assertEqual(vulns[2].severity, VulnerabilitySeverity.HIGH)

        report = CyberSecurityReport(
            target_name="Test DVWA",
            target_host="127.0.0.1",
            vulnerabilities=vulns,
            scope_summary="RFC 1918 & Localhost Lab Assessment"
        )
        summary = report.to_dict()
        self.assertEqual(summary["total_vulnerabilities"], 3)
        self.assertEqual(summary["severity_counts"]["CRITICAL"], 1)
        self.assertEqual(summary["severity_counts"]["HIGH"], 2)

        md = report.generate_markdown()
        self.assertIn("EXECUTIVE CYBERSECURITY ASSESSMENT REPORT", md)
        self.assertIn("CRITICAL: 1", md)
        self.assertIn("Remediation Roadmap", md)


class TestCyberLabWorkspaceAndTools(unittest.TestCase):
    """Verify tool integration, project templates, and engine registration."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_21_create_cybersecurity_assessment_project_dag(self):
        mgr = ProjectManager.create_cybersecurity_assessment_project(
            name="DVWA Security Audit",
            workspace_path=self.workspace_path,
            target_host="127.0.0.1",
            target_name="Local DVWA Container"
        )
        self.assertEqual(mgr.project.project_type, ProjectType.CYBERSECURITY_ASSESSMENT)
        tasks = mgr.dag.list_tasks()
        self.assertEqual(len(tasks), 6)
        task_ids = [t.id for t in tasks]
        self.assertIn("task_scope_validation", task_ids)
        self.assertIn("task_nmap_recon", task_ids)
        self.assertIn("task_zap_web_audit", task_ids)
        self.assertIn("task_sql_injection_audit", task_ids)
        self.assertIn("task_exploitability_assessment", task_ids)
        self.assertIn("task_executive_report", task_ids)

    def test_22_cyber_tools_in_engine_registry(self):
        engine = ZaraEngine(workspace_root=str(self.workspace_path), enable_voice=False)
        tool_names = engine.tools.list_tool_names()
        self.assertIn("nmap_scan", tool_names)
        self.assertIn("zap_web_audit", tool_names)
        self.assertIn("sqlmap_test", tool_names)
        self.assertIn("metasploit_check", tool_names)

    def test_23_cyber_scan_tool_execution(self):
        tool = CyberLabScanTool()
        # Scan authorized target
        res = tool.run(target="127.0.0.1", profile="quick")
        self.assertTrue(res.success)
        self.assertIn("open_ports", res.data)

        # Scan unauthorized target
        res_blocked = tool.run(target="1.1.1.1")
        self.assertFalse(res_blocked.success)
        self.assertIn("STRICTLY FORBIDDEN", res_blocked.error)


if __name__ == "__main__":
    unittest.main()
