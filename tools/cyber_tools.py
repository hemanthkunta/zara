"""
ZARA Cybersecurity Lab Tools:
Injection-safe, strictly scoped tools for Nmap scanning, ZAP web auditing,
SQLMap testing, and Metasploit checks on authorized lab targets.
"""
from typing import Dict, Any, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel
from modules.cyber_lab import (
    CyberLabManager,
    CyberLabScope,
    NmapScanRequest,
    ZAPScanRequest,
    SQLInjectionTestRequest,
    MetasploitRequest,
    ScopeViolationError
)


class CyberLabScanTool(BaseTool):
    """Run structured Nmap port and service enumeration on authorized lab target."""

    def __init__(self, manager: Optional[CyberLabManager] = None):
        super().__init__(
            name="nmap_scan",
            description="Run non-destructive Nmap port/service discovery on pre-approved lab targets.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "profile": {"type": "string", "enum": ["quick", "services", "full", "vulns"]},
                    "ports": {"type": "string"}
                },
                "required": ["target"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=90
        )
        self.manager = manager or CyberLabManager()

    def run(self, target: str, profile: str = "services", ports: Optional[str] = None) -> ToolResult:
        is_auth, lab_target, msg = self.manager.scope.verify_target(target)
        if not is_auth or not lab_target:
            return ToolResult(success=False, data=None, error=msg)

        req = NmapScanRequest(target_id=lab_target.target_id, scan_profile=profile, ports=ports)
        res = self.manager.nmap.execute(req, lab_target)
        return ToolResult(
            success=res.get("success", False),
            data=res,
            error=res.get("error")
        )


class CyberWebAuditTool(BaseTool):
    """Run OWASP ZAP / HTTP web application security audit on authorized lab target."""

    def __init__(self, manager: Optional[CyberLabManager] = None):
        super().__init__(
            name="zap_web_audit",
            description="Audit web security headers and baseline application vulnerabilities on authorized lab URL.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "scan_mode": {"type": "string", "enum": ["passive", "spider", "active"]}
                },
                "required": ["url"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=90
        )
        self.manager = manager or CyberLabManager()

    def run(self, url: str, scan_mode: str = "passive") -> ToolResult:
        is_auth, lab_target, msg = self.manager.scope.verify_target(url)
        if not is_auth or not lab_target:
            return ToolResult(success=False, data=None, error=msg)

        req = ZAPScanRequest(target_id=lab_target.target_id, url=url, scan_mode=scan_mode)
        res = self.manager.zap.execute(req, lab_target)
        return ToolResult(success=res.get("success", True), data=res)


class CyberSQLTestTool(BaseTool):
    """Run controlled SQL injection audit via SQLMap on authorized lab parameter."""

    def __init__(self, manager: Optional[CyberLabManager] = None):
        super().__init__(
            name="sqlmap_test",
            description="Test specified web application parameter for SQL injection vulnerabilities.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "parameter": {"type": "string"}
                },
                "required": ["url"]
            },
            risk_level=RiskLevel.MEDIUM,
            timeout_seconds=90
        )
        self.manager = manager or CyberLabManager()

    def run(self, url: str, parameter: Optional[str] = None) -> ToolResult:
        is_auth, lab_target, msg = self.manager.scope.verify_target(url)
        if not is_auth or not lab_target:
            return ToolResult(success=False, data=None, error=msg)

        req = SQLInjectionTestRequest(target_id=lab_target.target_id, url=url, parameter=parameter)
        res = self.manager.sqlmap.execute(req, lab_target)
        return ToolResult(success=res.get("success", False), data=res, error=res.get("error"))


class CyberExploitCheckTool(BaseTool):
    """Check exploitability with Metasploit (exploit execution requires confirmation ticket)."""

    def __init__(self, manager: Optional[CyberLabManager] = None):
        super().__init__(
            name="metasploit_check",
            description="Run controlled Metasploit module check on pre-approved lab target.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "target": {"type": "string"},
                    "module": {"type": "string"},
                    "is_check_only": {"type": "boolean"},
                    "confirmed": {"type": "boolean"}
                },
                "required": ["target", "module"]
            },
            risk_level=RiskLevel.HIGH,
            timeout_seconds=60
        )
        self.manager = manager or CyberLabManager()

    def run(
        self,
        target: str,
        module: str,
        is_check_only: bool = True,
        confirmed: bool = False
    ) -> ToolResult:
        is_auth, lab_target, msg = self.manager.scope.verify_target(target)
        if not is_auth or not lab_target:
            return ToolResult(success=False, data=None, error=msg)

        req = MetasploitRequest(target_id=lab_target.target_id, module=module, rhost=lab_target.host, is_check_only=is_check_only)
        if is_check_only:
            res = self.manager.metasploit.execute_check(req, lab_target)
            return ToolResult(success=True, data=res)
        else:
            try:
                res = self.manager.metasploit.execute_exploit(req, lab_target, is_confirmed=confirmed)
                return ToolResult(success=True, data=res)
            except ScopeViolationError as e:
                return ToolResult(success=False, data=None, error=str(e))
