"""
ZARA Phase 14: Advanced Memory, Personalization & Long-Term Context.
Provides structured, privacy-aware, project-isolated long-term memory,
hybrid semantic/keyword retrieval, consolidation, contradiction handling, and temporal decay.
"""
from __future__ import annotations

import os
import re
import math
import json
import uuid
import time
import sqlite3
import datetime
from pathlib import Path
from contextlib import contextmanager
from typing import List, Dict, Optional, Any, Tuple, Iterator, Set
from dataclasses import dataclass, field, asdict
from enum import Enum

from config.settings import MEMORY_DIR, MEMORY_FILE
from core.state import Reflection
from core.observability import AuditLogger
from modules.vector_memory import SemanticVectorStore

EPISODES_FILE = MEMORY_DIR / "episodes.jsonl"
PREFERENCES_FILE = MEMORY_DIR / "preferences.json"
VECTORS_DB_PATH = MEMORY_DIR / "vectors.db"


class MemoryType(str, Enum):
    FACT = "FACT"
    PREFERENCE = "PREFERENCE"
    INSTRUCTION = "INSTRUCTION"
    DECISION = "DECISION"
    PROJECT_CONTEXT = "PROJECT_CONTEXT"
    TASK_CONTEXT = "TASK_CONTEXT"
    SKILL = "SKILL"
    EXPERIENCE = "EXPERIENCE"
    ERROR_PATTERN = "ERROR_PATTERN"
    SUCCESS_PATTERN = "SUCCESS_PATTERN"
    USER_FEEDBACK = "USER_FEEDBACK"
    SYSTEM_KNOWLEDGE = "SYSTEM_KNOWLEDGE"


class MemoryScope(str, Enum):
    GLOBAL = "GLOBAL"
    USER = "USER"
    PROJECT = "PROJECT"
    TASK = "TASK"
    SESSION = "SESSION"


class MemorySource(str, Enum):
    USER_STATED = "USER_STATED"
    SYSTEM_OBSERVED = "SYSTEM_OBSERVED"
    TASK_RESULT = "TASK_RESULT"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    WEAK_INFERENCE = "WEAK_INFERENCE"


class PrivacyLevel(str, Enum):
    PUBLIC = "PUBLIC"
    NORMAL = "NORMAL"
    PRIVATE = "PRIVATE"
    SENSITIVE = "SENSITIVE"
    SECRET = "SECRET"


class TemporalStatus(str, Enum):
    CURRENT = "CURRENT"
    RECENT = "RECENT"
    HISTORICAL = "HISTORICAL"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class ConflictStatus(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    RESOLVED = "RESOLVED"
    OVERRIDDEN = "OVERRIDDEN"
    USER_OVERRIDDEN = "OVERRIDDEN"


DEFAULT_SOURCE_CONFIDENCE = {
    MemorySource.USER_STATED: 0.98,
    MemorySource.SYSTEM_OBSERVED: 0.92,
    MemorySource.TASK_RESULT: 0.88,
    MemorySource.MODEL_INFERENCE: 0.65,
    MemorySource.WEAK_INFERENCE: 0.35,
}

SECRET_PATTERNS = [
    re.compile(r"(?i)bearer\s+[a-zA-Z0-9_\-\.]{12,}"),
    re.compile(r"(?i)(api[_-]?key|secret_key|private_key)\s*[:=]\s*['\"]?[a-zA-Z0-9_\-\.]{12,}"),
    re.compile(r"(?i)(password|passwd)\s*[:=]\s*['\"]?[^\s'\"]{6,}"),
    re.compile(r"-----BEGIN (?:RSA|EC|OPENSSH|DSA|PGP)?\s*PRIVATE KEY-----"),
]


@dataclass
class MemoryItem:
    memory_id: str = field(default_factory=lambda: f"mem-{uuid.uuid4().hex[:12]}")
    type: MemoryType = MemoryType.FACT
    content: str = ""
    summary: str = ""
    scope: MemoryScope = MemoryScope.GLOBAL
    confidence: float = 1.0
    importance: float = 0.5
    source: MemorySource = MemorySource.SYSTEM_OBSERVED
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    embedding_reference: Optional[str] = None
    privacy_level: PrivacyLevel = PrivacyLevel.NORMAL
    temporal_status: TemporalStatus = TemporalStatus.CURRENT
    valid_from: Optional[str] = None
    valid_until: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    last_accessed: Optional[str] = None
    access_count: int = 0
    decay_factor: float = 1.0
    provenance: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True

    @property
    def last_accessed_at(self) -> Optional[str]:
        return self.last_accessed

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["type"] = self.type.value if hasattr(self.type, "value") else str(self.type)
        d["scope"] = self.scope.value if hasattr(self.scope, "value") else str(self.scope)
        d["source"] = self.source.value if hasattr(self.source, "value") else str(self.source)
        d["privacy_level"] = self.privacy_level.value if hasattr(self.privacy_level, "value") else str(self.privacy_level)
        d["temporal_status"] = self.temporal_status.value if hasattr(self.temporal_status, "value") else str(self.temporal_status)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MemoryItem:
        d = dict(data)
        if "type" in d and isinstance(d["type"], str):
            try:
                d["type"] = MemoryType(d["type"])
            except ValueError:
                d["type"] = MemoryType.FACT
        if "scope" in d and isinstance(d["scope"], str):
            try:
                d["scope"] = MemoryScope(d["scope"])
            except ValueError:
                d["scope"] = MemoryScope.GLOBAL
        if "source" in d and isinstance(d["source"], str):
            try:
                d["source"] = MemorySource(d["source"])
            except ValueError:
                d["source"] = MemorySource.SYSTEM_OBSERVED
        if "privacy_level" in d and isinstance(d["privacy_level"], str):
            try:
                d["privacy_level"] = PrivacyLevel(d["privacy_level"])
            except ValueError:
                d["privacy_level"] = PrivacyLevel.NORMAL
        if "temporal_status" in d and isinstance(d["temporal_status"], str):
            try:
                d["temporal_status"] = TemporalStatus(d["temporal_status"])
            except ValueError:
                d["temporal_status"] = TemporalStatus.CURRENT

        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class MemoryConflict:
    conflict_id: str = field(default_factory=lambda: f"conf-{uuid.uuid4().hex[:8]}")
    memory_ids: List[str] = field(default_factory=list)
    detected_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    resolution_status: ConflictStatus = ConflictStatus.UNRESOLVED
    resolution_reason: str = ""
    resolved_memory_id: Optional[str] = None

    @property
    def status(self) -> ConflictStatus:
        return self.resolution_status

    @property
    def conflict_type(self) -> str:
        return "CONTRADICTION"

    @property
    def item_a_id(self) -> str:
        return self.memory_ids[0] if self.memory_ids else ""

    @property
    def item_b_id(self) -> str:
        return self.memory_ids[1] if len(self.memory_ids) > 1 else ""

    @property
    def description(self) -> str:
        return self.resolution_reason or "Contradictory preference/rule detected"

    @property
    def resolution_note(self) -> str:
        return self.resolution_reason

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["resolution_status"] = self.resolution_status.value if hasattr(self.resolution_status, "value") else str(self.resolution_status)
        d["status"] = d["resolution_status"]
        d["conflict_type"] = self.conflict_type
        d["item_a_id"] = self.item_a_id
        d["item_b_id"] = self.item_b_id
        d["description"] = self.description
        d["resolution_note"] = self.resolution_note
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MemoryConflict:
        d = dict(data)
        if "resolution_status" in d and isinstance(d["resolution_status"], str):
            try:
                d["resolution_status"] = ConflictStatus(d["resolution_status"])
            except ValueError:
                d["resolution_status"] = ConflictStatus.UNRESOLVED
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return cls(**filtered)


@dataclass
class MemoryStats:
    total_count: int = 0
    count_by_type: Dict[str, int] = field(default_factory=dict)
    count_by_scope: Dict[str, int] = field(default_factory=dict)
    count_by_project: Dict[str, int] = field(default_factory=dict)
    average_confidence: float = 0.0
    average_importance: float = 0.0
    conflict_count: int = 0
    retrieval_count: int = 0

    @property
    def total_memories(self) -> int:
        return self.total_count

    @property
    def active_memories(self) -> int:
        return self.total_count

    @property
    def by_type(self) -> Dict[str, int]:
        return self.count_by_type

    @property
    def by_scope(self) -> Dict[str, int]:
        return self.count_by_scope

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["total_memories"] = self.total_memories
        d["active_memories"] = self.active_memories
        d["by_type"] = self.by_type
        d["by_scope"] = self.by_scope
        return d


def contains_secret(text: str) -> bool:
    """Detect whether text contains credentials, API keys, tokens, or passwords."""
    if not text:
        return False
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


def scrub_text(text: str) -> str:
    """Redact sensitive credentials using the central audit scrubber."""
    if not text:
        return ""
    scrubbed = AuditLogger.scrub_secrets(text)
    for pat in SECRET_PATTERNS:
        scrubbed = pat.sub("[REDACTED_SECRET]", scrubbed)
    return scrubbed


class MemoryStore:
    """Advanced, structured, privacy-aware long-term memory subsystem for ZARA."""

    def __init__(
        self,
        memory_path: Path = MEMORY_FILE,
        db_path: Path = VECTORS_DB_PATH
    ):
        self.memory_path = Path(memory_path).resolve()
        self.memory_dir = self.memory_path.parent
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.vector_store = SemanticVectorStore(self.db_path)
        self._retrieval_counter = 0

        # Weights for hybrid search ranking
        self.weight_vector = 0.6
        self.weight_keyword = 0.4
        self.decay_rate_days = 0.05

        self._ensure_exists()
        self.ensure_schema()

    def _init_tables_with_conn(self, conn: sqlite3.Connection) -> None:
        """Create structured memory tables and indexes on an existing connection if not present."""
        cursor = conn.cursor()
        try:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    memory_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    summary TEXT,
                    scope TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    importance REAL NOT NULL,
                    source TEXT NOT NULL,
                    project_id TEXT,
                    task_id TEXT,
                    session_id TEXT,
                    tags_json TEXT,
                    embedding_reference TEXT,
                    privacy_level TEXT NOT NULL,
                    temporal_status TEXT NOT NULL,
                    valid_from TEXT,
                    valid_until TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed TEXT,
                    access_count INTEGER DEFAULT 0,
                    decay_factor REAL DEFAULT 1.0,
                    provenance_json TEXT,
                    is_active INTEGER DEFAULT 1
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_scope ON memories(scope)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_project ON memories(project_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mem_active ON memories(is_active)")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memory_conflicts (
                    conflict_id TEXT PRIMARY KEY,
                    memory_ids_json TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    resolution_status TEXT NOT NULL,
                    resolution_reason TEXT,
                    resolved_memory_id TEXT
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conflict_res ON memory_conflicts(resolution_status)")
            conn.commit()
        finally:
            cursor.close()

    def ensure_schema(self) -> None:
        """Idempotently ensure all tables and indexes exist in the authoritative database."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        try:
            self._init_tables_with_conn(conn)
        finally:
            conn.close()

    def validate_schema(self) -> Tuple[bool, str]:
        """Verify presence of all required tables and indexes."""
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=5.0)
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = {row[0] for row in cursor.fetchall()}
                required_tables = {"memories", "memory_conflicts"}
                missing = required_tables - tables
                if missing:
                    return False, f"Missing required tables: {', '.join(sorted(missing))}"
                return True, "Schema valid"
            finally:
                conn.close()
        except Exception as e:
            return False, f"Database access error: {e}"

    @contextmanager
    def _connection(self, commit: bool = False) -> Iterator[sqlite3.Connection]:
        """Context manager guaranteeing SQLite connection cleanup, schema readiness, and no ResourceWarnings."""
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        try:
            # Self-healing schema validation: verify memories table exists
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='memories'")
                if not cursor.fetchone():
                    self._init_tables_with_conn(conn)
            finally:
                cursor.close()

            yield conn
            if commit:
                conn.commit()
        except Exception:
            if commit:
                try:
                    conn.rollback()
                except Exception:
                    pass
            raise
        finally:
            conn.close()

    def _ensure_exists(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.memory_path.exists():
            self.memory_path.write_text("# ZARA Self-Learning Memory Log\n\n", encoding="utf-8")
        if not PREFERENCES_FILE.exists():
            default_prefs = {
                "preferred_editor": "vscode",
                "default_language": "python",
                "style_guide": "pep8",
                "test_framework": "unittest",
                "risk_tolerance": "moderate"
            }
            PREFERENCES_FILE.write_text(json.dumps(default_prefs, indent=2), encoding="utf-8")

    def _init_tables(self) -> None:
        """Backward-compatible table initialization."""
        self.ensure_schema()

    # ──────────────────────────────────────────────────────────────────────────
    # Privacy & Secret Filtering
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def contains_secret(text: str) -> bool:
        """Detect whether text contains credentials, API keys, tokens, or passwords."""
        if not text:
            return False
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                return True
        return False

    @staticmethod
    def scrub_text(text: str) -> str:
        """Redact sensitive credentials using the central audit scrubber."""
        if not text:
            return ""
        scrubbed = AuditLogger.scrub_secrets(text)
        for pat in SECRET_PATTERNS:
            scrubbed = pat.sub("[REDACTED_SECRET]", scrubbed)
        return scrubbed

    # ──────────────────────────────────────────────────────────────────────────
    # Core Memory Operations (CRUD)
    # ──────────────────────────────────────────────────────────────────────────
    def store_memory(
        self,
        item: MemoryItem,
        auto_deduplicate: bool = True,
        detect_conflicts: bool = True
    ) -> MemoryItem:
        """Store a structured memory item with secret screening, deduplication, and conflict tracking."""
        # Privacy rejection
        if item.privacy_level == PrivacyLevel.SECRET or self.contains_secret(item.content):
            # Scrub content before evaluating or reject if level is SECRET
            if item.privacy_level == PrivacyLevel.SECRET:
                raise ValueError("Refusing to store memory with SECRET privacy level.")
            item.content = self.scrub_text(item.content)
            if item.summary:
                item.summary = self.scrub_text(item.summary)

        # Ensure confidence matches source if default
        if item.confidence == 1.0 and item.source in DEFAULT_SOURCE_CONFIDENCE:
            item.confidence = DEFAULT_SOURCE_CONFIDENCE[item.source]

        # Bound scores
        item.confidence = max(0.0, min(1.0, float(item.confidence)))
        item.importance = max(0.0, min(1.0, float(item.importance)))

        # Temporal validity check
        if item.valid_until:
            try:
                until_dt = datetime.datetime.fromisoformat(item.valid_until.replace("Z", "+00:00"))
                if datetime.datetime.now(datetime.timezone.utc) > until_dt:
                    item.temporal_status = TemporalStatus.EXPIRED
            except Exception:
                pass

        # Deduplication check
        if auto_deduplicate:
            dup = self._find_near_duplicate(item)
            if dup:
                return self._merge_duplicate(dup, item)

        # Conflict check
        if detect_conflicts:
            self._check_and_record_conflicts(item)

        # Embed into vector store
        embed_id = f"mem_{item.memory_id}"
        item.embedding_reference = embed_id
        self.vector_store.upsert_document(
            doc_id=embed_id,
            content=f"{item.type.value}: {item.content}",
            metadata={
                "memory_id": item.memory_id,
                "type": item.type.value,
                "scope": item.scope.value,
                "project_id": item.project_id
            }
        )

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO memories (
                        memory_id, type, content, summary, scope, confidence, importance,
                        source, project_id, task_id, session_id, tags_json, embedding_reference,
                        privacy_level, temporal_status, valid_from, valid_until, created_at,
                        updated_at, last_accessed, access_count, decay_factor, provenance_json, is_active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        content=excluded.content,
                        summary=excluded.summary,
                        confidence=excluded.confidence,
                        importance=excluded.importance,
                        updated_at=excluded.updated_at,
                        temporal_status=excluded.temporal_status,
                        access_count=excluded.access_count,
                        decay_factor=excluded.decay_factor,
                        is_active=excluded.is_active
                """, (
                    item.memory_id,
                    item.type.value,
                    item.content,
                    item.summary,
                    item.scope.value,
                    item.confidence,
                    item.importance,
                    item.source.value,
                    item.project_id,
                    item.task_id,
                    item.session_id,
                    json.dumps(item.tags),
                    item.embedding_reference,
                    item.privacy_level.value,
                    item.temporal_status.value,
                    item.valid_from,
                    item.valid_until,
                    item.created_at,
                    item.updated_at,
                    item.last_accessed,
                    item.access_count,
                    item.decay_factor,
                    json.dumps(item.provenance),
                    1 if item.is_active else 0
                ))
            finally:
                cursor.close()

        return item

    def get_memory(self, memory_id: str) -> Optional[MemoryItem]:
        """Fetch memory by unique identifier."""
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,))
                row = cursor.fetchone()
                if row:
                    return self._row_to_item(row)
                return None
            finally:
                cursor.close()

    def update_memory(self, item: MemoryItem) -> None:
        """Update existing memory record."""
        item.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.store_memory(item, auto_deduplicate=False, detect_conflicts=False)

    def delete_memory(self, memory_id: str, soft: bool = True) -> bool:
        """Delete or deactivate memory item."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                if soft:
                    cursor.execute("UPDATE memories SET is_active = 0 WHERE memory_id = ?", (memory_id,))
                else:
                    cursor.execute("DELETE FROM memories WHERE memory_id = ?", (memory_id,))
                return cursor.rowcount > 0
            finally:
                cursor.close()

    def list_memories(
        self,
        scope: Optional[MemoryScope] = None,
        project_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        active_only: bool = True,
        limit: int = 100
    ) -> List[MemoryItem]:
        """List memories with structured metadata filtering."""
        query = "SELECT * FROM memories WHERE 1=1"
        params: List[Any] = []

        if active_only:
            query += " AND is_active = 1"
        if scope:
            query += " AND scope = ?"
            params.append(scope.value)
        if project_id is not None:
            query += " AND project_id = ?"
            params.append(project_id)
        if memory_type:
            query += " AND type = ?"
            params.append(memory_type.value)

        query += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)

        items = []
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    items.append(self._row_to_item(row))
            finally:
                cursor.close()
        return items

    def get_memories_by_project(self, project_id: str) -> List[MemoryItem]:
        """Fetch all memories explicitly scoped to a project."""
        return self.list_memories(project_id=project_id)

    # ──────────────────────────────────────────────────────────────────────────
    # Intelligent Retrieval & Hybrid Search
    # ──────────────────────────────────────────────────────────────────────────
    def retrieve(
        self,
        query: str = "",
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        session_id: Optional[str] = None,
        scope: Optional[MemoryScope] = None,
        memory_types: Optional[List[MemoryType]] = None,
        memory_type: Optional[MemoryType] = None,
        tag_filter: Optional[str] = None,
        limit: int = 5,
        min_score: float = 0.05,
        min_confidence: float = 0.0,
        include_expired: bool = False,
        return_scores: bool = False
    ) -> Any:
        """Intelligent hybrid retrieval strictly respecting scope isolation, tag filters, and decay."""
        self._retrieval_counter += 1

        effective_types = memory_types
        if effective_types is None and memory_type is not None:
            effective_types = [memory_type]

        candidates = self._fetch_scoped_candidates(
            project_id=project_id,
            task_id=task_id,
            session_id=session_id,
            scope=scope,
            memory_types=effective_types,
            include_expired=include_expired
        )
        if tag_filter:
            candidates = [
                c for c in candidates
                if any(tag_filter.lower() == t.lower() for t in c.tags)
            ]
        if min_confidence > 0.0:
            candidates = [c for c in candidates if c.confidence >= min_confidence]

        if not candidates:
            return []

        # 1. Semantic dense search
        semantic_map: Dict[str, float] = {}
        if query and query.strip():
            semantic_results = self.vector_store.search_semantic(query, limit=50, min_score=0.01)
            for res in semantic_results:
                meta = res.get("metadata", {})
                mid = meta.get("memory_id")
                if mid:
                    semantic_map[mid] = res.get("similarity_score", 0.0)

        # 2. Lexical keyword scoring
        query_terms = [t.lower() for t in re.findall(r"\b\w{3,}\b", query)] if query else []

        scored: List[Tuple[MemoryItem, float]] = []
        now_dt = datetime.datetime.now(datetime.timezone.utc)

        for item in candidates:
            # Freshness / Decay calculation
            freshness = self._calculate_freshness(item, now_dt)
            if item.temporal_status == TemporalStatus.EXPIRED and not include_expired:
                continue

            if not query or not query.strip():
                # Query-less fallback: score by importance, confidence and freshness
                final_score = item.importance * item.confidence * freshness
                scored.append((item, round(final_score, 4)))
                continue

            # Vector score
            sim_vec = semantic_map.get(item.memory_id, 0.0)

            # Keyword score
            content_lower = item.content.lower()
            tag_lower = " ".join(item.tags).lower()
            term_matches = sum(1 for term in query_terms if term in content_lower or term in tag_lower)
            sim_kw = (term_matches / max(1, len(query_terms))) if query_terms else 0.0

            # Composite ranking
            base_score = (self.weight_vector * sim_vec) + (self.weight_keyword * sim_kw)
            if base_score <= 0.0 and query_terms:
                continue

            # Multipliers
            confidence_factor = math.pow(max(0.1, item.confidence), 0.5)
            importance_factor = math.pow(max(0.1, item.importance), 0.5)

            final_score = base_score * confidence_factor * importance_factor * freshness
            if final_score >= min_score:
                scored.append((item, round(final_score, 4)))

        # Sort descending
        scored.sort(key=lambda x: x[1], reverse=True)
        top_results = scored[:limit]

        # Update last_accessed and access_count for retrieved items
        now_iso = now_dt.isoformat()
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                for item, _ in top_results:
                    cursor.execute(
                        "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE memory_id = ?",
                        (now_iso, item.memory_id)
                    )
            finally:
                cursor.close()

        if return_scores:
            return top_results
        return [item for item, _ in top_results]

    def _fetch_scoped_candidates(
        self,
        project_id: Optional[str],
        task_id: Optional[str],
        session_id: Optional[str],
        scope: Optional[MemoryScope],
        memory_types: Optional[List[MemoryType]],
        include_expired: bool
    ) -> List[MemoryItem]:
        """Fetch candidates conforming strictly to hierarchical scoping rules."""
        query = "SELECT * FROM memories WHERE is_active = 1"
        params: List[Any] = []

        if not include_expired:
            query += " AND temporal_status != 'EXPIRED'"

        if memory_types:
            placeholders = ",".join(["?"] * len(memory_types))
            query += f" AND type IN ({placeholders})"
            params.extend([t.value for t in memory_types])

        candidates: List[MemoryItem] = []
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    item = self._row_to_item(row)
                    if not include_expired and item.temporal_status == TemporalStatus.EXPIRED:
                        continue
                    # Scope isolation enforcement
                    if scope and item.scope != scope:
                        continue

                    # Hierarchy & Project boundary checks
                    if item.scope == MemoryScope.GLOBAL or item.scope == MemoryScope.USER:
                        candidates.append(item)
                    elif item.scope == MemoryScope.PROJECT:
                        if project_id and item.project_id == project_id:
                            candidates.append(item)
                    elif item.scope == MemoryScope.TASK:
                        if project_id and item.project_id == project_id:
                            if task_id is None or item.task_id == task_id:
                                candidates.append(item)
                    elif item.scope == MemoryScope.SESSION:
                        if session_id and item.session_id == session_id:
                            candidates.append(item)
            finally:
                cursor.close()

        return candidates

    def _calculate_freshness(self, item: MemoryItem, now_dt: datetime.datetime) -> float:
        """Calculate temporal freshness decay factor."""
        try:
            created_dt = datetime.datetime.fromisoformat(item.created_at.replace("Z", "+00:00"))
            age_days = (now_dt - created_dt).total_seconds() / 86400.0
        except Exception:
            age_days = 0.0

        # Frequency / Access boost protects against decay
        effective_age = max(0.0, age_days - (item.access_count * 0.5))
        freshness = math.exp(-self.decay_rate_days * effective_age)

        # High importance slows decay
        if item.importance >= 0.8:
            freshness = max(0.6, freshness)
        return max(0.1, min(1.0, freshness))

    # ──────────────────────────────────────────────────────────────────────────
    # Deduplication, Merging & Consolidation
    # ──────────────────────────────────────────────────────────────────────────
    def _find_near_duplicate(self, candidate: MemoryItem, threshold: float = 0.95) -> Optional[MemoryItem]:
        """Find an existing active memory with matching scope/type that is semantically near-identical."""
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM memories WHERE is_active = 1 AND scope = ? AND type = ?",
                    (candidate.scope.value, candidate.type.value)
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()

        cand_tokens = set(SemanticVectorStore._tokenize(candidate.content))
        if not cand_tokens:
            return None
        cand_vec = self.vector_store._compute_vector(candidate.content)

        for row in rows:
            existing = self._row_to_item(row)
            if existing.project_id != candidate.project_id:
                continue
            if existing.content.strip().lower() == candidate.content.strip().lower():
                return existing
            exist_tokens = set(SemanticVectorStore._tokenize(existing.content))
            if cand_tokens != exist_tokens:
                jaccard = len(cand_tokens & exist_tokens) / max(1, len(cand_tokens | exist_tokens))
                if jaccard < 0.85:
                    continue
            exist_vec = self.vector_store._compute_vector(existing.content)
            sim = SemanticVectorStore._cosine_similarity(cand_vec, exist_vec)
            if sim >= threshold:
                return existing

        return None

    def _merge_duplicate(self, existing: MemoryItem, duplicate: MemoryItem) -> MemoryItem:
        """Merge duplicate into existing memory record, increasing confidence and recording provenance."""
        # Provenance tracking
        if duplicate.memory_id not in existing.provenance:
            existing.provenance.append(duplicate.memory_id)
        if duplicate.source.value not in existing.provenance:
            existing.provenance.append(f"source:{duplicate.source.value}")

        # Confidence aggregation: asymptotically approaches 1.0 with repeated confirmation
        existing.confidence = min(0.99, max(existing.confidence, duplicate.confidence) + (1.0 - existing.confidence) * 0.1)
        existing.access_count += 1
        existing.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Update tags
        merged_tags = list(set(existing.tags + duplicate.tags))
        existing.tags = merged_tags

        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE memories SET
                        confidence = ?,
                        access_count = ?,
                        updated_at = ?,
                        tags_json = ?,
                        provenance_json = ?
                    WHERE memory_id = ?
                """, (
                    existing.confidence,
                    existing.access_count,
                    existing.updated_at,
                    json.dumps(existing.tags),
                    json.dumps(existing.provenance),
                    existing.memory_id
                ))
            finally:
                cursor.close()

        return existing

    def consolidate_memories(
        self,
        scope: MemoryScope,
        project_id: Optional[str] = None,
        memory_type: Optional[MemoryType] = None,
        min_cluster_size: int = 2
    ) -> List[MemoryItem]:
        """Synthesize multiple individual observations of the same topic into consolidated knowledge."""
        items = self.list_memories(scope=scope, project_id=project_id, memory_type=memory_type)
        if len(items) < min_cluster_size:
            return []

        consolidated: List[MemoryItem] = []
        # Group by topic / key phrases
        visited: Set[str] = set()

        for i, m1 in enumerate(items):
            if m1.memory_id in visited:
                continue
            group = [m1]
            vec1 = self.vector_store._compute_vector(m1.content)

            for j in range(i + 1, len(items)):
                m2 = items[j]
                if m2.memory_id in visited:
                    continue
                vec2 = self.vector_store._compute_vector(m2.content)
                sim = SemanticVectorStore._cosine_similarity(vec1, vec2)
                if sim >= 0.70:
                    group.append(m2)

            if len(group) >= min_cluster_size:
                for g in group:
                    visited.add(g.memory_id)

                # Formulate consolidated statement
                highest_conf = max(g.confidence for g in group)
                agg_conf = min(0.99, highest_conf + 0.05 * (len(group) - 1))
                combined_content = f"Consolidated ({len(group)} observations): {group[0].content}"
                prov = [g.memory_id for g in group]

                c_item = MemoryItem(
                    type=MemoryType.SYSTEM_KNOWLEDGE,
                    content=combined_content,
                    summary=f"Synthesized from {len(group)} related memories",
                    scope=m1.scope,
                    confidence=agg_conf,
                    importance=max(g.importance for g in group),
                    source=MemorySource.TASK_RESULT,
                    project_id=project_id,
                    tags=list(set(sum([g.tags for g in group], []))),
                    provenance=prov
                )
                self.store_memory(c_item, auto_deduplicate=False, detect_conflicts=False)
                consolidated.append(c_item)

        return consolidated

    # ──────────────────────────────────────────────────────────────────────────
    # Contradiction Detection & Conflicts
    # ──────────────────────────────────────────────────────────────────────────
    def _check_and_record_conflicts(self, candidate: MemoryItem) -> None:
        """Detect and store conflicting statements in the same scope."""
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT * FROM memories WHERE is_active = 1 AND scope = ? AND type = ?",
                    (candidate.scope.value, candidate.type.value)
                )
                rows = cursor.fetchall()
            finally:
                cursor.close()

        cand_lower = candidate.content.lower()
        cand_words = set(re.findall(r"\b\w+\b", cand_lower))
        for row in rows:
            existing = self._row_to_item(row)
            if existing.memory_id == candidate.memory_id:
                continue
            exist_lower = existing.content.lower()
            exist_words = set(re.findall(r"\b\w+\b", exist_lower))

            is_conflict = False
            reason = ""

            # Check negations / polarity opposition
            negations = {"not", "never", "no", "avoid", "don't", "dont", "neither"}
            has_cand_neg = bool(cand_words & negations)
            has_exist_neg = bool(exist_words & negations)

            overlap = cand_words.intersection(exist_words)
            if has_cand_neg != has_exist_neg:
                cand_clean = re.sub(r"\b(not|never|no|avoid|don'?t|always)\b", "", cand_lower).strip()
                exist_clean = re.sub(r"\b(not|never|no|avoid|don'?t|always)\b", "", exist_lower).strip()
                sim = SemanticVectorStore._cosine_similarity(
                    self.vector_store._compute_vector(cand_clean),
                    self.vector_store._compute_vector(exist_clean)
                )
                if sim >= 0.70 or len(overlap) >= 2:
                    is_conflict = True
                    reason = f"Contradiction detected: '{existing.content}' vs '{candidate.content}'"
            elif any(k in cand_lower for k in ("prefer", "theme", "use", "mode", "framework")) and any(k in exist_lower for k in ("prefer", "theme", "use", "mode", "framework")):
                # Check if subject overlaps but options differ
                if len(overlap) >= 2 and cand_words != exist_words:
                    is_conflict = True
                    reason = f"Conflicting preferences: '{existing.content}' vs '{candidate.content}'"

            if is_conflict:
                conflict = MemoryConflict(
                    memory_ids=[existing.memory_id, candidate.memory_id],
                    resolution_status=ConflictStatus.UNRESOLVED,
                    resolution_reason=reason
                )
                # If existing was inference/system and candidate is explicit USER_STATED, user overrides
                if existing.source != MemorySource.USER_STATED and candidate.source == MemorySource.USER_STATED:
                    conflict.resolution_status = ConflictStatus.OVERRIDDEN
                    conflict.resolved_memory_id = candidate.memory_id
                    existing.temporal_status = TemporalStatus.HISTORICAL
                    self.update_memory(existing)

                self._save_conflict(conflict)

    def _save_conflict(self, conflict: MemoryConflict) -> None:
        """Persist conflict record to database."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    INSERT INTO memory_conflicts (
                        conflict_id, memory_ids_json, detected_at, resolution_status,
                        resolution_reason, resolved_memory_id
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conflict_id) DO UPDATE SET
                        resolution_status = excluded.resolution_status,
                        resolution_reason = excluded.resolution_reason,
                        resolved_memory_id = excluded.resolved_memory_id
                """, (
                    conflict.conflict_id,
                    json.dumps(conflict.memory_ids),
                    conflict.detected_at,
                    conflict.resolution_status.value,
                    conflict.resolution_reason,
                    conflict.resolved_memory_id
                ))
            finally:
                cursor.close()

    def list_conflicts(self, unresolved_only: bool = False) -> List[MemoryConflict]:
        """List tracked contradiction records."""
        query = "SELECT * FROM memory_conflicts"
        if unresolved_only:
            query += " WHERE resolution_status = 'UNRESOLVED'"
        query += " ORDER BY detected_at DESC"

        conflicts = []
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query)
                for row in cursor.fetchall():
                    conflicts.append(MemoryConflict(
                        conflict_id=row["conflict_id"],
                        memory_ids=json.loads(row["memory_ids_json"]),
                        detected_at=row["detected_at"],
                        resolution_status=ConflictStatus(row["resolution_status"]),
                        resolution_reason=row["resolution_reason"] or "",
                        resolved_memory_id=row["resolved_memory_id"]
                    ))
            finally:
                cursor.close()
        return conflicts

    def get_conflicts(self, status: Optional[ConflictStatus] = None) -> List[MemoryConflict]:
        """Fetch conflicts optionally filtered by ConflictStatus."""
        query = "SELECT * FROM memory_conflicts"
        params: List[Any] = []
        if status:
            query += " WHERE resolution_status = ?"
            params.append(status.value if hasattr(status, "value") else str(status))
        query += " ORDER BY detected_at DESC"

        conflicts = []
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                for row in cursor.fetchall():
                    conflicts.append(MemoryConflict(
                        conflict_id=row["conflict_id"],
                        memory_ids=json.loads(row["memory_ids_json"]),
                        detected_at=row["detected_at"],
                        resolution_status=ConflictStatus(row["resolution_status"]),
                        resolution_reason=row["resolution_reason"] or "",
                        resolved_memory_id=row["resolved_memory_id"]
                    ))
            finally:
                cursor.close()
        return conflicts

    def resolve_conflict(
        self,
        conflict_id: str,
        resolved_by: Optional[str] = None,
        resolution_status: ConflictStatus = ConflictStatus.USER_OVERRIDDEN,
        resolution_note: str = ""
    ) -> bool:
        """Resolve a recorded conflict with resolution status and note."""
        with self._connection(commit=True) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("""
                    UPDATE memory_conflicts
                    SET resolution_status = ?, resolved_memory_id = ?, resolution_reason = ?
                    WHERE conflict_id = ?
                """, (
                    resolution_status.value if hasattr(resolution_status, "value") else str(resolution_status),
                    resolved_by,
                    resolution_note,
                    conflict_id
                ))
                return cursor.rowcount > 0
            finally:
                cursor.close()

    # ──────────────────────────────────────────────────────────────────────────
    # Statistics & Project Export
    # ──────────────────────────────────────────────────────────────────────────
    def get_stats(self) -> MemoryStats:
        """Compute quantitative statistics and health metrics across all memories."""
        with self._connection(commit=False) as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM memories WHERE is_active = 1")
                total = cursor.fetchone()[0]

                cursor.execute("SELECT type, COUNT(*) FROM memories WHERE is_active = 1 GROUP BY type")
                by_type = {row[0]: row[1] for row in cursor.fetchall()}

                cursor.execute("SELECT scope, COUNT(*) FROM memories WHERE is_active = 1 GROUP BY scope")
                by_scope = {row[0]: row[1] for row in cursor.fetchall()}

                cursor.execute("SELECT project_id, COUNT(*) FROM memories WHERE is_active = 1 AND project_id IS NOT NULL GROUP BY project_id")
                by_project = {row[0]: row[1] for row in cursor.fetchall()}

                cursor.execute("SELECT AVG(confidence), AVG(importance) FROM memories WHERE is_active = 1")
                avg_row = cursor.fetchone()
                avg_conf = round(float(avg_row[0] or 0.0), 4)
                avg_imp = round(float(avg_row[1] or 0.0), 4)

                cursor.execute("SELECT COUNT(*) FROM memory_conflicts WHERE resolution_status = 'UNRESOLVED'")
                conf_count = cursor.fetchone()[0]

                return MemoryStats(
                    total_count=total,
                    count_by_type=by_type,
                    count_by_scope=by_scope,
                    count_by_project=by_project,
                    average_confidence=avg_conf,
                    average_importance=avg_imp,
                    conflict_count=conf_count,
                    retrieval_count=self._retrieval_counter
                )
            finally:
                cursor.close()

    def export_project_memories(self, project_id: str) -> Dict[str, Any]:
        """Export project-scoped memories to clean, secret-free serializable dictionary."""
        items = self.list_memories(project_id=project_id, active_only=True)
        return {
            "project_id": project_id,
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "count": len(items),
            "memories": [item.to_dict() for item in items]
        }

    def import_project_memories(self, data: Dict[str, Any]) -> int:
        """Safely import project memories with strict secret rejection."""
        imported_count = 0
        raw_list = data.get("memories", [])
        for entry in raw_list:
            item = MemoryItem.from_dict(entry)
            if self.contains_secret(item.content) or item.privacy_level == PrivacyLevel.SECRET:
                continue
            self.store_memory(item, auto_deduplicate=True)
            imported_count += 1
        return imported_count

    # ──────────────────────────────────────────────────────────────────────────
    # Helper Row Converter
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> MemoryItem:
        tags = json.loads(row["tags_json"]) if row["tags_json"] else []
        provenance = json.loads(row["provenance_json"]) if row["provenance_json"] else []
        return MemoryItem(
            memory_id=row["memory_id"],
            type=MemoryType(row["type"]),
            content=row["content"],
            summary=row["summary"] or "",
            scope=MemoryScope(row["scope"]),
            confidence=float(row["confidence"]),
            importance=float(row["importance"]),
            source=MemorySource(row["source"]),
            project_id=row["project_id"],
            task_id=row["task_id"],
            session_id=row["session_id"],
            tags=tags,
            embedding_reference=row["embedding_reference"],
            privacy_level=PrivacyLevel(row["privacy_level"]),
            temporal_status=(
                TemporalStatus.EXPIRED
                if row["valid_until"] and datetime.datetime.now(datetime.timezone.utc) > datetime.datetime.fromisoformat(row["valid_until"].replace("Z", "+00:00"))
                else TemporalStatus(row["temporal_status"])
            ),
            valid_from=row["valid_from"],
            valid_until=row["valid_until"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_accessed=row["last_accessed"],
            access_count=int(row["access_count"]),
            decay_factor=float(row["decay_factor"]),
            provenance=provenance,
            metadata=json.loads(row["metadata_json"]) if ("metadata_json" in row.keys() and row["metadata_json"]) else {},
            is_active=bool(row["is_active"])
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Backward Compatibility (Phases 1-13)
    # ──────────────────────────────────────────────────────────────────────────
    def append_reflection(self, reflection: Reflection) -> None:
        """Append a completed task reflection to text log, episodic JSONL, vector store, and structured memory."""
        self._ensure_exists()
        reflection.approach = AuditLogger.scrub_secrets(reflection.approach)
        reflection.result = AuditLogger.scrub_secrets(reflection.result)
        reflection.lesson = AuditLogger.scrub_secrets(reflection.lesson)

        with open(self.memory_path, "a", encoding="utf-8") as f:
            f.write(reflection.to_markdown())

        episode = {
            "timestamp": reflection.timestamp,
            "task": reflection.task,
            "tag": reflection.tag,
            "approach": reflection.approach,
            "result": reflection.result,
            "lesson": reflection.lesson
        }
        with open(EPISODES_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(episode) + "\n")

        # Index in vector store
        doc_content = f"Task: {reflection.task}\nApproach: {reflection.approach}\nResult: {reflection.result}\nLesson: {reflection.lesson}"
        doc_id = f"refl_{uuid.uuid4().hex[:12]}_{reflection.tag}"
        self.vector_store.upsert_document(
            doc_id=doc_id,
            content=doc_content,
            metadata={"tag": reflection.tag, "task": reflection.task, "timestamp": reflection.timestamp}
        )

        # Store structured EXPERIENCE memory
        mem_type = MemoryType.EXPERIENCE
        if "error" in reflection.lesson.lower() or "fail" in reflection.lesson.lower():
            mem_type = MemoryType.ERROR_PATTERN
        elif "pass" in reflection.result.lower() or "success" in reflection.result.lower():
            mem_type = MemoryType.SUCCESS_PATTERN

        self.store_memory(
            MemoryItem(
                type=mem_type,
                content=f"Task '{reflection.task}': {reflection.lesson}",
                summary=reflection.lesson[:120],
                scope=MemoryScope.GLOBAL,
                confidence=0.90,
                importance=0.65,
                source=MemorySource.TASK_RESULT,
                tags=[reflection.tag] if reflection.tag else ["reflection"]
            ),
            auto_deduplicate=False
        )

    def search_semantic(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Dense semantic search pass-through."""
        return self.vector_store.search_semantic(query, limit=limit)

    def search_lessons(self, query: str, tag_filter: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Search text memory log by keyword terms, returning structured headers and lessons."""
        if not self.memory_path.exists():
            return []

        content = self.memory_path.read_text(encoding="utf-8")
        entries = re.split(r"\n---\n", content)
        results = []
        query_terms = [t.lower() for t in query.split() if len(t) > 2]

        for entry in entries:
            entry_clean = entry.strip()
            if not entry_clean:
                continue
            entry_lower = entry_clean.lower()
            if tag_filter and tag_filter.lower() not in entry_lower:
                continue

            match_score = sum(1 for term in query_terms if term in entry_lower)
            if match_score > 0 or not query_terms:
                lines = entry_clean.splitlines()
                header = lines[0] if lines else ""
                approach, result, lesson = "", "", ""
                for line in lines:
                    if line.startswith("- Approach:"):
                        approach = line.replace("- Approach:", "").strip()
                    elif line.startswith("- Result:"):
                        result = line.replace("- Result:", "").strip()
                    elif line.startswith("- Lesson:"):
                        lesson = line.replace("- Lesson:", "").strip()

                results.append({
                    "score": match_score,
                    "header": header,
                    "approach": approach,
                    "result": result,
                    "lesson": lesson,
                    "raw": entry_clean
                })

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:limit]

    def get_preferences(self) -> Dict[str, Any]:
        try:
            return json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def update_preference(self, key: str, value: Any) -> None:
        prefs = self.get_preferences()
        prefs[key] = value
        PREFERENCES_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
        # Also persist structured preference memory item
        self.store_memory(MemoryItem(
            type=MemoryType.PREFERENCE,
            content=f"User preference '{key}' set to '{value}'",
            scope=MemoryScope.USER,
            confidence=0.98,
            importance=0.85,
            source=MemorySource.USER_STATED,
            tags=["preference", key]
        ))

    def get_all_entries(self) -> List[str]:
        if not self.memory_path.exists():
            return []
        content = self.memory_path.read_text(encoding="utf-8")
        return [e.strip() for e in content.split("---") if e.strip()]

    def close(self) -> None:
        """Cleanly close underlying vector store resources."""
        if hasattr(self, "vector_store") and hasattr(self.vector_store, "close"):
            self.vector_store.close()
