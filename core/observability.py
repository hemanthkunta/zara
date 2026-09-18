"""
ZARA Observability Module: Structured JSONL audit logging, secret scrubbing, and metrics.
"""
import json
import re
import datetime
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from config.settings import AUDIT_LOG_FILE, SYSTEM_LOG_FILE

# Regex patterns for redacting sensitive secrets
SECRET_PATTERNS = [
    (r'(?i)(api[-_]?key|auth[-_]?token|secret|password|bearer\s+)[:=]\s*["\']?([^"\'\s]+)["\']?', r'\1: [REDACTED]'),
    (r'sk-[a-zA-Z0-9]{20,}', '[REDACTED_API_KEY]'),
    (r'AIzaSy[a-zA-Z0-9_-]{33}', '[REDACTED_GEMINI_KEY]'),
]

class AuditLogger:
    _lock = threading.Lock()

    def __init__(self, log_path: Path = AUDIT_LOG_FILE):
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @classmethod
    def scrub_secrets(cls, text: str) -> str:
        """Redact sensitive keys, passwords, and tokens from log strings."""
        if not isinstance(text, str):
            text = str(text)
        for pattern, replacement in SECRET_PATTERNS:
            text = re.sub(pattern, replacement, text)
        return text

    def log_event(
        self,
        event_type: str,
        action: str,
        task_id: Optional[str] = None,
        run_id: Optional[str] = None,
        step_id: Optional[int] = None,
        tool: Optional[str] = None,
        model: Optional[str] = None,
        duration_seconds: float = 0.0,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        verification_passed: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        """Append a structured, sanitized audit entry to the JSONL log."""
        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "event_type": event_type,
            "action": action,
            "task_id": task_id,
            "run_id": run_id,
            "step_id": step_id,
            "tool": tool,
            "model": model,
            "duration_seconds": round(duration_seconds, 4),
            "verification_passed": verification_passed,
            "error": self.scrub_secrets(error) if error else None,
            "result": self.scrub_secrets(str(result))[:1000] if result is not None else None,
            "extra": extra or {}
        }

        entry_json = json.dumps(record) + "\n"
        with self._lock:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(entry_json)

# Singleton global audit logger instance
audit_logger = AuditLogger()
