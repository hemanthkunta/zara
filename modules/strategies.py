"""
ZARA Phase 17 — Strategy Registry Subsystem.
Provides a versioned, observable library of execution strategies across domains,
tracking outcome evidence, success rates, confidence, and lifecycle transitions.
"""
from __future__ import annotations

import datetime
import enum
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.settings import (
    STRATEGIES_FILE,
    STRATEGY_MIN_EVIDENCE_THRESHOLD,
    STRATEGY_VALIDATION_SUCCESS_RATE,
)
from core.observability import audit_logger


class StrategyStatus(str, enum.Enum):
    EXPERIMENTAL = "EXPERIMENTAL"
    VALIDATED = "VALIDATED"
    DEPRECATED = "DEPRECATED"
    BLOCKED = "BLOCKED"


class StrategyDomain(str, enum.Enum):
    CODING = "CODING"
    DEBUGGING = "DEBUGGING"
    RESEARCH = "RESEARCH"
    VISION = "VISION"
    GUI = "GUI"
    CYBER_LAB = "CYBER_LAB"
    BLENDER = "BLENDER"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    DOCUMENTATION = "DOCUMENTATION"
    GENERAL = "GENERAL"


@dataclass
class Strategy:
    strategy_id: str
    name: str
    description: str
    applicable_domains: List[str] = field(default_factory=list)
    conditions: Dict[str, Any] = field(default_factory=dict)
    steps: List[str] = field(default_factory=list)
    evidence_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    success_rate: float = 0.0
    confidence: float = 0.5
    status: StrategyStatus = StrategyStatus.EXPERIMENTAL
    version: int = 1
    history: List[Dict[str, Any]] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

    def record_outcome(self, success: bool, evidence: Optional[Dict[str, Any]] = None) -> None:
        """Record an execution outcome and update metrics and validation status."""
        self.evidence_count += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
        self.success_rate = round(self.success_count / self.evidence_count, 3)

        # Confidence scales with sample size and success rate
        sample_factor = min(1.0, self.evidence_count / 10.0)
        self.confidence = round(0.5 * sample_factor + 0.5 * self.success_rate * sample_factor, 3)

        self.history.append({
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "success": success,
            "evidence": evidence or {},
            "version": self.version,
            "success_rate": self.success_rate,
        })
        self.updated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # Validation check
        if (
            self.status == StrategyStatus.EXPERIMENTAL
            and self.evidence_count >= STRATEGY_MIN_EVIDENCE_THRESHOLD
            and self.success_rate >= STRATEGY_VALIDATION_SUCCESS_RATE
        ):
            self.status = StrategyStatus.VALIDATED
        elif (
            self.status == StrategyStatus.VALIDATED
            and self.evidence_count >= 5
            and self.success_rate < (STRATEGY_VALIDATION_SUCCESS_RATE - 0.15)
        ):
            self.status = StrategyStatus.DEPRECATED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "name": self.name,
            "description": self.description,
            "applicable_domains": list(self.applicable_domains),
            "conditions": dict(self.conditions),
            "steps": list(self.steps),
            "evidence_count": self.evidence_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "success_rate": self.success_rate,
            "confidence": self.confidence,
            "status": self.status.value if isinstance(self.status, StrategyStatus) else str(self.status),
            "version": self.version,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Strategy:
        st = data.get("status", StrategyStatus.EXPERIMENTAL.value)
        return cls(
            strategy_id=data["strategy_id"],
            name=data.get("name", ""),
            description=data.get("description", ""),
            applicable_domains=data.get("applicable_domains", []),
            conditions=data.get("conditions", {}),
            steps=data.get("steps", []),
            evidence_count=int(data.get("evidence_count", 0)),
            success_count=int(data.get("success_count", 0)),
            failure_count=int(data.get("failure_count", 0)),
            success_rate=float(data.get("success_rate", 0.0)),
            confidence=float(data.get("confidence", 0.5)),
            status=StrategyStatus(st) if isinstance(st, str) else st,
            version=int(data.get("version", 1)),
            history=data.get("history", []),
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
        )


class StrategyRegistry:
    """Thread-safe registry of versioned, observable execution strategies."""

    def __init__(self, storage_file: Path = STRATEGIES_FILE):
        self.storage_file = storage_file
        self._lock = threading.RLock()
        self.strategies: Dict[str, Strategy] = {}
        self._load()

    def _load(self) -> None:
        with self._lock:
            if not self.storage_file.exists():
                return
            try:
                data = json.loads(self.storage_file.read_text(encoding="utf-8"))
                for s_data in data:
                    strat = Strategy.from_dict(s_data)
                    self.strategies[strat.strategy_id] = strat
            except Exception as e:
                audit_logger.log_event("STRATEGY_REGISTRY_LOAD_FAILED", {"error": str(e)})

    def _save(self) -> None:
        with self._lock:
            try:
                self.storage_file.parent.mkdir(parents=True, exist_ok=True)
                serialized = [s.to_dict() for s in self.strategies.values()]
                temp_file = self.storage_file.with_suffix(".tmp")
                temp_file.write_text(json.dumps(serialized, indent=2), encoding="utf-8")
                temp_file.replace(self.storage_file)
            except Exception as e:
                audit_logger.log_event("STRATEGY_REGISTRY_SAVE_FAILED", {"error": str(e)})

    def register(self, strategy: Strategy) -> Strategy:
        with self._lock:
            self.strategies[strategy.strategy_id] = strategy
            self._save()
            return strategy

    def get(self, strategy_id: str) -> Optional[Strategy]:
        with self._lock:
            return self.strategies.get(strategy_id)

    def list_strategies(
        self,
        status: Optional[StrategyStatus] = None,
        domain: Optional[str] = None
    ) -> List[Strategy]:
        with self._lock:
            result = list(self.strategies.values())
            if status:
                result = [s for s in result if s.status == status]
            if domain:
                d_lower = domain.lower()
                result = [
                    s for s in result
                    if d_lower in [dom.lower() for dom in s.applicable_domains] or "general" in [dom.lower() for dom in s.applicable_domains]
                ]
            return result

    def record_outcome(
        self,
        strategy_id: str,
        success: bool,
        evidence: Optional[Dict[str, Any]] = None
    ) -> Optional[Strategy]:
        with self._lock:
            strat = self.strategies.get(strategy_id)
            if not strat:
                return None
            strat.record_outcome(success, evidence)
            self._save()
            return strat

    def deprecate(self, strategy_id: str, reason: str = "") -> bool:
        with self._lock:
            strat = self.strategies.get(strategy_id)
            if not strat:
                return False
            strat.status = StrategyStatus.DEPRECATED
            strat.history.append({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "action": "DEPRECATED",
                "reason": reason
            })
            self._save()
            return True

    def block(self, strategy_id: str, reason: str = "") -> bool:
        with self._lock:
            strat = self.strategies.get(strategy_id)
            if not strat:
                return False
            strat.status = StrategyStatus.BLOCKED
            strat.history.append({
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "action": "BLOCKED",
                "reason": reason
            })
            self._save()
            return True
