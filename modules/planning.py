"""ZARA Phase 11 - Hierarchical Planning, Validation, Cost Estimation & Decision Records.

Decomposes structured Goals into hierarchical task DAGs, validates quality and safety,
estimates resource consumption, selects capabilities, and logs concise operational decisions.
"""

from __future__ import annotations

import datetime
import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from config.settings import DECISIONS_LOG_FILE, RiskLevel
from core.state import StepStatus
from modules.goals import AmbiguityLevel, Goal, GoalDomain, RequirementType
from modules.workspace import PersistentTask, ProjectBudget


@dataclass
class PlanValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "missing_information": self.missing_information,
            "required_approvals": self.required_approvals,
        }


@dataclass
class PlanCost:
    estimated_steps: int = 1
    estimated_tool_calls: int = 2
    estimated_runtime: float = 30.0  # seconds
    estimated_retries: int = 0
    confidence: float = 0.85

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> PlanCost:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class DecisionRecord:
    decision_id: str
    project_id: str
    task_id: Optional[str]
    question: str
    options: List[str]
    selected_option: str
    rationale_summary: str  # Concise operational rationale ONLY. No hidden chain-of-thought.
    evidence: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DecisionRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class DecisionRegistry:
    """Manages persistent, auditable operational decision records."""

    def __init__(self, log_path: Path = DECISIONS_LOG_FILE):
        self.log_path = Path(log_path)
        self.decisions: List[DecisionRecord] = []
        self._load()

    def _load(self) -> None:
        if not self.log_path.exists():
            return
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            self.decisions.append(DecisionRecord.from_dict(json.loads(line)))
                        except Exception:
                            continue
        except Exception:
            pass

    def record(
        self,
        project_id: str,
        question: str,
        options: List[str],
        selected_option: str,
        rationale_summary: str,
        task_id: Optional[str] = None,
        evidence: Optional[str] = None,
    ) -> DecisionRecord:
        record = DecisionRecord(
            decision_id=f"dec-{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            task_id=task_id,
            question=question,
            options=options,
            selected_option=selected_option,
            rationale_summary=rationale_summary,
            evidence=evidence,
        )
        self.decisions.append(record)
        self._append_to_disk(record)
        return record

    def _append_to_disk(self, record: DecisionRecord) -> None:
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception:
            pass

    def list_by_project(self, project_id: str) -> List[DecisionRecord]:
        return [d for d in self.decisions if d.project_id == project_id]

    def get(self, decision_id: str) -> Optional[DecisionRecord]:
        for d in self.decisions:
            if d.decision_id == decision_id:
                return d
        return None


class PlanValidator:
    """Performs rigorous static validation on planned task DAGs before execution."""

    @staticmethod
    def validate(
        goal: Goal,
        tasks: List[PersistentTask],
        budget: Optional[ProjectBudget] = None,
        available_capabilities: Optional[Set[str]] = None,
        allowed_scopes: Optional[List[str]] = None,
    ) -> PlanValidationResult:
        errors: List[str] = []
        warnings: List[str] = []
        missing_info: List[str] = []
        required_approvals: List[str] = []

        # 1. Ambiguity & Missing Information Check
        if goal.ambiguity_level in (AmbiguityLevel.HIGH, AmbiguityLevel.CRITICAL):
            errors.append(f"Goal has unresolved ambiguity ({goal.ambiguity_level.value}): {goal.clarification_question or 'Missing critical details'}")
            if goal.clarification_question:
                missing_info.append(goal.clarification_question)

        if not tasks:
            errors.append("Plan contains zero executable tasks.")
            return PlanValidationResult(valid=False, errors=errors, warnings=warnings, missing_information=missing_info)

        task_ids = {t.id for t in tasks}

        # 2. Dependency Integrity & Cycle Detection
        adj: Dict[str, List[str]] = {t.id: [] for t in tasks}
        for task in tasks:
            for dep in task.dependencies:
                if dep not in task_ids:
                    errors.append(f"Task '{task.id}' depends on non-existent task '{dep}'.")
                else:
                    adj[dep].append(task.id)

        # Detect cycles using DFS
        visited: Dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited

        def has_cycle(u: str) -> bool:
            visited[u] = 1
            for v in adj.get(u, []):
                if visited.get(v, 0) == 1:
                    return True
                if visited.get(v, 0) == 0 and has_cycle(v):
                    return True
            visited[u] = 2
            return False

        for tid in task_ids:
            if visited.get(tid, 0) == 0:
                if has_cycle(tid):
                    errors.append(f"Cycle detected in task dependencies involving task '{tid}'.")
                    break

        # 3. Capability Validation
        standard_capabilities = {
            "coding", "debugging", "research", "browser", "mac_control",
            "vision", "blender", "cyber_lab", "terminal", "general"
        }
        all_capabilities = available_capabilities or standard_capabilities

        for task in tasks:
            if task.capability not in all_capabilities:
                errors.append(f"Task '{task.id}' requires unavailable capability: '{task.capability}'.")

        # 4. Verification Check
        for task in tasks:
            if not task.verification and not any(crit.required for crit in goal.success_criteria):
                warnings.append(f"Task '{task.id}' ({task.title}) has no verification method configured.")

        # 5. Domain Safety & Scope Checks
        if goal.domain == GoalDomain.CYBERSECURITY:
            for task in tasks:
                target = task.input_payload.get("target") or task.input_payload.get("url") or ""
                if target:
                    # Target must be allowlisted or safe local lab
                    safe_patterns = ["localhost", "127.0.0.1", "dvwa", "192.168."]
                    is_safe = any(p in str(target).lower() for p in safe_patterns)
                    if allowed_scopes:
                        is_safe = is_safe or any(s in str(target).lower() for s in allowed_scopes)
                    if not is_safe:
                        errors.append(f"Task '{task.id}' targets unauthorized external host '{target}'. Scope violation.")
            # Cyber operations always require approval check
            required_approvals.append("Cybersecurity assessment plan authorization")

        # 6. Budget Check
        if budget:
            estimated_steps = len(tasks)
            if estimated_steps > budget.max_steps:
                errors.append(f"Plan requires {estimated_steps} steps, exceeding maximum step budget of {budget.max_steps}.")

        valid = len(errors) == 0
        return PlanValidationResult(
            valid=valid,
            errors=errors,
            warnings=warnings,
            missing_information=missing_info,
            required_approvals=required_approvals,
        )


class HierarchicalPlanner:
    """Decomposes structured Goals into ordered, hierarchical task DAGs."""

    @staticmethod
    def select_capabilities(domain: GoalDomain) -> List[Tuple[str, str]]:
        """Return primary and secondary capabilities with rationale for selection."""
        if domain == GoalDomain.BLENDER:
            return [
                ("blender", "Procedural 3D scene generation and headless rendering"),
                ("vision", "Visual verification of rendered scene artifacts"),
            ]
        elif domain == GoalDomain.CYBERSECURITY:
            return [
                ("cyber_lab", "Target scope validation and specialized security auditing"),
                ("terminal", "Execution of scoped security audit commands"),
            ]
        elif domain == GoalDomain.CODING:
            return [
                ("coding", "Source code inspection, generation, and AST validation"),
                ("debugging", "Test execution and diagnostic hypothesis generation"),
            ]
        elif domain == GoalDomain.RESEARCH:
            return [
                ("research", "Information retrieval, source verification, and citation analysis"),
                ("browser", "Web content inspection and evidence extraction"),
            ]
        elif domain == GoalDomain.MAC_CONTROL:
            return [
                ("mac_control", "macOS GUI element interaction and application control"),
                ("vision", "Visual GUI state verification and screen inspection"),
            ]
        return [("general", "General command execution and workflow management")]

    @classmethod
    def estimate_cost(cls, goal: Goal, tasks: List[PersistentTask]) -> PlanCost:
        steps_count = len(tasks)
        tool_calls_per_step = 2
        runtime_per_step = 15.0  # seconds

        if goal.domain == GoalDomain.BLENDER:
            runtime_per_step = 30.0  # Rendering takes longer
        elif goal.domain == GoalDomain.RESEARCH:
            tool_calls_per_step = 3
        elif goal.domain == GoalDomain.CYBERSECURITY:
            tool_calls_per_step = 2
            runtime_per_step = 25.0

        return PlanCost(
            estimated_steps=steps_count,
            estimated_tool_calls=steps_count * tool_calls_per_step,
            estimated_runtime=steps_count * runtime_per_step,
            estimated_retries=1 if steps_count > 3 else 0,
            confidence=0.85 if goal.ambiguity_level == AmbiguityLevel.NONE else 0.60,
        )

    @classmethod
    def create_hierarchical_plan(
        cls,
        goal: Goal,
        project_id: str,
        world_state: Optional[Any] = None,
        relevant_memories: Optional[List[Any]] = None,
    ) -> List[PersistentTask]:
        """Generate hierarchical DAG tasks tailored to the Goal domain, informed by World Model state and prior memories."""
        tasks: List[PersistentTask] = []
        domain = goal.domain

        if domain == GoalDomain.BLENDER:
            t1 = PersistentTask(
                id=f"{project_id}-task-1",
                project_id=project_id,
                title="Inspect Blender environment & capabilities",
                description="Verify Blender installation, headless flags, and workspace output directory",
                capability="blender",
                dependencies=[],
                verification={"method": "system_check", "expected": "blender_available"},
            )
            t2 = PersistentTask(
                id=f"{project_id}-task-2",
                project_id=project_id,
                parent_id=t1.id,
                title="Generate procedural Blender script",
                description=f"Generate Python script for 3D goal: {goal.desired_outcome}",
                capability="blender",
                dependencies=[t1.id],
                verification={"method": "ast_validation", "expected": "clean_ast"},
            )
            t3 = PersistentTask(
                id=f"{project_id}-task-3",
                project_id=project_id,
                parent_id=t2.id,
                title="Execute headless render",
                description="Execute Blender headless rendering pipeline and output image artifact",
                capability="blender",
                dependencies=[t2.id],
                verification={"method": "file_exists", "expected": "output.png"},
            )
            t4 = PersistentTask(
                id=f"{project_id}-task-4",
                project_id=project_id,
                parent_id=t3.id,
                title="Vision verification of rendered scene",
                description="Perform computer vision inspection of rendered scene artifact",
                capability="vision",
                dependencies=[t3.id],
                verification={"method": "vision_verification", "expected": "scene_valid"},
            )
            tasks.extend([t1, t2, t3, t4])

        elif domain == GoalDomain.CYBERSECURITY:
            target = "http://127.0.0.1:8080/dvwa"
            for word in (goal.raw_request + " " + goal.desired_outcome).split():
                clean_w = word.strip(" ,;:\"'()")
                if any(x in clean_w.lower() for x in [".com", ".org", ".net", ".io", "127.", "localhost", "dvwa", "192.168.", "http://", "https://"]):
                    target = clean_w
                    break

            t1 = PersistentTask(
                id=f"{project_id}-task-1",
                project_id=project_id,
                title="Validate target scope & authorization",
                description=f"Verify target authorization against CyberLabScope for goal: {goal.desired_outcome}",
                capability="cyber_lab",
                dependencies=[],
                verification={"method": "scope_verified", "expected": "target_allowlisted"},
                input_payload={"target": target},
            )
            t2 = PersistentTask(
                id=f"{project_id}-task-2",
                project_id=project_id,
                parent_id=t1.id,
                title="Execute scoped security audit",
                description="Execute non-destructive security reconnaissance and vulnerability scan",
                capability="cyber_lab",
                dependencies=[t1.id],
                verification={"method": "scan_completed", "expected": "raw_output"},
                input_payload={"target": target},
            )
            t3 = PersistentTask(
                id=f"{project_id}-task-3",
                project_id=project_id,
                parent_id=t2.id,
                title="Normalize findings & generate security report",
                description="Structure findings, collect evidence, and output markdown security report",
                capability="cyber_lab",
                dependencies=[t2.id],
                verification={"method": "findings_check", "expected": "report_artifact"},
            )
            tasks.extend([t1, t2, t3])

        elif domain == GoalDomain.CODING:
            t1 = PersistentTask(
                id=f"{project_id}-task-1",
                project_id=project_id,
                title="Inspect repository & requirements",
                description=f"Analyze existing code structure for: {goal.desired_outcome}",
                capability="coding",
                dependencies=[],
                verification={"method": "files_inspected", "expected": "context_ready"},
            )
            t2 = PersistentTask(
                id=f"{project_id}-task-2",
                project_id=project_id,
                parent_id=t1.id,
                title="Implement code changes",
                description="Write or patch code according to specifications",
                capability="coding",
                dependencies=[t1.id],
                verification={"method": "ast_validation", "expected": "syntax_valid"},
            )
            t3 = PersistentTask(
                id=f"{project_id}-task-3",
                project_id=project_id,
                parent_id=t2.id,
                title="Run test suite & verify",
                description="Run automated tests and verify 0 failures",
                capability="debugging",
                dependencies=[t2.id],
                verification={"method": "run_tests", "expected": "all_pass"},
            )
            tasks.extend([t1, t2, t3])

        elif domain == GoalDomain.RESEARCH:
            t1 = PersistentTask(
                id=f"{project_id}-task-1",
                project_id=project_id,
                title="Execute structured research queries",
                description=f"Gather verified sources for research goal: {goal.desired_outcome}",
                capability="research",
                dependencies=[],
                verification={"method": "sources_gathered", "expected": "sources_non_empty"},
            )
            t2 = PersistentTask(
                id=f"{project_id}-task-2",
                project_id=project_id,
                parent_id=t1.id,
                title="Synthesize evidence & format report",
                description="Extract claims, link citations, and output structured summary",
                capability="research",
                dependencies=[t1.id],
                verification={"method": "citation_check", "expected": "valid_citations"},
            )
            tasks.extend([t1, t2])

        else:
            # GENERAL
            t1 = PersistentTask(
                id=f"{project_id}-task-1",
                project_id=project_id,
                title=f"Execute: {goal.normalized_goal}",
                description=goal.desired_outcome,
                capability="general",
                dependencies=[],
                verification={"method": "execution_check", "expected": "success"},
            )
            tasks.append(t1)

        if relevant_memories:
            memory_hints = [
                m.content if hasattr(m, "content") else str(m)
                for m in relevant_memories
            ]
            for t in tasks:
                if t.input_payload is None:
                    t.input_payload = {}
                t.input_payload["memory_hints"] = memory_hints

        return tasks

    @staticmethod
    def infer_task_resources(task: PersistentTask) -> List[Dict[str, Any]]:
        """Identify resources required by a task for safe parallel execution."""
        resources = []
        if task.artifacts:
            for art in task.artifacts:
                resources.append({"type": "filesystem", "target": art, "mode": "exclusive"})
        cap = (task.capability or "").lower()
        if "cyber" in cap:
            target = task.input_payload.get("target") or "localhost"
            resources.append({"type": "cyber_target", "target": str(target), "mode": "exclusive"})
        if "vision" in cap and ("mouse" in task.title.lower() or "gui" in task.title.lower()):
            resources.append({"type": "screen", "target": "gui:primary", "mode": "exclusive"})
        return resources


class PlanPreview:
    """Generates human-readable, auditable plan previews without exposing chain-of-thought."""

    @staticmethod
    def render(
        goal: Goal,
        tasks: List[PersistentTask],
        cost: PlanCost,
        validation: PlanValidationResult,
    ) -> str:
        lines: List[str] = [
            "============================================================",
            "                   ZARA PLAN PREVIEW                        ",
            "============================================================",
            f"Goal: {goal.normalized_goal}",
            f"Domain: {goal.domain.value} | Ambiguity: {goal.ambiguity_level.value}",
            f"Desired Outcome: {goal.desired_outcome}",
            "------------------------------------------------------------",
            "Steps:",
        ]
        for idx, t in enumerate(tasks, start=1):
            deps = f" (depends on: {', '.join(t.dependencies)})" if t.dependencies else ""
            lines.append(f"  {idx}. [{t.capability.upper()}] {t.title}{deps}")

        lines.extend([
            "------------------------------------------------------------",
            f"Estimated Steps: {cost.estimated_steps}",
            f"Estimated Tool Calls: {cost.estimated_tool_calls}",
            f"Estimated Runtime: {cost.estimated_runtime:.1f}s",
            f"Plan Valid: {'YES' if validation.valid else 'NO'}",
        ])
        if validation.required_approvals:
            lines.append(f"Approval Required: YES ({', '.join(validation.required_approvals)})")
        else:
            lines.append("Approval Required: NO")

        if validation.errors:
            lines.append("Errors:")
            for err in validation.errors:
                lines.append(f"  ! {err}")
        if validation.warnings:
            lines.append("Warnings:")
            for warn in validation.warnings:
                lines.append(f"  * {warn}")

        lines.append("============================================================")
        return "\n".join(lines)
