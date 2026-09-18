"""
ZARA Persistent Autonomous Workspace & Long-Running Projects System.
Manages durable workspace manifests, task DAGs, atomic checkpoints, crash recovery,
artifact registry, append-only event journals, approval continuity, and task watchdogs.
"""
import os
import sys
import json
import time
import uuid
import hashlib
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import BASE_DIR, PROJECTS_DIR, RiskLevel
from core.state import StepStatus


class ProjectStatus(str, Enum):
    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERING = "recovering"


class ProjectType(str, Enum):
    GENERAL = "general"
    CYBERSECURITY_ASSESSMENT = "cybersecurity_assessment"
    BLENDER_SCENE = "blender_scene"
    BLENDER_ENVIRONMENT = "blender_environment"


class RecoveryClassification(str, Enum):
    SAFE_RESUME = "SAFE_RESUME"
    RETRY = "RETRY"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"


class TaskHealth(str, Enum):
    HEALTHY = "healthy"
    STALLED = "stalled"
    TIMED_OUT = "timed_out"
    CRASHED = "crashed"
    UNKNOWN = "unknown"


@dataclass
class ProjectBudget:
    max_steps: int = 200
    steps_taken: int = 0
    max_retries: int = 25
    retries_used: int = 0
    max_execution_time_seconds: float = 7200.0
    execution_time_seconds: float = 0.0
    max_research_queries: int = 50
    research_queries: int = 0
    max_opened_pages: int = 50
    opened_pages: int = 0
    max_tool_calls: int = 300
    tool_calls: int = 0

    def record(
        self,
        steps: int = 0,
        retries: int = 0,
        exec_time: float = 0.0,
        queries: int = 0,
        pages: int = 0,
        tools: int = 0
    ) -> None:
        self.steps_taken += steps
        self.retries_used += retries
        self.execution_time_seconds += exec_time
        self.research_queries += queries
        self.opened_pages += pages
        self.tool_calls += tools

    def is_exceeded(self) -> Tuple[bool, Optional[str]]:
        if self.steps_taken >= self.max_steps:
            return True, f"Exceeded maximum steps budget ({self.steps_taken}/{self.max_steps})"
        if self.retries_used >= self.max_retries:
            return True, f"Exceeded maximum retries budget ({self.retries_used}/{self.max_retries})"
        if self.execution_time_seconds >= self.max_execution_time_seconds:
            return True, f"Exceeded maximum execution time ({self.execution_time_seconds:.1f}s/{self.max_execution_time_seconds:.1f}s)"
        if self.research_queries >= self.max_research_queries:
            return True, f"Exceeded maximum research queries ({self.research_queries}/{self.max_research_queries})"
        if self.opened_pages >= self.max_opened_pages:
            return True, f"Exceeded maximum opened pages ({self.opened_pages}/{self.max_opened_pages})"
        if self.tool_calls >= self.max_tool_calls:
            return True, f"Exceeded maximum tool calls ({self.tool_calls}/{self.max_tool_calls})"
        return False, None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectBudget":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ArtifactRecord:
    artifact_id: str
    project_id: str
    task_id: str
    path: str
    type: str  # code, test, document, research, report, data, image, other
    size: int
    checksum: str  # sha256
    created_at: str
    modified_at: str
    version: int = 1
    status: str = "registered"  # registered, verified, modified, deleted
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ArtifactRecord":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class PersistentTask:
    id: str
    project_id: str
    parent_id: Optional[str] = None
    title: str = ""
    description: str = ""
    status: StepStatus = StepStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    capability: str = "general"  # coding, research, terminal, vision, general
    attempts: int = 0
    max_attempts: int = 3
    checkpoint_id: Optional[str] = None
    artifacts: List[str] = field(default_factory=list)
    verification: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    completed_at: Optional[str] = None
    input_payload: Dict[str, Any] = field(default_factory=dict)
    output_result: Dict[str, Any] = field(default_factory=dict)
    last_heartbeat: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersistentTask":
        d = dict(data)
        if "status" in d:
            status_val = d["status"]
            try:
                d["status"] = StepStatus(status_val)
            except Exception:
                d["status"] = StepStatus.PENDING
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class DurableCheckpoint:
    checkpoint_id: str
    project_id: str
    task_id: str
    state_snapshot: Dict[str, Any]
    completed_steps: List[Dict[str, Any]]
    pending_steps: List[Dict[str, Any]]
    artifacts: List[Dict[str, Any]]
    verification: Optional[Dict[str, Any]] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DurableCheckpoint":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class JournalEntry:
    event_id: str
    timestamp: str
    project_id: str
    task_id: Optional[str]
    event_type: str
    payload: Dict[str, Any]
    schema_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JournalEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ProjectSnapshot:
    snapshot_id: str
    project_id: str
    timestamp: str
    files: Dict[str, Dict[str, Any]] = field(default_factory=dict)  # relpath -> {size, mtime, checksum}

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProjectSnapshot":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def diff(self, other: "ProjectSnapshot") -> Dict[str, List[str]]:
        """Compare two snapshots and return added, modified, and removed files."""
        current_paths = set(self.files.keys())
        other_paths = set(other.files.keys())

        added = sorted(list(current_paths - other_paths))
        removed = sorted(list(other_paths - current_paths))
        modified = []

        for p in current_paths & other_paths:
            if self.files[p].get("checksum") != other.files[p].get("checksum"):
                modified.append(p)

        return {
            "added": added,
            "modified": sorted(modified),
            "removed": removed
        }


@dataclass
class PersistentProject:
    project_id: str
    name: str
    description: str
    workspace_path: str
    status: ProjectStatus = ProjectStatus.CREATED
    project_type: ProjectType = ProjectType.GENERAL
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    current_task_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    version: str = "1.0"
    budget: ProjectBudget = field(default_factory=ProjectBudget)
    project_memory: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        d["project_type"] = self.project_type.value if hasattr(self.project_type, "value") else str(self.project_type)
        d["budget"] = self.budget.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersistentProject":
        d = dict(data)
        if "status" in d:
            try:
                d["status"] = ProjectStatus(d["status"])
            except Exception:
                d["status"] = ProjectStatus.CREATED
        if "project_type" in d:
            try:
                d["project_type"] = ProjectType(d["project_type"])
            except Exception:
                d["project_type"] = ProjectType.GENERAL
        else:
            d["project_type"] = ProjectType.GENERAL
        if "budget" in d and isinstance(d["budget"], dict):
            d["budget"] = ProjectBudget.from_dict(d["budget"])
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def _atomic_write_json(file_path: Path, data: Any) -> None:
    """Safely and atomically write JSON data to disk using a temporary file."""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = file_path.with_suffix(f".tmp.{uuid.uuid4().hex[:6]}")
    try:
        temp_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        temp_path.replace(file_path)
    except Exception:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise


def _compute_sha256(file_path: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    if not file_path.exists() or file_path.is_dir():
        return ""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


class ArtifactRegistry:
    """Persistent registry of all artifacts generated or modified in a project."""

    def __init__(self, manifest_file: Path, workspace_path: Path):
        self.manifest_file = Path(manifest_file)
        self.workspace_path = Path(workspace_path)
        self.artifacts: Dict[str, ArtifactRecord] = {}
        self.load()

    def register(
        self,
        rel_or_abs_path: str,
        task_id: str = "general",
        project_id: str = "default",
        artifact_type: str = "code",
        metadata: Optional[Dict[str, Any]] = None
    ) -> ArtifactRecord:
        """Register or update an artifact record with SHA-256 checksum."""
        file_path = Path(rel_or_abs_path)
        if not file_path.is_absolute():
            file_path = self.workspace_path / file_path
        file_path = file_path.resolve()
        ws_resolved = self.workspace_path.resolve()

        try:
            rel_path = str(file_path.relative_to(ws_resolved))
        except ValueError:
            rel_path = str(file_path)
        checksum = _compute_sha256(file_path) if file_path.exists() else ""
        size = file_path.stat().st_size if file_path.exists() else 0
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Check if already registered
        existing = self.get_by_path(rel_path)
        if existing:
            version = existing.version + 1 if existing.checksum != checksum else existing.version
            existing.size = size
            existing.checksum = checksum
            existing.modified_at = now
            existing.version = version
            existing.task_id = task_id
            existing.status = "verified" if checksum else "missing"
            if metadata:
                existing.metadata.update(metadata)
            self.save()
            return existing

        art_id = f"art-{uuid.uuid4().hex[:8]}"
        record = ArtifactRecord(
            artifact_id=art_id,
            project_id=project_id,
            task_id=task_id,
            path=rel_path,
            type=artifact_type,
            size=size,
            checksum=checksum,
            created_at=now,
            modified_at=now,
            version=1,
            status="verified" if checksum else "registered",
            metadata=metadata or {}
        )
        self.artifacts[art_id] = record
        self.save()
        return record

    def register_artifact(
        self,
        rel_or_abs_path: str,
        task_id: str = "general",
        project_id: str = "default",
        artifact_type: str = "code",
        metadata: Optional[Dict[str, Any]] = None
    ) -> ArtifactRecord:
        """Alias for register."""
        return self.register(rel_or_abs_path, task_id, project_id, artifact_type, metadata)


    def verify(self, artifact_id_or_path: str) -> Tuple[bool, str, str]:
        """
        Verify artifact integrity using SHA-256.
        Returns: (is_valid, current_checksum, expected_checksum)
        """
        record = self.artifacts.get(artifact_id_or_path) or self.get_by_path(artifact_id_or_path)
        if not record:
            return False, "", "not_found"

        file_path = self.workspace_path / record.path
        if not file_path.exists():
            record.status = "missing"
            self.save()
            return False, "", record.checksum

        current_checksum = _compute_sha256(file_path)
        is_valid = current_checksum == record.checksum
        record.status = "verified" if is_valid else "tampered"
        self.save()
        return is_valid, current_checksum, record.checksum

    def get(self, artifact_id: str) -> Optional[ArtifactRecord]:
        return self.artifacts.get(artifact_id)

    def get_by_path(self, rel_path: str) -> Optional[ArtifactRecord]:
        clean_target = str(Path(rel_path))
        for art in self.artifacts.values():
            if str(Path(art.path)) == clean_target:
                return art
        return None

    def list_all(self) -> List[ArtifactRecord]:
        return sorted(list(self.artifacts.values()), key=lambda a: a.created_at)

    def get_by_task(self, task_id: str) -> List[ArtifactRecord]:
        return [a for a in self.artifacts.values() if a.task_id == task_id]

    def load(self) -> None:
        if not self.manifest_file.exists():
            return
        try:
            data = json.loads(self.manifest_file.read_text(encoding="utf-8"))
            self.artifacts = {
                item["artifact_id"]: ArtifactRecord.from_dict(item)
                for item in data.get("artifacts", [])
            }
        except Exception:
            self.artifacts = {}

    def save(self) -> None:
        data = {
            "version": "1.0",
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "artifacts": [a.to_dict() for a in self.artifacts.values()]
        }
        _atomic_write_json(self.manifest_file, data)


class ProjectJournal:
    """Append-only thread-safe event journal stored as JSON Lines."""

    def __init__(self, journal_file: Path, project_id: str):
        self.journal_file = Path(journal_file)
        self.project_id = project_id
        self.journal_file.parent.mkdir(parents=True, exist_ok=True)

    def append(
        self,
        event_type: str,
        task_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None
    ) -> JournalEntry:
        """Append an event to the journal."""
        entry = JournalEntry(
            event_id=f"evt-{uuid.uuid4().hex[:8]}",
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            project_id=self.project_id,
            task_id=task_id,
            event_type=event_type,
            payload=payload or {}
        )
        line = json.dumps(entry.to_dict(), default=str) + "\n"
        with open(self.journal_file, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
        return entry

    def read_events(
        self,
        event_type: Optional[str] = None,
        task_id: Optional[str] = None
    ) -> List[JournalEntry]:
        """Read all or filtered events from the journal."""
        if not self.journal_file.exists():
            return []
        events = []
        with open(self.journal_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = JournalEntry.from_dict(data)
                    if event_type and entry.event_type != event_type:
                        continue
                    if task_id and entry.task_id != task_id:
                        continue
                    events.append(entry)
                except Exception:
                    continue
        return events


class PersistentDAG:
    """Directed Acyclic Graph manager for persistent project tasks."""

    def __init__(self, tasks_file: Path, project_id: str):
        self.tasks_file = Path(tasks_file)
        self.project_id = project_id
        self.tasks: Dict[str, PersistentTask] = {}
        self.load()

    def add_task(self, task: PersistentTask) -> None:
        self.tasks[task.id] = task
        self.save()

    def get_task(self, task_id: str) -> Optional[PersistentTask]:
        return self.tasks.get(task_id)

    def list_tasks(self) -> List[PersistentTask]:
        return list(self.tasks.values())

    def get_ready_tasks(self) -> List[PersistentTask]:
        """Find pending tasks whose all dependencies have PASSED."""
        ready = []
        for task in self.tasks.values():
            if task.status != StepStatus.PENDING:
                continue
            deps_met = True
            for dep_id in task.dependencies:
                dep_task = self.tasks.get(dep_id)
                if not dep_task or dep_task.status != StepStatus.PASSED:
                    deps_met = False
                    break
            if deps_met:
                ready.append(task)
        return ready

    def topological_sort(self) -> List[PersistentTask]:
        """Return tasks in dependency order."""
        visited: Set[str] = set()
        visiting: Set[str] = set()
        order: List[PersistentTask] = []

        def dfs(task_id: str):
            if task_id in visiting:
                raise ValueError(f"Cycle detected in task dependencies at {task_id}")
            if task_id in visited:
                return
            visiting.add(task_id)
            task = self.tasks.get(task_id)
            if task:
                for dep_id in task.dependencies:
                    if dep_id in self.tasks:
                        dfs(dep_id)
                visiting.remove(task_id)
                visited.add(task_id)
                order.append(task)

        for tid in self.tasks:
            if tid not in visited:
                dfs(tid)
        return order

    def update_task_status(
        self,
        task_id: str,
        status: StepStatus,
        error: Optional[str] = None,
        verification: Optional[Dict[str, Any]] = None,
        checkpoint_id: Optional[str] = None
    ) -> Optional[PersistentTask]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        task.status = status
        task.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if status == StepStatus.PASSED:
            task.completed_at = task.updated_at
        if error:
            task.error = error
        if verification:
            task.verification = verification
        if checkpoint_id:
            task.checkpoint_id = checkpoint_id
        self.save()
        return task

    def load(self) -> None:
        if not self.tasks_file.exists():
            return
        try:
            data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
            self.tasks = {
                t["id"]: PersistentTask.from_dict(t)
                for t in data.get("tasks", [])
            }
        except Exception:
            self.tasks = {}

    def save(self) -> None:
        data = {
            "version": "1.0",
            "project_id": self.project_id,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "tasks": [t.to_dict() for t in self.tasks.values()]
        }
        _atomic_write_json(self.tasks_file, data)


class TaskWatchdog:
    """Monitors task execution health, identifying stalled, timed out, or crashed tasks."""

    def __init__(self, default_timeout_seconds: float = 300.0, stall_threshold_seconds: float = 60.0):
        self.default_timeout_seconds = default_timeout_seconds
        self.stall_threshold_seconds = stall_threshold_seconds

    def check_health(
        self,
        task: PersistentTask,
        timeout_seconds: Optional[float] = None
    ) -> TaskHealth:
        """Classify task health based on status, timestamp, and heartbeat."""
        if task.status != StepStatus.RUNNING:
            return TaskHealth.HEALTHY

        now = datetime.datetime.now(datetime.timezone.utc)
        timeout = timeout_seconds or self.default_timeout_seconds

        # Check last heartbeat or update
        check_time_str = task.last_heartbeat or task.updated_at
        try:
            last_dt = datetime.datetime.fromisoformat(check_time_str)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
            elapsed = (now - last_dt).total_seconds()
        except Exception:
            return TaskHealth.UNKNOWN

        if elapsed > timeout:
            return TaskHealth.TIMED_OUT
        elif elapsed > self.stall_threshold_seconds:
            return TaskHealth.STALLED

        return TaskHealth.HEALTHY


class ProjectManager:
    """Authoritative lifecycle and persistence manager for long-running ZARA projects."""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path).resolve()
        self.zara_dir = self.workspace_path / ".zara"
        self.checkpoints_dir = self.zara_dir / "checkpoints"
        self.snapshots_dir = self.zara_dir / "snapshots"

        self.project_file = self.zara_dir / "project.json"
        self.state_file = self.zara_dir / "state.json"
        self.tasks_file = self.zara_dir / "tasks.json"
        self.artifacts_file = self.zara_dir / "artifacts.json"
        self.journal_file = self.zara_dir / "journal.jsonl"
        self.planning_file = self.zara_dir / "planning.json"
        self.decisions_file = self.zara_dir / "decisions.jsonl"
        self.summaries_file = self.zara_dir / "summaries.json"
        self.world_state_file = self.zara_dir / "world_state.json"
        self.world_snapshots_dir = self.zara_dir / "world_snapshots"

        # Ensure directory structure
        for d in (self.zara_dir, self.checkpoints_dir, self.snapshots_dir, self.world_snapshots_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.project: Optional[PersistentProject] = None
        self.dag: Optional[PersistentDAG] = None
        self.artifacts: Optional[ArtifactRegistry] = None
        self.journal: Optional[ProjectJournal] = None
        self.watchdog = TaskWatchdog()
        self.pending_approval_ticket: Optional[Dict[str, Any]] = None

        if self.project_file.exists():
            self._load_all()

    def create_project(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        budget: Optional[ProjectBudget] = None,
        project_type: ProjectType = ProjectType.GENERAL
    ) -> None:
        """Create and persist a project manifest on this manager instance."""
        proj_id = f"proj-{uuid.uuid4().hex[:8]}"
        self.project = PersistentProject(
            project_id=proj_id,
            name=name,
            description=description,
            workspace_path=str(self.workspace_path),
            status=ProjectStatus.CREATED,
            project_type=project_type,
            metadata=metadata or {},
            budget=budget or ProjectBudget(),
            created_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            updated_at=datetime.datetime.now(datetime.timezone.utc).isoformat()
        )
        self.dag = PersistentDAG(self.tasks_file)
        self.artifacts = ArtifactRegistry(self.artifacts_file, self.workspace_path)
        self.journal = ProjectJournal(self.journal_file)
        self.save_manifest()

    @classmethod
    def create(
        cls,
        name: str,
        workspace_path: Path,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
        budget: Optional[ProjectBudget] = None,
        project_type: ProjectType = ProjectType.GENERAL
    ) -> "ProjectManager":
        """Initialize and persist a brand new project manifest."""
        mgr = cls(workspace_path)
        proj_id = f"proj-{uuid.uuid4().hex[:8]}"
        mgr.project = PersistentProject(
            project_id=proj_id,
            name=name,
            description=description,
            workspace_path=str(mgr.workspace_path),
            status=ProjectStatus.CREATED,
            project_type=project_type,
            metadata=metadata or {},
            budget=budget or ProjectBudget()
        )
        mgr.dag = PersistentDAG(mgr.tasks_file, proj_id)
        mgr.artifacts = ArtifactRegistry(mgr.artifacts_file, mgr.workspace_path)
        mgr.journal = ProjectJournal(mgr.journal_file, proj_id)

        mgr.save_manifest()
        mgr.journal.append("PROJECT_CREATED", payload={"name": name, "workspace": str(mgr.workspace_path), "type": project_type.value})
        return mgr

    @classmethod
    def create_cybersecurity_assessment_project(
        cls,
        name: str,
        workspace_path: Path,
        target_host: str,
        target_name: str = "Authorized Lab Target",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ProjectManager":
        """Factory template for persistent cybersecurity lab assessment project with structured DAG."""
        meta = dict(metadata or {})
        meta.update({
            "target_host": target_host,
            "target_name": target_name,
            "domain": "cybersecurity"
        })
        mgr = cls.create(
            name=name,
            workspace_path=workspace_path,
            description=description or f"Cybersecurity lab vulnerability assessment against {target_name} ({target_host})",
            metadata=meta,
            project_type=ProjectType.CYBERSECURITY_ASSESSMENT
        )
        pid = mgr.project.project_id

        # Construct authoritative security DAG
        t1 = PersistentTask(id="task_scope_validation", project_id=pid, title="Scope & Authorization Validation", description=f"Validate {target_host} against strict lab allowlist.", capability="cyber")
        t2 = PersistentTask(id="task_nmap_recon", project_id=pid, title="Nmap Reconnaissance", description="Perform port and service enumeration.", dependencies=["task_scope_validation"], capability="cyber")
        t3 = PersistentTask(id="task_zap_web_audit", project_id=pid, title="OWASP ZAP Web Audit", description="Scan web endpoints and headers for vulnerabilities.", dependencies=["task_scope_validation"], capability="cyber")
        t4 = PersistentTask(id="task_sql_injection_audit", project_id=pid, title="SQLMap Injection Audit", description="Test injection points and parameter sanitization.", dependencies=["task_nmap_recon"], capability="cyber")
        t5 = PersistentTask(id="task_exploitability_assessment", project_id=pid, title="Metasploit Exploitability Assessment", description="Verify exploitability (requires human confirmation ticket).", dependencies=["task_zap_web_audit", "task_sql_injection_audit"], capability="cyber")
        t6 = PersistentTask(id="task_executive_report", project_id=pid, title="Executive Security Report", description="Synthesize findings, scrub credentials, and generate remediation report.", dependencies=["task_exploitability_assessment"], capability="cyber")

        for t in [t1, t2, t3, t4, t5, t6]:
            mgr.dag.add_task(t)

        mgr.save_manifest()
        return mgr

    @classmethod
    def create_blender_scene_project(
        cls,
        name: str,
        workspace_path: Path,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ProjectManager":
        """Factory template for procedural Blender 3D scene project with inspection and rendering DAG."""
        meta = dict(metadata or {})
        meta.update({
            "scene_type": scene_type,
            "mesh_name": mesh_name,
            "domain": "blender"
        })
        mgr = cls.create(
            name=name,
            workspace_path=workspace_path,
            description=description or f"Blender procedural 3D scene generation for {mesh_name} ({scene_type})",
            metadata=meta,
            project_type=ProjectType.BLENDER_SCENE
        )
        pid = mgr.project.project_id

        t1 = PersistentTask(id="task_blender_binary_check", project_id=pid, title="Blender Binary & Environment Verification", description="Verify headless Blender availability.", capability="blender")
        t2 = PersistentTask(id="task_generate_scene_script", project_id=pid, title="Procedural Script Generation", description=f"Generate Python script for {mesh_name}.", dependencies=["task_blender_binary_check"], capability="blender")
        t3 = PersistentTask(id="task_ast_security_validation", project_id=pid, title="AST & Security Validation", description="Statically validate syntax and shell command safety.", dependencies=["task_generate_scene_script"], capability="blender")
        t4 = PersistentTask(id="task_headless_render", project_id=pid, title="Headless Blender Render", description="Execute script and render PNG still.", dependencies=["task_ast_security_validation"], capability="blender")
        t5 = PersistentTask(id="task_scene_inspection", project_id=pid, title="Scene Hierarchy Inspection", description="Inspect objects, lights, cameras, and materials.", dependencies=["task_headless_render"], capability="blender")
        t6 = PersistentTask(id="task_vision_verification", project_id=pid, title="Vision Feedback Inspection", description="Verify rendered output against expected visual elements.", dependencies=["task_scene_inspection"], capability="vision")

        for t in [t1, t2, t3, t4, t5, t6]:
            mgr.dag.add_task(t)

        mgr.save_manifest()
        return mgr

    @classmethod
    def create_blender_environment_project(
        cls,
        name: str,
        workspace_path: Path,
        tree_count: int = 20,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None
    ) -> "ProjectManager":
        """Factory template for procedural forest environment project with undulating terrain and lighting DAG."""
        meta = dict(metadata or {})
        meta.update({
            "scene_type": "forest",
            "tree_count": tree_count,
            "domain": "blender"
        })
        mgr = cls.create(
            name=name,
            workspace_path=workspace_path,
            description=description or f"Blender procedural forest environment generation with {tree_count} trees and undulating terrain",
            metadata=meta,
            project_type=ProjectType.BLENDER_ENVIRONMENT
        )
        pid = mgr.project.project_id

        t1 = PersistentTask(id="task_env_addon_check", project_id=pid, title="Easy Tree Addon Detection", description="Check for modular_tree addon or use procedural fallback.", capability="blender")
        t2 = PersistentTask(id="task_env_generate_script", project_id=pid, title="Forest Environment Script Generation", description=f"Generate forest script with {tree_count} trees.", dependencies=["task_env_addon_check"], capability="blender")
        t3 = PersistentTask(id="task_env_ast_validation", project_id=pid, title="AST Security Validation", description="Validate procedural environment script.", dependencies=["task_env_generate_script"], capability="blender")
        t4 = PersistentTask(id="task_env_headless_render", project_id=pid, title="Headless Environment Render", description="Render realistic forest environment still.", dependencies=["task_env_ast_validation"], capability="blender")
        t5 = PersistentTask(id="task_env_scene_inspection", project_id=pid, title="Environment Scene Inspection", description="Validate tree trunks, foliage, lighting, and terrain meshes.", dependencies=["task_env_headless_render"], capability="blender")
        t6 = PersistentTask(id="task_env_vision_verification", project_id=pid, title="Vision Feedback Verification", description="Verify presence of terrain, canopy, and lighting in output render.", dependencies=["task_env_scene_inspection"], capability="vision")

        for t in [t1, t2, t3, t4, t5, t6]:
            mgr.dag.add_task(t)

        mgr.save_manifest()
        return mgr

    @classmethod
    def load(cls, workspace_path: Path) -> Optional["ProjectManager"]:
        """Load an existing project from its .zara manifest directory."""
        workspace_path = Path(workspace_path).resolve()
        if not (workspace_path / ".zara" / "project.json").exists():
            return None
        mgr = cls(workspace_path)
        return mgr

    def _load_all(self) -> None:
        """Load project metadata, tasks DAG, artifact registry, and journal."""
        data = json.loads(self.project_file.read_text(encoding="utf-8"))
        self.project = PersistentProject.from_dict(data)

        # Load active state (current task, pending approval ticket)
        if self.state_file.exists():
            try:
                state_data = json.loads(self.state_file.read_text(encoding="utf-8"))
                self.pending_approval_ticket = state_data.get("pending_approval")
                if "status" in state_data:
                    self.project.status = ProjectStatus(state_data["status"])
                if "current_task_id" in state_data:
                    self.project.current_task_id = state_data["current_task_id"]
                if "budget" in state_data and isinstance(state_data["budget"], dict):
                    self.project.budget = ProjectBudget.from_dict(state_data["budget"])
            except Exception:
                pass

        self.dag = PersistentDAG(self.tasks_file, self.project.project_id)
        self.artifacts = ArtifactRegistry(self.artifacts_file, self.workspace_path)
        self.journal = ProjectJournal(self.journal_file, self.project.project_id)

    def save_manifest(self) -> None:
        """Persist project.json and state.json atomically."""
        if not self.project:
            return

        self.project.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        _atomic_write_json(self.project_file, self.project.to_dict())

        state_data = {
            "version": "1.0",
            "project_id": self.project.project_id,
            "status": self.project.status.value,
            "current_task_id": self.project.current_task_id,
            "pending_approval": self.pending_approval_ticket,
            "budget": self.project.budget.to_dict(),
            "updated_at": self.project.updated_at
        }
        _atomic_write_json(self.state_file, state_data)

    def save_planning_state(
        self,
        goal: Optional[Dict[str, Any]] = None,
        current_plan: Optional[Dict[str, Any]] = None,
        plan_history: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """Persist structured goal and versioned plans to .zara/planning.json."""
        data = {
            "version": "1.0",
            "project_id": self.project.project_id if self.project else None,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "goal": goal,
            "current_plan": current_plan,
            "plan_history": plan_history or [],
        }
        _atomic_write_json(self.planning_file, data)

    def load_planning_state(self) -> Dict[str, Any]:
        """Load planning and goal state from .zara/planning.json."""
        if not self.planning_file.exists():
            return {}
        try:
            return json.loads(self.planning_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def record_decision(
        self,
        question: str,
        options: List[str],
        selected_option: str,
        rationale_summary: str,
        task_id: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Atomically append a structured decision record to .zara/decisions.jsonl."""
        proj_id = self.project.project_id if self.project else "unknown"
        record = {
            "decision_id": f"dec-{uuid.uuid4().hex[:8]}",
            "project_id": proj_id,
            "task_id": task_id,
            "question": question,
            "options": options,
            "selected_option": selected_option,
            "rationale_summary": rationale_summary,
            "evidence": evidence,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        try:
            self.decisions_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.decisions_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception:
            pass
        return record

    def list_decisions(self) -> List[Dict[str, Any]]:
        """Read all recorded decisions from .zara/decisions.jsonl."""
        if not self.decisions_file.exists():
            return []
        records = []
        try:
            with open(self.decisions_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except Exception:
                            continue
        except Exception:
            pass
        return records

    def save_compact_summary(self, summary_data: Dict[str, Any]) -> None:
        """Persist or append a deterministic context summary."""
        summaries = self.list_compact_summaries()
        summaries.append(summary_data)
        _atomic_write_json(self.summaries_file, summaries)

    def list_compact_summaries(self) -> List[Dict[str, Any]]:
        """Read all saved compact summaries."""
        if not self.summaries_file.exists():
            return []
        try:
            data = json.loads(self.summaries_file.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except Exception:
            return []

    # -------------------------------------------------------------
    # World Model State & Snapshot Persistence
    # -------------------------------------------------------------
    def save_world_state(self, state_dict: Dict[str, Any]) -> None:
        """Atomically persist normalized world state to .zara/world_state.json."""
        _atomic_write_json(self.world_state_file, state_dict)

    def load_world_state(self) -> Optional[Dict[str, Any]]:
        """Load persisted world state from .zara/world_state.json if available."""
        if not self.world_state_file.exists():
            return None
        try:
            return json.loads(self.world_state_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    def save_world_snapshot(self, snapshot: Any) -> Path:
        """Atomically persist a WorldSnapshot into .zara/world_snapshots/{snapshot_id}.json."""
        snap_dict = snapshot.to_dict() if hasattr(snapshot, "to_dict") else dict(snapshot)
        snap_id = snap_dict.get("snapshot_id", f"snap_{uuid.uuid4().hex[:8]}")
        snap_file = self.world_snapshots_dir / f"{snap_id}.json"
        _atomic_write_json(snap_file, snap_dict)
        return snap_file

    def list_world_snapshots(self) -> List[str]:
        """List all saved world snapshot IDs."""
        if not self.world_snapshots_dir.exists():
            return []
        return sorted([f.stem for f in self.world_snapshots_dir.glob("*.json")])

    def load_world_snapshot(self, snapshot_id: str) -> Optional[Dict[str, Any]]:
        """Load a specific WorldSnapshot by ID from .zara/world_snapshots/."""
        snap_file = self.world_snapshots_dir / f"{snapshot_id}.json"
        if not snap_file.exists():
            return None
        try:
            return json.loads(snap_file.read_text(encoding="utf-8"))
        except Exception:
            return None

    # -------------------------------------------------------------
    # Task Management & DAG Integration
    # -------------------------------------------------------------
    def create_task(
        self,
        title: str,
        description: str = "",
        dependencies: Optional[List[str]] = None,
        capability: str = "general",
        input_payload: Optional[Dict[str, Any]] = None,
        parent_id: Optional[str] = None
    ) -> PersistentTask:
        """Add a persistent task to the project DAG."""
        if not self.project or not self.dag:
            raise RuntimeError("Project not initialized")

        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task = PersistentTask(
            id=task_id,
            project_id=self.project.project_id,
            parent_id=parent_id,
            title=title,
            description=description,
            status=StepStatus.PENDING,
            dependencies=dependencies or [],
            capability=capability,
            input_payload=input_payload or {}
        )
        self.dag.add_task(task)
        self.journal.append("TASK_CREATED", task_id=task.id, payload={"title": title, "capability": capability})
        return task

    def start_task(self, task_id: str) -> Optional[PersistentTask]:
        """Mark task as RUNNING and set as current active task."""
        task = self.dag.get_task(task_id)
        if not task:
            return None
        task.status = StepStatus.RUNNING
        task.attempts += 1
        task.last_heartbeat = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.project.current_task_id = task_id
        self.project.status = ProjectStatus.ACTIVE
        self.dag.save()
        self.save_manifest()
        self.journal.append("TASK_STARTED", task_id=task.id, payload={"attempt": task.attempts})
        return task

    def complete_task(
        self,
        task_id: str,
        output_result: Optional[Dict[str, Any]] = None,
        verification: Optional[Dict[str, Any]] = None
    ) -> Optional[PersistentTask]:
        """Mark task as PASSED with verification evidence."""
        task = self.dag.get_task(task_id)
        if not task:
            return None
        task.status = StepStatus.PASSED
        task.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if output_result:
            task.output_result = output_result
        if verification:
            task.verification = verification

        # If this was current task, clear it
        if self.project.current_task_id == task_id:
            self.project.current_task_id = None

        # Check if all tasks in DAG are complete
        all_tasks = self.dag.list_tasks()
        if all_tasks and all(t.status == StepStatus.PASSED for t in all_tasks):
            self.project.status = ProjectStatus.COMPLETED
            self.journal.append("PROJECT_COMPLETED", payload={"tasks_completed": len(all_tasks)})

        self.dag.save()
        self.save_manifest()
        self.journal.append("TASK_COMPLETED", task_id=task.id, payload={"verification": verification})
        return task

    def fail_task(self, task_id: str, error: str) -> Optional[PersistentTask]:
        """Mark task as FAILED and update project status to BLOCKED or FAILED."""
        task = self.dag.get_task(task_id)
        if not task:
            return None
        task.status = StepStatus.FAILED
        task.error = error
        self.project.status = ProjectStatus.BLOCKED
        self.dag.save()
        self.save_manifest()
        self.journal.append("TASK_FAILED", task_id=task.id, payload={"error": error})
        return task

    # -------------------------------------------------------------
    # Checkpointing
    # -------------------------------------------------------------
    def create_checkpoint(
        self,
        task_id: str,
        state_snapshot: Dict[str, Any],
        completed_steps: List[Dict[str, Any]],
        pending_steps: List[Dict[str, Any]],
        verification: Optional[Dict[str, Any]] = None
    ) -> DurableCheckpoint:
        """Create a durable point-in-time task checkpoint."""
        ckpt_id = f"ckpt-{uuid.uuid4().hex[:8]}"
        checkpoint = DurableCheckpoint(
            checkpoint_id=ckpt_id,
            project_id=self.project.project_id,
            task_id=task_id,
            state_snapshot=state_snapshot,
            completed_steps=completed_steps,
            pending_steps=pending_steps,
            artifacts=[a.to_dict() for a in self.artifacts.get_by_task(task_id)],
            verification=verification
        )
        ckpt_file = self.checkpoints_dir / f"checkpoint_{ckpt_id}.json"
        _atomic_write_json(ckpt_file, checkpoint.to_dict())

        # Update task checkpoint reference
        task = self.dag.get_task(task_id)
        if task:
            task.checkpoint_id = ckpt_id
            self.dag.save()

        self.journal.append("CHECKPOINT_CREATED", task_id=task_id, payload={"checkpoint_id": ckpt_id})
        return checkpoint

    def load_checkpoint(self, checkpoint_id: str) -> Optional[DurableCheckpoint]:
        """Load a checkpoint by ID."""
        ckpt_file = self.checkpoints_dir / f"checkpoint_{checkpoint_id}.json"
        if not ckpt_file.exists():
            return None
        try:
            data = json.loads(ckpt_file.read_text(encoding="utf-8"))
            return DurableCheckpoint.from_dict(data)
        except Exception:
            return None

    def list_checkpoints(self, task_id: Optional[str] = None) -> List[DurableCheckpoint]:
        """List all available checkpoints."""
        checkpoints = []
        for file in sorted(self.checkpoints_dir.glob("checkpoint_*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                ckpt = DurableCheckpoint.from_dict(data)
                if task_id is None or ckpt.task_id == task_id:
                    checkpoints.append(ckpt)
            except Exception:
                continue
        return sorted(checkpoints, key=lambda c: c.timestamp, reverse=True)

    # -------------------------------------------------------------
    # Crash Recovery & Classification
    # -------------------------------------------------------------
    def classify_recovery(self, task_id: Optional[str] = None) -> Tuple[RecoveryClassification, Dict[str, Any]]:
        """
        Analyze project and task state to classify recovery mode.
        Returns (Classification, DiagnosisDetails).
        """
        tid = task_id or self.project.current_task_id
        if not tid:
            # Check for any RUNNING task
            for t in self.dag.list_tasks():
                if t.status == StepStatus.RUNNING:
                    tid = t.id
                    break

        if not tid:
            return RecoveryClassification.SAFE_RESUME, {"reason": "No active or interrupted tasks found."}

        task = self.dag.get_task(tid)
        if not task:
            return RecoveryClassification.MANUAL_INTERVENTION, {"error": f"Task {tid} not found in DAG."}

        # 1. Check if waiting for human confirmation
        if self.pending_approval_ticket or self.project.status == ProjectStatus.WAITING_APPROVAL:
            return RecoveryClassification.REQUIRES_APPROVAL, {
                "task_id": tid,
                "ticket": self.pending_approval_ticket,
                "reason": "Task was paused awaiting user confirmation."
            }

        # 2. Check artifact integrity
        task_artifacts = self.artifacts.get_by_task(tid) or self.artifacts.list_all()
        for art in task_artifacts:
            is_valid, current_cs, expected_cs = self.artifacts.verify(art.artifact_id)
            if not is_valid:
                return RecoveryClassification.REQUIRES_VERIFICATION, {
                    "task_id": tid,
                    "artifact": art.path,
                    "reason": f"Artifact '{art.path}' checksum mismatch (expected {expected_cs[:8]}, found {current_cs[:8]})."
                }

        # 3. Check for durable checkpoint
        if task.checkpoint_id:
            ckpt = self.load_checkpoint(task.checkpoint_id)
            if ckpt and ckpt.pending_steps:
                return RecoveryClassification.SAFE_RESUME, {
                    "task_id": tid,
                    "checkpoint_id": task.checkpoint_id,
                    "completed_steps_count": len(ckpt.completed_steps),
                    "pending_steps_count": len(ckpt.pending_steps),
                    "reason": f"Safe checkpoint available with {len(ckpt.pending_steps)} remaining steps."
                }

        # 4. Check attempts
        if task.attempts < task.max_attempts:
            return RecoveryClassification.RETRY, {
                "task_id": tid,
                "attempt": task.attempts,
                "max_attempts": task.max_attempts,
                "reason": f"Task interrupted on attempt {task.attempts}, eligible for retry."
            }

        return RecoveryClassification.MANUAL_INTERVENTION, {
            "task_id": tid,
            "attempts": task.attempts,
            "reason": "Exceeded max attempts without checkpoint."
        }

    def recover_project(self) -> Dict[str, Any]:
        """Perform crash recovery analysis and safe resumption prep."""
        self.project.status = ProjectStatus.RECOVERING
        self.journal.append("RECOVERY_STARTED")
        classification, details = self.classify_recovery()

        result = {
            "project_id": self.project.project_id,
            "classification": classification.value,
            "details": details,
            "recovered_task_id": details.get("task_id")
        }

        if classification == RecoveryClassification.SAFE_RESUME:
            self.project.status = ProjectStatus.ACTIVE
            result["action"] = "Resumed from clean checkpoint."
        elif classification == RecoveryClassification.REQUIRES_APPROVAL:
            self.project.status = ProjectStatus.WAITING_APPROVAL
            result["action"] = "Restored pending approval ticket. Waiting for user input."
        elif classification == RecoveryClassification.REQUIRES_VERIFICATION:
            self.project.status = ProjectStatus.BLOCKED
            result["action"] = "Execution halted pending manual verification of modified artifacts."
        elif classification == RecoveryClassification.RETRY:
            self.project.status = ProjectStatus.ACTIVE
            result["action"] = "Task reset to retry."
        else:
            self.project.status = ProjectStatus.BLOCKED
            result["action"] = "Manual intervention required."

        self.save_manifest()
        self.journal.append("RECOVERY_COMPLETED", payload=result)
        return result

    # -------------------------------------------------------------
    # Orphan Work Detection
    # -------------------------------------------------------------
    def detect_orphaned_work(self) -> List[Dict[str, Any]]:
        """Identify abandoned running tasks, temp files, or unindexed files."""
        orphans = []
        for task in self.dag.list_tasks():
            if task.status == StepStatus.RUNNING:
                health = self.watchdog.check_health(task)
                orphans.append({
                    "type": "interrupted_task",
                    "task_id": task.id,
                    "title": task.title,
                    "health": health.value,
                    "last_activity": task.last_heartbeat or task.updated_at
                })

        # Check for lingering .tmp files in .zara
        for tmp in self.zara_dir.glob("*.tmp*"):
            orphans.append({
                "type": "stale_temp_file",
                "path": str(tmp.relative_to(self.workspace_path)),
                "size": tmp.stat().st_size
            })

        return orphans

    def cleanup_orphaned_work(self, safe_only: bool = True) -> int:
        """Safely clean up confirmed orphaned temporary files."""
        cleaned = 0
        for tmp in self.zara_dir.glob("*.tmp*"):
            try:
                tmp.unlink()
                cleaned += 1
            except Exception:
                pass
        return cleaned

    # -------------------------------------------------------------
    # Pause / Resume / Cancel
    # -------------------------------------------------------------
    def pause_project(self, reason: str = "User requested") -> None:
        """Gracefully pause the active project."""
        self.project.status = ProjectStatus.PAUSED
        self.save_manifest()
        self.journal.append("PROJECT_PAUSED", payload={"reason": reason})

    def resume_project(self) -> Dict[str, Any]:
        """Resume a paused project."""
        if self.project.status not in (ProjectStatus.PAUSED, ProjectStatus.BLOCKED, ProjectStatus.RECOVERING):
            return {"status": self.project.status.value, "message": "Project is not paused."}

        # Check recovery status before resuming
        classification, details = self.classify_recovery()
        if classification == RecoveryClassification.REQUIRES_APPROVAL:
            self.project.status = ProjectStatus.WAITING_APPROVAL
            self.save_manifest()
            return {"status": "WAITING_APPROVAL", "details": details}

        self.project.status = ProjectStatus.ACTIVE
        self.save_manifest()
        self.journal.append("PROJECT_RESUMED")
        return {"status": "ACTIVE", "details": details}

    def cancel_project(self, reason: str = "User cancelled") -> None:
        """Cancel project and mark all uncompleted tasks as SKIPPED/CANCELLED."""
        self.project.status = ProjectStatus.CANCELLED
        for task in self.dag.list_tasks():
            if task.status in (StepStatus.PENDING, StepStatus.RUNNING):
                task.status = StepStatus.SKIPPED
                task.error = f"Project cancelled: {reason}"
        self.dag.save()
        self.save_manifest()
        self.journal.append("PROJECT_CANCELLED", payload={"reason": reason})

    # -------------------------------------------------------------
    # Approval Continuity
    # -------------------------------------------------------------
    def request_approval(self, ticket: Dict[str, Any]) -> None:
        """Persist a pending confirmation ticket across process boundaries."""
        self.pending_approval_ticket = ticket
        self.project.status = ProjectStatus.WAITING_APPROVAL
        self.save_manifest()
        self.journal.append("APPROVAL_REQUESTED", payload=ticket)

    def grant_approval(self, ticket_id: Optional[str] = None) -> bool:
        """Approve pending ticket and return project to ACTIVE."""
        if not self.pending_approval_ticket:
            return False
        if ticket_id and self.pending_approval_ticket.get("ticket_id") != ticket_id:
            return False
        self.pending_approval_ticket = None
        self.project.status = ProjectStatus.ACTIVE
        self.save_manifest()
        self.journal.append("APPROVAL_GRANTED", payload={"ticket_id": ticket_id})
        return True

    def deny_approval(self, ticket_id: Optional[str] = None, reason: str = "User rejected") -> bool:
        """Deny pending ticket and mark project BLOCKED."""
        if not self.pending_approval_ticket:
            return False
        if ticket_id and self.pending_approval_ticket.get("ticket_id") != ticket_id:
            return False
        self.pending_approval_ticket = None
        self.project.status = ProjectStatus.BLOCKED
        self.save_manifest()
        self.journal.append("APPROVAL_DENIED", payload={"ticket_id": ticket_id, "reason": reason})
        return True

    def resolve_approval(self, ticket_id: Optional[str] = None, approved: bool = True, reason: str = "User rejected") -> bool:
        """Resolve a pending approval ticket with either grant or deny."""
        if approved:
            return self.grant_approval(ticket_id)
        return self.deny_approval(ticket_id, reason=reason)

    # -------------------------------------------------------------
    # Snapshots & Version Awareness
    # -------------------------------------------------------------
    def create_snapshot(self) -> ProjectSnapshot:
        """Take a lightweight file inventory snapshot of the project workspace."""
        snap_id = f"snap-{uuid.uuid4().hex[:8]}"
        files: Dict[str, Dict[str, Any]] = {}

        # Scan workspace files, ignoring .zara, .git, venv, pycache
        ignore_dirs = {".zara", ".git", "venv", ".venv", "__pycache__"}
        for root, dirs, filenames in os.walk(self.workspace_path):
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            for fn in filenames:
                if fn.endswith((".pyc", ".swp", ".tmp")):
                    continue
                full_p = Path(root) / fn
                rel_p = str(full_p.relative_to(self.workspace_path))
                try:
                    stat = full_p.stat()
                    files[rel_p] = {
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                        "checksum": _compute_sha256(full_p)
                    }
                except Exception:
                    continue

        snapshot = ProjectSnapshot(
            snapshot_id=snap_id,
            project_id=self.project.project_id,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            files=files
        )
        snap_file = self.snapshots_dir / f"snapshot_{snap_id}.json"
        _atomic_write_json(snap_file, snapshot.to_dict())
        return snapshot

    def list_snapshots(self) -> List[ProjectSnapshot]:
        """List all project snapshots."""
        snapshots = []
        for file in sorted(self.snapshots_dir.glob("snapshot_*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                snapshots.append(ProjectSnapshot.from_dict(data))
            except Exception:
                continue
        return sorted(snapshots, key=lambda s: s.timestamp, reverse=True)

    # -------------------------------------------------------------
    # Session Continuity & Project Memory
    # -------------------------------------------------------------
    def update_project_memory(self, key: str, value: Any) -> None:
        """Update project-specific contextual memory without global bleeding."""
        self.project.project_memory[key] = value
        self.save_manifest()

    def get_project_memory(self, key: Optional[str] = None) -> Any:
        if key:
            return self.project.project_memory.get(key)
        return dict(self.project.project_memory)

    # -------------------------------------------------------------
    # Safe Shutdown
    # -------------------------------------------------------------
    def shutdown(self, graceful: bool = True) -> None:
        """Flush checkpoints, journal, and state cleanly to disk."""
        if self.project:
            self.journal.append("SHUTDOWN_REQUESTED", payload={"graceful": graceful})
            if graceful and self.project.status == ProjectStatus.ACTIVE:
                self.project.status = ProjectStatus.PAUSED
            self.save_manifest()
            self.journal.append("SHUTDOWN_COMPLETED")

    # -------------------------------------------------------------
    # Status Reporting
    # -------------------------------------------------------------
    def get_status(self) -> Dict[str, Any]:
        """Get structured operational progress report."""
        if not self.project or not self.dag:
            return {"error": "Project not loaded"}

        tasks = self.dag.list_tasks()
        passed_count = sum(1 for t in tasks if t.status == StepStatus.PASSED)
        failed_count = sum(1 for t in tasks if t.status in (StepStatus.FAILED, StepStatus.BLOCKED))
        running_count = sum(1 for t in tasks if t.status == StepStatus.RUNNING)
        pending_count = sum(1 for t in tasks if t.status == StepStatus.PENDING)

        return {
            "project_id": self.project.project_id,
            "name": self.project.name,
            "description": self.project.description,
            "status": self.project.status.value,
            "workspace_path": str(self.workspace_path),
            "current_task_id": self.project.current_task_id,
            "tasks_total": len(tasks),
            "tasks_passed": passed_count,
            "tasks_running": running_count,
            "tasks_pending": pending_count,
            "tasks_failed": failed_count,
            "artifacts_count": len(self.artifacts.list_all()),
            "checkpoints_count": len(self.list_checkpoints()),
            "budget": self.project.budget.to_dict(),
            "has_pending_approval": self.pending_approval_ticket is not None,
            "created_at": self.project.created_at,
            "updated_at": self.project.updated_at
        }


def discover_projects(search_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan directory tree for projects containing a valid .zara manifest."""
    root = Path(search_dir or PROJECTS_DIR).resolve()
    discovered = []

    if not root.exists():
        return []

    # Check root itself
    if (root / ".zara" / "project.json").exists():
        try:
            data = json.loads((root / ".zara" / "project.json").read_text(encoding="utf-8"))
            discovered.append({"path": str(root), "name": data.get("name"), "id": data.get("project_id"), "status": data.get("status")})
        except Exception:
            pass

    # Check subdirectories
    for item in root.iterdir():
        if item.is_dir() and (item / ".zara" / "project.json").exists():
            try:
                data = json.loads((item / ".zara" / "project.json").read_text(encoding="utf-8"))
                discovered.append({
                    "path": str(item),
                    "name": data.get("name"),
                    "id": data.get("project_id"),
                    "status": data.get("status")
                })
            except Exception:
                continue

    return discovered
