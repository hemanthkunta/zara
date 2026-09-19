"""
ZARA Phase 17 — Controlled Experiment Subsystem.
Defines bounded, repeatable, observable, and reversible A/B experiment trials
with automated regression detection and baseline state recovery.
"""
from __future__ import annotations

import datetime
import enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class ExperimentStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class Experiment:
    experiment_id: str
    hypothesis: str
    baseline: Dict[str, Any]
    candidate: Dict[str, Any]
    metrics: Dict[str, float] = field(default_factory=dict)
    sample_size: int = 0
    target_sample_size: int = 5
    results: Dict[str, Any] = field(default_factory=dict)
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    completed_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "hypothesis": self.hypothesis,
            "baseline": self.baseline,
            "candidate": self.candidate,
            "metrics": self.metrics,
            "sample_size": self.sample_size,
            "target_sample_size": self.target_sample_size,
            "results": self.results,
            "status": self.status.value if isinstance(self.status, ExperimentStatus) else str(self.status),
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Experiment:
        st = data.get("status", ExperimentStatus.PROPOSED.value)
        return cls(
            experiment_id=data["experiment_id"],
            hypothesis=data.get("hypothesis", ""),
            baseline=data.get("baseline", {}),
            candidate=data.get("candidate", {}),
            metrics=data.get("metrics", {}),
            sample_size=int(data.get("sample_size", 0)),
            target_sample_size=int(data.get("target_sample_size", 5)),
            results=data.get("results", {}),
            status=ExperimentStatus(st) if isinstance(st, str) else st,
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            completed_at=data.get("completed_at"),
        )
