"""
ZARA Task Checkpointing and Crash Recovery Module.
Guarantees resilience: saves state after every verified step and enables safe task resumption.
"""
import json
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List
from config.settings import CHECKPOINTS_DIR
from core.state import TaskContext, PlanStep, StepStatus, ActionType

class RecoveryManager:
    def __init__(self, checkpoints_dir: Path = CHECKPOINTS_DIR):
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, context: TaskContext, run_id: Optional[str] = None) -> Path:
        """Save active task context state to disk as a JSON checkpoint."""
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_task_name = "".join(c for c in context.task[:30] if c.isalnum() or c in ("-", "_")).lower() or "task"
        filename = f"checkpoint_{safe_task_name}.json"
        path = self.checkpoints_dir / filename

        steps_data = [
            {
                "id": s.id,
                "title": s.title,
                "action_type": s.action_type.value,
                "description": s.description,
                "target": s.target,
                "payload": s.payload,
                "success_condition": s.success_condition,
                "status": s.status.value,
                "attempts": s.attempts,
                "actual_output": s.actual_output,
                "error_message": s.error_message
            }
            for s in context.steps
        ]

        data = {
            "task": context.task,
            "tag": context.tag,
            "working_dir": context.working_dir,
            "current_step_index": context.current_step_index,
            "is_completed": context.is_completed,
            "requires_human_input": context.requires_human_input,
            "blocker_reason": context.blocker_reason,
            "steps": steps_data,
            "checkpoint_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    def load_checkpoint(self, checkpoint_path: Path) -> Optional[TaskContext]:
        """Load and reconstruct TaskContext from a checkpoint file."""
        if not checkpoint_path.exists():
            return None

        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            steps = []
            for s in data.get("steps", []):
                step = PlanStep(
                    id=s["id"],
                    title=s["title"],
                    action_type=ActionType(s["action_type"]),
                    description=s["description"],
                    target=s["target"],
                    payload=s["payload"],
                    success_condition=s["success_condition"],
                    status=StepStatus(s["status"]),
                    attempts=s["attempts"],
                    actual_output=s.get("actual_output"),
                    error_message=s.get("error_message")
                )
                steps.append(step)

            context = TaskContext(
                task=data["task"],
                tag=data["tag"],
                working_dir=data["working_dir"],
                steps=steps,
                current_step_index=data.get("current_step_index", 0),
                is_completed=data.get("is_completed", False),
                requires_human_input=data.get("requires_human_input", False),
                blocker_reason=data.get("blocker_reason")
            )
            return context
        except Exception:
            return None

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints for incomplete or recoverable tasks."""
        results = []
        for file in sorted(self.checkpoints_dir.glob("checkpoint_*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                results.append({
                    "file": str(file),
                    "task": data.get("task"),
                    "completed": data.get("is_completed"),
                    "current_step": data.get("current_step_index"),
                    "total_steps": len(data.get("steps", [])),
                    "checkpoint_time": data.get("checkpoint_time")
                })
            except Exception:
                pass
        return results
