"""
ZARA Phase 15 - Resource Locking Subsystem.
Provides granular, thread-safe resource locks across filesystem paths, terminal,
GUI devices, cyber targets, and workspace projects to prevent race conditions
and file corruption during parallel worker execution.
"""

from __future__ import annotations

import os
import time
import uuid
import threading
import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set, Any
from enum import Enum
from dataclasses import dataclass, field, asdict

from config.settings import WORKER_LOCK_TIMEOUT_SECONDS


class ResourceType(str, Enum):
    FILESYSTEM = "filesystem"
    TERMINAL = "terminal"
    SCREEN = "screen"
    KEYBOARD = "keyboard"
    MOUSE = "mouse"
    BROWSER = "browser"
    BLENDER = "blender"
    CYBER_TARGET = "cyber_target"
    PROJECT = "project"
    MEMORY = "memory"


class AccessMode(str, Enum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"
    READ_ONLY = "read_only"


@dataclass
class ResourceLock:
    lock_id: str
    resource_type: ResourceType
    resource_target: str
    worker_id: str
    mode: AccessMode
    acquired_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    expires_at: float = 0.0  # Unix timestamp
    project_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: Optional[float] = None) -> bool:
        current = now if now is not None else time.time()
        return current > self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lock_id": self.lock_id,
            "resource_type": self.resource_type.value if isinstance(self.resource_type, ResourceType) else str(self.resource_type),
            "resource_target": self.resource_target,
            "worker_id": self.worker_id,
            "mode": self.mode.value if isinstance(self.mode, AccessMode) else str(self.mode),
            "acquired_at": self.acquired_at,
            "expires_at": self.expires_at,
            "project_id": self.project_id,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ResourceLock:
        rtype = data.get("resource_type", ResourceType.FILESYSTEM.value)
        mode = data.get("mode", AccessMode.EXCLUSIVE.value)
        return cls(
            lock_id=data["lock_id"],
            resource_type=ResourceType(rtype) if isinstance(rtype, str) else rtype,
            resource_target=data["resource_target"],
            worker_id=data["worker_id"],
            mode=AccessMode(mode) if isinstance(mode, str) else mode,
            acquired_at=data.get("acquired_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            expires_at=data.get("expires_at", 0.0),
            project_id=data.get("project_id"),
            metadata=data.get("metadata", {}),
        )


class ResourceManager:
    """Thread-safe manager for fine-grained resource and file locking across workers."""

    def __init__(self, default_timeout: float = WORKER_LOCK_TIMEOUT_SECONDS):
        self.default_timeout = default_timeout
        self._locks: Dict[str, List[ResourceLock]] = {}  # key: (resource_type, normalized_target) -> list of active locks
        self._lock = threading.RLock()

    @staticmethod
    def normalize_target(resource_type: ResourceType, target: str) -> str:
        """Normalize resource target (e.g. resolve absolute path for filesystem)."""
        target_str = str(target).strip()
        if resource_type == ResourceType.FILESYSTEM:
            try:
                return str(Path(target_str).resolve())
            except Exception:
                return os.path.abspath(target_str)
        elif resource_type in (ResourceType.SCREEN, ResourceType.KEYBOARD, ResourceType.MOUSE):
            return "gui:primary"
        elif resource_type == ResourceType.CYBER_TARGET:
            return target_str.lower()
        elif resource_type == ResourceType.PROJECT:
            return target_str
        return target_str.lower()

    def _get_key(self, resource_type: ResourceType, target: str) -> str:
        if resource_type in (ResourceType.SCREEN, ResourceType.KEYBOARD, ResourceType.MOUSE):
            return f"gui:{self.normalize_target(resource_type, target)}"
        return f"{resource_type.value}:{self.normalize_target(resource_type, target)}"

    def cleanup_expired_locks(self, now: Optional[float] = None) -> int:
        """Purge all expired locks (orphan recovery). Returns count removed."""
        current = now if now is not None else time.time()
        removed_count = 0
        with self._lock:
            for key in list(self._locks.keys()):
                valid_locks = []
                for lock in self._locks[key]:
                    if lock.is_expired(current):
                        removed_count += 1
                    else:
                        valid_locks.append(lock)
                if valid_locks:
                    self._locks[key] = valid_locks
                else:
                    self._locks.pop(key, None)
        return removed_count

    def check_conflict(
        self,
        resource_type: ResourceType,
        target: str,
        mode: AccessMode,
        requesting_worker_id: Optional[str] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Check whether acquiring this lock would cause a conflict.
        Returns (has_conflict, conflict_reason).
        """
        self.cleanup_expired_locks()
        key = self._get_key(resource_type, target)
        with self._lock:
            active_locks = self._locks.get(key, [])
            if not active_locks:
                return False, None

            # Check locks held by OTHER workers
            other_locks = [l for l in active_locks if l.worker_id != requesting_worker_id]
            if not other_locks:
                # Only current worker holds locks on this target
                return False, None

            # If any other worker holds EXCLUSIVE, conflict
            for l in other_locks:
                if l.mode == AccessMode.EXCLUSIVE:
                    return True, f"Resource '{target}' is exclusively locked by worker '{l.worker_id}'"

            # If requesting EXCLUSIVE and other workers hold SHARED or READ_ONLY, conflict
            if mode == AccessMode.EXCLUSIVE:
                holders = ", ".join(set(l.worker_id for l in other_locks))
                return True, f"Resource '{target}' is currently held in {other_locks[0].mode.value} mode by {holders}"

            return False, None

    def acquire(
        self,
        resource_type: ResourceType,
        target: str,
        worker_id: str,
        mode: AccessMode = AccessMode.EXCLUSIVE,
        timeout: Optional[float] = None,
        project_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        Attempt to acquire a lock on the specified resource.
        Returns (success, error_or_reason).
        """
        if not worker_id:
            return False, "worker_id cannot be empty"
        if not target:
            return False, "resource target cannot be empty"

        # GUI devices must strictly use EXCLUSIVE mode to prevent conflicting input injection
        if resource_type in (ResourceType.KEYBOARD, ResourceType.MOUSE, ResourceType.SCREEN):
            mode = AccessMode.EXCLUSIVE

        norm_target = self.normalize_target(resource_type, target)
        key = self._get_key(resource_type, target)
        ttl = timeout if timeout is not None else self.default_timeout
        expires_at = time.time() + ttl

        with self._lock:
            has_conflict, reason = self.check_conflict(
                resource_type=resource_type,
                target=target,
                mode=mode,
                requesting_worker_id=worker_id
            )
            if has_conflict:
                return False, reason

            # Re-entrant check for same worker
            existing = [l for l in self._locks.get(key, []) if l.worker_id == worker_id]
            if existing:
                # Refresh expiration and update mode if upgrading
                for ex in existing:
                    ex.expires_at = expires_at
                    if mode == AccessMode.EXCLUSIVE:
                        ex.mode = AccessMode.EXCLUSIVE
                return True, None

            # Create new lock
            lock = ResourceLock(
                lock_id=f"lck_{uuid.uuid4().hex[:8]}",
                resource_type=resource_type,
                resource_target=norm_target,
                worker_id=worker_id,
                mode=mode,
                expires_at=expires_at,
                project_id=project_id,
                metadata=metadata or {}
            )
            if key not in self._locks:
                self._locks[key] = []
            self._locks[key].append(lock)
            return True, None

    def release(
        self,
        resource_type: ResourceType,
        target: str,
        worker_id: str
    ) -> bool:
        """Release a lock held by worker_id on the target. Returns True if released."""
        key = self._get_key(resource_type, target)
        with self._lock:
            if key not in self._locks:
                return False
            initial_count = len(self._locks[key])
            self._locks[key] = [l for l in self._locks[key] if l.worker_id != worker_id]
            if not self._locks[key]:
                self._locks.pop(key, None)
            return len(self._locks.get(key, [])) < initial_count

    def release_all(self, worker_id: str) -> int:
        """Release all locks held by a worker. Returns number of locks released."""
        released = 0
        with self._lock:
            for key in list(self._locks.keys()):
                remaining = []
                for l in self._locks[key]:
                    if l.worker_id == worker_id:
                        released += 1
                    else:
                        remaining.append(l)
                if remaining:
                    self._locks[key] = remaining
                else:
                    self._locks.pop(key, None)
        return released

    def get_locks(
        self,
        worker_id: Optional[str] = None,
        resource_type: Optional[ResourceType] = None,
        project_id: Optional[str] = None
    ) -> List[ResourceLock]:
        """List active, unexpired locks matching optional filters."""
        self.cleanup_expired_locks()
        result = []
        with self._lock:
            for locks in self._locks.values():
                for l in locks:
                    if worker_id and l.worker_id != worker_id:
                        continue
                    if resource_type and l.resource_type != resource_type:
                        continue
                    if project_id and l.project_id != project_id:
                        continue
                    result.append(l)
        return result

    def clear(self) -> None:
        """Clear all locks (used in tests and shutdown)."""
        with self._lock:
            self._locks.clear()
