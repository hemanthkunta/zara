"""
ZARA Core Engine: 8-Stage Autonomous Looping State Machine.
Perceive -> Plan -> Act -> Verify -> Diagnose & Retry -> Reflect -> Persist -> Continue/Report
"""
import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable

from config.settings import (
    BASE_DIR,
    MAX_DIAGNOSE_RETRIES,
    ENABLE_VOICE
)
from core.state import (
    TaskContext,
    PlanStep,
    StepStatus,
    ActionType,
    ExecutionResult,
    Diagnosis,
    Reflection
)
from brain.router import LLMRouter
from tools.registry import ToolRegistry
from tools.filesystem import ReadFileTool, WriteFileTool, PatchFileTool, ListDirTool
from tools.terminal import TerminalExecutionTool, TestRunnerTool
from tools.macos_control import MacOSNotificationTool, MacOSClipboardTool, MacOSScreenshotTool
from modules.memory import MemoryStore
from modules.execution import ExecutionEngine
from modules.coding import CodingModule
from modules.debugging import DebuggingModule
from modules.voice import VoiceSynthesizer
from modules.security import SecurityModule, ScopeViolationError
from modules.job_hunter import JobHunterModule
from modules.orchestrator import TaskOrchestrator
from modules.self_improvement import SelfImprovementEvaluator
from modules.verification import VerificationEngine
from core.recovery import RecoveryManager
from core.observability import audit_logger

class ZaraEngine:
    def __init__(
        self,
        workspace_root: str = str(BASE_DIR),
        use_docker: bool = False,
        enable_voice: bool = ENABLE_VOICE,
        on_step_update: Optional[Callable[[str, PlanStep], None]] = None
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.use_docker = use_docker
        self.on_step_update = on_step_update

        # Subsystems
        self.brain = LLMRouter()
        self.memory = MemoryStore()
        self.execution = ExecutionEngine(str(self.workspace_root), use_docker=use_docker)
        self.coding = CodingModule(str(self.workspace_root))
        self.debugging = DebuggingModule()
        self.voice = VoiceSynthesizer(enabled=enable_voice)
        self.security = SecurityModule()
        self.job_hunter = JobHunterModule()
        self.orchestrator = TaskOrchestrator()
        self.verification = VerificationEngine(self.workspace_root)
        self.recovery = RecoveryManager()
        self.self_improvement = SelfImprovementEvaluator(self.memory)

        # Initialize Tool Registry
        self.tools = ToolRegistry()
        self._register_default_tools()

    def _register_default_tools(self) -> None:
        self.tools.register(ReadFileTool(self.workspace_root))
        self.tools.register(WriteFileTool(self.workspace_root))
        self.tools.register(PatchFileTool(self.workspace_root))
        self.tools.register(ListDirTool(self.workspace_root))
        self.tools.register(TerminalExecutionTool(self.workspace_root, use_docker=self.use_docker))
        self.tools.register(TestRunnerTool(self.workspace_root))
        self.tools.register(MacOSNotificationTool())
        self.tools.register(MacOSClipboardTool())
        self.tools.register(MacOSScreenshotTool())

    # 1. PERCEIVE
    def perceive(self, task: str, tag: str = "dev") -> TaskContext:
        """Read task, query memory for prior lessons, and inspect repo state."""
        self.voice.speak(f"Perceiving task: {task[:60]}")
        past_lessons_raw = self.memory.search_lessons(f"{task} {tag}", limit=3)
        past_lessons = [
            f"[{entry['header']}] Lesson: {entry['lesson']}" for entry in past_lessons_raw if entry.get("lesson")
        ]

        context = TaskContext(
            task=task,
            tag=tag,
            working_dir=str(self.workspace_root),
            past_lessons=past_lessons
        )
        audit_logger.log_event("LOOP_PERCEIVE", action="perceive", extra={"task": task, "tag": tag})
        return context

    # 2. PLAN
    def plan(self, context: TaskContext, custom_steps: Optional[List[PlanStep]] = None) -> List[PlanStep]:
        """Break task into verifiable steps with clear success criteria using LLM Brain."""
        if custom_steps:
            context.steps = custom_steps
            return custom_steps

        # Check special gated workflows
        if "security" in context.task.lower() and "audit" in context.task.lower():
            context.steps = [
                PlanStep(
                    id=1,
                    title="Verify security target scope and perform port audit",
                    action_type=ActionType.SECURITY_AUDIT,
                    description="Defensive check on localhost pre-approved scope",
                    target="127.0.0.1",
                    payload={"target": "127.0.0.1", "audit_type": "port_scan"},
                    success_condition="Authorized scan completes and generates findings"
                )
            ]
            return context.steps

        elif "job" in context.task.lower() and "apply" in context.task.lower():
            context.steps = [
                PlanStep(
                    id=1,
                    title="Draft tailored job application to human review queue",
                    action_type=ActionType.JOB_DRAFT,
                    description="Draft cover letter and packet into queue/job_applications",
                    target="queue/job_applications",
                    payload={"job_id": "eng-001", "company": "TargetCorp", "role": "Engineer"},
                    success_condition="Draft packet created with status pending_human_approval"
                )
            ]
            return context.steps

        # Use LLM Brain to plan discrete steps
        plan_prompt = (
            f"You are ZARA. Break this task into discrete, verifiable steps:\n"
            f"Task: {context.task}\n"
            f"Working directory: {context.working_dir}\n"
            f"Past Lessons: {context.past_lessons}\n"
            f"Return JSON with 'steps' array of objects: title, action_type ('code', 'execute', 'test'), target, payload, success_condition."
        )
        plan_data = self.brain.generate_structured(plan_prompt)
        steps: List[PlanStep] = []

        if isinstance(plan_data, dict) and "steps" in plan_data and isinstance(plan_data["steps"], list):
            for i, s in enumerate(plan_data["steps"]):
                try:
                    action_type = ActionType(s.get("action_type", "execute"))
                except ValueError:
                    action_type = ActionType.EXECUTE

                steps.append(PlanStep(
                    id=i + 1,
                    title=s.get("title", f"Step {i+1}"),
                    action_type=action_type,
                    description=s.get("description", s.get("title", "")),
                    target=s.get("target", ""),
                    payload=s.get("payload", {}),
                    success_condition=s.get("success_condition", "Exits with return code 0")
                ))

        if not steps:
            # Fallback default step
            steps = [
                PlanStep(
                    id=1,
                    title=f"Execute: {context.task}",
                    action_type=ActionType.EXECUTE,
                    description="Run requested task directly",
                    target=context.task,
                    payload={"command": context.task},
                    success_condition="Command exits with return code 0"
                )
            ]

        context.steps = steps
        audit_logger.log_event("LOOP_PLAN", action="plan", extra={"step_count": len(steps)})
        return steps

    # 3. ACT
    def act(self, step: PlanStep, context: TaskContext) -> ExecutionResult:
        """Execute exactly one step at a time."""
        step.status = StepStatus.RUNNING
        step.attempts += 1
        self._notify_step("ACT", step)

        if step.action_type == ActionType.CODE:
            file_path = step.payload.get("file_path", step.target)
            content = step.payload.get("content", "")
            success, err = self.coding.write_file(file_path, content)
            if success:
                return ExecutionResult(success=True, exit_code=0, stdout=f"Wrote file {file_path}", stderr="")
            else:
                return ExecutionResult(success=False, exit_code=1, stdout="", stderr=err or "Code write failed")

        elif step.action_type in (ActionType.EXECUTE, ActionType.TEST):
            command = step.payload.get("command", step.target)
            return self.execution.execute(command, task_id=context.task[:30])

        elif step.action_type == ActionType.SECURITY_AUDIT:
            target = step.payload.get("target", "127.0.0.1")
            try:
                findings = self.security.run_authorized_port_scan(target)
                return ExecutionResult(success=True, exit_code=0, stdout=str(findings), stderr="")
            except ScopeViolationError as e:
                return ExecutionResult(success=False, exit_code=-1, stdout="", stderr=str(e))

        elif step.action_type == ActionType.JOB_DRAFT:
            job_id = step.payload.get("job_id", "job-1")
            company = step.payload.get("company", "Example Inc")
            role = step.payload.get("role", "Engineer")
            draft_path = self.job_hunter.draft_application(
                job_id=job_id,
                company=company,
                role=role,
                job_description=step.payload.get("description", "Software Engineer role"),
                candidate_profile=step.payload.get("candidate_profile", {"name": "Candidate"})
            )
            return ExecutionResult(
                success=True,
                exit_code=0,
                stdout=f"Application drafted and queued at {draft_path} for human approval.",
                stderr=""
            )

        return ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Unknown action type {step.action_type}")

    # 4. VERIFY
    def verify(self, step: PlanStep, result: ExecutionResult) -> bool:
        """Verify real check against expected success condition."""
        self._notify_step("VERIFY", step)
        step.actual_output = result.stdout or result.stderr

        if not result.success or result.exit_code != 0:
            step.error_message = result.stderr or f"Exit code {result.exit_code}"
            step.status = StepStatus.FAILED
            return False

        # Additional verification logic if verify_command provided
        verify_cmd = step.payload.get("verify_command")
        if verify_cmd:
            verify_res = self.execution.execute(verify_cmd)
            if not verify_res.success or verify_res.exit_code != 0:
                step.error_message = f"Verification check failed ({verify_cmd}): {verify_res.stderr}"
                step.status = StepStatus.FAILED
                return False

        step.status = StepStatus.PASSED
        return True

    # 5. DIAGNOSE & RETRY
    def diagnose_and_retry(self, step: PlanStep, result: ExecutionResult, context: TaskContext) -> bool:
        """Diagnose failure, formulate targeted hypothesis, and retry up to MAX_DIAGNOSE_RETRIES."""
        while step.attempts < MAX_DIAGNOSE_RETRIES:
            self._notify_step(f"DIAGNOSE (Attempt {step.attempts}/{MAX_DIAGNOSE_RETRIES})", step)
            error_output = result.stderr or result.stdout or "Step failed without stdout/stderr"

            diagnosis = self.debugging.diagnose_failure(
                step_title=step.title,
                expected_condition=step.success_condition,
                error_output=error_output,
                attempt=step.attempts,
                llm_router=self.brain
            )
            context.diagnoses.append(diagnosis)

            # Apply targeted fix if actionable fix is present
            fix = diagnosis.proposed_fix
            if fix.get("action") == "create_file" and fix.get("file"):
                self.coding.write_file(fix["file"], "# Auto-created by ZARA diagnostic\n")
            elif step.payload.get("retry_patch"):
                patch = step.payload["retry_patch"]
                self.coding.patch_file(patch["file"], patch["old"], patch["new"])

            # Retry ACT & VERIFY
            result = self.act(step, context)
            if self.verify(step, result):
                return True

        # Exceeded max retries
        step.status = StepStatus.BLOCKED
        context.requires_human_input = True
        context.blocker_reason = (
            f"Step '{step.title}' failed after {MAX_DIAGNOSE_RETRIES} attempts. "
            f"Last error: {step.error_message}. Escalating to user."
        )
        self.voice.speak("Step failed multiple times. User review required.")
        return False

    # 6. REFLECT
    def reflect(self, context: TaskContext) -> Reflection:
        """Synthesize concise 1-3 line lesson learned."""
        total_steps = len(context.steps)
        approach = f"Executed {total_steps} planned steps with rigorous automated verification."
        if context.diagnoses:
            approach += f" Encountered and addressed {len(context.diagnoses)} intermediate errors."

        if context.is_completed:
            result = f"All {total_steps} steps passed verification criteria."
            lesson = f"Completed '{context.task}' cleanly. Verifying discrete units prevented regression."
        else:
            result = f"Stopped due to blocker: {context.blocker_reason}"
            lesson = f"Task '{context.task}' required human escalation; check dependencies or credentials."

        reflection = Reflection(
            task=context.task,
            tag=context.tag,
            approach=approach,
            result=result,
            lesson=lesson
        )
        context.reflections.append(reflection)
        return reflection

    # 7. PERSIST
    def persist(self, reflection: Reflection) -> None:
        """Append reflection to memory/zara_log.md."""
        self.memory.append_reflection(reflection)

    # 8. CONTINUE OR REPORT (Full Loop)
    def run_task(
        self,
        task: str,
        tag: str = "dev",
        steps: Optional[List[PlanStep]] = None
    ) -> Dict[str, Any]:
        """Full autonomous state machine loop."""
        # 1. PERCEIVE
        context = self.perceive(task, tag)

        # 2. PLAN
        self.plan(context, custom_steps=steps)

        # Step 3 -> 4 -> 5 Loop
        for i, step in enumerate(context.steps):
            context.current_step_index = i
            result = self.act(step, context)

            is_verified = self.verify(step, result)
            if not is_verified:
                success_after_retry = self.diagnose_and_retry(step, result, context)
                if not success_after_retry:
                    break

            # Save checkpoint after each verified step for crash recovery
            self.recovery.save_checkpoint(context)

        # Check completion
        context.is_completed = all(s.status == StepStatus.PASSED for s in context.steps)

        # 6. REFLECT
        reflection = self.reflect(context)

        # 7. PERSIST
        self.persist(reflection)

        # Self-improvement evaluation
        self.self_improvement.evaluate_task(context)

        # 8. REPORT
        summary = {
            "task": context.task,
            "status": "COMPLETED" if context.is_completed else "BLOCKED",
            "steps_total": len(context.steps),
            "steps_passed": sum(1 for s in context.steps if s.status == StepStatus.PASSED),
            "blocker_reason": context.blocker_reason,
            "reflection": reflection.to_markdown(),
            "past_lessons_used": len(context.past_lessons)
        }

        if context.is_completed:
            self.voice.speak("Task verified and completed successfully.")
        else:
            self.voice.speak("Task execution paused. Action requires human input.")

        return summary

    def _notify_step(self, stage: str, step: PlanStep) -> None:
        if self.on_step_update:
            self.on_step_update(stage, step)
