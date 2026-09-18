"""
ZARA Authorized Cybersecurity Laboratory Module: Scope verification, defensive audits, and security reports.
STRICT SCOPE RULE: Only targets pre-approved in config/security_scope.json may be audited.
"""
import json
import socket
import urllib.request
import ssl
from pathlib import Path
from typing import Tuple, Dict, Any, List
from config.settings import SECURITY_SCOPE_FILE
from core.observability import audit_logger

class ScopeViolationError(Exception):
    pass

class SecurityModule:
    def __init__(self, scope_file: Path = SECURITY_SCOPE_FILE):
        self.scope_file = Path(scope_file)
        self.scope_data = self._load_scope()

    def _load_scope(self) -> Dict[str, Any]:
        if not self.scope_file.exists():
            return {"allowed_hosts": ["localhost", "127.0.0.1", "::1"], "strict_mode": True}
        try:
            return json.loads(self.scope_file.read_text(encoding="utf-8"))
        except Exception:
            return {"allowed_hosts": ["localhost", "127.0.0.1", "::1"], "strict_mode": True}

    def verify_target(self, target: str) -> Tuple[bool, str]:
        """Verify target against pre-approved authorization scope list."""
        allowed_hosts = self.scope_data.get("allowed_hosts", [])
        allowed_domains = self.scope_data.get("allowed_domains", [])

        clean_target = target.replace("https://", "").replace("http://", "").split("/")[0].split(":")[0]

        if clean_target in allowed_hosts or any(clean_target.endswith(d) for d in allowed_domains):
            return True, f"Target '{target}' is authorized in pre-approved security scope."
        else:
            return False, (
                f"TARGET SCOPE VIOLATION: Target '{target}' is NOT in pre-approved scope "
                f"({self.scope_file}). Security testing is strictly prohibited on unauthorized targets."
            )

    def run_authorized_port_scan(self, host: str = "127.0.0.1", ports: Optional[List[int]] = None) -> Dict[str, Any]:
        """Run non-intrusive TCP connect audit on pre-approved target ports."""
        is_allowed, msg = self.verify_target(host)
        if not is_allowed:
            raise ScopeViolationError(msg)

        ports = ports or [80, 443, 8000, 8080, 3000, 5000]
        results = {}

        for port in ports:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            try:
                code = s.connect_ex((host, port))
                results[str(port)] = "OPEN" if code == 0 else "CLOSED"
            except Exception as e:
                results[str(port)] = f"ERROR: {str(e)}"
            finally:
                s.close()

        findings = {
            "target": host,
            "scan_type": "authorized_port_audit",
            "results": results,
            "summary": f"Scanned {len(ports)} ports on authorized target {host}."
        }
        audit_logger.log_event("SECURITY_AUDIT", action="port_scan", result=findings)
        return findings

    def run_http_header_audit(self, url: str) -> Dict[str, Any]:
        """Audit HTTP security headers on an authorized web target."""
        is_allowed, msg = self.verify_target(url)
        if not is_allowed:
            raise ScopeViolationError(msg)

        recommended_headers = [
            "Strict-Transport-Security",
            "Content-Security-Policy",
            "X-Frame-Options",
            "X-Content-Type-Options",
            "Referrer-Policy"
        ]

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZARA-Security-Audit/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = dict(resp.headers)
            missing = [h for h in recommended_headers if h.lower() not in [k.lower() for k in headers]]
            present = [h for h in recommended_headers if h.lower() in [k.lower() for k in headers]]

            return {
                "target": url,
                "status": "completed",
                "present_headers": present,
                "missing_headers": missing,
                "grade": "SECURE" if len(missing) <= 1 else "NEEDS_HARDENING"
            }
        except Exception as e:
            return {"target": url, "status": "failed", "error": str(e)}

    def plan_security_audit(self, target: str, audit_type: str) -> Dict[str, Any]:
        is_allowed, msg = self.verify_target(target)
        if not is_allowed:
            raise ScopeViolationError(msg)
        return {
            "target": target,
            "audit_type": audit_type,
            "authorized": True,
            "requires_user_confirmation": True,
            "scope_notice": "Audit will only perform defensive inspection as configured."
        }
