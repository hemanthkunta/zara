"""
ZARA Multi-Agent Subtask Orchestration Module: Task decomposition, role specialization, and state dependency tracking.
Roles: Planner, Coder, Tester, Reviewer.
"""
from pathlib import Path
import json
import uuid
import datetime
from typing import List, Dict, Optional, Any
from enum import Enum
from config.settings import BASE_DIR

TASKS_STORE = BASE_DIR / "queue" / "task_queue.json"

class AgentRole(str, Enum):
    PLANNER = "planner"
    CODER = "coder"
    TESTER = "tester"
    REVIEWER = "reviewer"

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

    def enqueue_task(
        self,
        title: str,
        description: str,
        priority: int = 1,
        auto_decompose: bool = True
    ) -> str:
        """Enqueue main task with optional role-specialized subtask breakdown."""
        data = self._load()
        task_id = f"task-{uuid.uuid4().hex[:8]}"

        subtasks = []
        if auto_decompose:
            subtasks = [
                {
                    "subtask_id": f"{task_id}-plan",
                    "role": AgentRole.PLANNER.value,
                    "title": f"Analyze & Plan: {title}",
                    "status": "pending",
                    "depends_on": []
                },
                {
                    "subtask_id": f"{task_id}-code",
                    "role": AgentRole.CODER.value,
                    "title": f"Implement changes for: {title}",
                    "status": "pending",
                    "depends_on": [f"{task_id}-plan"]
                },
                {
                    "subtask_id": f"{task_id}-test",
                    "role": AgentRole.TESTER.value,
                    "title": f"Execute test suite & verify {title}",
                    "status": "pending",
                    "depends_on": [f"{task_id}-code"]
                },
                {
                    "subtask_id": f"{task_id}-review",
                    "role": AgentRole.REVIEWER.value,
                    "title": f"Review diff & persist lessons for: {title}",
                    "status": "pending",
                    "depends_on": [f"{task_id}-test"]
                }
            ]

        task = {
            "id": task_id,
            "title": title,
            "description": description,
            "priority": priority,
            "status": "pending",  # pending, running, done, blocked, failed
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "subtasks": subtasks
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

    def update_subtask_status(self, task_id: str, subtask_id: str, status: str) -> bool:
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                for sub in t.get("subtasks", []):
                    if sub["subtask_id"] == subtask_id:
                        sub["status"] = status
                        t["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        self._save(data)
                        return True
        return False

    def get_ready_subtasks(self, task_id: str) -> List[Dict[str, Any]]:
        """Return subtasks whose dependencies have successfully completed."""
        data = self._load()
        for t in data["tasks"]:
            if t["id"] == task_id:
                completed_ids = {s["subtask_id"] for s in t.get("subtasks", []) if s["status"] in ("done", "completed")}
                ready = []
                for s in t.get("subtasks", []):
                    if s["status"] == "pending":
                        deps = s.get("depends_on", [])
                        if all(dep in completed_ids for dep in deps):
                            ready.append(s)
                return ready
        return []

    def list_tasks(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        data = self._load()
        if status:
            return [t for t in data["tasks"] if t["status"] == status]
        return data["tasks"]
