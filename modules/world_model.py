"""
ZARA World Model: Multimodal Perception & Unified World Model.
Normalizes independent sensory observations (Voice, Screen/Vision, Active Apps/Windows,
Browser, Terminal, Filesystem, Blender, Cyber Lab, Projects, Tasks, Events, Memory)
into a coherent, timestamped, confidence-weighted, and privacy-respecting world state.

Architectural Rule:
The World Model is strictly an observation/state layer. It is NOT a second planner
or autonomous brain. The Master Orchestrator (ZaraEngine) remains the authoritative
execution coordinator. The World Model never modifies or grants safety/authorization policies.
"""
import os
import re
import json
import time
import uuid
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Set
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import (
    WORLD_TTL_ACTIVE_APP,
    WORLD_TTL_SCREEN,
    WORLD_TTL_TERMINAL,
    WORLD_TTL_FILESYSTEM,
    WORLD_TTL_BROWSER,
    WORLD_TTL_BLENDER,
    WORLD_TTL_CYBER,
    WORLD_TTL_PROJECT,
    WORLD_DIR,
    WORLD_SNAPSHOTS_DIR
)
from core.observability import audit_logger


class Modality(str, Enum):
    VOICE = "voice"
    VISION = "vision"
    SCREEN = "screen"
    BROWSER = "browser"
    TERMINAL = "terminal"
    FILESYSTEM = "filesystem"
    BLENDER = "blender"
    CYBER = "cyber"
    PROJECT = "project"
    TASK = "task"
    EVENT = "event"
    MEMORY = "memory"


class TemporalStatus(str, Enum):
    CURRENT = "current"
    RECENT = "recent"
    STALE = "stale"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    APPLICATION = "application"
    WINDOW = "window"
    FILE = "file"
    DIRECTORY = "directory"
    BROWSER_PAGE = "browser_page"
    TERMINAL_PROCESS = "terminal_process"
    BLENDER_SCENE = "blender_scene"
    CYBER_TARGET = "cyber_target"
    PROJECT = "project"
    TASK = "task"
    ARTIFACT = "artifact"
    DEVICE = "device"


class SourcePriority(int, Enum):
    DIRECT_SYSTEM_API = 100
    RECENT_STRUCTURED_TOOL = 80
    RECENT_SCREEN_VISION = 60
    RECENT_USER_STATEMENT = 40
    MEMORY = 20
    STALE_OBSERVATION = 10
    UNKNOWN = 0


# Prompt injection patterns in external observation content
OBSERVATION_INJECTION_PATTERNS = [
    r"(?i)\bignore\s+(?:all\s+)?previous\s+instructions\b",
    r"(?i)\bsystem\s+override\b",
    r"(?i)\byou\s+are\s+now\s+(?:an?\s+)?(?:evil|unrestricted|bypass)\b",
    r"(?i)\bdeveloper\s+mode\b",
    r"(?i)\bbypass\s+safety\b",
    r"(?i)\bgrant\s+(?:all\s+)?permissions\b",
    r"(?i)\bauthorize\s+(?:all\s+)?targets\b",
    r"(?i)\bdisable\s+(?:all\s+)?confirmations\b",
    r"(?i)\bexecute\s+following\s+shell\s+command\b",
    r"(?i)\breveal\s+(?:all\s+)?(?:secrets|passwords|keys|tokens)\b"
]

# Sensitive credentials patterns to redact for privacy
CREDENTIAL_REDACTION_PATTERNS = [
    (r"(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{12,}", r"\1[REDACTED_TOKEN]"),
    (r"(?i)(api[_-]?key\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{12,}(['\"]?)", r"\1[REDACTED_API_KEY]\2"),
    (r"(?i)(password\s*[:=]\s*['\"]?)[^\s'\"]{6,}(['\"]?)", r"\1[REDACTED_PASSWORD]\2"),
    (r"(?i)(secret\s*[:=]\s*['\"]?)[a-zA-Z0-9_\-\.]{12,}(['\"]?)", r"\1[REDACTED_SECRET]\2"),
]


def sanitize_observation_payload(payload: Any) -> Any:
    """Sanitize observation payload: neutralize prompt injections and redact credentials."""
    if isinstance(payload, str):
        cleaned = payload
        # Redact credentials
        for pat, repl in CREDENTIAL_REDACTION_PATTERNS:
            cleaned = re.sub(pat, repl, cleaned)
        # Neutralize prompt injection directives
        for pat in OBSERVATION_INJECTION_PATTERNS:
            cleaned = re.sub(pat, "[UNTRUSTED DIRECTIVE REMOVED BY ZARA WORLD MODEL]", cleaned)
        return cleaned
    elif isinstance(payload, dict):
        return {k: sanitize_observation_payload(v) for k, v in payload.items()}
    elif isinstance(payload, list):
        return [sanitize_observation_payload(item) for item in payload]
    return payload


@dataclass
class Observation:
    observation_id: str = field(default_factory=lambda: f"obs_{uuid.uuid4().hex[:10]}")
    modality: Modality = Modality.EVENT
    source: str = "system"  # direct_system_api, tool_result, screen_vision, user_statement, memory
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    payload: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 1.0
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    trusted: bool = False  # False for external content, True for verified internal state

    def __post_init__(self):
        if isinstance(self.modality, str):
            try:
                self.modality = Modality(self.modality)
            except Exception:
                self.modality = Modality.EVENT
        self.payload = sanitize_observation_payload(self.payload)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "modality": self.modality.value if hasattr(self.modality, "value") else str(self.modality),
            "source": self.source,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "confidence": self.confidence,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "trusted": self.trusted
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Observation":
        d = dict(data)
        if "modality" in d and isinstance(d["modality"], str):
            try:
                d["modality"] = Modality(d["modality"])
            except Exception:
                d["modality"] = Modality.EVENT
        return cls(**d)


@dataclass
class Entity:
    entity_id: str
    type: EntityType
    name: str
    state: str = "ACTIVE"
    attributes: Dict[str, Any] = field(default_factory=dict)
    first_seen: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_seen: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    confidence: float = 1.0
    provenance: List[str] = field(default_factory=list)

    def __post_init__(self):
        if isinstance(self.type, str):
            try:
                self.type = EntityType(self.type)
            except Exception:
                self.type = EntityType.APPLICATION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "type": self.type.value if hasattr(self.type, "value") else str(self.type),
            "name": self.name,
            "state": self.state,
            "attributes": self.attributes,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "confidence": self.confidence,
            "provenance": list(self.provenance)
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entity":
        d = dict(data)
        if "type" in d and isinstance(d["type"], str):
            try:
                d["type"] = EntityType(d["type"])
            except Exception:
                d["type"] = EntityType.APPLICATION
        return cls(**d)


@dataclass
class Relationship:
    source_id: str
    predicate: str  # CONTAINS, PRODUCES, USES, BELONGS_TO, SUPPORTS, DESCRIBES
    target_id: str
    confidence: float = 1.0
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "predicate": self.predicate,
            "target_id": self.target_id,
            "confidence": self.confidence,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Relationship":
        return cls(**data)


@dataclass
class ObservationConflict:
    entity_id: str
    observations: List[str]
    conflict_type: str
    resolution: str
    confidence: float = 0.5
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "observations": self.observations,
            "conflict_type": self.conflict_type,
            "resolution": self.resolution,
            "confidence": self.confidence,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ObservationConflict":
        return cls(**data)


@dataclass
class WorldState:
    world_id: str = field(default_factory=lambda: f"wrld_{uuid.uuid4().hex[:10]}")
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    active_app: Optional[str] = None
    active_window: Optional[str] = None
    screen_state: Optional[Dict[str, Any]] = None
    voice_state: Optional[Dict[str, Any]] = None
    browser_state: Optional[Dict[str, Any]] = None
    terminal_state: Optional[Dict[str, Any]] = None
    filesystem_state: Optional[Dict[str, Any]] = None
    blender_state: Optional[Dict[str, Any]] = None
    cyber_state: Optional[Dict[str, Any]] = None
    project_state: Optional[Dict[str, Any]] = None
    task_state: Optional[Dict[str, Any]] = None
    recent_events: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "world_id": self.world_id,
            "timestamp": self.timestamp,
            "active_app": self.active_app,
            "active_window": self.active_window,
            "screen_state": self.screen_state,
            "voice_state": self.voice_state,
            "browser_state": self.browser_state,
            "terminal_state": self.terminal_state,
            "filesystem_state": self.filesystem_state,
            "blender_state": self.blender_state,
            "cyber_state": self.cyber_state,
            "project_state": self.project_state,
            "task_state": self.task_state,
            "recent_events": self.recent_events,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldState":
        return cls(**data)


@dataclass
class WorldSnapshot:
    snapshot_id: str = field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:10]}")
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    entities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    active_project: Optional[str] = None
    active_task: Optional[str] = None
    confidence: float = 1.0
    state_summary: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "entities": self.entities,
            "relationships": self.relationships,
            "active_project": self.active_project,
            "active_task": self.active_task,
            "confidence": self.confidence,
            "state_summary": self.state_summary
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorldSnapshot":
        return cls(**data)


class WorldModel:
    """
    Central Multimodal World Model for ZARA.
    Normalizes observations into unified world state, fuses entities, tracks relationships,
    detects conflicts using source priority, and enforces temporal staleness policies.
    """

    def __init__(self, workspace_root: Optional[str] = None, event_bus: Optional[Any] = None):
        self.workspace_root = workspace_root or "."
        self.event_bus = event_bus
        self.current_state: WorldState = WorldState()
        self.previous_state: Optional[WorldState] = None
        self.observations: List[Observation] = []
        self.entities: Dict[str, Entity] = {}
        self.relationships: List[Relationship] = []
        self.conflicts: List[ObservationConflict] = []
        self.modality_timestamps: Dict[Modality, float] = {}
        self.snapshots: Dict[str, WorldSnapshot] = {}

        # Modality freshness TTLs (seconds)
        self.ttl_config: Dict[Modality, int] = {
            Modality.SCREEN: WORLD_TTL_SCREEN,
            Modality.VISION: WORLD_TTL_SCREEN,
            Modality.TERMINAL: WORLD_TTL_TERMINAL,
            Modality.FILESYSTEM: WORLD_TTL_FILESYSTEM,
            Modality.BROWSER: WORLD_TTL_BROWSER,
            Modality.BLENDER: WORLD_TTL_BLENDER,
            Modality.CYBER: WORLD_TTL_CYBER,
            Modality.PROJECT: WORLD_TTL_PROJECT,
            Modality.TASK: WORLD_TTL_PROJECT,
            Modality.VOICE: 30,
            Modality.EVENT: 60,
            Modality.MEMORY: 86400,
        }

    @staticmethod
    def get_source_priority_value(source: str) -> int:
        """Map source string to integer priority."""
        src = source.lower()
        if "api" in src or "macos_control" in src or "system" in src:
            return SourcePriority.DIRECT_SYSTEM_API.value
        if "tool" in src:
            return SourcePriority.RECENT_STRUCTURED_TOOL.value
        if "vision" in src or "screen" in src or "ocr" in src:
            return SourcePriority.RECENT_SCREEN_VISION.value
        if "user" in src or "voice" in src:
            return SourcePriority.RECENT_USER_STATEMENT.value
        if "memory" in src or "reflection" in src:
            return SourcePriority.MEMORY.value
        return SourcePriority.UNKNOWN.value

    def get_staleness(self, modality: Modality) -> TemporalStatus:
        """Evaluate the temporal freshness of a modality."""
        last_time = self.modality_timestamps.get(modality)
        if last_time is None:
            return TemporalStatus.UNKNOWN
        
        age = time.time() - last_time
        ttl = self.ttl_config.get(modality, 30)

        if age <= ttl:
            return TemporalStatus.CURRENT
        elif age <= ttl * 3:
            return TemporalStatus.RECENT
        else:
            return TemporalStatus.STALE

    def observe(self, observation: Observation) -> None:
        """
        Ingest a new multimodal observation:
        Validate, sanitize, buffer, extract entities, update relationships, and update world state.
        """
        # 1. Store observation
        self.observations.append(observation)
        if len(self.observations) > 200:
            self.observations = self.observations[-200:]

        now_ts = time.time()
        self.modality_timestamps[observation.modality] = now_ts

        # 2. Extract / Fuse Entities & Relationships based on Modality
        self._fuse_observation(observation)

        # 3. Update current WorldState
        self._update_state_from_observation(observation)

    def _fuse_observation(self, obs: Observation) -> None:
        """Fuse incoming observation into normalized Entity and Relationship models."""
        mod = obs.modality
        payload = obs.payload or {}
        obs_id = obs.observation_id
        now_iso = obs.timestamp

        if mod == Modality.SCREEN or mod == Modality.VISION:
            app_name = payload.get("application") or payload.get("app")
            win_title = payload.get("window_title") or payload.get("title")
            if app_name and app_name.lower() != "desktop":
                ent_id = f"app:{app_name.lower().strip()}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.APPLICATION,
                    name=app_name,
                    state="ACTIVE" if payload.get("is_active", True) else "BACKGROUND",
                    attributes={"active_window": win_title, "screen_dimensions": payload.get("screen_dimensions")},
                    obs=obs
                )
                if win_title:
                    win_id = f"win:{app_name.lower()}:{win_title.lower().strip()}"
                    self._upsert_entity(
                        entity_id=win_id,
                        entity_type=EntityType.WINDOW,
                        name=win_title,
                        state="FOCUSED" if payload.get("is_focused", True) else "OPEN",
                        attributes={"application": app_name},
                        obs=obs
                    )
                    self.add_relationship(ent_id, "CONTAINS", win_id, confidence=obs.confidence)

        elif mod == Modality.BROWSER:
            url = payload.get("url")
            title = payload.get("title") or payload.get("page_title")
            domain = payload.get("domain")
            if url:
                ent_id = f"browser:{url.strip()}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.BROWSER_PAGE,
                    name=title or url,
                    state="OPEN",
                    attributes={"url": url, "domain": domain, "research_context": payload.get("research_context")},
                    obs=obs
                )
                if obs.task_id:
                    self.add_relationship(f"task:{obs.task_id}", "USES", ent_id, confidence=obs.confidence)
                if payload.get("evidence"):
                    self.add_relationship(ent_id, "SUPPORTS", f"research:{obs.project_id or 'default'}", confidence=obs.confidence)

        elif mod == Modality.TERMINAL:
            pid = payload.get("process_id") or payload.get("pid")
            cmd = payload.get("command")
            status = payload.get("status", "COMPLETED" if payload.get("exit_code") == 0 else "RUNNING")
            ent_id = f"proc:{pid or uuid.uuid4().hex[:6]}"
            self._upsert_entity(
                entity_id=ent_id,
                entity_type=EntityType.TERMINAL_PROCESS,
                name=cmd or "Terminal Command",
                state=status,
                attributes={
                    "command": cmd,
                    "exit_code": payload.get("exit_code"),
                    "stdout_summary": (payload.get("stdout") or "")[:200],
                    "project_id": obs.project_id,
                    "task_id": obs.task_id
                },
                obs=obs
            )
            if obs.task_id:
                self.add_relationship(f"task:{obs.task_id}", "USES", ent_id, confidence=obs.confidence)

        elif mod == Modality.FILESYSTEM:
            path = payload.get("path") or payload.get("file_path")
            if path:
                p = Path(path)
                if not p.is_absolute() and self.workspace_root:
                    p = Path(self.workspace_root) / p
                resolved_p = p.resolve()
                ent_id = f"file:{resolved_p}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.FILE,
                    name=resolved_p.name,
                    state=payload.get("state", "MODIFIED"),
                    attributes={
                        "size": payload.get("size"),
                        "checksum": payload.get("checksum"),
                        "artifact_id": payload.get("artifact_id")
                    },
                    obs=obs
                )
                if obs.project_id:
                    self.add_relationship(ent_id, "BELONGS_TO", f"proj:{obs.project_id}", confidence=obs.confidence)
                if obs.task_id and payload.get("artifact_id"):
                    self.add_relationship(f"task:{obs.task_id}", "PRODUCES", ent_id, confidence=obs.confidence)

        elif mod == Modality.BLENDER:
            scene_name = payload.get("scene_name") or payload.get("scene") or "Scene"
            ent_id = f"blender:{scene_name.strip()}"
            self._upsert_entity(
                entity_id=ent_id,
                entity_type=EntityType.BLENDER_SCENE,
                name=scene_name,
                state="ACTIVE",
                attributes={
                    "objects": payload.get("objects", []),
                    "cameras": payload.get("cameras", []),
                    "lights": payload.get("lights", []),
                    "materials": payload.get("materials", []),
                    "render_status": payload.get("render_status"),
                    "last_render": payload.get("last_render")
                },
                obs=obs
            )
            if obs.project_id:
                self.add_relationship(ent_id, "BELONGS_TO", f"proj:{obs.project_id}", confidence=obs.confidence)

        elif mod == Modality.CYBER:
            target = payload.get("target") or payload.get("host")
            if target:
                ent_id = f"cyber:{target.strip()}"
                # CRITICAL: World Model observation never confers authorization!
                # Authorization MUST strictly come from trusted system state
                is_auth = payload.get("authorized", False) if obs.trusted else False
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.CYBER_TARGET,
                    name=target,
                    state="AUTHORIZED" if is_auth else "UNAUTHORIZED",
                    attributes={
                        "environment_status": payload.get("environment_status"),
                        "last_validation": payload.get("last_validation"),
                        "active_assessment": payload.get("active_assessment"),
                        "findings_count": payload.get("findings_count", 0),
                        "trusted_authorization": is_auth
                    },
                    obs=obs
                )
                if obs.project_id:
                    self.add_relationship(ent_id, "BELONGS_TO", f"proj:{obs.project_id}", confidence=obs.confidence)

        elif mod == Modality.PROJECT:
            proj_id = payload.get("project_id") or obs.project_id
            if proj_id:
                ent_id = f"proj:{proj_id}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.PROJECT,
                    name=payload.get("name") or proj_id,
                    state=payload.get("status", "ACTIVE"),
                    attributes={
                        "type": payload.get("type"),
                        "current_step": payload.get("current_step"),
                        "budget_status": payload.get("budget_status"),
                        "pending_approval": payload.get("pending_approval")
                    },
                    obs=obs
                )

        elif mod == Modality.TASK:
            task_id = payload.get("task_id") or obs.task_id
            if task_id:
                ent_id = f"task:{task_id}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.TASK,
                    name=payload.get("name") or payload.get("title") or task_id,
                    state=payload.get("status", "ACTIVE"),
                    attributes={
                        "step": payload.get("step"),
                        "tool": payload.get("tool"),
                        "project_id": obs.project_id
                    },
                    obs=obs
                )
                if obs.project_id:
                    self.add_relationship(f"proj:{obs.project_id}", "CONTAINS", ent_id, confidence=obs.confidence)

        elif mod == Modality.VOICE:
            transcript = payload.get("transcript") or payload.get("text")
            if transcript:
                ent_id = f"voice:{obs_id}"
                self._upsert_entity(
                    entity_id=ent_id,
                    entity_type=EntityType.DEVICE,
                    name="Voice Request",
                    state="TRANSCRIBED",
                    attributes={
                        "transcript": transcript,
                        "command_type": payload.get("command_type", "COMMAND"),
                        "associated_project": obs.project_id,
                        "associated_task": obs.task_id
                    },
                    obs=obs
                )
                if obs.project_id:
                    self.add_relationship(ent_id, "DESCRIBES", f"proj:{obs.project_id}", confidence=obs.confidence)

    def _upsert_entity(
        self,
        entity_id: str,
        entity_type: EntityType,
        name: str,
        state: str,
        attributes: Dict[str, Any],
        obs: Observation
    ) -> Entity:
        """Update or insert an entity using Source Priority resolution."""
        obs_prio = self.get_source_priority_value(obs.source)

        if entity_id in self.entities:
            existing = self.entities[entity_id]
            # Check for conflicting states
            if existing.state != state and state:
                # Resolve conflict based on source priority
                prev_obs_id = existing.provenance[-1] if existing.provenance else None
                prev_obs = next((o for o in self.observations if o.observation_id == prev_obs_id), None)
                prev_prio = self.get_source_priority_value(prev_obs.source) if prev_obs else 50

                if obs_prio >= prev_prio:
                    # New observation wins
                    conflict = ObservationConflict(
                        entity_id=entity_id,
                        observations=[prev_obs_id or "unknown", obs.observation_id],
                        conflict_type="state_mismatch",
                        resolution=f"Selected '{state}' from higher priority source '{obs.source}' over '{existing.state}'",
                        confidence=obs.confidence
                    )
                    self.conflicts.append(conflict)
                    existing.state = state
                    existing.confidence = obs.confidence
                else:
                    # Existing observation retained
                    conflict = ObservationConflict(
                        entity_id=entity_id,
                        observations=[prev_obs_id or "unknown", obs.observation_id],
                        conflict_type="state_mismatch",
                        resolution=f"Retained '{existing.state}' from higher priority source over '{state}' from '{obs.source}'",
                        confidence=existing.confidence
                    )
                    self.conflicts.append(conflict)
            
            # Merge attributes
            for k, v in attributes.items():
                if v is not None:
                    existing.attributes[k] = v
            
            existing.last_seen = obs.timestamp
            if obs.observation_id not in existing.provenance:
                existing.provenance.append(obs.observation_id)
            return existing
        else:
            # Create new entity
            ent = Entity(
                entity_id=entity_id,
                type=entity_type,
                name=name,
                state=state,
                attributes=attributes,
                first_seen=obs.timestamp,
                last_seen=obs.timestamp,
                confidence=obs.confidence,
                provenance=[obs.observation_id]
            )
            self.entities[entity_id] = ent
            return ent

    def add_relationship(self, source_id: str, predicate: str, target_id: str, confidence: float = 1.0) -> Relationship:
        """Add or update an entity relationship."""
        for rel in self.relationships:
            if rel.source_id == source_id and rel.predicate == predicate and rel.target_id == target_id:
                rel.confidence = confidence
                rel.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
                return rel
        
        rel = Relationship(
            source_id=source_id,
            predicate=predicate,
            target_id=target_id,
            confidence=confidence
        )
        self.relationships.append(rel)
        return rel

    def _update_state_from_observation(self, obs: Observation) -> None:
        """Synchronize current WorldState with observation payload."""
        payload = obs.payload or {}
        mod = obs.modality

        if mod == Modality.SCREEN or mod == Modality.VISION:
            app = payload.get("application") or payload.get("app")
            win = payload.get("window_title") or payload.get("title")
            if app and app.lower() != "desktop":
                self.current_state.active_app = app
            if win:
                self.current_state.active_window = win
            self.current_state.screen_state = {
                "application": app,
                "window_title": win,
                "elements_count": len(payload.get("elements", [])),
                "untrusted_screen_text": payload.get("untrusted_screen_text", ""),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.VOICE:
            self.current_state.voice_state = {
                "transcript": payload.get("transcript") or payload.get("text"),
                "command_type": payload.get("command_type", "COMMAND"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.BROWSER:
            self.current_state.browser_state = {
                "current_url": payload.get("url"),
                "page_title": payload.get("title") or payload.get("page_title"),
                "domain": payload.get("domain"),
                "last_observed": obs.timestamp
            }

        elif mod == Modality.TERMINAL:
            self.current_state.terminal_state = {
                "process_id": payload.get("process_id") or payload.get("pid"),
                "command": payload.get("command"),
                "status": payload.get("status"),
                "exit_code": payload.get("exit_code"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.FILESYSTEM:
            self.current_state.filesystem_state = {
                "last_modified_file": payload.get("path") or payload.get("file_path"),
                "size": payload.get("size"),
                "artifact_id": payload.get("artifact_id"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.BLENDER:
            self.current_state.blender_state = {
                "scene": payload.get("scene_name") or payload.get("scene"),
                "objects_count": len(payload.get("objects", [])),
                "render_status": payload.get("render_status"),
                "last_render": payload.get("last_render"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.CYBER:
            self.current_state.cyber_state = {
                "authorized_target": payload.get("target"),
                "environment_status": payload.get("environment_status"),
                "last_validation": payload.get("last_validation"),
                "findings_count": payload.get("findings_count", 0),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.PROJECT:
            self.current_state.project_state = {
                "active_project": payload.get("project_id") or obs.project_id,
                "status": payload.get("status"),
                "current_step": payload.get("current_step"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.TASK:
            self.current_state.task_state = {
                "active_task": payload.get("task_id") or obs.task_id,
                "status": payload.get("status"),
                "step": payload.get("step"),
                "timestamp": obs.timestamp
            }

        elif mod == Modality.EVENT:
            evt_entry = {
                "type": payload.get("type", "custom"),
                "source": obs.source,
                "timestamp": obs.timestamp
            }
            self.current_state.recent_events.append(evt_entry)
            if len(self.current_state.recent_events) > 20:
                self.current_state.recent_events = self.current_state.recent_events[-20:]

        self.current_state.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()

    def update_world(
        self,
        active_app: Optional[str] = None,
        active_window: Optional[str] = None,
        active_project: Optional[str] = None,
        active_task: Optional[str] = None,
        confidence: Optional[float] = None
    ) -> WorldState:
        """Manually or periodically refresh top-level state attributes and update WorldState."""
        if active_app is not None:
            self.current_state.active_app = active_app
        if active_window is not None:
            self.current_state.active_window = active_window
        if active_project is not None:
            if not self.current_state.project_state:
                self.current_state.project_state = {}
            self.current_state.project_state["active_project"] = active_project
        if active_task is not None:
            if not self.current_state.task_state:
                self.current_state.task_state = {}
            self.current_state.task_state["active_task"] = active_task
        if confidence is not None:
            self.current_state.confidence = confidence

        self.current_state.timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return self.current_state

    def diff(self, previous: Optional[WorldState] = None, current: Optional[WorldState] = None) -> Dict[str, Any]:
        """
        Compute meaningful difference between two world states.
        Returns a structured diff dictionary.
        """
        prev = previous or self.previous_state or WorldState()
        curr = current or self.current_state

        changes = {}

        if prev.active_app != curr.active_app:
            changes["active_app"] = {"previous": prev.active_app, "current": curr.active_app}

        if prev.active_window != curr.active_window:
            changes["active_window"] = {"previous": prev.active_window, "current": curr.active_window}

        prev_proj = (prev.project_state or {}).get("active_project")
        curr_proj = (curr.project_state or {}).get("active_project")
        if prev_proj != curr_proj:
            changes["active_project"] = {"previous": prev_proj, "current": curr_proj}

        prev_task = (prev.task_state or {}).get("active_task")
        curr_task = (curr.task_state or {}).get("active_task")
        if prev_task != curr_task:
            changes["active_task"] = {"previous": prev_task, "current": curr_task}

        prev_term = (prev.terminal_state or {}).get("process_id")
        curr_term = (curr.terminal_state or {}).get("process_id")
        if prev_term != curr_term:
            changes["terminal"] = {"previous": prev.terminal_state, "current": curr.terminal_state}

        prev_fs = (prev.filesystem_state or {}).get("last_modified_file")
        curr_fs = (curr.filesystem_state or {}).get("last_modified_file")
        if prev_fs != curr_fs:
            changes["filesystem"] = {"previous": prev.filesystem_state, "current": curr.filesystem_state}

        prev_blender = (prev.blender_state or {}).get("render_status")
        curr_blender = (curr.blender_state or {}).get("render_status")
        if prev_blender != curr_blender:
            changes["blender"] = {"previous": prev.blender_state, "current": curr.blender_state}

        prev_cyber = (prev.cyber_state or {}).get("findings_count")
        curr_cyber = (curr.cyber_state or {}).get("findings_count")
        if prev_cyber != curr_cyber:
            changes["cyber"] = {"previous": prev.cyber_state, "current": curr.cyber_state}

        return {
            "has_changes": len(changes) > 0,
            "changes_count": len(changes),
            "changes": changes,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    def create_snapshot(
        self,
        active_project: Optional[str] = None,
        active_task: Optional[str] = None
    ) -> WorldSnapshot:
        """Create a durable, lightweight WorldSnapshot answering 'What was happening a few minutes ago?'."""
        proj = active_project or (self.current_state.project_state or {}).get("active_project")
        task = active_task or (self.current_state.task_state or {}).get("active_task")

        snapshot = WorldSnapshot(
            entities={eid: ent.to_dict() for eid, ent in self.entities.items()},
            relationships=[rel.to_dict() for rel in self.relationships],
            active_project=proj,
            active_task=task,
            confidence=self.current_state.confidence,
            state_summary={
                "active_app": self.current_state.active_app,
                "active_window": self.current_state.active_window,
                "screen_summary": bool(self.current_state.screen_state),
                "terminal_summary": (self.current_state.terminal_state or {}).get("status"),
                "filesystem_summary": (self.current_state.filesystem_state or {}).get("last_modified_file"),
                "blender_summary": (self.current_state.blender_state or {}).get("scene"),
                "cyber_summary": (self.current_state.cyber_state or {}).get("authorized_target"),
                "events_count": len(self.current_state.recent_events)
            }
        )
        self.snapshots[snapshot.snapshot_id] = snapshot
        return snapshot

    def refresh(
        self,
        modalities: Optional[List[Modality]] = None,
        probe_fn: Optional[Dict[Modality, Any]] = None
    ) -> WorldState:
        """
        Refresh state for requested or stale modalities before high-impact operations.
        Optionally uses provided probe functions for specific modalities.
        """
        target_modalities = modalities or [
            m for m in [Modality.SCREEN, Modality.FILESYSTEM, Modality.CYBER, Modality.BLENDER]
            if self.get_staleness(m) in (TemporalStatus.STALE, TemporalStatus.UNKNOWN)
        ]

        if probe_fn:
            for mod in target_modalities:
                fn = probe_fn.get(mod)
                if callable(fn):
                    try:
                        res = fn()
                        if isinstance(res, Observation):
                            self.observe(res)
                    except Exception as e:
                        audit_logger.log_event("world_model_refresh_error", {"modality": str(mod), "error": str(e)})

        return self.current_state

    # ──────────────────────────────────────────────────────────────────────────
    # Safe Read-Only Query APIs
    # ──────────────────────────────────────────────────────────────────────────

    def get_active_app(self) -> Optional[str]:
        return self.current_state.active_app

    def get_active_window(self) -> Optional[str]:
        return self.current_state.active_window

    def get_active_project(self) -> Optional[str]:
        return (self.current_state.project_state or {}).get("active_project")

    def get_active_task(self) -> Optional[str]:
        return (self.current_state.task_state or {}).get("active_task")

    def get_recent_changes(self) -> List[Dict[str, Any]]:
        return list(self.current_state.recent_events)

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self.entities.get(entity_id)

    def get_project_entities(self, project_id: str) -> List[Entity]:
        """Return all entities belonging to or linked to a project."""
        target_proj_id = f"proj:{project_id}"
        proj_entities = []
        for ent_id, ent in self.entities.items():
            if ent_id == target_proj_id:
                proj_entities.append(ent)
                continue
            # Check relationships
            for rel in self.relationships:
                if (rel.source_id == ent_id and rel.target_id == target_proj_id) or \
                   (rel.source_id == target_proj_id and rel.target_id == ent_id):
                    proj_entities.append(ent)
                    break
        return proj_entities

    def get_world_snapshot(self, snapshot_id: Optional[str] = None) -> Optional[WorldSnapshot]:
        if snapshot_id:
            return self.snapshots.get(snapshot_id)
        return self.create_snapshot()

    def get_world_diff(self) -> Dict[str, Any]:
        return self.diff(self.previous_state, self.current_state)

    def check_authorization(self, target: str, cyber_scope: Optional[Any] = None) -> bool:
        """
        Safe Authorization Query:
        World Model observations NEVER grant authorization independently.
        Authorizations MUST come directly from an active CyberLabScope or internal security guard.
        """
        if cyber_scope is not None and hasattr(cyber_scope, "is_authorized"):
            return cyber_scope.is_authorized(target)
        # Default fail-closed
        return False
