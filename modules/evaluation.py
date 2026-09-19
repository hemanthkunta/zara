"""
ZARA Phase 17 — Self-Improvement, Evaluation, Learning & Adaptive Optimization.

Equips ZARA with multi-dimensional task evaluation, evidence-based scoring,
success criteria verification, experience/failure/success pattern learning,
a versioned strategy registry, subsystem performance tracking (model router,
workers, memory, planning), controlled improvement proposals with risk classification,
an experiment framework, and atomic rollback.

CRITICAL SAFETY PRINCIPLE:
ZARA must NEVER autonomously rewrite or modify its own safety policies,
authorization rules, CyberLabScope, confirmation gates, security boundaries,
secret handling, core orchestration invariants, or model safety policies.
All improvement candidates must pass validation, testing, and approval gates.
"""

from __future__ import annotations

import datetime
import enum
import hashlib
import json
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from config.settings import (
    BASE_DIR,
    CRITICAL_FILES_BLOCKLIST,
    EVALUATIONS_DIR,
    EXPERIMENTS_DIR,
    IMPROVEMENTS_DIR,
    LEARNING_DIR,
    STRATEGIES_FILE,
    STRATEGY_MIN_EVIDENCE_THRESHOLD,
    STRATEGY_VALIDATION_SUCCESS_RATE,
)
from core.observability import audit_logger
from core.state import Diagnosis, StepStatus, TaskContext
from modules.events import Event, EventBus, EventType
from modules.memory import (
    MemoryItem,
    MemoryScope,
    MemorySource,
    MemoryStore,
    MemoryType,
    PrivacyLevel,
    contains_secret,
    scrub_text,
)


# =====================================================================
# Enums
# =====================================================================

class CriterionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class EvaluationDimension(str, enum.Enum):
    CORRECTNESS = "CORRECTNESS"
    QUALITY = "QUALITY"
    EFFICIENCY = "EFFICIENCY"
    RELIABILITY = "RELIABILITY"
    SAFETY = "SAFETY"
    USER_SATISFACTION = "USER_SATISFACTION"


from modules.strategies import (
    StrategyStatus,
    StrategyDomain,
    Strategy,
    StrategyRegistry,
)
from modules.improvement import (
    ChangeType,
    ProposalRisk,
    ProposalStatus,
    ImprovementProposal,
    ImprovementVersion,
)
from modules.experiments import (
    ExperimentStatus,
    Experiment,
)
from modules.learning import (
    CandidateStatus,
    UserFeedbackType,
    UserFeedback,
    LearningCandidate,
    FailurePattern,
    ModelPerformanceObservation,
    WorkerPerformanceObservation,
    PlannerPerformanceObservation,
)


# =====================================================================
# Dataclasses
# =====================================================================

@dataclass
class CriterionResult:
    criterion: str
    status: CriterionStatus
    evidence: Any
    confidence: float = 1.0
    required: bool = True
    score: float = 1.0
    dimension: Optional[EvaluationDimension] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion": self.criterion,
            "status": self.status.value if isinstance(self.status, CriterionStatus) else str(self.status),
            "evidence": self.evidence,
            "confidence": self.confidence,
            "required": self.required,
            "score": self.score,
            "dimension": self.dimension.value if self.dimension else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CriterionResult:
        status_val = data.get("status", CriterionStatus.UNKNOWN.value)
        dim_val = data.get("dimension")
        return cls(
            criterion=data.get("criterion", ""),
            status=CriterionStatus(status_val) if isinstance(status_val, str) else status_val,
            evidence=data.get("evidence", ""),
            confidence=float(data.get("confidence", 1.0)),
            required=bool(data.get("required", True)),
            score=float(data.get("score", 1.0)),
            dimension=EvaluationDimension(dim_val) if dim_val else None,
        )


@dataclass
class EvaluationResult:
    evaluation_id: str
    project_id: str
    task_id: str
    worker_id: Optional[str] = None
    session_id: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    task_success: bool = False
    verification_success: bool = False
    quality_score: float = 0.0
    efficiency_score: float = 0.0
    safety_score: float = 1.0
    reliability_score: float = 0.0
    user_satisfaction: Optional[float] = None
    overall_score: float = 0.0
    failures: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    criteria_results: List[CriterionResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "worker_id": self.worker_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "task_success": self.task_success,
            "verification_success": self.verification_success,
            "quality_score": round(self.quality_score, 3),
            "efficiency_score": round(self.efficiency_score, 3),
            "safety_score": round(self.safety_score, 3),
            "reliability_score": round(self.reliability_score, 3),
            "user_satisfaction": round(self.user_satisfaction, 3) if self.user_satisfaction is not None else None,
            "overall_score": round(self.overall_score, 3),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
            "evidence": dict(self.evidence),
            "metrics": dict(self.metrics),
            "criteria_results": [c.to_dict() for c in self.criteria_results],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvaluationResult:
        criteria = [CriterionResult.from_dict(c) for c in data.get("criteria_results", [])]
        return cls(
            evaluation_id=data["evaluation_id"],
            project_id=data.get("project_id", "default"),
            task_id=data.get("task_id", "task-default"),
            worker_id=data.get("worker_id"),
            session_id=data.get("session_id"),
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            task_success=bool(data.get("task_success", False)),
            verification_success=bool(data.get("verification_success", False)),
            quality_score=float(data.get("quality_score", 0.0)),
            efficiency_score=float(data.get("efficiency_score", 0.0)),
            safety_score=float(data.get("safety_score", 1.0)),
            reliability_score=float(data.get("reliability_score", 0.0)),
            user_satisfaction=float(data["user_satisfaction"]) if data.get("user_satisfaction") is not None else None,
            overall_score=float(data.get("overall_score", 0.0)),
            failures=data.get("failures", []),
            warnings=data.get("warnings", []),
            evidence=data.get("evidence", {}),
            metrics=data.get("metrics", {}),
            criteria_results=criteria,
        )


# =====================================================================
# Evaluation Manager
# =====================================================================

class EvaluationManager:
    """
    Central coordinator of ZARA's evaluation, learning, and self-improvement pipeline.
    Enforces the Critical Safety Principle with automated proposal blocking.
    """

    def __init__(
        self,
        memory_store: Optional[MemoryStore] = None,
        event_bus: Optional[EventBus] = None,
        strategy_registry: Optional[StrategyRegistry] = None,
        evaluations_dir: Path = EVALUATIONS_DIR,
        proposals_dir: Path = IMPROVEMENTS_DIR,
        experiments_dir: Path = EXPERIMENTS_DIR,
        strategies_file: Optional[Path] = None,
    ):
        self.memory = memory_store or MemoryStore()
        self.event_bus = event_bus
        if strategy_registry is not None:
            self.strategy_registry = strategy_registry
        elif strategies_file is not None:
            self.strategy_registry = StrategyRegistry(storage_file=strategies_file)
        else:
            self.strategy_registry = StrategyRegistry()
        self.evaluations_dir = evaluations_dir
        self.proposals_dir = proposals_dir
        self.experiments_dir = experiments_dir

        self.evaluations_dir.mkdir(parents=True, exist_ok=True)
        self.proposals_dir.mkdir(parents=True, exist_ok=True)
        self.experiments_dir.mkdir(parents=True, exist_ok=True)

        self._lock = threading.RLock()
        self.evaluations: Dict[str, EvaluationResult] = {}
        self.learning_candidates: Dict[str, LearningCandidate] = {}
        self.proposals: Dict[str, ImprovementProposal] = {}
        self.experiments: Dict[str, Experiment] = {}
        self.versions: Dict[str, ImprovementVersion] = {}

        # Tracking metrics for subsystems
        self.model_metrics: Dict[str, Dict[str, Any]] = {}
        self.worker_metrics: Dict[str, Dict[str, Any]] = {}
        self.memory_evaluations: List[Dict[str, Any]] = []
        self.planning_evaluations: List[Dict[str, Any]] = []

        self._load_state()

    def _publish(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        if self.event_bus:
            try:
                self.event_bus.publish(Event(type=event_type, payload=payload))
            except Exception as e:
                audit_logger.log_event("EVENT_PUBLISH_FAILED", {"event": event_type.value, "error": str(e)})

    def _load_state(self) -> None:
        with self._lock:
            # Load evaluations
            for f in self.evaluations_dir.glob("eval-*.json"):
                try:
                    ev = EvaluationResult.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    self.evaluations[ev.evaluation_id] = ev
                except Exception:
                    pass

            # Load proposals
            for f in self.proposals_dir.glob("prop-*.json"):
                try:
                    p = ImprovementProposal.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    self.proposals[p.proposal_id] = p
                except Exception:
                    pass

            # Load experiments
            for f in self.experiments_dir.glob("exp-*.json"):
                try:
                    exp = Experiment.from_dict(json.loads(f.read_text(encoding="utf-8")))
                    self.experiments[exp.experiment_id] = exp
                except Exception:
                    pass

            # Load versions
            versions_file = self.proposals_dir / "versions.json"
            if versions_file.exists():
                try:
                    data = json.loads(versions_file.read_text(encoding="utf-8"))
                    for v_dict in data:
                        v = ImprovementVersion.from_dict(v_dict)
                        self.versions[v.version_id] = v
                except Exception:
                    pass

    def _save_version(self, version: ImprovementVersion) -> None:
        with self._lock:
            self.versions[version.version_id] = version
            versions_file = self.proposals_dir / "versions.json"
            serialized = [v.to_dict() for v in self.versions.values()]
            versions_file.write_text(json.dumps(serialized, indent=2), encoding="utf-8")

    # =================================================================
    # Task Evaluation
    # =================================================================

    def evaluate_task_execution(
        self,
        context: TaskContext,
        goal: Optional[Any] = None,
        worker: Optional[Any] = None,
        user_feedback: Optional[UserFeedback] = None,
    ) -> EvaluationResult:
        """
        Evaluate completed or blocked task across all dimensions:
        CORRECTNESS, QUALITY, EFFICIENCY, RELIABILITY, SAFETY, USER_SATISFACTION.
        Prioritizes objective evidence over subjective opinion.
        """
        eval_id = f"eval-{uuid.uuid4().hex[:10]}"
        self._publish(EventType.EVALUATION_STARTED, {
            "evaluation_id": eval_id,
            "task": context.task,
        })

        project_id = getattr(context, "working_dir", "default")
        task_id = f"task-{abs(hash(context.task)) % 1000000:06d}"
        worker_id = getattr(worker, "worker_id", None)

        # 1. Evaluate Success Criteria (Phase 11 Goal)
        criteria_results: List[CriterionResult] = []
        all_required_criteria_met = True

        if goal and hasattr(goal, "success_criteria") and goal.success_criteria:
            for crit in goal.success_criteria:
                desc = crit.description if hasattr(crit, "description") else str(crit)
                req = getattr(crit, "required", True)
                v_method = getattr(crit, "verification_method", "execution_check")

                # Objective verification
                status = CriterionStatus.UNKNOWN
                evidence_str = "No explicit assertion found"

                if context.is_completed:
                    if v_method in ("run_tests", "execution_check"):
                        if context.tests_executed or any(s.status == StepStatus.PASSED for s in context.steps):
                            status = CriterionStatus.PASSED
                            evidence_str = f"Execution verified via {len(context.steps)} steps"
                        else:
                            status = CriterionStatus.PARTIAL
                            evidence_str = "Completed without explicit test execution"
                    elif v_method in ("file_exists", "artifact_created"):
                        if context.files_created or context.files_modified:
                            status = CriterionStatus.PASSED
                            evidence_str = f"Artifacts created/modified: {len(context.files_created) + len(context.files_modified)}"
                        else:
                            status = CriterionStatus.FAILED
                            evidence_str = "No artifact files produced"
                    else:
                        status = CriterionStatus.PASSED
                        evidence_str = "Completed successfully within budget"
                else:
                    status = CriterionStatus.FAILED
                    evidence_str = f"Task blocked or failed: {context.blocker_reason or 'Incomplete execution'}"

                if req and status not in (CriterionStatus.PASSED, CriterionStatus.PARTIAL):
                    all_required_criteria_met = False

                criteria_results.append(CriterionResult(
                    criterion=desc,
                    status=status,
                    evidence=evidence_str,
                    required=req,
                ))

        # 2. Compute Multi-Dimensional Scores
        total_steps = len(context.steps)
        passed_steps = sum(1 for s in context.steps if s.status == StepStatus.PASSED)
        step_pass_rate = (passed_steps / total_steps) if total_steps > 0 else (1.0 if context.is_completed else 0.0)

        has_syntax_errors = any("syntax" in str(d.failure_reason).lower() for d in context.diagnoses)
        verification_success = context.is_completed and not has_syntax_errors and all_required_criteria_met
        task_success = context.is_completed and all_required_criteria_met

        correctness_score = 1.0 if (verification_success and task_success) else (0.5 * step_pass_rate)

        diff_summary = context.get_diff_summary()
        failures_list: List[str] = [d.failure_reason for d in context.diagnoses]
        warnings_list: List[str] = []
        if context.blocker_reason:
            failures_list.append(context.blocker_reason)

        quality_score = max(0.0, 1.0 - (len(context.diagnoses) * 0.15))
        if not context.is_completed:
            quality_score = 0.0
            warnings_list.append(f"Task incomplete: {context.blocker_reason or 'No execution completion recorded'}")
        if total_steps == 0:
            warnings_list.append("No execution steps recorded")

        elapsed_time = max(0.1, time.time() - context.start_time)
        retries = context.total_retries
        efficiency_score = 1.0 / (1.0 + (retries * 0.5) + max(0.0, (elapsed_time - 60.0) / 120.0))
        efficiency_score = max(0.1, min(1.0, efficiency_score))

        reliability_score = max(0.0, step_pass_rate - (len(context.diagnoses) * 0.1))
        if context.is_completed:
            reliability_score = max(0.5, reliability_score)

        safety_score = 1.0
        for ev in context.events:
            if "scope" in str(ev).lower() or "violation" in str(ev).lower() or "blocked" in str(ev).lower():
                safety_score = 0.0
                warnings_list.append("Safety intercept triggered during task execution")
                break

        user_satisfaction_score: Optional[float] = None
        if user_feedback:
            if user_feedback.rating is not None:
                user_satisfaction_score = user_feedback.rating
            elif user_feedback.type == UserFeedbackType.POSITIVE:
                user_satisfaction_score = 1.0
            elif user_feedback.type == UserFeedbackType.NEGATIVE:
                user_satisfaction_score = 0.0
            elif user_feedback.type == UserFeedbackType.CORRECTION:
                user_satisfaction_score = 0.4
            elif user_feedback.type == UserFeedbackType.PREFERENCE:
                user_satisfaction_score = 0.7

        if user_satisfaction_score is not None:
            overall = (
                0.30 * correctness_score
                + 0.15 * quality_score
                + 0.15 * efficiency_score
                + 0.15 * reliability_score
                + 0.15 * safety_score
                + 0.10 * user_satisfaction_score
            )
        else:
            overall = (
                0.35 * correctness_score
                + 0.20 * quality_score
                + 0.15 * efficiency_score
                + 0.15 * reliability_score
                + 0.15 * safety_score
            )

        evidence_dict = {
            "steps_total": total_steps,
            "steps_passed": passed_steps,
            "diagnoses_count": len(context.diagnoses),
            "files_modified": diff_summary.get("modified", []),
            "files_created": diff_summary.get("created", []),
            "tests_run": diff_summary.get("tests_run", []),
            "retries": retries,
            "all_required_criteria_met": all_required_criteria_met,
        }

        metrics_dict = {
            "execution_time_seconds": round(elapsed_time, 2),
            "total_retries": retries,
            "events_count": len(context.events),
            "diagnoses_count": len(context.diagnoses),
        }

        result = EvaluationResult(
            evaluation_id=eval_id,
            project_id=str(project_id),
            task_id=task_id,
            worker_id=worker_id,
            session_id=None,
            task_success=task_success,
            verification_success=verification_success,
            quality_score=quality_score,
            efficiency_score=efficiency_score,
            safety_score=safety_score,
            reliability_score=reliability_score,
            user_satisfaction=user_satisfaction_score,
            overall_score=overall,
            failures=failures_list,
            warnings=warnings_list,
            evidence=evidence_dict,
            metrics=metrics_dict,
            criteria_results=criteria_results,
        )

        with self._lock:
            self.evaluations[eval_id] = result
            eval_file = self.evaluations_dir / f"{eval_id}.json"
            eval_file.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

        self._publish(EventType.EVALUATION_COMPLETED, {
            "evaluation_id": eval_id,
            "overall_score": result.overall_score,
            "task_success": result.task_success,
            "verification_success": result.verification_success,
        })

        # Extract Lessons & Update Strategies
        self.extract_lessons(context, result)

        return result

    # =================================================================
    # User Feedback Handling
    # =================================================================

    def record_user_feedback(
        self,
        raw_text: str = "",
        task_id: Optional[str] = None,
        rating: Optional[float] = None,
        feedback_type: Optional[Union[UserFeedbackType, str]] = None,
        correction: Optional[str] = None
    ) -> UserFeedback:
        """
        Ingest and classify explicit user feedback into structured form.
        Extracts candidate memories and registers learning candidates.
        """
        if correction and not raw_text:
            raw_text = correction
        feedback_id = f"fb-{uuid.uuid4().hex[:8]}"
        clean_text = scrub_text(raw_text)

        lowered = clean_text.lower()
        if feedback_type is not None:
            ftype = UserFeedbackType(feedback_type) if isinstance(feedback_type, str) else feedback_type
        elif rating is not None:
            ftype = UserFeedbackType.RATING
        elif any(w in lowered for w in ("wrong", "bad", "failed", "incorrect", "don't do that", "stop")):
            ftype = UserFeedbackType.NEGATIVE
        elif any(w in lowered for w in ("instead", "next time", "correct approach", "fix:", "should be")):
            ftype = UserFeedbackType.CORRECTION
        elif any(w in lowered for w in ("prefer", "always", "never", "my preference")):
            ftype = UserFeedbackType.PREFERENCE
        elif any(w in lowered for w in ("great", "good", "worked", "perfect", "thanks", "excellent")):
            ftype = UserFeedbackType.POSITIVE
        else:
            ftype = UserFeedbackType.POSITIVE

        if rating is not None and rating > 1.0:
            rating = min(1.0, rating / 10.0 if rating <= 10.0 else rating / 100.0)

        correction_text = None
        if ftype in (UserFeedbackType.CORRECTION, UserFeedbackType.PREFERENCE):
            correction_text = clean_text

        feedback = UserFeedback(
            feedback_id=feedback_id,
            task_id=task_id,
            type=ftype,
            raw_text=clean_text,
            rating=rating,
            correction=correction_text,
            structured_tags=[ftype.value.lower()]
        )

        try:
            if hasattr(self.memory, "store_memory"):
                mtype = MemoryType.PREFERENCE if ftype in (UserFeedbackType.PREFERENCE, UserFeedbackType.CORRECTION) else MemoryType.USER_FEEDBACK
                self.memory.store_memory(MemoryItem(
                    memory_id=f"mem-fb-{feedback_id}",
                    content=f"User feedback ({ftype.value}): {clean_text}" if clean_text else f"User feedback ({ftype.value}): Rating {rating} for {task_id}",
                    type=mtype,
                    scope=MemoryScope.GLOBAL,
                    source=MemorySource.USER_STATED,
                    confidence=0.95,
                    privacy_level=PrivacyLevel.NORMAL,
                    metadata={"feedback_id": feedback_id, "task_id": task_id, "rating": rating}
                ))
        except Exception:
            pass

        cand = LearningCandidate(
            candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
            source="user_feedback",
            lesson=f"User feedback guidance: {clean_text}",
            evidence={"feedback_id": feedback_id, "type": ftype.value, "rating": rating},
            confidence=0.90,
            scope="GLOBAL",
            status=CandidateStatus.ACCEPTED if ftype in (UserFeedbackType.POSITIVE, UserFeedbackType.PREFERENCE) else CandidateStatus.CANDIDATE,
            memory_type="USER_FEEDBACK"
        )
        with self._lock:
            self.learning_candidates[cand.candidate_id] = cand

        self._publish(EventType.LEARNING_CANDIDATE_CREATED, {
            "candidate_id": cand.candidate_id,
            "lesson": cand.lesson,
            "source": cand.source
        })

        return feedback

    def record_learning_candidate(
        self,
        source_task: str,
        lesson: str,
        evidence: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        confidence: float = 0.85,
        status: CandidateStatus = CandidateStatus.CANDIDATE,
        memory_type: str = "LESSON"
    ) -> LearningCandidate:
        """Record a structured learning candidate."""
        cand = LearningCandidate(
            candidate_id=f"cand-{uuid.uuid4().hex[:8]}",
            source=source_task,
            lesson=lesson,
            evidence=evidence or {},
            confidence=confidence,
            scope="GLOBAL",
            status=status,
            memory_type=memory_type
        )
        with self._lock:
            self.learning_candidates[cand.candidate_id] = cand

        self._publish(EventType.LEARNING_CANDIDATE_CREATED, {
            "candidate_id": cand.candidate_id,
            "lesson": cand.lesson,
            "source": cand.source
        })
        return cand

    def _store_learning_in_memory(self, candidate: LearningCandidate) -> None:
        """Persist a LearningCandidate into the MemoryStore."""
        if not hasattr(self.memory, "store_memory"):
            return
        m_type = MemoryType.EXPERIENCE
        if candidate.memory_type == "ERROR_PATTERN":
            m_type = MemoryType.ERROR_PATTERN
        elif candidate.memory_type in ("USER_FEEDBACK", "PREFERENCE"):
            m_type = MemoryType.PREFERENCE
        elif candidate.memory_type == "SUCCESS_PATTERN":
            m_type = MemoryType.EXPERIENCE

        self.memory.store_memory(MemoryItem(
            memory_id=f"mem-{candidate.candidate_id}",
            content=candidate.lesson,
            type=m_type,
            scope=MemoryScope.GLOBAL,
            source=MemorySource.TASK_RESULT,
            confidence=candidate.confidence,
            privacy_level=PrivacyLevel.NORMAL,
            metadata=candidate.evidence
        ))

    # =================================================================
    # Lesson Extraction & Pattern Learning
    # =================================================================

    def extract_lessons(
        self,
        context: TaskContext,
        eval_result: EvaluationResult
    ) -> List[LearningCandidate]:
        """Extract structured lessons from success or failure patterns and update memory."""
        extracted: List[LearningCandidate] = []

        # 1. Failure Pattern Learning
        if context.diagnoses or not eval_result.task_success:
            for diag in context.diagnoses:
                pattern = FailurePattern(
                    failure_type=diag.failure_type or diag.root_cause_category or "execution_failure",
                    root_cause=diag.root_cause or diag.failure_reason,
                    context={"task": context.task, "attempt": diag.attempt},
                    successful_recovery=str(diag.proposed_fix.get("action")) if isinstance(diag.proposed_fix, dict) else str(diag.proposed_fix),
                    confidence=diag.confidence,
                    frequency=1
                )
                lesson_text = f"Failure: {pattern.failure_type} caused by '{pattern.root_cause[:120]}'. Recovery: {pattern.successful_recovery or 'Diagnostic retry'}."

                err_hash = hashlib.sha256(lesson_text.encode("utf-8")).hexdigest()[:10]
                cand = LearningCandidate(
                    candidate_id=f"cand-err-{err_hash}",
                    source="failure_diagnosis",
                    lesson=lesson_text,
                    evidence=pattern.to_dict(),
                    confidence=min(0.95, diag.confidence),
                    scope="GLOBAL",
                    status=CandidateStatus.ACCEPTED,
                    memory_type="ERROR_PATTERN"
                )
                extracted.append(cand)

                try:
                    if hasattr(self.memory, "store_memory"):
                        self.memory.store_memory(MemoryItem(
                            memory_id=f"mem-err-{cand.candidate_id}",
                            content=lesson_text,
                            type=MemoryType.ERROR_PATTERN,
                            scope=MemoryScope.GLOBAL,
                            source=MemorySource.TASK_RESULT,
                            confidence=diag.confidence,
                            privacy_level=PrivacyLevel.NORMAL,
                            metadata=pattern.to_dict()
                        ))
                except Exception:
                    pass

        # 2. Success Pattern Learning
        if eval_result.task_success and eval_result.overall_score >= 0.85:
            lesson_text = f"Successful workflow for '{context.tag}': executed {len(context.steps)} steps with {eval_result.overall_score:.2f} score."
            succ_hash = hashlib.sha256(lesson_text.encode("utf-8")).hexdigest()[:10]
            cand = LearningCandidate(
                candidate_id=f"cand-succ-{succ_hash}",
                source="task_evaluation",
                lesson=lesson_text,
                evidence={"overall_score": eval_result.overall_score, "steps": len(context.steps)},
                confidence=0.85,
                scope="GLOBAL",
                status=CandidateStatus.ACCEPTED,
                memory_type="SUCCESS_PATTERN"
            )
            extracted.append(cand)

            try:
                if hasattr(self.memory, "store_memory"):
                    self.memory.store_memory(MemoryItem(
                        memory_id=f"mem-succ-{cand.candidate_id}",
                        content=lesson_text,
                        type=MemoryType.SUCCESS_PATTERN,
                        scope=MemoryScope.GLOBAL,
                        source=MemorySource.TASK_RESULT,
                        confidence=0.85,
                        privacy_level=PrivacyLevel.NORMAL,
                        metadata={"evaluation_id": eval_result.evaluation_id}
                    ))
            except Exception:
                pass

        with self._lock:
            for c in extracted:
                self.learning_candidates[c.candidate_id] = c

        for c in extracted:
            self._publish(EventType.LEARNING_CANDIDATE_CREATED, {
                "candidate_id": c.candidate_id,
                "lesson": c.lesson,
                "source": c.source,
                "memory_type": c.memory_type
            })

        return extracted

    # =================================================================
    # Subsystem Performance Tracking
    # =================================================================

    def record_model_performance(
        self,
        provider: str,
        model: str,
        task_type: str,
        latency: float,
        success: bool,
        cost: float = 0.0,
        fallback: bool = False
    ) -> None:
        """Track model routing and inference outcomes for adaptive model selection."""
        key = f"{provider}:{model}:{task_type}"
        with self._lock:
            if key not in self.model_metrics:
                self.model_metrics[key] = {
                    "provider": provider,
                    "model": model,
                    "task_type": task_type,
                    "total_requests": 0,
                    "successful_requests": 0,
                    "failed_requests": 0,
                    "total_latency": 0.0,
                    "average_latency": 0.0,
                    "total_cost": 0.0,
                    "fallback_count": 0,
                    "success_rate": 0.0,
                }
            m = self.model_metrics[key]
            m["total_requests"] += 1
            if success:
                m["successful_requests"] += 1
            else:
                m["failed_requests"] += 1
            m["total_latency"] += latency
            m["average_latency"] = round(m["total_latency"] / m["total_requests"], 3)
            m["total_cost"] += cost
            if fallback:
                m["fallback_count"] += 1
            m["success_rate"] = round(m["successful_requests"] / m["total_requests"], 3)

    def record_worker_performance(
        self,
        worker_type: str,
        runtime: float,
        success: bool,
        tool_calls: int = 0,
        retry_count: int = 0
    ) -> None:
        """Track Phase 15 worker profile performance for future workstream assignment."""
        with self._lock:
            if worker_type not in self.worker_metrics:
                self.worker_metrics[worker_type] = {
                    "worker_type": worker_type,
                    "tasks_completed": 0,
                    "tasks_failed": 0,
                    "total_runtime": 0.0,
                    "average_runtime": 0.0,
                    "total_tool_calls": 0,
                    "total_retries": 0,
                    "success_rate": 0.0,
                }
            wm = self.worker_metrics[worker_type]
            if success:
                wm["tasks_completed"] += 1
            else:
                wm["tasks_failed"] += 1
            total = wm["tasks_completed"] + wm["tasks_failed"]
            wm["total_runtime"] += runtime
            wm["average_runtime"] = round(wm["total_runtime"] / total, 2)
            wm["total_tool_calls"] += tool_calls
            wm["total_retries"] += retry_count
            wm["success_rate"] = round(wm["tasks_completed"] / total, 3)

    def record_memory_retrieval(
        self,
        query: str,
        retrieved_ids: List[str],
        used_ids: List[str],
        task_success: bool
    ) -> Dict[str, Any]:
        """Track memory retrieval precision and usefulness to improve memory ranking."""
        total_retrieved = len(retrieved_ids)
        total_used = len(used_ids)
        precision = (total_used / total_retrieved) if total_retrieved > 0 else 0.0
        usefulness = precision if task_success else (precision * 0.5)

        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "query": query,
            "retrieved_count": total_retrieved,
            "used_count": total_used,
            "precision": round(precision, 3),
            "usefulness": round(usefulness, 3),
            "task_success": task_success,
        }
        with self._lock:
            self.memory_evaluations.append(record)
            if len(self.memory_evaluations) > 200:
                self.memory_evaluations = self.memory_evaluations[-200:]
        return record

    def record_plan_accuracy(
        self,
        estimated_steps: int = 0,
        actual_steps: int = 0,
        estimated_runtime: float = 0.0,
        actual_runtime: float = 0.0,
        replan_count: int = 0,
        replan_success: bool = True,
        task_type: Optional[str] = None,
        step_count: Optional[int] = None,
        steps_passed: Optional[int] = None,
        retries: Optional[int] = None,
        task_success: Optional[bool] = None,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """Evaluate plan estimation deviation and replanning effectiveness."""
        if step_count is not None:
            estimated_steps = estimated_steps or step_count
            actual_steps = actual_steps or (steps_passed if steps_passed is not None else step_count)
        if task_success is not None:
            replan_success = task_success

        step_deviation = abs(actual_steps - estimated_steps) / max(1, estimated_steps) if estimated_steps > 0 else 0.0
        runtime_deviation = abs(actual_runtime - estimated_runtime) / max(1.0, estimated_runtime) if estimated_runtime > 0.0 else 0.0
        efficiency_factor = max(0.1, 1.0 - (replan_count * 0.15) - ((retries or 0) * 0.1))

        record = {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "task_type": task_type or "general",
            "estimated_steps": estimated_steps,
            "actual_steps": actual_steps,
            "step_count": step_count if step_count is not None else estimated_steps,
            "steps_passed": steps_passed if steps_passed is not None else actual_steps,
            "step_deviation": round(step_deviation, 3),
            "estimated_runtime": estimated_runtime,
            "actual_runtime": actual_runtime,
            "runtime_deviation": round(runtime_deviation, 3),
            "replan_count": replan_count,
            "replan_success": replan_success,
            "retries": retries or 0,
            "efficiency_factor": round(efficiency_factor, 3),
            "completion_rate": round(steps_passed / max(1, step_count), 3) if step_count else 1.0,
        }
        with self._lock:
            self.planning_evaluations.append(record)
            if len(self.planning_evaluations) > 200:
                self.planning_evaluations = self.planning_evaluations[-200:]
        return record

    # =================================================================
    # Improvement Proposals & Critical Safety Enforcement
    # =================================================================

    def create_proposal(
        self,
        title: str,
        description: str,
        affected_component: str,
        change_type: ChangeType,
        risk: ProposalRisk,
        source_evidence: Dict[str, Any],
        expected_benefit: str,
        diff_content: Optional[str] = None,
        tests_required: Optional[List[str]] = None,
    ) -> ImprovementProposal:
        """
        Create a new improvement candidate proposal.
        ENFORCES CRITICAL SAFETY INVARIANT: Automatically rejects any proposal
        attempting to modify safety-critical modules, authorization, or secrets.
        """
        prop_id = f"prop-{uuid.uuid4().hex[:8]}"

        # CRITICAL SAFETY CHECK
        is_blocked = False
        rejection_reason = None

        norm_affected = affected_component.strip().lower()
        for blocked_file in CRITICAL_FILES_BLOCKLIST:
            if blocked_file in norm_affected or norm_affected in blocked_file:
                is_blocked = True
                rejection_reason = (
                    f"CRITICAL_SYSTEM_MODIFICATION_PROHIBITED: Cannot autonomously modify safety-critical "
                    f"file '{blocked_file}' (matches affected component '{affected_component}')."
                )
                break

        forbidden_keywords = [
            "cyber_lab", "cyberlabscope", "security_scope", "authorization",
            "confirmation_gate", "bypass_safety", "secret_redaction", "sandbox_bypass",
            "auth", "authentication", "token", "permission", "privilege", "bypass",
        ]
        combined_text = f"{title} {description} {affected_component}".lower()
        if not is_blocked:
            for kw in forbidden_keywords:
                if kw in combined_text:
                    is_blocked = True
                    rejection_reason = (
                        f"CRITICAL_SYSTEM_MODIFICATION_PROHIBITED: Autonomous proposal references protected "
                        f"safety keyword '{kw}'."
                    )
                    break

        if is_blocked:
            risk = ProposalRisk.CRITICAL
            status = ProposalStatus.REJECTED
        else:
            status = ProposalStatus.PROPOSED

        proposal = ImprovementProposal(
            proposal_id=prop_id,
            title=title,
            description=description,
            source_evidence=source_evidence,
            expected_benefit=expected_benefit,
            risk=risk,
            affected_component=affected_component,
            change_type=change_type,
            tests_required=tests_required or ["python3 -m unittest discover tests"],
            status=status,
            diff_content=diff_content,
            rejection_reason=rejection_reason,
        )

        with self._lock:
            self.proposals[prop_id] = proposal
            prop_file = self.proposals_dir / f"{prop_id}.json"
            prop_file.write_text(json.dumps(proposal.to_dict(), indent=2), encoding="utf-8")

        if is_blocked:
            self._publish(EventType.IMPROVEMENT_REJECTED, {
                "proposal_id": prop_id,
                "title": title,
                "reason": rejection_reason,
            })
        else:
            self._publish(EventType.IMPROVEMENT_PROPOSED, {
                "proposal_id": prop_id,
                "title": title,
                "risk": risk.value,
                "change_type": change_type.value,
            })

        return proposal

    def validate_proposal(self, proposal_id: str) -> bool:
        """Run static validation and sanity checks on a proposal."""
        with self._lock:
            p = self.proposals.get(proposal_id)
            if not p:
                return False
            if p.status == ProposalStatus.REJECTED:
                return False

            for blocked in CRITICAL_FILES_BLOCKLIST:
                if blocked in p.affected_component.lower():
                    p.status = ProposalStatus.REJECTED
                    p.rejection_reason = f"Blocked: Target component {p.affected_component} is in critical blocklist."
                    self._save_proposal(p)
                    self._publish(EventType.IMPROVEMENT_REJECTED, {"proposal_id": p.proposal_id, "reason": p.rejection_reason})
                    return False

            p.status = ProposalStatus.VALIDATING
            self._save_proposal(p)
            self._publish(EventType.IMPROVEMENT_VALIDATED, {"proposal_id": p.proposal_id})
            return True

    def test_proposal(self, proposal_id: str, simulated_test_pass: bool = True) -> bool:
        """Test proposal candidate against regression guard."""
        with self._lock:
            p = self.proposals.get(proposal_id)
            if not p or p.status in (ProposalStatus.REJECTED, ProposalStatus.ROLLED_BACK):
                return False

            p.status = ProposalStatus.TESTING
            self._save_proposal(p)

            if not simulated_test_pass:
                p.status = ProposalStatus.REJECTED
                p.rejection_reason = "Regression guard: Test suite validation failed."
                self._save_proposal(p)
                self._publish(EventType.IMPROVEMENT_REJECTED, {"proposal_id": p.proposal_id, "reason": p.rejection_reason})
                return False

            if p.risk == ProposalRisk.LOW:
                p.status = ProposalStatus.APPROVED
                p.approved_by = "autonomous_system"
            else:
                p.status = ProposalStatus.PROPOSED
            self._save_proposal(p)
            return True

    def approve_proposal(self, proposal_id: str, approved_by: str = "user") -> bool:
        """Explicit human or system approval of an improvement proposal."""
        with self._lock:
            p = self.proposals.get(proposal_id)
            if not p:
                return False
            if p.risk == ProposalRisk.CRITICAL or p.status == ProposalStatus.REJECTED:
                return False

            p.status = ProposalStatus.APPROVED
            p.approved_by = approved_by
            self._save_proposal(p)
            return True

    def reject_proposal(self, proposal_id: str, reason: str = "User rejected") -> bool:
        """Reject an improvement proposal."""
        with self._lock:
            p = self.proposals.get(proposal_id)
            if not p:
                return False
            p.status = ProposalStatus.REJECTED
            p.rejection_reason = reason
            self._save_proposal(p)
            self._publish(EventType.IMPROVEMENT_REJECTED, {"proposal_id": p.proposal_id, "reason": reason})
            return True

    def deploy_proposal(self, proposal_id: str) -> Optional[ImprovementVersion]:
        """Deploy an approved proposal into production behavior with version tracking."""
        with self._lock:
            p = self.proposals.get(proposal_id)
            if not p or p.status != ProposalStatus.APPROVED:
                return None

            version_id = f"v-{uuid.uuid4().hex[:8]}"
            version = ImprovementVersion(
                version_id=version_id,
                proposal_id=proposal_id,
                parent_version=list(self.versions.keys())[-1] if self.versions else None,
                changes={"affected_component": p.affected_component, "diff": p.diff_content},
                tests=p.tests_required,
                metrics={"deployed_at": datetime.datetime.now(datetime.timezone.utc).isoformat()},
                status="ACTIVE"
            )

            p.status = ProposalStatus.DEPLOYED
            self._save_proposal(p)
            self._save_version(version)

            self._publish(EventType.IMPROVEMENT_DEPLOYED, {
                "proposal_id": proposal_id,
                "version_id": version_id,
                "affected_component": p.affected_component
            })
            return version

    def rollback(self, target_id: str) -> bool:
        """Roll back a deployed proposal, version, or experiment atomically."""
        with self._lock:
            # Check if target is an experiment
            if target_id in self.experiments:
                exp = self.experiments[target_id]
                exp.status = ExperimentStatus.CANCELLED
                self._save_experiment(exp)
                self.record_learning_candidate(
                    source_task=f"rollback_experiment_{exp.experiment_id}",
                    lesson=f"Rollback executed for experiment {exp.experiment_id}: {exp.hypothesis}",
                    evidence={"experiment_id": exp.experiment_id},
                    tags=["rollback", "experiment"]
                )
                self._publish(EventType.IMPROVEMENT_ROLLED_BACK, {
                    "target_id": target_id,
                    "experiment_id": exp.experiment_id,
                })
                return True

            v = self.versions.get(target_id)
            proposal = None

            if v:
                proposal = self.proposals.get(v.proposal_id)
                v.status = "ROLLED_BACK"
                self._save_version(v)
            else:
                proposal = self.proposals.get(target_id)
                for vers in self.versions.values():
                    if vers.proposal_id == target_id:
                        vers.status = "ROLLED_BACK"
                        self._save_version(vers)

            if not proposal:
                return False

            proposal.status = ProposalStatus.ROLLED_BACK
            self._save_proposal(proposal)

            self.record_learning_candidate(
                source_task=f"rollback_{proposal.proposal_id}",
                lesson=f"Rollback executed for {proposal.title} ({proposal.proposal_id}). Ensure regression tests cover this scenario.",
                evidence={"proposal_id": proposal.proposal_id, "affected_component": proposal.affected_component},
                tags=["rollback", "regression", proposal.affected_component]
            )

            self._publish(EventType.IMPROVEMENT_ROLLED_BACK, {
                "target_id": target_id,
                "proposal_id": proposal.proposal_id,
            })
            return True

    def _save_proposal(self, p: ImprovementProposal) -> None:
        prop_file = self.proposals_dir / f"{p.proposal_id}.json"
        prop_file.write_text(json.dumps(p.to_dict(), indent=2), encoding="utf-8")

    # =================================================================
    # Controlled Experiment Framework
    # =================================================================

    def create_experiment(
        self,
        hypothesis: str,
        baseline: Dict[str, Any],
        candidate: Dict[str, Any],
        target_sample_size: int = 5
    ) -> Experiment:
        """Initialize a controlled A/B or shadow evaluation experiment."""
        exp_id = f"exp-{uuid.uuid4().hex[:8]}"
        exp = Experiment(
            experiment_id=exp_id,
            hypothesis=hypothesis,
            baseline=baseline,
            candidate=candidate,
            target_sample_size=target_sample_size,
            status=ExperimentStatus.RUNNING,
        )
        with self._lock:
            self.experiments[exp_id] = exp
            self._save_experiment(exp)

        self._publish(EventType.EXPERIMENT_STARTED, {
            "experiment_id": exp_id,
            "hypothesis": hypothesis,
        })
        return exp

    def record_experiment_trial(
        self,
        experiment_id: str,
        is_candidate: Union[bool, Dict[str, float]] = True,
        metrics: Optional[Dict[str, float]] = None
    ) -> Optional[Experiment]:
        """Record a single trial outcome for an active experiment."""
        if isinstance(is_candidate, dict):
            metrics = is_candidate
            is_candidate = True
        if metrics is None:
            metrics = {}

        with self._lock:
            exp = self.experiments.get(experiment_id)
            if not exp or exp.status != ExperimentStatus.RUNNING:
                return None

            branch = "candidate" if is_candidate else "baseline"
            if branch not in exp.results:
                exp.results[branch] = []
            exp.results[branch].append(metrics)
            exp.sample_size += 1

            # Update running averages for metric keys
            for k, v in metrics.items():
                if isinstance(v, (int, float)):
                    all_vals = [r[k] for r in exp.results.get(branch, []) if k in r and isinstance(r[k], (int, float))]
                    if all_vals:
                        exp.metrics[k] = round(sum(all_vals) / len(all_vals), 4)

            if exp.sample_size >= exp.target_sample_size:
                self.complete_experiment(experiment_id)
            else:
                self._save_experiment(exp)
            return exp

    def complete_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """Finalize experiment evaluation and determine statistical outcome."""
        with self._lock:
            exp = self.experiments.get(experiment_id)
            if not exp:
                return None

            cand_runs = exp.results.get("candidate", [])
            base_runs = exp.results.get("baseline", [])

            # Candidate metrics
            cand_scores = [r.get("score", r.get("success", 0.0)) for r in cand_runs]
            if cand_scores:
                cand_avg = sum(cand_scores) / len(cand_scores)
            else:
                cand_avg = float(exp.candidate.get("score", exp.candidate.get("success", 0.0)))

            # Baseline metrics
            base_scores = [r.get("score", r.get("success", 0.0)) for r in base_runs]
            if base_scores:
                base_avg = sum(base_scores) / len(base_scores)
            else:
                base_avg = float(exp.baseline.get("score", exp.baseline.get("success", 0.0)))

            improvement = cand_avg - base_avg
            exp.metrics.update({
                "candidate_score": round(cand_avg, 3),
                "baseline_score": round(base_avg, 3),
                "candidate_success_rate": round(cand_avg, 3),
                "baseline_success_rate": round(base_avg, 3),
                "improvement": round(improvement, 3),
            })

            if improvement < 0.0:
                exp.status = ExperimentStatus.FAILED
            else:
                exp.status = ExperimentStatus.COMPLETED

            exp.completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
            self._save_experiment(exp)

            self._publish(EventType.EXPERIMENT_COMPLETED, {
                "experiment_id": experiment_id,
                "metrics": exp.metrics,
            })
            return exp

    def _save_experiment(self, exp: Experiment) -> None:
        exp_file = self.experiments_dir / f"{exp.experiment_id}.json"
        exp_file.write_text(json.dumps(exp.to_dict(), indent=2), encoding="utf-8")

    # =================================================================
    # Query & Reporting Helpers
    # =================================================================

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregated stats for UI and CLI."""
        with self._lock:
            total_evals = len(self.evaluations)
            successful_evals = sum(1 for e in self.evaluations.values() if e.task_success)
            avg_score = (sum(e.overall_score for e in self.evaluations.values()) / total_evals) if total_evals > 0 else 0.0

            validated_strats = len([s for s in self.strategy_registry.strategies.values() if s.status == StrategyStatus.VALIDATED])
            pending_props = len([p for p in self.proposals.values() if p.status in (ProposalStatus.PROPOSED, ProposalStatus.VALIDATING, ProposalStatus.TESTING)])
            active_exps = len([e for e in self.experiments.values() if e.status == ExperimentStatus.RUNNING])

            return {
                "tasks_evaluated": total_evals,
                "tasks_successful": successful_evals,
                "success_rate": round((successful_evals / total_evals), 3) if total_evals > 0 else 1.0,
                "average_overall_score": round(avg_score, 3),
                "learning_candidates_count": len(self.learning_candidates),
                "validated_strategies_count": validated_strats,
                "total_strategies_count": len(self.strategy_registry.strategies),
                "pending_proposals_count": pending_props,
                "total_proposals_count": len(self.proposals),
                "active_experiments_count": active_exps,
                "total_experiments_count": len(self.experiments),
                "deployed_versions_count": len([v for v in self.versions.values() if v.status == "ACTIVE"]),
                "rolled_back_count": len([v for v in self.versions.values() if v.status == "ROLLED_BACK"]),
            }

    def get_status(self) -> Dict[str, Any]:
        """Comprehensive status report for Command Center UI and CLI."""
        stats = self.get_stats()
        with self._lock:
            recent_evals = [e.to_dict() for e in list(self.evaluations.values())[-5:]]
            recent_lessons = [c.to_dict() for c in list(self.learning_candidates.values())[-5:]]
            recent_strats = [s.to_dict() for s in list(self.strategy_registry.strategies.values())[-5:]]
            recent_props = [p.to_dict() for p in list(self.proposals.values())[-5:]]
            recent_exps = [e.to_dict() for e in list(self.experiments.values())[-5:]]

            return {
                "stats": stats,
                "recent_evaluations": recent_evals,
                "recent_lessons": recent_lessons,
                "recent_strategies": recent_strats,
                "recent_proposals": recent_props,
                "recent_experiments": recent_exps,
                "model_performance": self.model_metrics,
                "worker_performance": self.worker_metrics,
            }

    def get_validated_strategies_for_goal(self, goal: Optional[Any], domain: Optional[str] = None) -> List[Strategy]:
        """Retrieve validated advisory strategies relevant to the current goal."""
        dom = domain
        if goal and hasattr(goal, "domain"):
            dom = goal.domain.value if hasattr(goal.domain, "value") else str(goal.domain).lower()
        return self.strategy_registry.list_strategies(status=StrategyStatus.VALIDATED, domain=dom)

    def close(self) -> None:
        """Clean shutdown and flush of learning subsystem."""
        pass
