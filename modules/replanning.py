"""ZARA Phase 11 - Adaptive Replanning, Plan Versioning & Failure Taxonomy.

Handles plan deviations, diagnoses root causes, safely creates versioned plan revisions,
and enforces strict replan depth, revision, and loop limits.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config.settings import (
    MAX_ADAPTIVE_RETRIES,
    MAX_PLAN_REVISIONS,
    MAX_REPLAN_DEPTH,
)
from core.state import Diagnosis, StepStatus
from modules.goals import Goal
from modules.planning import HierarchicalPlanner, PlanCost, PlanValidationResult, PlanValidator
from modules.workspace import PersistentTask, ProjectBudget


class PlanningFailureType(str, enum.Enum):
    INVALID_PLAN = "INVALID_PLAN"
    MISSING_INPUT = "MISSING_INPUT"
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    AUTHORIZATION_FAILURE = "AUTHORIZATION_FAILURE"
    SAFETY_BLOCK = "SAFETY_BLOCK"
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    RESOURCE_EXCEEDED = "RESOURCE_EXCEEDED"
    EXECUTION_FAILURE = "EXECUTION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    UNKNOWN = "UNKNOWN"


@dataclass
class PlanVersion:
    plan_id: str
    version: int
    parent_plan_id: Optional[str]
    reason_for_change: str
    tasks: List[PersistentTask]
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    validation: Optional[PlanValidationResult] = None
    cost: Optional[PlanCost] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "version": self.version,
            "parent_plan_id": self.parent_plan_id,
            "reason_for_change": self.reason_for_change,
            "tasks": [t.to_dict() for t in self.tasks],
            "created_at": self.created_at,
            "validation": self.validation.to_dict() if self.validation else None,
            "cost": self.cost.to_dict() if self.cost else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanVersion:
        val_data = data.get("validation")
        cost_data = data.get("cost")
        return cls(
            plan_id=data.get("plan_id", f"plan-{uuid.uuid4().hex[:8]}"),
            version=data.get("version", 1),
            parent_plan_id=data.get("parent_plan_id"),
            reason_for_change=data.get("reason_for_change", "Initial plan"),
            tasks=[PersistentTask.from_dict(t) for t in data.get("tasks", [])],
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            validation=PlanValidationResult(**val_data) if val_data else None,
            cost=PlanCost.from_dict(cost_data) if cost_data else None,
        )


class AdaptiveReplanner:
    """Adapts execution plans dynamically while guarding against infinite planning loops."""

    def __init__(
        self,
        project_id: str,
        max_revisions: int = MAX_PLAN_REVISIONS,
        max_depth: int = MAX_REPLAN_DEPTH,
        max_adaptive_retries: int = MAX_ADAPTIVE_RETRIES,
    ):
        self.project_id = project_id
        self.max_revisions = max_revisions
        self.max_depth = max_depth
        self.max_adaptive_retries = max_adaptive_retries
        self.history: List[PlanVersion] = []
        self._seen_failure_signatures: Dict[str, int] = {}

    def get_current_version(self) -> Optional[PlanVersion]:
        return self.history[-1] if self.history else None

    def initialize_plan(
        self,
        goal: Goal,
        tasks: List[PersistentTask],
        budget: Optional[ProjectBudget] = None,
    ) -> Tuple[PlanVersion, PlanValidationResult]:
        """Validate and register version 1 of the execution plan."""
        validation = PlanValidator.validate(goal=goal, tasks=tasks, budget=budget)
        cost = HierarchicalPlanner.estimate_cost(goal, tasks)
        v1 = PlanVersion(
            plan_id=f"plan-{uuid.uuid4().hex[:8]}",
            version=1,
            parent_plan_id=None,
            reason_for_change="Initial plan creation",
            tasks=tasks,
            validation=validation,
            cost=cost,
        )
        self.history.append(v1)
        return v1, validation

    @staticmethod
    def classify_failure(
        error_msg: str,
        diagnosis: Optional[Diagnosis] = None,
    ) -> PlanningFailureType:
        """Map error and diagnostic signals into unified planning failure taxonomy."""
        msg_lower = (error_msg or "").lower()
        diag_str = str(diagnosis.hypothesis if diagnosis else "").lower()
        combined = f"{msg_lower} {diag_str}"

        if any(w in combined for w in ["scope", "unauthorized", "cyberlabscope", "forbidden target"]):
            return PlanningFailureType.AUTHORIZATION_FAILURE
        if any(w in combined for w in ["destructive", "blocked command", "safety violation", "safety_block"]):
            return PlanningFailureType.SAFETY_BLOCK
        if any(w in combined for w in ["budget exceeded", "resource exceeded", "runtime exceeded", "max tool calls"]):
            return PlanningFailureType.RESOURCE_EXCEEDED
        if any(w in combined for w in ["capability", "tool not found", "no provider", "unsupported capability"]):
            return PlanningFailureType.MISSING_CAPABILITY
        if any(w in combined for w in ["missing input", "file not found", "no such file", "input missing"]):
            return PlanningFailureType.MISSING_INPUT
        if any(w in combined for w in ["dependency failed", "blocked by dependency", "cycle detected"]):
            return PlanningFailureType.DEPENDENCY_FAILURE
        if any(w in combined for w in ["verification failed", "assertionerror", "test failure", "expected artifact missing"]):
            return PlanningFailureType.VERIFICATION_FAILURE
        if any(w in combined for w in ["environment", "os error", "connection refused", "timeout"]):
            return PlanningFailureType.ENVIRONMENT_FAILURE
        if any(w in combined for w in ["syntaxerror", "nameerror", "attributeerror", "exception"]):
            return PlanningFailureType.EXECUTION_FAILURE

        return PlanningFailureType.UNKNOWN

    def replan(
        self,
        goal: Goal,
        failed_task: PersistentTask,
        diagnosis: Optional[Diagnosis] = None,
        budget: Optional[ProjectBudget] = None,
        available_capabilities: Optional[Set[str]] = None,
    ) -> Tuple[Optional[PlanVersion], str]:
        """Produce an adapted, validated plan revision or block execution if limits are exceeded."""
        current_version = self.get_current_version()
        if not current_version:
            return None, "INVALID_PLAN: No current plan exists to revise."

        if failed_task.id not in {t.id for t in current_version.tasks}:
            return None, f"INVALID_TASK: Task '{failed_task.id}' not found in active plan."

        # 1. Revision count & Depth Check
        current_v_num = current_version.version
        if current_v_num >= self.max_revisions:
            return None, f"BLOCKED: Maximum plan revisions limit reached ({current_v_num}/{self.max_revisions}). Requires user decision."

        replan_depth = len([p for p in self.history if p.parent_plan_id is not None])
        if replan_depth >= self.max_depth:
            return None, f"BLOCKED: Maximum replan depth reached ({replan_depth}/{self.max_depth}). Requires user decision."

        # 2. Failure Classification & Safety Gates
        err_msg = failed_task.error or (diagnosis.failure_reason if diagnosis else "")
        failure_type = self.classify_failure(err_msg, diagnosis)

        if failure_type in (PlanningFailureType.AUTHORIZATION_FAILURE, PlanningFailureType.SAFETY_BLOCK):
            return None, f"BLOCKED: {failure_type.value} encountered. Automatic replanning forbidden for authorization/safety violations."

        # 3. Loop & Thrashing Protection
        sig = f"{failed_task.capability}:{failure_type.value}:{err_msg[:60]}"
        self._seen_failure_signatures[sig] = self._seen_failure_signatures.get(sig, 0) + 1
        if self._seen_failure_signatures[sig] > self.max_adaptive_retries:
            return None, f"BLOCKED: Replan loop detected for '{failed_task.title}' ({failure_type.value}). Exceeded {self.max_adaptive_retries} adaptive attempts."

        # 4. Synthesize Adapted Plan
        new_tasks: List[PersistentTask] = []
        repair_step_inserted = False

        for task in current_version.tasks:
            if task.id != failed_task.id:
                # Keep completed or independent tasks
                new_tasks.append(PersistentTask.from_dict(task.to_dict()))
            else:
                # Insert targeted repair / fallback step based on diagnosis or failure type
                if failure_type == PlanningFailureType.MISSING_CAPABILITY:
                    # Alternate capability
                    revised_task = PersistentTask.from_dict(task.to_dict())
                    revised_task.capability = "general"  # Fallback to general capability
                    revised_task.status = StepStatus.PENDING
                    revised_task.error = None
                    new_tasks.append(revised_task)
                    repair_step_inserted = True

                elif failure_type == PlanningFailureType.RESOURCE_EXCEEDED:
                    # Streamline plan by reducing scope or retries
                    revised_task = PersistentTask.from_dict(task.to_dict())
                    revised_task.max_attempts = 1
                    revised_task.status = StepStatus.PENDING
                    revised_task.error = None
                    new_tasks.append(revised_task)
                    repair_step_inserted = True

                else:
                    # Insert explicit repair task before repeating failed task
                    repair_task_id = f"{self.project_id}-repair-{uuid.uuid4().hex[:4]}"
                    repair_title = f"Repair & remediate: {task.title}"
                    repair_desc = diagnosis.recommended_action if diagnosis and diagnosis.recommended_action else f"Fix {err_msg[:80]}"
                    repair_task = PersistentTask(
                        id=repair_task_id,
                        project_id=self.project_id,
                        parent_id=task.id,
                        title=repair_title,
                        description=repair_desc,
                        capability="debugging" if task.capability == "coding" else task.capability,
                        dependencies=list(task.dependencies),
                        verification={"method": "remediation_check", "expected": "resolved"},
                    )
                    new_tasks.append(repair_task)

                    # Re-queue failed task depending on repair task
                    retry_task = PersistentTask.from_dict(task.to_dict())
                    retry_task.dependencies = [repair_task.id]
                    retry_task.status = StepStatus.PENDING
                    retry_task.attempts = task.attempts + 1
                    retry_task.error = None
                    new_tasks.append(retry_task)
                    repair_step_inserted = True

        if not repair_step_inserted:
            return None, "BLOCKED: Unable to devise a valid adaptation for this failure."

        # 5. Validate New Plan
        validation = PlanValidator.validate(
            goal=goal,
            tasks=new_tasks,
            budget=budget,
            available_capabilities=available_capabilities,
        )

        if not validation.valid:
            return None, f"BLOCKED: Revised plan failed validation: {'; '.join(validation.errors)}"

        cost = HierarchicalPlanner.estimate_cost(goal, new_tasks)
        new_version = PlanVersion(
            plan_id=f"plan-{uuid.uuid4().hex[:8]}",
            version=current_v_num + 1,
            parent_plan_id=current_version.plan_id,
            reason_for_change=f"Adapted for {failure_type.value} in task '{failed_task.title}': {err_msg[:60]}",
            tasks=new_tasks,
            validation=validation,
            cost=cost,
        )
        self.history.append(new_version)
        return new_version, "SUCCESS"
