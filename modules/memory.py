"""
ZARA Hierarchical Memory Module: Multi-tier memory store (short-term, episodic, persistent lessons, preferences).
"""
import json
import re
import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from config.settings import MEMORY_DIR, MEMORY_FILE
from core.state import Reflection
from core.observability import AuditLogger

EPISODES_FILE = MEMORY_DIR / "episodes.jsonl"
PREFERENCES_FILE = MEMORY_DIR / "preferences.json"

class MemoryStore:
    def __init__(self, memory_path: Path = MEMORY_FILE):
        self.memory_path = Path(memory_path)
        self.memory_dir = self.memory_path.parent
        self._ensure_exists()

    def _ensure_exists(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        if not self.memory_path.exists():
            self.memory_path.write_text(
                "# ZARA Self-Learning Memory Log\n\n",
                encoding="utf-8"
            )
        if not PREFERENCES_FILE.exists():
            default_prefs = {
                "preferred_editor": "vscode",
                "default_language": "python",
                "style_guide": "pep8",
                "test_framework": "unittest",
                "risk_tolerance": "moderate"
            }
            PREFERENCES_FILE.write_text(json.dumps(default_prefs, indent=2), encoding="utf-8")

    def append_reflection(self, reflection: Reflection) -> None:
        """Append a completed task reflection to the persistent log with secrets scrubbed."""
        self._ensure_exists()
        # Scrub secrets
        reflection.approach = AuditLogger.scrub_secrets(reflection.approach)
        reflection.result = AuditLogger.scrub_secrets(reflection.result)
        reflection.lesson = AuditLogger.scrub_secrets(reflection.lesson)

        with open(self.memory_path, "a", encoding="utf-8") as f:
            f.write(reflection.to_markdown())

        # Also store in structured episodic JSONL
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

    def search_lessons(self, query: str, tag_filter: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Search memory log for relevant past lessons by keywords and optional tag."""
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
                approach = ""
                result = ""
                lesson = ""
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
        """Read user preferences from memory."""
        try:
            return json.loads(PREFERENCES_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def update_preference(self, key: str, value: Any) -> None:
        """Update a specific preference."""
        prefs = self.get_preferences()
        prefs[key] = value
        PREFERENCES_FILE.write_text(json.dumps(prefs, indent=2), encoding="utf-8")

    def get_all_entries(self) -> List[str]:
        if not self.memory_path.exists():
            return []
        content = self.memory_path.read_text(encoding="utf-8")
        return [e.strip() for e in content.split("---") if e.strip()]
