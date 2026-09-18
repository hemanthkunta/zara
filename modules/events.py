"""
ZARA Central Event System:
Event definitions, persistent event bus, event deduplication,
condition watchers, and trigger loop / storm protection.
"""
import os
import re
import json
import uuid
import time
import threading
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Set
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import (
    BASE_DIR,
    EVENTS_LOG_FILE,
    MAX_TRIGGER_CHAIN_DEPTH,
    TRIGGER_COOLDOWN_SECONDS
)
from core.observability import audit_logger


class EventType(str, Enum):
    TIMER = "timer"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_STALLED = "task_stalled"
    PROJECT_BLOCKED = "project_blocked"
    PROJECT_COMPLETED = "project_completed"
    ARTIFACT_CHANGED = "artifact_changed"
    APPROVAL_PENDING = "approval_pending"
    SYSTEM_START = "system_start"
    SYSTEM_RESUME = "system_resume"
    SYSTEM_SHUTDOWN = "system_shutdown"
    FILE_CHANGED = "file_changed"
    AUTONOMOUS_TICK = "autonomous_tick"
    SCHEDULED_JOB_TRIGGERED = "scheduled_job_triggered"
    MAINTENANCE_REQUIRED = "maintenance_required"
    CHAIN_BLOCKED = "autonomous_chain_blocked"
    SCREEN_CHANGED = "screen_changed"
    APP_CHANGED = "app_changed"
    BLENDER_CHANGED = "blender_changed"
    CYBER_STATE_CHANGED = "cyber_state_changed"
    WORLD_STATE_CHANGED = "world_state_changed"
    MEMORY_CREATED = "memory_created"
    MEMORY_UPDATED = "memory_updated"
    MEMORY_CONFLICT = "memory_conflict"
    MEMORY_DELETED = "memory_deleted"
    WORKER_CREATED = "worker_created"
    WORKER_STARTED = "worker_started"
    WORKER_WAITING = "worker_waiting"
    WORKER_BLOCKED = "worker_blocked"
    WORKER_COMPLETED = "worker_completed"
    WORKER_FAILED = "worker_failed"
    WORKER_CANCELLED = "worker_cancelled"
    WORKER_RETRYING = "worker_retrying"
    WORKER_RESOURCE_LOCKED = "worker_resource_locked"
    WORKER_RESOURCE_RELEASED = "worker_resource_released"
    PARALLEL_BATCH_STARTED = "parallel_batch_started"
    PARALLEL_BATCH_COMPLETED = "parallel_batch_completed"
    MODEL_REQUEST_STARTED = "model_request_started"
    MODEL_SELECTED = "model_selected"
    MODEL_REQUEST_COMPLETED = "model_request_completed"
    MODEL_REQUEST_FAILED = "model_request_failed"
    MODEL_RETRY = "model_retry"
    MODEL_FAILOVER = "model_failover"
    PROVIDER_HEALTH_CHANGED = "provider_health_changed"
    CIRCUIT_BREAKER_OPENED = "circuit_breaker_opened"
    CIRCUIT_BREAKER_CLOSED = "circuit_breaker_closed"
    EVALUATION_STARTED = "evaluation_started"
    EVALUATION_COMPLETED = "evaluation_completed"
    LEARNING_CANDIDATE_CREATED = "learning_candidate_created"
    LEARNING_CANDIDATE_ACCEPTED = "learning_candidate_accepted"
    LEARNING_CANDIDATE_REJECTED = "learning_candidate_rejected"
    STRATEGY_CREATED = "strategy_created"
    STRATEGY_VALIDATED = "strategy_validated"
    STRATEGY_DEPRECATED = "strategy_deprecated"
    IMPROVEMENT_PROPOSED = "improvement_proposed"
    IMPROVEMENT_VALIDATED = "improvement_validated"
    IMPROVEMENT_REJECTED = "improvement_rejected"
    EXPERIMENT_STARTED = "experiment_started"
    EXPERIMENT_COMPLETED = "experiment_completed"
    IMPROVEMENT_DEPLOYED = "improvement_deployed"
    IMPROVEMENT_ROLLED_BACK = "improvement_rolled_back"
    CUSTOM = "custom"


def sanitize_event_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize external untrusted event payloads against prompt injection overrides and secrets."""
    clean = {}
    injection_patterns = [
        r"(?i)\bignore\s+previous\s+instructions\b",
        r"(?i)\bsystem\s+override\b",
        r"(?i)\bbypass\s+safety\b",
        r"(?i)\bdeveloper\s+mode\b"
    ]
    for k, v in payload.items():
        if isinstance(v, str):
            sanitized_str = v
            for pat in injection_patterns:
                sanitized_str = re.sub(pat, "[SANITIZED_PROMPT_INJECTION]", sanitized_str)
            sanitized_str = audit_logger.scrub_secrets(sanitized_str)
            clean[k] = sanitized_str
        elif isinstance(v, dict):
            clean[k] = sanitize_event_payload(v)
        else:
            clean[k] = v
    return clean


@dataclass
class Event:
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:10]}")
    type: EventType = EventType.CUSTOM
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    source: str = "system"  # scheduler, workspace, system, external, condition_watcher
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    schema_version: str = "1.0"
    chain_id: Optional[str] = None
    depth: int = 0

    def __post_init__(self):
        if not self.chain_id:
            self.chain_id = f"chn_{uuid.uuid4().hex[:8]}"
        if isinstance(self.type, str):
            try:
                self.type = EventType(self.type)
            except Exception:
                self.type = EventType.CUSTOM
        self.payload = sanitize_event_payload(self.payload)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value if hasattr(self.type, "value") else str(self.type)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        d = dict(data)
        if "type" in d:
            try:
                d["type"] = EventType(d["type"])
            except Exception:
                d["type"] = EventType.CUSTOM
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ConditionWatcher:
    watcher_id: str
    name: str
    event_type: EventType
    predicate: Callable[[Event], bool]
    handler: Callable[[Event], Any]
    max_triggers: int = 100
    cooldown_seconds: float = TRIGGER_COOLDOWN_SECONDS
    trigger_count: int = 0
    last_triggered_timestamp: float = 0.0
    enabled: bool = True

    def should_trigger(self, event: Event, current_time: float) -> bool:
        if not self.enabled or self.trigger_count >= self.max_triggers:
            return False
        if event.type != self.event_type:
            return False
        if current_time - self.last_triggered_timestamp < self.cooldown_seconds:
            return False
        try:
            return bool(self.predicate(event))
        except Exception:
            return False

    def execute(self, event: Event, current_time: float) -> Any:
        self.trigger_count += 1
        self.last_triggered_timestamp = current_time
        return self.handler(event)


class EventBus:
    """Thread-safe event publishing, deduplication, and subscriber routing bus."""

    def __init__(
        self,
        events_file: Optional[Path] = None,
        max_chain_depth: int = MAX_TRIGGER_CHAIN_DEPTH,
        cooldown_seconds: float = TRIGGER_COOLDOWN_SECONDS
    ):
        self.events_file = Path(events_file or EVENTS_LOG_FILE)
        self.max_chain_depth = max_chain_depth
        self.cooldown_seconds = cooldown_seconds

        self._lock = threading.RLock()
        self._subscribers: Dict[EventType, List[Callable[[Event], None]]] = {}
        self._watchers: Dict[str, ConditionWatcher] = {}
        self._seen_event_ids: Set[str] = set()
        self._chain_depths: Dict[str, int] = {}
        self._chain_last_seen: Dict[str, float] = {}

        # Ensure directory
        self.events_file.parent.mkdir(parents=True, exist_ok=True)

    def publish(self, event: Event, clock_time: Optional[float] = None) -> bool:
        """
        Publish an event to subscribers and watchers with deduplication and loop prevention.
        Returns True if processed, False if rejected/deduplicated/blocked.
        """
        now = clock_time if clock_time is not None else time.time()

        with self._lock:
            # 1. Event Deduplication ("Process Once")
            if event.event_id in self._seen_event_ids:
                return False
            self._seen_event_ids.add(event.event_id)
            # Bound seen cache to last 5000 IDs
            if len(self._seen_event_ids) > 5000:
                self._seen_event_ids = set(list(self._seen_event_ids)[-2500:])

            # 2. Trigger Loop & Chain-Depth Guard
            chain_id = event.chain_id or "root"
            cur_depth = event.depth

            self._chain_last_seen[chain_id] = now
            self._chain_depths[chain_id] = cur_depth

            if cur_depth > self.max_chain_depth:
                # Flag AUTONOMOUS_CHAIN_BLOCKED to protect against infinite trigger loops
                audit_logger.log_event(
                    "AUTONOMOUS_CHAIN_BLOCKED",
                    action="halt_loop",
                    extra={
                        "chain_id": chain_id,
                        "depth": cur_depth,
                        "max_depth": self.max_chain_depth,
                        "event_type": event.type.value
                    }
                )
                return False

            # 3. Persistence to Append-Only JSONL
            self._persist_event(event)

            # 4. Dispatch to Direct Subscribers
            subscribers = list(self._subscribers.get(event.type, []))
            all_subs = list(self._subscribers.get(EventType.CUSTOM, [])) if event.type != EventType.CUSTOM else []
            for handler in subscribers + all_subs:
                try:
                    handler(event)
                except Exception as e:
                    audit_logger.log_event("EVENT_HANDLER_ERROR", action="dispatch", error=str(e))

            # 5. Dispatch to Condition Watchers
            for watcher in list(self._watchers.values()):
                if watcher.should_trigger(event, now):
                    try:
                        watcher.execute(event, now)
                    except Exception as e:
                        audit_logger.log_event("WATCHER_EXEC_ERROR", action="execute", error=str(e))

            return True

    def _persist_event(self, event: Event) -> None:
        try:
            with open(self.events_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict()) + "\n")
        except Exception:
            pass

    def subscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> str:
        with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = []
            self._subscribers[event_type].append(callback)
            return f"sub_{uuid.uuid4().hex[:8]}"

    def unsubscribe(self, event_type: EventType, callback: Callable[[Event], None]) -> bool:
        with self._lock:
            if event_type in self._subscribers and callback in self._subscribers[event_type]:
                self._subscribers[event_type].remove(callback)
                return True
            return False


    def register_watcher(self, watcher: ConditionWatcher) -> str:
        with self._lock:
            self._watchers[watcher.watcher_id] = watcher
            return watcher.watcher_id

    def unregister_watcher(self, watcher_id: str) -> bool:
        with self._lock:
            return bool(self._watchers.pop(watcher_id, None))

    def get_watcher(self, watcher_id: str) -> Optional[ConditionWatcher]:
        with self._lock:
            return self._watchers.get(watcher_id)

    def list_watchers(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {
                    "watcher_id": w.watcher_id,
                    "name": w.name,
                    "event_type": w.event_type.value,
                    "trigger_count": w.trigger_count,
                    "enabled": w.enabled
                }
                for w in self._watchers.values()
            ]

    def read_persisted_events(self, limit: int = 100) -> List[Event]:
        """Read recent events from disk for recovery."""
        if not self.events_file.exists():
            return []
        events = []
        try:
            lines = self.events_file.read_text(encoding="utf-8").strip().splitlines()
            for line in lines[-limit:]:
                if line.strip():
                    events.append(Event.from_dict(json.loads(line)))
        except Exception:
            pass
        return events

    def clear(self) -> None:
        """Reset internal state for testing."""
        with self._lock:
            self._subscribers.clear()
            self._watchers.clear()
            self._seen_event_ids.clear()
            self._chain_depths.clear()
            self._chain_last_seen.clear()
