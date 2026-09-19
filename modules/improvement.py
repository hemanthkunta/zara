"""
ZARA Phase 17 — Improvement Proposal Subsystem.
Defines risk-classified improvement proposals, safety review invariants,
required test gates, and version records.
"""
from __future__ import annotations

import datetime
import enum
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class ChangeType(str, enum.Enum):
    CONFIGURATION = "CONFIGURATION"
    PROMPT_TEMPLATE = "PROMPT_TEMPLATE"
    ROUTING_POLICY = "ROUTING_POLICY"
    RETRIEVAL_POLICY = "RETRIEVAL_POLICY"
    PLANNING_HEURISTIC = "PLANNING_HEURISTIC"
    WORKER_ASSIGNMENT = "WORKER_ASSIGNMENT"
    UI = "UI"
    DOCUMENTATION = "DOCUMENTATION"
    CODE = "CODE"
    WORKFLOW = "WORKFLOW"


class ProposalRisk(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ProposalStatus(str, enum.Enum):
    PROPOSED = "PROPOSED"
    VALIDATING = "VALIDATING"
    TESTING = "TESTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEPLOYED = "DEPLOYED"
    ROLLED_BACK = "ROLLED_BACK"


@dataclass
class ImprovementProposal:
    proposal_id: str
    title: str
    description: str
    source_evidence: Dict[str, Any]
    expected_benefit: str
    risk: ProposalRisk
    affected_component: str
    change_type: ChangeType
    tests_required: List[str] = field(default_factory=list)
    status: ProposalStatus = ProposalStatus.PROPOSED
    diff_content: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    approved_by: Optional[str] = None
    rejection_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "title": self.title,
            "description": self.description,
            "source_evidence": self.source_evidence,
            "expected_benefit": self.expected_benefit,
            "risk": self.risk.value if isinstance(self.risk, ProposalRisk) else str(self.risk),
            "affected_component": self.affected_component,
            "change_type": self.change_type.value if isinstance(self.change_type, ChangeType) else str(self.change_type),
            "tests_required": list(self.tests_required),
            "status": self.status.value if isinstance(self.status, ProposalStatus) else str(self.status),
            "diff_content": self.diff_content,
            "created_at": self.created_at,
            "approved_by": self.approved_by,
            "rejection_reason": self.rejection_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ImprovementProposal:
        risk_val = data.get("risk", ProposalRisk.MEDIUM.value)
        ctype_val = data.get("change_type", ChangeType.CONFIGURATION.value)
        status_val = data.get("status", ProposalStatus.PROPOSED.value)
        return cls(
            proposal_id=data["proposal_id"],
            title=data.get("title", ""),
            description=data.get("description", ""),
            source_evidence=data.get("source_evidence", {}),
            expected_benefit=data.get("expected_benefit", ""),
            risk=ProposalRisk(risk_val) if isinstance(risk_val, str) else risk_val,
            affected_component=data.get("affected_component", ""),
            change_type=ChangeType(ctype_val) if isinstance(ctype_val, str) else ctype_val,
            tests_required=data.get("tests_required", []),
            status=ProposalStatus(status_val) if isinstance(status_val, str) else status_val,
            diff_content=data.get("diff_content"),
            created_at=data.get("created_at", datetime.datetime.now(datetime.timezone.utc).isoformat()),
            approved_by=data.get("approved_by"),
            rejection_reason=data.get("rejection_reason"),
        )


@dataclass
class ImprovementVersion:
    version_id: str
    proposal_id: str
    parent_version: Optional[str]
    changes: Dict[str, Any]
    tests: List[str]
    metrics: Dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    status: str = "ACTIVE"  # ACTIVE, ROLLED_BACK
    rollback_target: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ImprovementVersion:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
