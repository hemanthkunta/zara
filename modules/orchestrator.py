"""
ZARA Multi-Task Orchestration Module: Task queue state management and checkpointing.
"""
from pathlib import Path
import json
import uuid
import datetime
from typing import List, Dict, Optional, Any
from config.settings import BASE_DIR

TASKS_STORE = BASE_DIR / "queue" / "task_queue.json"

class TaskOrchestrator:
    def __init__(self, queue_file: Path = TASKS_STORE):
        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_queue_file()

    def _ensure_queue_file(self) -> None:
        if not self.queue_file.exists():
            self._save({"tasks": []})

    def _load(self) -> Dict[str, Any]:
        try:
            return json.loads(self.queue_file.read_text(encoding="utf-8"))
        except Exception:
            return {"tasks": []}

    def _save(self, data: Dict[str, Any]) -> None:
        self.queue_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def enqueue_task(self, title: str, description: str, priority: int = 1) -> str:
        data = self._load()
        task_id = f"task-{uuid.uuid4().hex[:8]}"
        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",  # pending, running, done, blocked
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "subtasks": []
        }
        data["tasks"].append(task)
        self._save(data)
        return task_id

    def update_task_status(self, task_id: str, status: str, notes: Optional[str] = None) -> bool:
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["status"] = status
                t["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                if notes:
                    t["notes"] = notes
                self._save(data)
                return True
        return False

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._load()
        if status:
            return [t for t in data["tasks"] if t["status"] == status]
        return data["tasks"]
