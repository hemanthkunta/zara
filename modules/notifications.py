"""
ZARA Notification System:
Multi-channel notification dispatcher (CLI, Log, Desktop, Voice)
with quiet-hours queuing and severity filtering.
"""
import os
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import LOGS_DIR
from core.observability import audit_logger


class NotificationSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Notification:
    notification_id: str = field(default_factory=lambda: f"notif_{uuid.uuid4().hex[:8]}")
    severity: NotificationSeverity = NotificationSeverity.INFO
    title: str = ""
    message: str = ""
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    channels: List[str] = field(default_factory=lambda: ["cli", "log"])
    delivered: bool = False
    queued_for_quiet_hours: bool = False

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value if hasattr(self.severity, "value") else str(self.severity)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Notification":
        d = dict(data)
        if "severity" in d:
            try:
                d["severity"] = NotificationSeverity(d["severity"])
            except Exception:
                d["severity"] = NotificationSeverity.INFO
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class NotificationManager:
    """Manages multi-channel notification routing, quiet-hours deferrals, and notification logs."""

    def __init__(
        self,
        notifications_file: Optional[Path] = None,
        voice_synthesizer: Optional[Any] = None
    ):
        self.notifications_file = Path(notifications_file or (LOGS_DIR / "notifications.jsonl"))
        self.voice = voice_synthesizer
        self.quiet_hours_queue: List[Notification] = []
        self.history: List[Notification] = []
        self.notifications_file.parent.mkdir(parents=True, exist_ok=True)

    def notify(
        self,
        title: str,
        message: str,
        severity: NotificationSeverity = NotificationSeverity.INFO,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        channels: Optional[List[str]] = None,
        is_quiet_hours: bool = False
    ) -> Notification:
        """Dispatch or queue a notification according to severity and quiet hours."""
        notif = Notification(
            severity=severity,
            title=title,
            message=message,
            project_id=project_id,
            task_id=task_id,
            channels=channels or ["cli", "log"]
        )

        # Quiet Hours Policy:
        # Non-critical notifications are queued during quiet hours.
        # CRITICAL notifications always pass through immediately to desktop/log.
        if is_quiet_hours and severity != NotificationSeverity.CRITICAL:
            notif.queued_for_quiet_hours = True
            self.quiet_hours_queue.append(notif)
            self._persist_notification(notif)
            return notif

        # Dispatch immediately
        self._dispatch(notif, is_quiet_hours=is_quiet_hours)
        notif.delivered = True
        self.history.append(notif)
        self._persist_notification(notif)
        return notif

    def _dispatch(self, notif: Notification, is_quiet_hours: bool = False) -> None:
        """Deliver notification to enabled channels."""
        # 1. Log Channel
        if "log" in notif.channels:
            audit_logger.log_event(
                "NOTIFICATION_DISPATCHED",
                action="notify",
                extra={
                    "severity": notif.severity.value,
                    "title": notif.title,
                    "message": notif.message,
                    "project_id": notif.project_id
                }
            )

        # 2. CLI Channel (Printed if active)
        if "cli" in notif.channels:
            prefix = "🔔" if notif.severity == NotificationSeverity.INFO else ("⚠️" if notif.severity == NotificationSeverity.WARNING else "🚨")
            print(f"\n{prefix} [ZARA NOTIFICATION] {notif.title}: {notif.message}")

        # 3. Voice Channel (Suppressed during quiet hours)
        if "voice" in notif.channels and not is_quiet_hours:
            if self.voice and hasattr(self.voice, "speak"):
                try:
                    self.voice.speak(f"{notif.title}. {notif.message}")
                except Exception:
                    pass

        # 4. Desktop Notification Channel
        if "desktop" in notif.channels:
            try:
                from tools.macos_control import MacOSNotificationTool
                tool = MacOSNotificationTool()
                tool.run(title=f"ZARA: {notif.title}", message=notif.message)
            except Exception:
                pass

    def flush_quiet_hours_queue(self) -> List[Notification]:
        """Release queued notifications when quiet hours expire."""
        released = []
        while self.quiet_hours_queue:
            notif = self.quiet_hours_queue.pop(0)
            self._dispatch(notif, is_quiet_hours=False)
            notif.delivered = True
            notif.queued_for_quiet_hours = False
            self.history.append(notif)
            self._persist_notification(notif)
            released.append(notif)
        return released

    def _persist_notification(self, notif: Notification) -> None:
        try:
            with open(self.notifications_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(notif.to_dict()) + "\n")
        except Exception:
            pass

    def get_pending_count(self) -> int:
        return len(self.quiet_hours_queue)

    def clear(self) -> None:
        self.quiet_hours_queue.clear()
        self.history.clear()
