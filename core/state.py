"""
State definitions and data models for ZARA's autonomous loop.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import datetime
import time
from config.settings import RiskLevel

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"

class ActionType(str, Enum):
    TOOL = "tool"
    CODE = "code"
    EXECUTE = "execute"
    TEST = "test"
    SEARCH = "search"
    JOB_DRAFT = "job_draft"
    SECURITY_AUDIT = "security_audit"
    CONFIRMATION = "confirmation"
    BASH = "execute"

@dataclass
class PlanStep:
    id: int = 1
    title: str = ""
    action_type: ActionType = ActionType.EXECUTE
    description: str = ""
    target: str = ""
    step_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    success_condition: str = "Command exits with return code 0"
    tool: Optional[str] = None
    arguments: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[int] = field(default_factory=list)
    observation: Optional[Dict[str, Any]] = None
    verification: Optional[Dict[str, Any]] = None
    failure_type: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    retries: int = 0
    actual_output: Optional[str] = None
    error_message: Optional[str] = None

    def __post_init__(self):
        if self.step_id and not self.title:
            self.title = self.step_id
        if self.retries and not self.attempts:
            self.attempts = self.retries
        elif self.attempts and not self.retries:
            self.retries = self.attempts
        # Sync arguments and payload for backwards compatibility
        if self.arguments and not self.payload:
            self.payload = dict(self.arguments)
        elif self.payload and not self.arguments:
            self.arguments = dict(self.payload)

@dataclass
class ExecutionResult:
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float = 0.0
    command: Optional[str] = None

@dataclass
class Diagnosis:
    attempt: int = 1
    failure_reason: str = ""
    hypothesis: str = ""
    proposed_fix: Any = field(default_factory=dict)
    suggested_fix: Optional[str] = None
    root_cause_category: Optional[str] = None  # tool_arguments, command, code_logic, dependency, verification
    corrected_arguments: Optional[Dict[str, Any]] = None
    corrected_tool: Optional[str] = None
    failure_type: Optional[str] = None
    root_cause: Optional[str] = None
    affected_file: Optional[str] = None
    affected_line: Optional[int] = None
    explanation: Optional[str] = None
    recommended_action: Optional[str] = None
    confidence: float = 1.0

    def __post_init__(self):
        if not self.hypothesis:
            self.hypothesis = self.failure_reason
        if self.suggested_fix and not self.proposed_fix:
            self.proposed_fix = {"action": self.suggested_fix}
        elif not self.proposed_fix:
            self.proposed_fix = {"action": "retry"}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "failure_type": self.failure_type or self.root_cause_category or "unknown",
            "root_cause": self.root_cause or self.hypothesis,
            "affected_file": self.affected_file,
            "affected_line": self.affected_line,
            "explanation": self.explanation or self.hypothesis,
            "recommended_action": self.recommended_action or (self.proposed_fix.get("action") if isinstance(self.proposed_fix, dict) else str(self.proposed_fix)),
            "confidence": self.confidence,
            "attempt": self.attempt,
            "corrected_tool": self.corrected_tool,
            "corrected_arguments": self.corrected_arguments,
            "proposed_fix": self.proposed_fix
        }

@dataclass
class Reflection:
    task: str
    tag: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    approach: str = ""
    result: str = ""
    lesson: str = ""

    def to_markdown(self) -> str:
        return (
            f"## [{self.timestamp}] — [{self.tag}]\n"
            f"- Approach: {self.approach.strip()}\n"
            f"- Result: {self.result.strip()}\n"
            f"- Lesson: {self.lesson.strip()}\n"
            f"---\n\n"
        )

@dataclass
class TaskContext:
    task: str
    tag: str = "general"
    working_dir: str = "."
    past_lessons: List[str] = field(default_factory=list)
    steps: List[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    is_completed: bool = False
    requires_human_input: bool = False
    blocker_reason: Optional[str] = None
    diagnoses: List[Diagnosis] = field(default_factory=list)
    reflections: List[Reflection] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    total_retries: int = 0
    start_time: float = field(default_factory=time.time)
    # Phase 3 Coding & Debugging State
    files_inspected: List[str] = field(default_factory=list)
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)
    tests_discovered: List[str] = field(default_factory=list)
    tests_executed: List[str] = field(default_factory=list)
    patches_applied: List[Dict[str, Any]] = field(default_factory=list)
    # Phase 4 Autonomous Research & Browser State
    research_queries: List[str] = field(default_factory=list)
    sources: List["ResearchSource"] = field(default_factory=list)
    evidence: List["ResearchEvidence"] = field(default_factory=list)
    opened_urls: List[str] = field(default_factory=list)
    failed_sources: List[str] = field(default_factory=list)
    research_notes: List[str] = field(default_factory=list)
    source_conflicts: List["SourceConflict"] = field(default_factory=list)
    # Phase 14 Advanced Memory State
    relevant_memories: List[Any] = field(default_factory=list)
    source_relationships: Dict[str, List[str]] = field(default_factory=dict)
    research_report: Optional["ResearchReport"] = None
    # Phase 5 Visual Understanding & Computer Interaction State
    current_gui_state: Optional["GUIState"] = None
    screenshot_paths: List[str] = field(default_factory=list)
    pending_confirmation: Optional["PendingConfirmation"] = None

    def get_diff_summary(self) -> Dict[str, Any]:
        """Produce structured change and test execution summary."""
        return {
            "created": sorted(list(set(self.files_created))),
            "modified": sorted(list(set(self.files_modified))),
            "deleted": [],
            "tests_added": sorted(list(set([f for f in self.files_created if "test" in f.lower()]))),
            "tests_run": sorted(list(set(self.tests_executed))),
            "fixes": [d.proposed_fix for d in self.diagnoses if d.proposed_fix] or self.patches_applied
        }

    def add_source(
        self,
        source: Optional["ResearchSource"] = None,
        *,
        url: str = "",
        title: str = "",
        domain: str = "",
        reliability_score: float = 0.8,
        reliability: str = "primary",
        is_authoritative: bool = False,
        relevant_excerpt: str = "",
        content_length: int = 0,
        source_id: Optional[str] = None
    ) -> "ResearchSource":
        """Register a research source with deduplication by URL/source_id."""
        if source is None:
            sid = source_id or f"src_{len(self.sources) + 1:02d}"
            if not domain and url:
                parsed = urllib.parse.urlparse(url)
                domain = parsed.netloc
            source = ResearchSource(
                source_id=sid,
                url=url,
                title=title or domain or "Web Source",
                domain=domain,
                reliability=reliability,
                reliability_score=reliability_score,
                content_length=content_length,
                is_authoritative=is_authoritative,
                relevant_excerpt=relevant_excerpt
            )

        for existing in self.sources:
            if existing.url == source.url or existing.source_id == source.source_id:
                return existing

        self.sources.append(source)
        if source.url and source.url not in self.opened_urls:
            self.opened_urls.append(source.url)
        return source

    def add_evidence(
        self,
        ev: Optional["ResearchEvidence"] = None,
        *,
        source_id: str = "",
        claim: str = "",
        snippet: str = "",
        evidence: str = "",
        confidence: float = 1.0,
        verified: bool = True
    ) -> "ResearchEvidence":
        """Record evidence linked to a claim and source."""
        if ev is None:
            ev = ResearchEvidence(
                claim=claim,
                evidence=evidence or snippet,
                source_id=source_id,
                confidence=confidence,
                verified=verified
            )
        self.evidence.append(ev)
        return ev

    def get_source_by_id(self, source_id: str) -> Optional["ResearchSource"]:
        """Retrieve a registered source by its source_id or id."""
        for s in self.sources:
            if s.source_id == source_id or getattr(s, "id", None) == source_id:
                return s
        return None

    def validate_citations(self) -> tuple[bool, List[Dict[str, Any]]]:
        """Verify that every cited source_id in evidence corresponds to a real registered source."""
        registered_ids = {s.source_id for s in self.sources} | {getattr(s, "id", "") for s in self.sources}
        invalid_items = []
        for ev in self.evidence:
            if ev.source_id and ev.source_id not in registered_ids:
                invalid_items.append({"evidence": ev, "invalid_source_id": ev.source_id})
        return len(invalid_items) == 0, invalid_items


@dataclass
class ResearchSource:
    source_id: str
    url: str
    title: str
    domain: str
    retrieved_at: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    relevant_excerpt: str = ""
    reliability: str = "primary"  # authoritative, primary, secondary, unverified
    reliability_score: float = 0.8
    content_length: int = 0
    is_authoritative: bool = False

    @property
    def id(self) -> str:
        return self.source_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "url": self.url,
            "title": self.title,
            "domain": self.domain,
            "retrieved_at": self.retrieved_at,
            "relevant_excerpt": self.relevant_excerpt,
            "reliability": self.reliability,
            "reliability_score": self.reliability_score,
            "content_length": self.content_length,
            "is_authoritative": self.is_authoritative
        }


@dataclass
class ResearchEvidence:
    claim: str
    evidence: str
    source_id: str
    confidence: float = 1.0
    verified: bool = True

    @property
    def snippet(self) -> str:
        return self.evidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "evidence": self.evidence,
            "source_id": self.source_id,
            "confidence": self.confidence,
            "verified": self.verified
        }


@dataclass
class SourceConflict:
    claim: str
    source_a: str
    source_b: str
    difference: str
    resolution: str
    confidence: float = 0.5
    topic: str = ""
    conflicting_claims: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.topic:
            self.topic = self.claim
        if not self.conflicting_claims:
            self.conflicting_claims = [self.claim, self.difference]
        if not self.sources:
            self.sources = [self.source_a, self.source_b]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim": self.claim,
            "topic": self.topic,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "difference": self.difference,
            "resolution": self.resolution,
            "confidence": self.confidence,
            "conflicting_claims": self.conflicting_claims,
            "sources": self.sources
        }


@dataclass
class ResearchReport:
    question: str
    key_findings: List[str] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    sources: List[Dict[str, Any]] = field(default_factory=list)
    conflicts: List[Dict[str, Any]] = field(default_factory=list)
    conclusion: str = ""

    @property
    def summary(self) -> str:
        return self.conclusion or (self.key_findings[0] if self.key_findings else f"Research report on {self.question}")

    def to_markdown(self) -> str:
        md = [f"# Research Report: {self.question}\n"]
        md.append("## Key Findings")
        for finding in self.key_findings:
            md.append(f"- {finding}")
        md.append("\n## Evidence")
        for ev in self.evidence:
            claim = ev.get("claim", "")
            snippet = ev.get("evidence", "")
            sid = ev.get("source_id", "")
            md.append(f"- **{claim}** (Source: [{sid}]): \"{snippet}\"")
        md.append("\n## Sources")
        for src in self.sources:
            sid = src.get("source_id", "")
            title = src.get("title", "")
            url = src.get("url", "")
            domain = src.get("domain", "")
            reliability = src.get("reliability", "primary")
            md.append(f"- **[{sid}]** {title} — {url} (Domain: {domain}, Reliability: {reliability})")
        md.append("\n## Conflicts / Uncertainty")
        if self.conflicts:
            for c in self.conflicts:
                md.append(f"- Claim: {c.get('claim')}\n  Conflict between {c.get('source_a')} and {c.get('source_b')}: {c.get('difference')}\n  Resolution: {c.get('resolution')} (Confidence: {c.get('confidence')})")
        else:
            md.append("No material conflicts identified across sources.")
        md.append(f"\n## Conclusion\n{self.conclusion}\n")
        return "\n".join(md)


@dataclass
class GUIElement:
    type: str  # "button", "field", "text", "menu", "dialog", "icon", "window"
    label: str
    x: int
    y: int
    width: int = 0
    height: int = 0
    confidence: float = 1.0
    interactive: bool = True

    @property
    def center_x(self) -> int:
        return self.x + self.width // 2 if self.width else self.x

    @property
    def center_y(self) -> int:
        return self.y + self.height // 2 if self.height else self.y

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "confidence": self.confidence,
            "interactive": self.interactive
        }


@dataclass
class GUIState:
    application: str = "Desktop"
    window_title: str = ""
    elements: List[GUIElement] = field(default_factory=list)
    focused_element: Optional[str] = None
    alerts: List[str] = field(default_factory=list)
    screen_dimensions: Dict[str, int] = field(default_factory=lambda: {"width": 1920, "height": 1080})
    display_id: int = 1
    timestamp: str = field(default_factory=lambda: datetime.datetime.now().isoformat())
    untrusted_screen_text: str = ""

    def find_element(self, label: str, element_type: Optional[str] = None) -> Optional[GUIElement]:
        label_lower = label.lower()
        for el in self.elements:
            if element_type and el.type.lower() != element_type.lower():
                continue
            if label_lower in el.label.lower():
                return el
        return None

    def find_buttons(self) -> List[GUIElement]:
        return [el for el in self.elements if el.type.lower() == "button"]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "application": self.application,
            "window_title": self.window_title,
            "elements": [e.to_dict() for e in self.elements],
            "focused_element": self.focused_element,
            "alerts": self.alerts,
            "screen_dimensions": self.screen_dimensions,
            "display_id": self.display_id,
            "timestamp": self.timestamp,
            "untrusted_screen_text": self.untrusted_screen_text
        }


@dataclass
class PendingConfirmation:
    action_id: str
    tool: str
    arguments: Dict[str, Any]
    risk_level: RiskLevel
    description: str
    created_at: float = field(default_factory=time.time)
    confirmed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "tool": self.tool,
            "arguments": self.arguments,
            "risk_level": self.risk_level.value if isinstance(self.risk_level, RiskLevel) else str(self.risk_level),
            "description": self.description,
            "created_at": self.created_at,
            "confirmed": self.confirmed
        }


class VoiceState(Enum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    THINKING = "THINKING"
    ACTING = "ACTING"
    SPEAKING = "SPEAKING"
    INTERRUPTED = "INTERRUPTED"
    ERROR = "ERROR"


class VoiceCommandType(Enum):
    COMMAND = "COMMAND"
    QUESTION = "QUESTION"
    FOLLOW_UP = "FOLLOW_UP"
    CANCELLATION = "CANCELLATION"
    CONFIRMATION = "CONFIRMATION"


@dataclass
class TranscriptionResult:
    success: bool
    text: str
    confidence: float = 1.0
    duration_seconds: float = 0.0
    language: str = "en-US"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "text": self.text,
            "confidence": self.confidence,
            "duration_seconds": self.duration_seconds,
            "language": self.language,
            "error": self.error
        }


@dataclass
class AudioResult:
    success: bool
    audio_bytes: Optional[bytes] = None
    audio_path: Optional[str] = None
    duration_seconds: float = 0.0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "audio_path": self.audio_path,
            "duration_seconds": self.duration_seconds,
            "error": self.error
        }


@dataclass
class VoiceActivityResult:
    is_speech: bool
    energy: float = 0.0
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_speech": self.is_speech,
            "energy": self.energy,
            "confidence": self.confidence
        }


@dataclass
class VoiceClassificationResult:
    command_type: VoiceCommandType
    clean_text: str
    is_wake: bool = False
    confidence: float = 1.0
    requires_confirmation: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "command_type": self.command_type.value,
            "clean_text": self.clean_text,
            "is_wake": self.is_wake,
            "confidence": self.confidence,
            "requires_confirmation": self.requires_confirmation
        }
