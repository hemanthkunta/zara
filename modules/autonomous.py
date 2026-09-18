"""
ZARA Autonomous Mode, Daily Queue Synthesizer, Resource Budgets,
Quiet Hours Manager, and Proactive Maintenance Engine.
"""
import os
import json
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import (
    BASE_DIR,
    CONFIG_DIR,
    AUTONOMOUS_MODE,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
    MAX_AUTONOMOUS_RUNS_PER_DAY,
    MAX_AUTONOMOUS_TOOL_CALLS_PER_DAY,
    MAX_AUTONOMOUS_RUNTIME_SECONDS_PER_DAY
)
from core.observability import audit_logger


class AutonomousMode(str, Enum):
    OFF = "OFF"
    ON = "ON"


@dataclass
class AutonomousBudget:
    max_runs: int = MAX_AUTONOMOUS_RUNS_PER_DAY
    runs_used: int = 0
    max_tool_calls: int = MAX_AUTONOMOUS_TOOL_CALLS_PER_DAY
    tool_calls_used: int = 0
    max_runtime_seconds: float = float(MAX_AUTONOMOUS_RUNTIME_SECONDS_PER_DAY)
    runtime_seconds_used: float = 0.0
    max_research_queries: int = 30
    research_queries_used: int = 0
    max_retries: int = 15
    retries_used: int = 0
    max_notifications: int = 50
    notifications_used: int = 0
    date_tracked: str = field(default_factory=lambda: datetime.date.today().isoformat())

    def record(
        self,
        runs: int = 0,
        tool_calls: int = 0,
        runtime_seconds: float = 0.0,
        queries: int = 0,
        retries: int = 0,
        notifications: int = 0
    ) -> None:
        self.runs_used += runs
        self.tool_calls_used += tool_calls
        self.runtime_seconds_used += runtime_seconds
        self.research_queries_used += queries
        self.retries_used += retries
        self.notifications_used += notifications

    def is_exhausted(self) -> bool:
        return (
            self.runs_used >= self.max_runs or
            self.tool_calls_used >= self.max_tool_calls or
            self.runtime_seconds_used >= self.max_runtime_seconds or
            self.retries_used >= self.max_retries
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AutonomousBudget":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class QuietHoursManager:
    """Calculates whether current time falls within configured quiet hours window."""

    def __init__(
        self,
        start_time_str: str = QUIET_HOURS_START,
        end_time_str: str = QUIET_HOURS_END
    ):
        self.start_hour, self.start_minute = map(int, start_time_str.split(":"))
        self.end_hour, self.end_minute = map(int, end_time_str.split(":"))

    def is_quiet_hours(self, current_dt: Optional[datetime.datetime] = None) -> bool:
        dt = current_dt or datetime.datetime.now()
        cur_min = dt.hour * 60 + dt.minute
        start_min = self.start_hour * 60 + self.start_minute
        end_min = self.end_hour * 60 + self.end_minute

        if start_min <= end_min:
            return start_min <= cur_min < end_min
        else:
            # Overnights (e.g. 23:00 to 07:00)
            return cur_min >= start_min or cur_min < end_min


class AutonomousModeManager:
    """Manages autonomous mode toggles, daily budgets, and quiet-hours enforcement."""

    def __init__(
        self,
        config_file: Optional[Path] = None,
        initial_mode: Optional[AutonomousMode] = None
    ):
        self.config_file = Path(config_file or (CONFIG_DIR / "autonomous_config.json"))
        self.mode = initial_mode or (AutonomousMode.ON if AUTONOMOUS_MODE else AutonomousMode.OFF)
        self.budget = AutonomousBudget()
        self.quiet_hours = QuietHoursManager()
        self.load()

    def load(self) -> None:
        if self.config_file.exists():
            try:
                data = json.loads(self.config_file.read_text(encoding="utf-8"))
                self.mode = AutonomousMode(data.get("mode", self.mode.value))
                if "budget" in data:
                    self.budget = AutonomousBudget.from_dict(data["budget"])
            except Exception:
                pass

    def save(self) -> None:
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "mode": self.mode.value,
            "budget": self.budget.to_dict(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        try:
            self.config_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def enable(self) -> None:
        self.mode = AutonomousMode.ON
        self.save()
        audit_logger.log_event("AUTONOMOUS_MODE_ENABLED", action="toggle", extra={"mode": "ON"})

    def disable(self) -> None:
        self.mode = AutonomousMode.OFF
        self.save()
        audit_logger.log_event("AUTONOMOUS_MODE_DISABLED", action="toggle", extra={"mode": "OFF"})

    def is_enabled(self) -> bool:
        return self.mode == AutonomousMode.ON

    def can_execute_autonomously(self) -> Tuple[bool, str]:
        """Verify if autonomous task execution is currently allowed."""
        if not self.is_enabled():
            return False, "Autonomous execution is disabled (AUTONOMOUS MODE: OFF)."
        if self.budget.is_exhausted():
            return False, "Daily autonomous resource budget is exhausted (PAUSED_BY_BUDGET)."
        return True, "Autonomous execution permitted."


class DailyQueueSynthesizer:
    """Synthesizes scheduled tasks, persistent DAGs, and monitored events into an authoritative daily queue."""

    def __init__(self, scheduler: Any, project_manager: Optional[Any] = None):
        self.scheduler = scheduler
        self.project_manager = project_manager

    def synthesize(self) -> List[Dict[str, Any]]:
        """Generate structured prioritized daily work items."""
        queue = []

        # 1. Gather due scheduled jobs
        if self.scheduler:
            due_jobs = self.scheduler.get_due_jobs()
            for job in due_jobs:
                queue.append({
                    "source": "scheduler",
                    "id": job.job_id,
                    "title": job.name,
                    "priority": job.priority.value,
                    "priority_rank": job.priority.rank,
                    "capability": job.capability,
                    "status": job.status.value,
                    "payload": job.action_payload
                })

        # 2. Gather ready persistent DAG tasks if project active
        if self.project_manager and getattr(self.project_manager, "dag", None):
            ready_tasks = self.project_manager.dag.get_ready_tasks()
            for task in ready_tasks:
                queue.append({
                    "source": "project_dag",
                    "id": task.id,
                    "title": task.title,
                    "priority": "normal",
                    "priority_rank": 20,
                    "capability": task.capability,
                    "status": task.status.value if hasattr(task.status, "value") else str(task.status),
                    "payload": task.input_payload
                })

        # Sort by priority rank descending
        queue.sort(key=lambda x: x["priority_rank"], reverse=True)
        return queue


class ProactiveMaintenance:
    """Non-destructive proactive maintenance engine for long-running ZARA projects."""

    def __init__(self, project_manager: Optional[Any] = None, event_bus: Optional[Any] = None):
        self.project_manager = project_manager
        self.event_bus = event_bus

    def check_project_health(self) -> Dict[str, Any]:
        """Inspect project and identify stalled tasks, pending approvals, or missing artifacts."""
        if not self.project_manager or not self.project_manager.project:
            return {"status": "no_active_project"}

        issues = []
        # 1. Pending approvals
        if self.project_manager.pending_approval_ticket:
            issues.append({
                "type": "PENDING_APPROVAL",
                "message": f"Project has pending human confirmation ticket: {self.project_manager.pending_approval_ticket.get('action_id')}"
            })

        # 2. Stalled tasks via watchdog
        if self.project_manager.dag:
            for task in self.project_manager.dag.list_tasks():
                if hasattr(self.project_manager.watchdog, "check_health"):
                    health = self.project_manager.watchdog.check_health(task)
                elif hasattr(self.project_manager.watchdog, "check_task_health"):
                    health = self.project_manager.watchdog.check_task_health(
                        last_heartbeat=task.last_heartbeat,
                        started_at=task.created_at
                    )
                else:
                    continue
                if hasattr(health, "value") and health.value in ("stalled", "timed_out"):
                    issues.append({
                        "type": "STALLED_TASK",
                        "task_id": task.id,
                        "health": health.value,
                        "message": f"Task '{task.title}' ({task.id}) is {health.value}."
                    })

        # 3. Artifact verification
        if self.project_manager.artifacts:
            for rec in self.project_manager.artifacts.list_all():
                art_p = Path(rec.path)
                if not art_p.is_absolute() and self.project_manager.workspace_path:
                    art_p = Path(self.project_manager.workspace_path) / art_p
                if not art_p.exists():
                    issues.append({
                        "type": "MISSING_ARTIFACT",
                        "artifact_id": rec.artifact_id,
                        "file_path": str(art_p),
                        "message": f"Registered artifact '{rec.path}' not found on disk."
                    })

        return {
            "project_id": self.project_manager.project.project_id,
            "project_name": self.project_manager.project.name,
            "issues_count": len(issues),
            "issues": issues
        }
