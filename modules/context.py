"""ZARA Phase 11 - Tiered Context Management & Deterministic Context Compaction.

Provides four-tier context separation (Global, Project, Task, Step), priority-based assembly,
and deterministic compaction of raw execution logs into concise, auditable summaries.
"""

from __future__ import annotations

import datetime
import enum
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from config.settings import MAX_CONTEXT_HISTORY_TOKENS
from core.state import PlanStep, StepStatus, TaskContext
from modules.goals import Goal
from modules.planning import DecisionRecord
from modules.workspace import ArtifactRecord, PersistentTask, ProjectManager


class ContextTier(str, enum.Enum):
    GLOBAL = "GLOBAL"
    PROJECT = "PROJECT"
    TASK = "TASK"
    STEP = "STEP"


@dataclass
class CompactSummary:
    summary_id: str
    project_id: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    important_facts: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    current_state: str = ""
    pending_work: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CompactSummary:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_markdown(self) -> str:
        lines = [
            f"### Context Summary [{self.timestamp}]",
            f"**Current State**: {self.current_state}",
            "",
            "**Key Facts**:",
        ]
        for f in self.important_facts:
            lines.append(f"- {f}")

        if self.decisions:
            lines.append("")
            lines.append("**Recent Decisions**:")
            for d in self.decisions:
                lines.append(f"- {d}")

        if self.pending_work:
            lines.append("")
            lines.append("**Pending Work**:")
            for p in self.pending_work:
                lines.append(f"- {p}")

        return "\n".join(lines)


class ContextCompactor:
    """Deterministically extracts important facts, decisions, state, and pending work into compact summary."""

    @staticmethod
    def compact(
        project_id: str,
        goal: Optional[Goal],
        tasks: List[PersistentTask],
        artifacts: List[ArtifactRecord],
        decisions: List[DecisionRecord],
        task_context: Optional[TaskContext] = None,
    ) -> CompactSummary:
        facts: List[str] = []

        if goal:
            facts.append(f"Domain: {goal.domain.value}; Goal: {goal.normalized_goal}")

        # Artifact facts
        if artifacts:
            recent_artifacts = artifacts[-5:]
            facts.append(f"Registered Artifacts ({len(artifacts)} total): {', '.join(a.path for a in recent_artifacts)}")

        # Task context facts
        if task_context:
            if task_context.files_modified:
                facts.append(f"Files Modified: {', '.join(task_context.files_modified[-5:])}")
            if task_context.tests_executed:
                facts.append(f"Tests Executed: {len(task_context.tests_executed)} tests run")
            if task_context.diagnoses:
                last_diag = task_context.diagnoses[-1]
                facts.append(f"Last Diagnosis: {last_diag.failure_reason[:80]}")

        # Decisions summary
        decision_summaries = [
            f"{d.question} -> {d.selected_option} ({d.rationale_summary[:60]})"
            for d in decisions[-5:]
        ]

        # Current state
        passed_count = sum(1 for t in tasks if t.status == StepStatus.PASSED)
        total_count = len(tasks)
        current_state = f"{passed_count}/{total_count} tasks completed successfully."

        # Pending work
        pending = [
            f"[{t.capability.upper()}] {t.title}"
            for t in tasks
            if t.status in (StepStatus.PENDING, StepStatus.RUNNING)
        ]

        return CompactSummary(
            summary_id=f"sum-{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            important_facts=facts,
            decisions=decision_summaries,
            current_state=current_state,
            pending_work=pending,
        )


class ContextManager:
    """Orchestrates tiered context assembly, prioritization, and selective memory loading."""

    def __init__(self, project_id: str, max_tokens: int = MAX_CONTEXT_HISTORY_TOKENS):
        self.project_id = project_id
        self.max_tokens = max_tokens
        self.compact_summaries: List[CompactSummary] = []

    def add_summary(self, summary: CompactSummary) -> None:
        self.compact_summaries.append(summary)

    def assemble_context(
        self,
        goal: Optional[Goal],
        current_task: Optional[PersistentTask],
        current_step: Optional[PlanStep] = None,
        tasks: Optional[List[PersistentTask]] = None,
        decisions: Optional[List[DecisionRecord]] = None,
        artifacts: Optional[List[ArtifactRecord]] = None,
        task_context: Optional[TaskContext] = None,
    ) -> Dict[str, Any]:
        """Assemble context strictly ordered by priority:

        1. Current Step / Task (Highest Priority)
        2. Current Project State & Goal
        3. Relevant Decisions
        4. Relevant Artifacts
        5. Compact Historical Summary
        """
        context: Dict[str, Any] = {}

        # 1. Step / Task Context (Priority 1)
        if current_step:
            context["current_step"] = {
                "id": current_step.id,
                "title": current_step.title,
                "action_type": current_step.action_type.value,
                "target": current_step.target,
                "attempts": current_step.attempts,
            }
        if current_task:
            context["current_task"] = {
                "id": current_task.id,
                "title": current_task.title,
                "capability": current_task.capability,
                "status": current_task.status.value if hasattr(current_task.status, "value") else str(current_task.status),
                "dependencies": current_task.dependencies,
                "verification": current_task.verification,
            }

        # 2. Project State & Goal (Priority 2)
        if goal:
            context["goal"] = {
                "domain": goal.domain.value,
                "outcome": goal.desired_outcome,
                "ambiguity": goal.ambiguity_level.value,
            }

        if tasks:
            context["progress"] = {
                "total": len(tasks),
                "passed": sum(1 for t in tasks if t.status == StepStatus.PASSED),
                "pending": sum(1 for t in tasks if t.status == StepStatus.PENDING),
                "failed": sum(1 for t in tasks if t.status == StepStatus.FAILED),
            }

        # 3. Relevant Decisions (Priority 3)
        if decisions:
            context["recent_decisions"] = [
                {"question": d.question, "choice": d.selected_option, "rationale": d.rationale_summary}
                for d in decisions[-3:]
            ]

        # 4. Relevant Artifacts (Priority 4)
        if artifacts:
            context["recent_artifacts"] = [
                {"path": a.path, "type": a.type}
                for a in artifacts[-3:]
            ]

        # 5. Compact Summary (Priority 5)
        if self.compact_summaries:
            context["latest_summary"] = self.compact_summaries[-1].to_dict()

        return context
