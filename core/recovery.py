"""
ZARA Task Checkpointing and Crash Recovery Module (Phase 18 Hardened).
Guarantees resilience: saves state after every verified step, enables safe task resumption,
and classifies crash recovery paths (SAFE_RESUME, RETRY, REQUIRES_VERIFICATION, REQUIRES_APPROVAL, MANUAL_INTERVENTION).
"""
import json
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from enum import Enum

from config.settings import CHECKPOINTS_DIR
from core.state import TaskContext, PlanStep, StepStatus, ActionType
from core.persistence import atomic_write_json, safe_read_json, quarantine_corrupt_file


class RecoveryClassification(str, Enum):
    SAFE_RESUME = "SAFE_RESUME"
    RETRY = "RETRY"
    REQUIRES_VERIFICATION = "REQUIRES_VERIFICATION"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    MANUAL_INTERVENTION = "MANUAL_INTERVENTION"


class RecoveryManager:
    def __init__(self, checkpoints_dir: Path = CHECKPOINTS_DIR):
        self.checkpoints_dir = Path(checkpoints_dir)
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

    def save_checkpoint(self, context: TaskContext, run_id: Optional[str] = None) -> Path:
        """Save active task context state to disk as an atomic JSON checkpoint."""
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

        # Use atomic persistence to prevent partially-written checkpoints
        atomic_write_json(path, data)
        return path

    def load_checkpoint(self, checkpoint_path: Path) -> Optional[TaskContext]:
        """Load and reconstruct TaskContext from a checkpoint file with corruption detection."""
        path = Path(checkpoint_path)
        if not path.exists():
            return None

        data, is_valid = safe_read_json(path)
        if not is_valid or not isinstance(data, dict):
            # Quarantine corrupted checkpoint
            quarantine_corrupt_file(path)
            return None

        try:
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
            quarantine_corrupt_file(path)
            return None

    def classify_recovery(self, context: TaskContext) -> Tuple[RecoveryClassification, str]:
        """
        Classify crash recovery strategy for a task context according to Phase 18 safety policies.
        Never blindly replays dangerous or unverified actions.
        """
        if context.is_completed:
            return RecoveryClassification.SAFE_RESUME, "Task already completed successfully."

        if context.requires_human_input or context.blocker_reason:
            return (
                RecoveryClassification.MANUAL_INTERVENTION,
                f"Task requires user guidance: {context.blocker_reason or 'Human input required'}"
            )

        if not context.steps:
            return RecoveryClassification.RETRY, "No planned steps recorded; replanning required."

        idx = min(context.current_step_index, len(context.steps) - 1)
        step = context.steps[idx]

        # Sensitive actions (cyber lab, command execution, destructive file ops) require approval or fresh verification
        sensitive_keywords = ("cyber", "nmap", "zap", "metasploit", "exploit", "deploy", "drop", "delete", "rm -rf")
        act_val = step.action_type.value if hasattr(step.action_type, "value") else str(step.action_type)
        is_sensitive = (
            act_val in ("execute", "security_audit", "execute_command", "custom") or
            any(k in (step.title + " " + step.description + " " + (step.target or "")).lower() for k in sensitive_keywords)
        )

        st_val = step.status.value if hasattr(step.status, "value") else str(step.status)

        if st_val in ("passed", "completed"):
            if idx + 1 < len(context.steps):
                next_step = context.steps[idx + 1]
                next_act_val = next_step.action_type.value if hasattr(next_step.action_type, "value") else str(next_step.action_type)
                next_is_sensitive = (
                    next_act_val in ("execute", "security_audit", "execute_command", "custom") or
                    any(k in (next_step.title + " " + next_step.description + " " + (next_step.target or "")).lower() for k in sensitive_keywords)
                )
                if next_is_sensitive:
                    return RecoveryClassification.REQUIRES_APPROVAL, f"Step {next_step.id} ('{next_step.title}') is sensitive and requires fresh confirmation."
                return RecoveryClassification.SAFE_RESUME, f"Safe to resume execution from step {next_step.id} ('{next_step.title}')."
            return RecoveryClassification.SAFE_RESUME, "All steps completed."

        if st_val == "failed":
            if is_sensitive:
                return RecoveryClassification.REQUIRES_APPROVAL, f"Failed sensitive step {step.id} ('{step.title}') requires explicit user authorization to retry."
            if "timeout" in (step.error_message or "").lower() or "network" in (step.error_message or "").lower():
                return RecoveryClassification.RETRY, f"Step {step.id} failed with transient error: {step.error_message}. Safe to retry."
            return RecoveryClassification.REQUIRES_VERIFICATION, f"Step {step.id} failed verification: {step.error_message}. Requires diagnostic verification."

        # In-progress step when crashed
        if is_sensitive:
            return RecoveryClassification.REQUIRES_APPROVAL, f"Interrupted sensitive step {step.id} ('{step.title}') requires confirmation before rerun."
        return RecoveryClassification.REQUIRES_VERIFICATION, f"Step {step.id} was interrupted mid-flight; verify state before continuing."

    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints for incomplete or recoverable tasks."""
        results = []
        for file in sorted(self.checkpoints_dir.glob("checkpoint_*.json")):
            try:
                data, is_valid = safe_read_json(file)
                if not is_valid or not isinstance(data, dict):
                    continue
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

    def get_latest_checkpoint(self) -> Optional[Tuple[Path, TaskContext]]:
        """Return the most recently modified checkpoint file and its reconstructed TaskContext."""
        files = sorted(self.checkpoints_dir.glob("checkpoint_*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            ctx = self.load_checkpoint(f)
            if ctx:
                return f, ctx
        return None
