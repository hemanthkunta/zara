"""
State definitions and data models for ZARA's autonomous loop.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
import datetime

class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"

class ActionType(str, Enum):
    CODE = "code"
    EXECUTE = "execute"
    TEST = "test"
    SEARCH = "search"
    JOB_DRAFT = "job_draft"
    SECURITY_AUDIT = "security_audit"
    CONFIRMATION = "confirmation"

@dataclass
class PlanStep:
    id: int
    title: str
    action_type: ActionType
    description: str
    target: str
    payload: Dict[str, Any]
    success_condition: str
    status: StepStatus = StepStatus.PENDING
    attempts: int = 0
    actual_output: Optional[str] = None
    error_message: Optional[str] = None

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
    attempt: int
    failure_reason: str
    hypothesis: str
    proposed_fix: Dict[str, Any]

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
    tag: str
    working_dir: str
    past_lessons: List[str] = field(default_factory=list)
    steps: List[PlanStep] = field(default_factory=list)
    current_step_index: int = 0
    is_completed: bool = False
    requires_human_input: bool = False
    blocker_reason: Optional[str] = None
    diagnoses: List[Diagnosis] = field(default_factory=list)
    reflections: List[Reflection] = field(default_factory=list)
