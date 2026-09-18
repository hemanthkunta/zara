"""
ZARA Persistence Integrity & Atomic File Operations Module (Phase 18).
Guarantees WRITE -> VALIDATE -> ATOMIC COMMIT -> RECOVER persistence invariants.
"""
import os
import json
import uuid
import hashlib
import shutil
import datetime
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.observability import audit_logger

_PERSISTENCE_LOCK = threading.Lock()


def compute_checksum(file_path: Path) -> str:
    """Calculate SHA-256 checksum of a file."""
    path = Path(file_path)
    if not path.exists() or path.is_dir():
        return ""
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def atomic_write_json(file_path: Path, data: Any, indent: int = 2) -> None:
    """
    Safely and atomically write JSON data to disk using a temporary file and fsync.
    WRITE -> VALIDATE -> ATOMIC COMMIT.
    """
    path = Path(file_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")

    serialized = json.dumps(data, indent=indent, default=str)

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())

        # Validate that written content is parseable before committing
        with open(temp_path, "r", encoding="utf-8") as f:
            json.load(f)

        # Atomic commit via replace
        temp_path.replace(path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise IOError(f"Failed to atomically persist JSON to {path}: {e}") from e


def atomic_write_text(file_path: Path, text: str) -> None:
    """Safely and atomically write text to disk using a temporary file and fsync."""
    path = Path(file_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f".tmp.{uuid.uuid4().hex[:8]}")

    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())

        temp_path.replace(path)
    except Exception as e:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception:
                pass
        raise IOError(f"Failed to atomically persist text to {path}: {e}") from e


def safe_read_json(file_path: Path, default: Any = None) -> Tuple[Any, bool]:
    """
    Read JSON from disk with corruption detection.
    Returns (data, is_valid). If file does not exist or is corrupt, returns (default, False).
    """
    path = Path(file_path)
    if not path.exists():
        return default, False

    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return default, False
        data = json.loads(content)
        return data, True
    except Exception:
        return default, False


def safe_append_jsonl(file_path: Path, record: Dict[str, Any]) -> None:
    """Thread-safe append of a structured dictionary to a JSONL file."""
    path = Path(file_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    serialized = json.dumps(record, default=str) + "\n"

    with _PERSISTENCE_LOCK:
        with open(path, "a", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()


def quarantine_corrupt_file(file_path: Path) -> Optional[Path]:
    """Move a corrupt file out of the active path to a .corrupt timestamped backup."""
    path = Path(file_path)
    if not path.exists():
        return None

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    corrupt_path = path.with_suffix(f".corrupt.{timestamp}")
    try:
        shutil.move(str(path), str(corrupt_path))
        audit_logger.log_event(
            event_type="file_quarantined",
            action="quarantine_corrupt_file",
            extra={"original_path": str(path), "quarantine_path": str(corrupt_path)}
        )
        return corrupt_path
    except Exception:
        return None


def cleanup_temp_files(directory: Path, pattern: str = "*.tmp*") -> int:
    """Scan directory and unlink leftover temporary files from interrupted writes."""
    dir_path = Path(directory)
    if not dir_path.exists():
        return 0

    cleaned = 0
    for tmp in dir_path.glob(pattern):
        try:
            if tmp.is_file():
                tmp.unlink()
                cleaned += 1
        except Exception:
            pass
    return cleaned
