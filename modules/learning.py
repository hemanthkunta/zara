"""
ZARA Phase 17 — Task Outcome Learning Subsystem.
Extracts structured lessons (experiences, success patterns, error patterns, user feedback)
and tracks subsystem performance observations across Model Router, Multi-Agent Workers,
Memory Retrieval, and Hierarchical Planning.
"""
from __future__ import annotations

import datetime
import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class CandidateStatus(str, enum.Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATING = "VALIDATING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


class UserFeedbackType(str, enum.Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    CORRECTION = "CORRECTION"
    PREFERENCE = "PREFERENCE"
    RATING = "RATING"


@dataclass
class UserFeedback:
    feedback_id: str
    task_id: Optional[str] = None
    type: UserFeedbackType = UserFeedbackType.POSITIVE
    raw_text: str = ""
    rating: Optional[float] = None  # Normalized 0.0 to 1.0
    correction: Optional[str] = None
    structured_tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feedback_id": self.feedback_id,
            "task_id": self.task_id,
            "type": self.type.value if isinstance(self.type, UserFeedbackType) else str(self.type),
            "raw_text": self.raw_text,
            "rating": round(self.rating, 3) if self.rating is not None else None,
            "correction": self.correction,
            "structured_tags": self.structured_tags,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> UserFeedback:
        ftype = data.get("type", UserFeedbackType.POSITIVE.value)
        return cls(
            feedback_id=data["feedback_id"],
            task_id=data.get("task_id"),
            type=UserFeedbackType(ftype) if isinstance(ftype, str) else ftype,
            raw_text=data.get("raw_text", ""),
            rating=float(data["rating"]) if data.get("rating") is not None else None,
            correction=data.get("correction"),
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )


@dataclass
class LearningCandidate:
    candidate_id: str
    source: str  # task_evaluation, user_feedback, failure_diagnosis, worker_performance
    lesson: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.85
    scope: str = "GLOBAL"  # GLOBAL, PROJECT, TASK, DOMAIN
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    status: CandidateStatus = CandidateStatus.CANDIDATE
    memory_type: str = "EXPERIENCE"  # EXPERIENCE, ERROR_PATTERN, SUCCESS_PATTERN, USER_FEEDBACK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "source": self.source,
            "lesson": self.lesson,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 3),
            "scope": self.scope,
            "created_at": self.created_at,
            "status": self.status.value if isinstance(self.status, CandidateStatus) else str(self.status),
            "memory_type": self.memory_type,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> LearningCandidate:
        st = data.get("status", CandidateStatus.CANDIDATE.value)
        return cls(
            candidate_id=data["candidate_id"],
            source=data.get("source", "task_evaluation"),
            lesson=data.get("lesson", ""),
            evidence=data.get("evidence", {}),
            confidence=float(data.get("confidence", 0.85)),
            scope=data.get("scope", "GLOBAL"),
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            status=CandidateStatus(st) if isinstance(st, str) else st,
            memory_type=data.get("memory_type", "EXPERIENCE"),
        )


@dataclass
class FailurePattern:
    failure_type: str
    root_cause: str
    context: Dict[str, Any]
    successful_recovery: Optional[str] = None
    confidence: float = 0.8
    frequency: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FailurePattern:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ModelPerformanceObservation:
    provider: str
    model: str
    task_type: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency: float = 0.0
    average_latency: float = 0.0
    total_cost: float = 0.0
    fallback_count: int = 0
    success_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerPerformanceObservation:
    worker_type: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_runtime: float = 0.0
    average_runtime: float = 0.0
    total_tool_calls: int = 0
    total_retries: int = 0
    success_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PlannerPerformanceObservation:
    task_domain: str
    step_count: int
    dependency_depth: int
    replan_count: int
    success: bool
    runtime: float
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
