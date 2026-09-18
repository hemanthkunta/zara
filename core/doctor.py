"""
ZARA Environment & Dependency Doctor (Phase 18).
Performs actionable diagnostics across runtime dependencies, tools, configuration, and persistence.
Classifies dependencies as REQUIRED, OPTIONAL, LAB_ONLY, or PLATFORM_SPECIFIC without leaking secrets.
"""
import sys
import shutil
import socket
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import (
    BASE_DIR, CONFIG_DIR, LOGS_DIR, MEMORY_DIR, CHECKPOINTS_DIR, BACKUPS_DIR,
    UI_HOST, UI_PORT, SECURITY_SCOPE_FILE
)
from config.validator import ConfigValidator


class DependencyCategory(str, Enum):
    REQUIRED = "REQUIRED"
    OPTIONAL = "OPTIONAL"
    LAB_ONLY = "LAB_ONLY"
    PLATFORM_SPECIFIC = "PLATFORM_SPECIFIC"


class DependencyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MISSING = "MISSING"
    WARNING = "WARNING"


@dataclass
class DoctorCheck:
    name: str
    category: DependencyCategory
    status: DependencyStatus
    message: str
    remediation: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value if hasattr(self.category, "value") else str(self.category)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        return d


@dataclass
class DoctorReport:
    checks: List[DoctorCheck]
    issues_found: int
    warnings_found: int
    can_run_core: bool
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "issues_found": self.issues_found,
            "warnings_found": self.warnings_found,
            "can_run_core": self.can_run_core,
            "timestamp": self.timestamp
        }


class EnvironmentDoctor:
    """Diagnoses environment readiness, dependencies, and actionable remediation steps."""

    @classmethod
    def run_diagnostics(cls, workspace_root: Optional[Path] = None) -> DoctorReport:
        ws = Path(workspace_root or BASE_DIR).resolve()
        checks: List[DoctorCheck] = []

        # 1. Python runtime
        py_ver = sys.version_info
        if py_ver >= (3, 10):
            checks.append(DoctorCheck(
                name="Python Runtime",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message=f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} satisfies requirement (>= 3.10)"
            ))
        else:
            checks.append(DoctorCheck(
                name="Python Runtime",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.MISSING,
                message=f"Python {py_ver.major}.{py_ver.minor}.{py_ver.micro} is below minimum requirement",
                remediation="Upgrade to Python 3.10 or newer."
            ))

        # 2. Git
        git_bin = shutil.which("git")
        if git_bin:
            checks.append(DoctorCheck(
                name="Git Version Control",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message="Git executable detected in PATH",
                details={"path": git_bin}
            ))
        else:
            checks.append(DoctorCheck(
                name="Git Version Control",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.MISSING,
                message="Git not found in PATH",
                remediation="Install Git via your package manager (e.g. 'brew install git' or 'apt install git')."
            ))

        # 3. SQLite3
        try:
            import sqlite3
            checks.append(DoctorCheck(
                name="SQLite3 Database",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message=f"SQLite3 v{sqlite3.sqlite_version} operational"
            ))
        except Exception as e:
            checks.append(DoctorCheck(
                name="SQLite3 Database",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.MISSING,
                message=f"SQLite3 module unavailable: {e}",
                remediation="Reinstall Python with SQLite3 support enabled."
            ))

        # 4. Workspace Access
        if ws.exists() and os.access(ws, os.W_OK):
            checks.append(DoctorCheck(
                name="Workspace Permissions",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message=f"Workspace root '{ws}' is writable"
            ))
        else:
            checks.append(DoctorCheck(
                name="Workspace Permissions",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.MISSING,
                message=f"Workspace root '{ws}' does not exist or is not writable",
                remediation=f"Ensure directory '{ws}' exists and has read/write permissions."
            ))

        # 5. Security Scope File
        if SECURITY_SCOPE_FILE.exists():
            checks.append(DoctorCheck(
                name="Cyber Lab Scope Allowlist",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message="Security scope file present with authorized local lab targets"
            ))
        else:
            checks.append(DoctorCheck(
                name="Cyber Lab Scope Allowlist",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.WARNING,
                message=f"Security scope file '{SECURITY_SCOPE_FILE}' not found; defaulting to localhost only",
                remediation="Create 'config/security_scope.json' with authorized local targets."
            ))

        # 6. AI Model Provider Keys (OPTIONAL - sanitized, never prints actual keys)
        has_gemini = bool(os.getenv("GEMINI_API_KEY"))
        has_anthropic = bool(os.getenv("ANTHROPIC_API_KEY"))
        has_openai = bool(os.getenv("OPENAI_API_KEY"))
        has_ollama = bool(shutil.which("ollama"))

        configured_ai = []
        if has_gemini: configured_ai.append("Google Gemini")
        if has_anthropic: configured_ai.append("Anthropic Claude")
        if has_openai: configured_ai.append("OpenAI GPT")
        if has_ollama: configured_ai.append("Local Ollama")

        if configured_ai:
            checks.append(DoctorCheck(
                name="AI Model Providers",
                category=DependencyCategory.OPTIONAL,
                status=DependencyStatus.AVAILABLE,
                message=f"Configured providers: {', '.join(configured_ai)}",
                details={"configured": configured_ai}
            ))
        else:
            checks.append(DoctorCheck(
                name="AI Model Providers",
                category=DependencyCategory.OPTIONAL,
                status=DependencyStatus.WARNING,
                message="No external AI API keys or Ollama detected; running with deterministic offline Mock provider",
                remediation="Export GEMINI_API_KEY, ANTHROPIC_API_KEY, or start Ollama for live LLM inference."
            ))

        # 7. macOS Voice TTS
        say_bin = shutil.which("say")
        if say_bin:
            checks.append(DoctorCheck(
                name="macOS Voice Synthesizer",
                category=DependencyCategory.PLATFORM_SPECIFIC,
                status=DependencyStatus.AVAILABLE,
                message="Native macOS 'say' TTS command available (Samantha voice supported)"
            ))
        else:
            checks.append(DoctorCheck(
                name="macOS Voice Synthesizer",
                category=DependencyCategory.PLATFORM_SPECIFIC,
                status=DependencyStatus.WARNING,
                message="'say' command not found (non-macOS or headless environment); voice operates in mock mode",
                remediation="macOS TTS is native to Darwin. On Linux, set ZARA_ENABLE_VOICE=false."
            ))

        # 8. Blender 3D
        blender_bin = shutil.which("blender")
        if blender_bin:
            checks.append(DoctorCheck(
                name="Blender 3D",
                category=DependencyCategory.OPTIONAL,
                status=DependencyStatus.AVAILABLE,
                message=f"Headless Blender 3D binary found at {blender_bin}"
            ))
        else:
            checks.append(DoctorCheck(
                name="Blender 3D",
                category=DependencyCategory.OPTIONAL,
                status=DependencyStatus.WARNING,
                message="Blender executable not found in PATH; 3D generation uses procedural scripts without rendering",
                remediation="Install Blender (e.g. 'brew install --cask blender') and ensure it is in PATH."
            ))

        # 9. Cybersecurity Lab Tools (LAB_ONLY)
        cyber_tools = {
            "Nmap (Network Scanner)": shutil.which("nmap"),
            "OWASP ZAP (Web Auditor)": shutil.which("zap.sh") or shutil.which("zap"),
            "SQLMap (Injection Auditor)": shutil.which("sqlmap"),
            "Metasploit (Framework)": shutil.which("msfconsole"),
        }
        installed_cyber = [k for k, v in cyber_tools.items() if v]
        missing_cyber = [k for k, v in cyber_tools.items() if not v]

        if installed_cyber:
            checks.append(DoctorCheck(
                name="Cybersecurity Lab Tools",
                category=DependencyCategory.LAB_ONLY,
                status=DependencyStatus.AVAILABLE,
                message=f"Installed lab tools: {', '.join(installed_cyber)}"
            ))
        if missing_cyber:
            checks.append(DoctorCheck(
                name="Cybersecurity Lab Tools (Optional)",
                category=DependencyCategory.LAB_ONLY,
                status=DependencyStatus.WARNING,
                message=f"Optional lab tools not in PATH: {', '.join(missing_cyber)}",
                remediation="Install tools inside isolated cybersecurity lab VM/Docker only (e.g. 'brew install nmap sqlmap')."
            ))

        # 10. Configuration Bounds Validation
        cfg_res = ConfigValidator.validate()
        if cfg_res.is_valid:
            checks.append(DoctorCheck(
                name="Configuration Sanity",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.AVAILABLE,
                message="All configuration parameters within valid security and operational bounds"
            ))
        else:
            checks.append(DoctorCheck(
                name="Configuration Sanity",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.MISSING,
                message=f"Configuration errors detected: {'; '.join(cfg_res.errors)}",
                remediation="Review environment variables and config/settings.py."
            ))

        # 11. Command Center UI Port Availability
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.2)
        try:
            res = sock.connect_ex((UI_HOST, UI_PORT))
            if res == 0:
                # Port is currently in use (could be ZARA UI already running)
                checks.append(DoctorCheck(
                    name="Command Center UI Port",
                    category=DependencyCategory.REQUIRED,
                    status=DependencyStatus.AVAILABLE,
                    message=f"UI port {UI_PORT} is currently active and listening on {UI_HOST}"
                ))
            else:
                checks.append(DoctorCheck(
                    name="Command Center UI Port",
                    category=DependencyCategory.REQUIRED,
                    status=DependencyStatus.AVAILABLE,
                    message=f"UI port {UI_PORT} is available to bind on {UI_HOST}"
                ))
        except Exception as e:
            checks.append(DoctorCheck(
                name="Command Center UI Port",
                category=DependencyCategory.REQUIRED,
                status=DependencyStatus.WARNING,
                message=f"Could not probe UI port: {e}"
            ))
        finally:
            sock.close()

        # Calculation
        issues_found = sum(1 for c in checks if c.status == DependencyStatus.MISSING and c.category == DependencyCategory.REQUIRED)
        warnings_found = sum(1 for c in checks if c.status == DependencyStatus.WARNING or (c.status == DependencyStatus.MISSING and c.category != DependencyCategory.REQUIRED))
        can_run_core = issues_found == 0

        import datetime
        return DoctorReport(
            checks=checks,
            issues_found=issues_found,
            warnings_found=warnings_found,
            can_run_core=can_run_core,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
