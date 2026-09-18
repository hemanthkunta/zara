"""
ZARA Persistent Scheduler & Priority Job Queue:
Deterministic time abstraction, cron validation, recurring schedules,
missed schedule recovery, and prioritized queue management.
"""
import os
import json
import uuid
import time
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import SCHEDULES_FILE, RiskLevel
from core.observability import audit_logger


# -------------------------------------------------------------
# Clock Abstraction (Injectable for Deterministic Testing)
# -------------------------------------------------------------

class Clock:
    """Base time provider."""
    def now(self) -> datetime.datetime:
        raise NotImplementedError

    def timestamp(self) -> float:
        return self.now().timestamp()


class SystemClock(Clock):
    """Production system clock using UTC."""
    def now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)


class MockClock(Clock):
    """Deterministic mock clock that can be advanced instantaneously in tests."""
    def __init__(self, initial_time: Optional[datetime.datetime] = None):
        self._current_time = initial_time or datetime.datetime(2026, 9, 18, 9, 0, 0, tzinfo=datetime.timezone.utc)

    def now(self) -> datetime.datetime:
        return self._current_time

    def set_time(self, new_time: datetime.datetime) -> None:
        if new_time.tzinfo is None:
            new_time = new_time.replace(tzinfo=datetime.timezone.utc)
        self._current_time = new_time

    def advance(self, seconds: float = 0, minutes: float = 0, hours: float = 0, days: float = 0) -> datetime.datetime:
        delta = datetime.timedelta(seconds=seconds, minutes=minutes, hours=hours, days=days)
        self._current_time += delta
        return self._current_time


# -------------------------------------------------------------
# Enums and Schedule Models
# -------------------------------------------------------------

class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CRON = "cron"


class JobStatus(str, Enum):
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        ranks = {"low": 10, "normal": 20, "high": 30, "critical": 40}
        return ranks.get(self.value, 20)


class MissedSchedulePolicy(str, Enum):
    RUN_NOW = "run_now"
    SKIP = "skip"
    RESCHEDULE = "reschedule"
    REQUIRES_USER_DECISION = "requires_user_decision"


@dataclass
class ScheduledJob:
    job_id: str
    name: str
    schedule_type: ScheduleType
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    cron_expression: Optional[str] = None
    interval_seconds: Optional[float] = None
    run_at: Optional[str] = None
    next_run: Optional[str] = None
    last_run: Optional[str] = None
    status: JobStatus = JobStatus.SCHEDULED
    priority: JobPriority = JobPriority.NORMAL
    enabled: bool = True
    max_runs: Optional[int] = None
    runs_completed: int = 0
    retry_policy: Dict[str, Any] = field(default_factory=lambda: {"max_retries": 2, "backoff": 2.0})
    retries_used: int = 0
    missed_policy: MissedSchedulePolicy = MissedSchedulePolicy.RUN_NOW
    capability: str = "general"
    action_payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["schedule_type"] = self.schedule_type.value if hasattr(self.schedule_type, "value") else str(self.schedule_type)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        d["priority"] = self.priority.value if hasattr(self.priority, "value") else str(self.priority)
        d["missed_policy"] = self.missed_policy.value if hasattr(self.missed_policy, "value") else str(self.missed_policy)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScheduledJob":
        d = dict(data)
        if "schedule_type" in d:
            try:
                d["schedule_type"] = ScheduleType(d["schedule_type"])
            except Exception:
                d["schedule_type"] = ScheduleType.ONCE
        if "status" in d:
            try:
                d["status"] = JobStatus(d["status"])
            except Exception:
                d["status"] = JobStatus.SCHEDULED
        if "priority" in d:
            try:
                d["priority"] = JobPriority(d["priority"])
            except Exception:
                d["priority"] = JobPriority.NORMAL
        if "missed_policy" in d:
            try:
                d["missed_policy"] = MissedSchedulePolicy(d["missed_policy"])
            except Exception:
                d["missed_policy"] = MissedSchedulePolicy.RUN_NOW
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# -------------------------------------------------------------
# Cron Syntax Parsing and Next-Run Calculation
# -------------------------------------------------------------

class CronValidationResult:
    def __init__(self, is_valid: bool, error: str = ""):
        self.is_valid = is_valid
        self.error = error

    def __bool__(self) -> bool:
        return self.is_valid

    def __iter__(self):
        return iter((self.is_valid, self.error))

    def __getitem__(self, index: int):
        return (self.is_valid, self.error)[index]


def validate_cron_expression(expr: str) -> CronValidationResult:
    """Validate 5-field standard cron format (minute hour dom month dow)."""
    if not expr or not isinstance(expr, str):
        return CronValidationResult(False, "Cron expression must be a non-empty string.")
    parts = expr.strip().split()
    if len(parts) != 5:
        return CronValidationResult(False, f"Must contain exactly 5 fields, got {len(parts)}.")
    # Validate each field roughly
    for idx, part in enumerate(parts):
        if part == "*":
            continue
        if part.startswith("*/"):
            step = part[2:]
            if not step.isdigit() or int(step) <= 0:
                return CronValidationResult(False, f"Invalid step expression: {part}")
            continue
        # Check numbers, ranges, or comma lists
        for sub in part.split(","):
            if "-" in sub:
                rng = sub.split("-")
                if len(rng) != 2 or not rng[0].isdigit() or not rng[1].isdigit():
                    return CronValidationResult(False, f"Invalid range expression: {sub}")
                val = int(rng[0])
            elif not sub.isdigit():
                return CronValidationResult(False, f"Invalid cron value: {sub}")
            else:
                val = int(sub)
            if idx == 0 and not (0 <= val <= 59):
                return CronValidationResult(False, f"Minute value {val} out of range (0-59)")
            elif idx == 1 and not (0 <= val <= 23):
                return CronValidationResult(False, f"Hour value {val} out of range (0-23)")
            elif idx == 2 and not (1 <= val <= 31):
                return CronValidationResult(False, f"Day of month value {val} out of range (1-31)")
            elif idx == 3 and not (1 <= val <= 12):
                return CronValidationResult(False, f"Month value {val} out of range (1-12)")
            elif idx == 4 and not (0 <= val <= 7):
                return CronValidationResult(False, f"Day of week value {val} out of range (0-7)")
    return CronValidationResult(True, "Valid cron expression.")



def calculate_next_run(job: ScheduledJob, current_time: datetime.datetime) -> Optional[datetime.datetime]:
    """Calculate the next execution timestamp based on schedule type and current time."""
    if not job.enabled:
        return None
    if job.max_runs is not None and job.runs_completed >= job.max_runs:
        return None

    if job.schedule_type == ScheduleType.ONCE:
        if job.run_at:
            dt = datetime.datetime.fromisoformat(job.run_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            return dt
        return current_time

    elif job.schedule_type == ScheduleType.INTERVAL:
        secs = job.interval_seconds or 60.0
        return current_time + datetime.timedelta(seconds=secs)

    elif job.schedule_type == ScheduleType.HOURLY:
        # Next top of the hour
        return current_time.replace(minute=0, second=0, microsecond=0) + datetime.timedelta(hours=1)

    elif job.schedule_type == ScheduleType.DAILY:
        # Tomorrow at the same time or specific hour
        target_hour = job.metadata.get("hour", 9)
        next_dt = current_time.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if next_dt <= current_time:
            next_dt += datetime.timedelta(days=1)
        return next_dt

    elif job.schedule_type == ScheduleType.WEEKLY:
        # Next week on specified day (default Saturday = 5)
        dow = job.metadata.get("day_of_week", 5)
        days_ahead = (dow - current_time.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        target_hour = job.metadata.get("hour", 9)
        return (current_time + datetime.timedelta(days=days_ahead)).replace(hour=target_hour, minute=0, second=0, microsecond=0)

    elif job.schedule_type == ScheduleType.CRON:
        if not job.cron_expression or not validate_cron_expression(job.cron_expression):
            return current_time + datetime.timedelta(hours=1)
        # Calculate next matching minute by incrementing minute-by-minute (bounded up to 1 month)
        candidate = current_time.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
        parts = job.cron_expression.split()
        for _ in range(60 * 24 * 31):
            if _cron_matches(parts, candidate):
                return candidate
            candidate += datetime.timedelta(minutes=1)
        return current_time + datetime.timedelta(days=1)

    return current_time + datetime.timedelta(hours=1)


def _cron_matches(parts: List[str], dt: datetime.datetime) -> bool:
    minute_p, hour_p, dom_p, month_p, dow_p = parts

    def match_part(part: str, val: int) -> bool:
        if part == "*":
            return True
        if part.startswith("*/"):
            step = int(part[2:])
            return val % step == 0
        if "-" in part:
            low, high = part.split("-")
            if low.isdigit() and high.isdigit():
                return int(low) <= val <= int(high)
        if "," in part:
            return val in [int(x) for x in part.split(",") if x.isdigit()]
        return val == int(part)

    # Note: in cron Sunday can be 0 or 7
    dow_val = dt.isoweekday() % 7

    return (
        match_part(minute_p, dt.minute) and
        match_part(hour_p, dt.hour) and
        match_part(dom_p, dt.day) and
        match_part(month_p, dt.month) and
        match_part(dow_p, dow_val)
    )


# -------------------------------------------------------------
# Persistent Scheduler
# -------------------------------------------------------------

class PersistentScheduler:
    """Manages scheduled jobs with atomic disk persistence, missed schedule handling, and mockable clock."""

    def __init__(
        self,
        schedules_file: Optional[Path] = None,
        clock: Optional[Clock] = None
    ):
        self.schedules_file = Path(schedules_file or SCHEDULES_FILE)
        self.clock = clock or SystemClock()
        self.jobs: Dict[str, ScheduledJob] = {}
        self.load()

    def load(self) -> None:
        """Load jobs from persistent storage."""
        if self.schedules_file.exists():
            try:
                data = json.loads(self.schedules_file.read_text(encoding="utf-8"))
                self.jobs = {j["job_id"]: ScheduledJob.from_dict(j) for j in data.get("jobs", [])}
            except Exception:
                self.jobs = {}
        else:
            self.jobs = {}

    def save(self) -> None:
        """Atomically persist jobs to disk."""
        self.schedules_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.schedules_file.with_suffix(f".tmp.{uuid.uuid4().hex[:6]}")
        data = {
            "version": "1.0",
            "updated_at": self.clock.now().isoformat(),
            "jobs": [j.to_dict() for j in self.jobs.values()]
        }
        try:
            temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_file.replace(self.schedules_file)
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def schedule_job(
        self,
        name: str,
        schedule_type: ScheduleType,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        cron_expression: Optional[str] = None,
        interval_seconds: Optional[float] = None,
        run_at: Optional[datetime.datetime] = None,
        priority: JobPriority = JobPriority.NORMAL,
        missed_policy: MissedSchedulePolicy = MissedSchedulePolicy.RUN_NOW,
        capability: str = "general",
        action_payload: Optional[Dict[str, Any]] = None,
        max_runs: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ScheduledJob:
        """Create and persist a new scheduled job."""
        job_id = f"job_{uuid.uuid4().hex[:8]}"

        run_at_str = run_at.isoformat() if run_at else None
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            project_id=project_id,
            task_id=task_id,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            interval_seconds=interval_seconds,
            run_at=run_at_str,
            status=JobStatus.SCHEDULED,
            priority=priority,
            missed_policy=missed_policy,
            capability=capability,
            action_payload=action_payload or {},
            max_runs=max_runs or (1 if schedule_type == ScheduleType.ONCE else None),
            metadata=metadata or {},
            created_at=self.clock.now().isoformat()
        )

        # Compute first next_run
        next_dt = calculate_next_run(job, self.clock.now())
        job.next_run = next_dt.isoformat() if next_dt else None

        self.jobs[job_id] = job
        self.save()

        audit_logger.log_event(
            "JOB_SCHEDULED",
            action="schedule",
            extra={"job_id": job_id, "name": name, "next_run": job.next_run}
        )
        return job

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        return self.jobs.get(job_id)

    def list_jobs(self, status: Optional[JobStatus] = None) -> List[ScheduledJob]:
        if status:
            return [j for j in self.jobs.values() if j.status == status]
        return list(self.jobs.values())

    def pause_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status in (JobStatus.SCHEDULED, JobStatus.RUNNING):
            job.status = JobStatus.PAUSED
            self.save()
            return True
        return False

    def resume_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job and job.status == JobStatus.PAUSED:
            job.status = JobStatus.SCHEDULED
            # Recompute next run if expired
            if job.next_run:
                try:
                    dt = datetime.datetime.fromisoformat(job.next_run)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=datetime.timezone.utc)
                    if dt < self.clock.now():
                        next_dt = calculate_next_run(job, self.clock.now())
                        job.next_run = next_dt.isoformat() if next_dt else None
                except Exception:
                    pass
            self.save()
            return True
        return False

    def cancel_job(self, job_id: str) -> bool:
        job = self.jobs.get(job_id)
        if job:
            job.status = JobStatus.CANCELLED
            job.enabled = False
            self.save()
            return True
        return False

    def get_due_jobs(self) -> List[ScheduledJob]:
        """Find enabled jobs whose scheduled next_run timestamp is <= current time."""
        now = self.clock.now()
        due = []
        for job in self.jobs.values():
            if not job.enabled or job.status != JobStatus.SCHEDULED or not job.next_run:
                continue
            try:
                run_dt = datetime.datetime.fromisoformat(job.next_run)
                if run_dt.tzinfo is None:
                    run_dt = run_dt.replace(tzinfo=datetime.timezone.utc)
                if run_dt <= now:
                    due.append(job)
            except Exception:
                continue

        # Sort by priority rank descending
        due.sort(key=lambda j: j.priority.rank, reverse=True)
        return due

    def mark_job_running(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if job:
            job.status = JobStatus.RUNNING
            job.last_run = self.clock.now().isoformat()
            self.save()

    def mark_job_completed(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        job.runs_completed += 1
        job.retries_used = 0

        # Check if max runs reached
        if job.max_runs is not None and job.runs_completed >= job.max_runs:
            job.status = JobStatus.COMPLETED
            job.next_run = None
        else:
            job.status = JobStatus.SCHEDULED
            next_dt = calculate_next_run(job, self.clock.now())
            job.next_run = next_dt.isoformat() if next_dt else None

        self.save()

    def mark_job_failed(self, job_id: str, error: str = "", fatal: bool = False) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return

        is_fatal = fatal or "scopeviolation" in error.lower() or "unauthorized" in error.lower()
        max_retries = job.retry_policy.get("max_retries", 2)
        if not is_fatal and job.retries_used < max_retries:
            job.retries_used += 1
            job.status = JobStatus.SCHEDULED
            # Short exponential backoff retry
            backoff_secs = 30.0 * (job.retry_policy.get("backoff", 2.0) ** (job.retries_used - 1))
            job.next_run = (self.clock.now() + datetime.timedelta(seconds=backoff_secs)).isoformat()
        else:
            job.status = JobStatus.FAILED
            job.next_run = None

        self.save()

    def recover_missed_schedules(self) -> List[Tuple[ScheduledJob, str]]:
        """
        On startup, detect and handle jobs whose next_run passed while ZARA was offline.
        Returns list of (job, action_taken).
        """
        now = self.clock.now()
        actions = []

        for job in self.jobs.values():
            if not job.enabled or job.status != JobStatus.SCHEDULED or not job.next_run:
                continue
            try:
                run_dt = datetime.datetime.fromisoformat(job.next_run)
                if run_dt.tzinfo is None:
                    run_dt = run_dt.replace(tzinfo=datetime.timezone.utc)
                if run_dt < now:
                    policy = job.missed_policy
                    if policy == MissedSchedulePolicy.RUN_NOW:
                        # Keep next_run so get_due_jobs executes it
                        actions.append((job, "run_now"))
                    elif policy == MissedSchedulePolicy.SKIP:
                        next_dt = calculate_next_run(job, now)
                        job.next_run = next_dt.isoformat() if next_dt else None
                        actions.append((job, "skipped_to_next"))
                    elif policy == MissedSchedulePolicy.RESCHEDULE:
                        next_dt = calculate_next_run(job, now)
                        job.next_run = next_dt.isoformat() if next_dt else None
                        actions.append((job, "rescheduled"))
                    elif policy == MissedSchedulePolicy.REQUIRES_USER_DECISION:
                        job.status = JobStatus.WAITING_APPROVAL
                        actions.append((job, "waiting_approval"))
            except Exception:
                continue

        if actions:
            self.save()
        return actions


# -------------------------------------------------------------
# Persistent Job Queue
# -------------------------------------------------------------

@dataclass
class QueueItem:
    item_id: str
    job_id: str
    name: str
    priority: JobPriority
    capability: str
    payload: Dict[str, Any]
    status: str = "READY"  # READY, RUNNING, VERIFYING, COMPLETED, FAILED
    attempts: int = 0
    enqueued_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["priority"] = self.priority.value if hasattr(self.priority, "value") else str(self.priority)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "QueueItem":
        d = dict(data)
        if "priority" in d:
            try:
                d["priority"] = JobPriority(d["priority"])
            except Exception:
                d["priority"] = JobPriority.NORMAL
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class JobQueue:
    """Persistent priority queue with crash resilience and bounded retries."""

    def __init__(self, queue_file: Optional[Path] = None):
        self.queue_file = Path(queue_file or (SCHEDULES_FILE.parent / "job_queue.json"))
        self.items: Dict[str, QueueItem] = {}
        self.is_paused: bool = False
        self.load()

    def load(self) -> None:
        if self.queue_file.exists():
            try:
                data = json.loads(self.queue_file.read_text(encoding="utf-8"))
                self.items = {item["item_id"]: QueueItem.from_dict(item) for item in data.get("items", [])}
                self.is_paused = data.get("is_paused", False)
                # Crash recovery: Any item left RUNNING reverts to READY
                for it in self.items.values():
                    if it.status in ("RUNNING", "VERIFYING"):
                        it.status = "READY"
            except Exception:
                self.items = {}
        else:
            self.items = {}

    def save(self) -> None:
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file = self.queue_file.with_suffix(f".tmp.{uuid.uuid4().hex[:6]}")
        data = {
            "version": "1.0",
            "is_paused": self.is_paused,
            "items": [it.to_dict() for it in self.items.values()]
        }
        try:
            temp_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
            temp_file.replace(self.queue_file)
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def _save(self) -> None:
        self.save()


    def enqueue(
        self,
        job_or_id: Any,
        name: Optional[str] = None,
        priority: Optional[JobPriority] = None,
        capability: str = "general",
        payload: Optional[Dict[str, Any]] = None
    ) -> QueueItem:
        if isinstance(job_or_id, ScheduledJob):
            job_id = job_or_id.job_id
            job_name = job_or_id.name
            job_prio = job_or_id.priority
            job_cap = job_or_id.capability
            job_load = dict(job_or_id.action_payload)
        else:
            job_id = str(job_or_id)
            job_name = name or job_id
            job_prio = priority or JobPriority.NORMAL
            job_cap = capability
            job_load = dict(payload or {})

        # Check if already enqueued
        for item in self.items.values():
            if item.job_id == job_id and item.status in ("READY", "RUNNING"):
                return item

        item_id = f"qitem_{uuid.uuid4().hex[:8]}"
        item = QueueItem(
            item_id=item_id,
            job_id=job_id,
            name=job_name,
            priority=job_prio,
            capability=job_cap,
            payload=job_load,
            status="READY"
        )
        self.items[item_id] = item
        self.save()
        return item


    def pop_ready(self) -> Optional[QueueItem]:
        """Pop highest priority ready item."""
        if self.is_paused:
            return None

        ready = [it for it in self.items.values() if it.status == "READY"]
        if not ready:
            return None

        # Sort by priority rank descending, then enqueued_at ascending
        ready.sort(key=lambda x: (x.priority.rank, -x.attempts), reverse=True)
        chosen = ready[0]
        chosen.status = "RUNNING"
        chosen.attempts += 1
        self.save()
        return chosen

    def peek_ready(self) -> Optional[QueueItem]:
        """Peek highest priority ready item without marking running."""
        ready = [it for it in self.items.values() if it.status == "READY"]
        if not ready:
            return None
        ready.sort(key=lambda x: (x.priority.rank, -x.attempts), reverse=True)
        return ready[0]

    def pop(self) -> Optional[QueueItem]:
        return self.pop_ready()

    def peek(self) -> Optional[QueueItem]:
        return self.peek_ready()


    def mark_completed(self, item_id: str) -> None:
        if item_id in self.items:
            self.items[item_id].status = "COMPLETED"
            self.save()

    def mark_failed(self, item_id: str, max_attempts: int = 3) -> None:
        item = self.items.get(item_id)
        if item:
            if item.attempts < max_attempts:
                item.status = "READY"
            else:
                item.status = "FAILED"
            self.save()

    def pause(self) -> None:
        self.is_paused = True
        self.save()

    def resume(self) -> None:
        self.is_paused = False
        self.save()

    def clear(self) -> None:
        self.items.clear()
        self.save()
