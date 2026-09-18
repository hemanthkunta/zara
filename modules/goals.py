"""ZARA Phase 11 - Goal Understanding, Ambiguity Detection & Requirements Extraction.

Transforms unstructured user requests into structured, auditable Goal models with
explicit requirements, constraints, assumptions, success criteria, and ambiguity detection.
"""

from __future__ import annotations

import enum
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class GoalDomain(str, enum.Enum):
    CODING = "CODING"
    BLENDER = "BLENDER"
    CYBERSECURITY = "CYBERSECURITY"
    RESEARCH = "RESEARCH"
    MAC_CONTROL = "MAC_CONTROL"
    SYSTEM = "SYSTEM"
    GENERAL = "GENERAL"


class AmbiguityLevel(str, enum.Enum):
    NONE = "NONE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RequirementType(str, enum.Enum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    SAFETY = "SAFETY"
    TECHNICAL = "TECHNICAL"
    RESOURCE = "RESOURCE"


class ConstraintType(str, enum.Enum):
    SAFETY = "SAFETY"
    AUTHORIZATION = "AUTHORIZATION"
    USER = "USER"
    TIME = "TIME"
    RESOURCE = "RESOURCE"
    TECHNICAL = "TECHNICAL"
    ENVIRONMENT = "ENVIRONMENT"
    BUDGET = "BUDGET"


@dataclass
class Requirement:
    id: str
    text: str
    type: RequirementType = RequirementType.USER
    priority: str = "HIGH"  # HIGH, MEDIUM, LOW
    mandatory: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "type": self.type.value if isinstance(self.type, RequirementType) else str(self.type),
            "priority": self.priority,
            "mandatory": self.mandatory,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Requirement:
        req_type = data.get("type", RequirementType.USER.value)
        if isinstance(req_type, str):
            try:
                req_type = RequirementType(req_type)
            except ValueError:
                req_type = RequirementType.USER
        return cls(
            id=data.get("id", f"req-{uuid.uuid4().hex[:6]}"),
            text=data.get("text", ""),
            type=req_type,
            priority=data.get("priority", "HIGH"),
            mandatory=data.get("mandatory", True),
        )


@dataclass
class Assumption:
    id: str
    statement: str
    source: str = "system_inference"  # system_inference, user_context, environment
    confidence: str = "HIGH"          # HIGH, MEDIUM, LOW
    reversible: bool = True
    verified: bool = False
    status: str = "PENDING"           # PENDING, VERIFIED, INVALIDATED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "source": self.source,
            "confidence": self.confidence,
            "reversible": self.reversible,
            "verified": self.verified,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Assumption:
        return cls(
            id=data.get("id", f"asm-{uuid.uuid4().hex[:6]}"),
            statement=data.get("statement", ""),
            source=data.get("source", "system_inference"),
            confidence=data.get("confidence", "HIGH"),
            reversible=data.get("reversible", True),
            verified=data.get("verified", False),
            status=data.get("status", "PENDING"),
        )


@dataclass
class Constraint:
    id: str
    type: ConstraintType
    value: Any
    source: str = "system_default"  # system_default, user_prompt, safety_policy
    priority: str = "HIGH"
    enforced: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value if isinstance(self.type, ConstraintType) else str(self.type),
            "value": self.value,
            "source": self.source,
            "priority": self.priority,
            "enforced": self.enforced,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Constraint:
        ctype = data.get("type", ConstraintType.SAFETY.value)
        if isinstance(ctype, str):
            try:
                ctype = ConstraintType(ctype)
            except ValueError:
                ctype = ConstraintType.SAFETY
        return cls(
            id=data.get("id", f"cst-{uuid.uuid4().hex[:6]}"),
            type=ctype,
            value=data.get("value"),
            source=data.get("source", "system_default"),
            priority=data.get("priority", "HIGH"),
            enforced=data.get("enforced", True),
        )


@dataclass
class SuccessCriterion:
    id: str
    description: str
    verification_method: str = "execution_check"  # run_tests, file_exists, scene_rendered, scope_verified, etc.
    required: bool = True
    status: str = "PENDING"  # PENDING, PASSED, FAILED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "verification_method": self.verification_method,
            "required": self.required,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SuccessCriterion:
        return cls(
            id=data.get("id", f"crit-{uuid.uuid4().hex[:6]}"),
            description=data.get("description", ""),
            verification_method=data.get("verification_method", "execution_check"),
            required=data.get("required", True),
            status=data.get("status", "PENDING"),
        )


@dataclass
class Goal:
    goal_id: str
    raw_request: str
    normalized_goal: str
    domain: GoalDomain = GoalDomain.GENERAL
    desired_outcome: str = ""
    requirements: List[Requirement] = field(default_factory=list)
    assumptions: List[Assumption] = field(default_factory=list)
    constraints: List[Constraint] = field(default_factory=list)
    preferences: Dict[str, Any] = field(default_factory=dict)
    success_criteria: List[SuccessCriterion] = field(default_factory=list)
    ambiguity_level: AmbiguityLevel = AmbiguityLevel.NONE
    clarification_needed: bool = False
    clarification_question: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal_id": self.goal_id,
            "raw_request": self.raw_request,
            "normalized_goal": self.normalized_goal,
            "domain": self.domain.value if isinstance(self.domain, GoalDomain) else str(self.domain),
            "desired_outcome": self.desired_outcome,
            "requirements": [r.to_dict() for r in self.requirements],
            "assumptions": [a.to_dict() for a in self.assumptions],
            "constraints": [c.to_dict() for c in self.constraints],
            "preferences": self.preferences,
            "success_criteria": [s.to_dict() for s in self.success_criteria],
            "ambiguity_level": self.ambiguity_level.value if isinstance(self.ambiguity_level, AmbiguityLevel) else str(self.ambiguity_level),
            "clarification_needed": self.clarification_needed,
            "clarification_question": self.clarification_question,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Goal:
        domain = data.get("domain", GoalDomain.GENERAL.value)
        if isinstance(domain, str):
            try:
                domain = GoalDomain(domain)
            except ValueError:
                domain = GoalDomain.GENERAL

        ambiguity = data.get("ambiguity_level", AmbiguityLevel.NONE.value)
        if isinstance(ambiguity, str):
            try:
                ambiguity = AmbiguityLevel(ambiguity)
            except ValueError:
                ambiguity = AmbiguityLevel.NONE

        return cls(
            goal_id=data.get("goal_id", f"goal-{uuid.uuid4().hex[:8]}"),
            raw_request=data.get("raw_request", ""),
            normalized_goal=data.get("normalized_goal", ""),
            domain=domain,
            desired_outcome=data.get("desired_outcome", ""),
            requirements=[Requirement.from_dict(r) for r in data.get("requirements", [])],
            assumptions=[Assumption.from_dict(a) for a in data.get("assumptions", [])],
            constraints=[Constraint.from_dict(c) for c in data.get("constraints", [])],
            preferences=data.get("preferences", {}),
            success_criteria=[SuccessCriterion.from_dict(s) for s in data.get("success_criteria", [])],
            ambiguity_level=ambiguity,
            clarification_needed=data.get("clarification_needed", False),
            clarification_question=data.get("clarification_question"),
            confidence=float(data.get("confidence", 1.0)),
        )


class GoalParser:
    """Deterministic and pattern-based goal parser with ambiguity and requirement extraction."""

    @staticmethod
    def normalize_request(request: str) -> str:
        """Strip redundant whitespace, normalize punctuation and common prefixes."""
        normalized = request.strip()
        # Remove polite conversational openers if any
        normalized = re.sub(r"^(please[,\s]*|can\s+you\s+|could\s+you\s+|zara[,\s]*|jarvis[,\s]*)+", "", normalized, flags=re.IGNORECASE).strip()
        # Collapse multiple spaces
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    @classmethod
    def detect_domain(cls, request: str) -> GoalDomain:
        req_lower = request.lower()
        if any(w in req_lower for w in ["blender", "render", "3d", "suzanne", "forest scene", "mesh", "procedural terrain"]):
            return GoalDomain.BLENDER
        if any(w in req_lower for w in ["dvwa", "nmap", "nikto", "zap", "security assessment", "vulnerability scan", "penetration test", "cyber lab", "exploit", "cve", "scan this server", "vulnerabilit", "port scan"]):
            return GoalDomain.CYBERSECURITY
        if any(w in req_lower for w in ["write code", "implement", "refactor", "unit test", "test suite", "run test", "bug fix", "debug", "python script", "function", "class", "patch code", "build module", "repository"]):
            return GoalDomain.CODING
        if any(w in req_lower for w in ["research", "summarize", "find latest", "papers", "arxiv", "web search", "investigate", "look up"]):
            return GoalDomain.RESEARCH
        if any(w in req_lower for w in ["click", "screen", "window", "application", "keyboard", "macos", "open app"]):
            return GoalDomain.MAC_CONTROL
        if any(w in req_lower for w in ["disk space", "system info", "cpu", "memory usage", "clean cache"]):
            return GoalDomain.SYSTEM
        return GoalDomain.GENERAL

    @classmethod
    def detect_ambiguity(cls, request: str, domain: GoalDomain) -> tuple[AmbiguityLevel, bool, Optional[str]]:
        """Detect goal underspecification and determine if clarification is required."""
        req_lower = request.lower().strip()

        # Very vague / underspecified requests
        if len(req_lower.split()) < 3 and req_lower in ["deploy", "fix it", "scan", "test", "run", "do it", "make it work"]:
            return AmbiguityLevel.CRITICAL, True, f"Your goal '{request}' is too brief. What specific target or application should be targeted?"

        # Domain-specific ambiguity checks
        if domain == GoalDomain.CYBERSECURITY:
            # Check if a target or scope is mentioned
            has_target = any(t in req_lower for t in ["dvwa", "localhost", "127.0.0.1", "192.168.", "test-server", "http://", "https://", "target:"])
            if not has_target and any(w in req_lower for w in ["scan this server", "pentest", "vulnerability scan", "security audit", "vulnerabilit"]):
                return AmbiguityLevel.HIGH, True, "Which specific target host or authorized URL should be scanned?"

        if domain == GoalDomain.CODING:
            if req_lower in ["deploy this application", "build the app", "make the software", "fix the bug"]:
                return AmbiguityLevel.HIGH, True, "Could you specify which repository, language, or file path you want to work on?"

        # Moderate ambiguity
        if any(w in req_lower for w in ["create a blender forest", "make a 3d scene"]):
            return AmbiguityLevel.LOW, False, None

        if len(req_lower.split()) <= 4:
            return AmbiguityLevel.MEDIUM, False, None

        return AmbiguityLevel.NONE, False, None

    @classmethod
    def parse_goal(cls, raw_request: str, project_id: Optional[str] = None) -> Goal:
        """Parse raw user prompt into a structured Goal representation."""
        normalized = cls.normalize_request(raw_request)
        domain = cls.detect_domain(normalized)
        ambiguity_level, clarification_needed, clarification_q = cls.detect_ambiguity(normalized, domain)

        goal_id = f"goal-{uuid.uuid4().hex[:8]}"
        desired_outcome = normalized

        requirements: List[Requirement] = []
        assumptions: List[Assumption] = []
        constraints: List[Constraint] = []
        success_criteria: List[SuccessCriterion] = []

        # 1. Base User Requirement
        requirements.append(
            Requirement(
                id=f"req-{uuid.uuid4().hex[:6]}",
                text=f"Fulfill objective: {normalized}",
                type=RequirementType.USER,
                priority="HIGH",
                mandatory=True,
            )
        )

        # 2. Domain-Specific Requirements, Constraints, Assumptions & Criteria
        if domain == GoalDomain.BLENDER:
            desired_outcome = f"Render and verify 3D scene: {normalized}"
            requirements.extend([
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Generate Blender procedural script", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Perform headless render to image artifact", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Verify rendered image artifact exists and is non-empty", type=RequirementType.SAFETY, priority="HIGH"),
            ])
            constraints.extend([
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.ENVIRONMENT, value="blender_headless", source="system_policy", enforced=True),
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.SAFETY, value="stay_inside_workspace", source="safety_policy", enforced=True),
            ])
            assumptions.append(
                Assumption(id=f"asm-{uuid.uuid4().hex[:6]}", statement="Blender 3D executable is installed and available", source="system_check", confidence="HIGH", reversible=True)
            )
            success_criteria.extend([
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Blender script executes without Python exceptions", verification_method="execution_check", required=True),
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Output render image file exists in workspace", verification_method="file_exists", required=True),
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Rendered scene passes visual inspection", verification_method="vision_verification", required=False),
            ])

        elif domain == GoalDomain.CYBERSECURITY:
            desired_outcome = f"Conduct authorized security assessment: {normalized}"
            requirements.extend([
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Validate target scope against authorized lab targets", type=RequirementType.SAFETY, priority="HIGH", mandatory=True),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Execute scoped security scans without destructive payloads", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Collect evidence and generate structured report", type=RequirementType.USER, priority="HIGH"),
            ])
            constraints.extend([
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.AUTHORIZATION, value="allowlisted_targets_only", source="safety_policy", priority="HIGH", enforced=True),
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.SAFETY, value="no_destructive_exploits", source="safety_policy", priority="HIGH", enforced=True),
            ])
            assumptions.append(
                Assumption(id=f"asm-{uuid.uuid4().hex[:6]}", statement="Target is an authorized lab environment (e.g. DVWA)", source="scope_policy", confidence="MEDIUM", reversible=True)
            )
            success_criteria.extend([
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Target passes CyberLabScope allowlist validation", verification_method="scope_verified", required=True),
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Structured findings and evidence generated", verification_method="findings_check", required=True),
            ])

        elif domain == GoalDomain.CODING:
            desired_outcome = f"Complete code implementation and verification: {normalized}"
            requirements.extend([
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Implement required code changes", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Pass static syntax and AST validation", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Run automated test suite and achieve 0 failures", type=RequirementType.SAFETY, priority="HIGH"),
            ])
            constraints.extend([
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.TECHNICAL, value="pass_all_tests", source="engineering_standard", enforced=True),
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.BUDGET, value={"max_retries": 3}, source="system_policy", enforced=True),
            ])
            assumptions.append(
                Assumption(id=f"asm-{uuid.uuid4().hex[:6]}", statement="Project test suite can be run automatically", source="project_inspection", confidence="HIGH", reversible=True)
            )
            success_criteria.extend([
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Code passes AST and syntax validation", verification_method="ast_validation", required=True),
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Test suite passes with 0 failures", verification_method="run_tests", required=True),
            ])

        elif domain == GoalDomain.RESEARCH:
            desired_outcome = f"Synthesize evidence-backed research report: {normalized}"
            requirements.extend([
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Query verified sources and extract factual evidence", type=RequirementType.TECHNICAL, priority="HIGH"),
                Requirement(id=f"req-{uuid.uuid4().hex[:6]}", text="Provide verifiable citations for factual claims", type=RequirementType.USER, priority="HIGH"),
            ])
            constraints.extend([
                Constraint(id=f"cst-{uuid.uuid4().hex[:6]}", type=ConstraintType.BUDGET, value={"max_queries": 5}, source="system_budget", enforced=True),
            ])
            assumptions.append(
                Assumption(id=f"asm-{uuid.uuid4().hex[:6]}", statement="Web search or knowledge retrieval is reachable", source="network_check", confidence="HIGH", reversible=True)
            )
            success_criteria.append(
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Research summary includes source citations", verification_method="citation_check", required=True)
            )

        else:
            # GENERAL
            desired_outcome = normalized
            success_criteria.append(
                SuccessCriterion(id=f"crit-{uuid.uuid4().hex[:6]}", description="Task executed and outcome observed", verification_method="execution_check", required=True)
            )

        confidence = 1.0
        if ambiguity_level == AmbiguityLevel.CRITICAL:
            confidence = 0.2
        elif ambiguity_level == AmbiguityLevel.HIGH:
            confidence = 0.5
        elif ambiguity_level == AmbiguityLevel.MEDIUM:
            confidence = 0.8

        return Goal(
            goal_id=goal_id,
            raw_request=raw_request,
            normalized_goal=normalized,
            domain=domain,
            desired_outcome=desired_outcome,
            requirements=requirements,
            assumptions=assumptions,
            constraints=constraints,
            success_criteria=success_criteria,
            ambiguity_level=ambiguity_level,
            clarification_needed=clarification_needed,
            clarification_question=clarification_q,
            confidence=confidence,
        )
