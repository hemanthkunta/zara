"""
ZARA Safe Backup & Restore Module (Phase 18).
Archives and restores persistent project state, checkpoints, memories, and learning records.
Strictly excludes secrets and protects against path traversal vulnerabilities.
"""
import os
import tarfile
import json
import datetime
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from config.settings import (
    BASE_DIR, BACKUPS_DIR, MEMORY_DIR, CHECKPOINTS_DIR, LEARNING_DIR, CONFIG_DIR
)
from core.persistence import compute_checksum, atomic_write_json
from core.observability import audit_logger


class BackupManager:
    """Safely creates and restores self-contained archives of ZARA state."""

    EXCLUDED_PATTERNS = {
        ".env", ".env.local", ".git", "__pycache__", "workers", "audit.jsonl",
        "screenshots", "voice", "blender_renders"
    }

    def __init__(self, backups_dir: Path = BACKUPS_DIR, base_dir: Path = BASE_DIR):
        self.backups_dir = Path(backups_dir)
        self.base_dir = Path(base_dir).resolve()
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(self, output_path: Optional[Path] = None) -> Path:
        """
        Create a compressed .tar.gz archive of state stores (checkpoints, memory, learning, config templates).
        Excludes secret files and large ephemeral logs.
        """
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = Path(output_path) if output_path else (self.backups_dir / f"zara_backup_{timestamp}.tar.gz")
        dest.parent.mkdir(parents=True, exist_ok=True)

        manifest = {
            "version": "1.0",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "source_dir": str(self.base_dir),
            "files": []
        }

        # Select items to archive strictly relative to self.base_dir
        items_to_archive: List[Path] = []

        for dir_name in ("checkpoints", "memory", "learning", "config", ".zara"):
            candidate_dir = self.base_dir / dir_name
            if candidate_dir.exists() and candidate_dir.is_dir():
                for p in candidate_dir.rglob("*"):
                    if p.is_file() and not self._is_excluded(p):
                        items_to_archive.append(p)

        temp_tar = dest.with_suffix(f".tmp.{timestamp}")
        try:
            with tarfile.open(temp_tar, "w:gz") as tar:
                for p in items_to_archive:
                    rel_path = p.relative_to(self.base_dir)
                    manifest["files"].append({
                        "path": str(rel_path),
                        "size": p.stat().st_size,
                        "sha256": compute_checksum(p)
                    })
                    tar.add(str(p), arcname=str(rel_path))

                # Add manifest into archive
                manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
                import io
                ti = tarfile.TarInfo(name="backup_manifest.json")
                ti.size = len(manifest_bytes)
                ti.mtime = int(datetime.datetime.now().timestamp())
                tar.addfile(ti, io.BytesIO(manifest_bytes))

            temp_tar.replace(dest)
            audit_logger.log_event(
                event_type="backup_created",
                action="create_backup",
                extra={"backup_path": str(dest), "file_count": len(manifest["files"])}
            )
            return dest
        except Exception as e:
            if temp_tar.exists():
                temp_tar.unlink()
            raise IOError(f"Failed to create backup archive: {e}") from e

    def restore_backup(
        self,
        backup_path: Path,
        target_dir: Optional[Path] = None,
        create_pre_restore_checkpoint: bool = True
    ) -> Dict[str, Any]:
        """
        Safely restore state from a .tar.gz archive.
        Validates against path traversal and creates a pre-restore backup checkpoint.
        """
        src = Path(backup_path).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Backup archive '{src}' does not exist.")

        dest_dir = Path(target_dir or self.base_dir).resolve()

        # Step 1: Pre-restore safety backup
        pre_restore_backup = None
        if create_pre_restore_checkpoint:
            pre_restore_backup = self.create_backup(
                output_path=self.backups_dir / f"pre_restore_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
            )

        # Step 2: Validate archive against directory traversal
        extracted_files: List[str] = []
        with tarfile.open(src, "r:gz") as tar:
            for member in tar.getmembers():
                # Security: Strictly prevent path traversal (../ or absolute path)
                if member.name.startswith("/") or ".." in member.name:
                    raise ValueError(f"Security violation: archive contains illegal path traversal member '{member.name}'")

            # Step 3: Extract files safely
            for member in tar.getmembers():
                if member.name == "backup_manifest.json":
                    continue
                target_file = dest_dir / member.name
                target_file.parent.mkdir(parents=True, exist_ok=True)
                tar.extract(member, path=dest_dir)
                extracted_files.append(member.name)

        audit_logger.log_event(
            event_type="backup_restored",
            action="restore_backup",
            extra={"backup_source": str(src), "files_restored": len(extracted_files)}
        )

        return {
            "success": True,
            "backup_source": str(src),
            "files_restored": len(extracted_files),
            "pre_restore_backup": str(pre_restore_backup) if pre_restore_backup else None,
            "extracted": extracted_files
        }

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backup archives with creation times and sizes."""
        results = []
        for f in sorted(self.backups_dir.glob("*.tar.gz"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                results.append({
                    "file": str(f),
                    "filename": f.name,
                    "size_bytes": f.stat().st_size,
                    "modified": datetime.datetime.fromtimestamp(f.stat().st_mtime, tz=datetime.timezone.utc).isoformat()
                })
            except Exception:
                pass
        return results

    def _is_excluded(self, path: Path) -> bool:
        """Check whether a path should be omitted from backups."""
        name = path.name.lower()
        parts = {p.lower() for p in path.parts}
        if any(exc in parts for exc in self.EXCLUDED_PATTERNS):
            return True
        if name.startswith(".env") or name.endswith(".tmp") or ".tmp." in name:
            return True
        if name.endswith(".pyc") or name.endswith(".swp"):
            return True
        return False
