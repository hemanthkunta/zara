"""
ZARA Core Engine: 8-Stage Autonomous Looping State Machine.
Perceive -> Plan -> Act -> Verify -> Diagnose & Retry -> Reflect -> Persist -> Continue/Report
"""
import os
import time
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Callable, Tuple

from config.settings import (
    BASE_DIR,
    MAX_DIAGNOSE_RETRIES,
    ENABLE_VOICE,
    MAX_STEPS,
    MAX_RETRIES_PER_STEP,
    MAX_TOTAL_RETRIES,
    MAX_EXECUTION_TIME_SECONDS,
    MAX_RESEARCH_QUERIES,
    MAX_SOURCES,
    MAX_PAGES,
    MAX_RESEARCH_TIME_SECONDS,
    FailureType
)
from core.state import (
    TaskContext,
    PlanStep,
    StepStatus,
    ActionType,
    ExecutionResult,
    Diagnosis,
    Reflection,
    ResearchSource,
    ResearchEvidence,
    SourceConflict,
    ResearchReport
)
from core.prompts import PLANNING_PROMPT_TEMPLATE
from brain.router import LLMRouter
from tools.registry import ToolRegistry
from tools.filesystem import ReadFileTool, WriteFileTool, PatchFileTool, ListDirTool
from tools.terminal import TerminalExecutionTool, TestRunnerTool
from tools.macos_control import (
    MacOSNotificationTool,
    MacOSClipboardTool,
    MacOSScreenshotTool,
    MouseMoveTool,
    MouseClickTool,
    KeyboardTypeTool,
    KeyboardHotkeyTool,
    ApplicationLaunchTool,
    ApplicationCloseTool,
    ActiveWindowTool,
    ScreenshotLifecycleManager
)
from tools.browser import (
    BrowserTool,
    WebSearchTool,
    BrowserOpenTool,
    ExtractContentTool,
    FollowLinkTool,
    CollectSourceTool
)
from modules.memory import MemoryStore
from modules.memory_extractor import MemoryExtractor
from modules.execution import ExecutionEngine
from modules.coding import CodingModule
from modules.debugging import DebuggingModule
from modules.research import ResearchEngine
from modules.voice import VoiceSynthesizer
from modules.security import SecurityModule, ScopeViolationError
from modules.job_hunter import JobHunterModule
from modules.orchestrator import TaskOrchestrator
from modules.self_improvement import SelfImprovementEvaluator
from modules.verification import VerificationEngine
from modules.vision import VisionModule
from modules.cyber_lab import CyberLabManager
from modules.blender import BlenderModule
from tools.cyber_tools import (
    CyberLabScanTool,
    CyberWebAuditTool,
    CyberSQLTestTool,
    CyberExploitCheckTool
)
from tools.blender_tools import (
    BlenderScriptTool,
    BlenderExecuteTool,
    BlenderInspectTool,
    BlenderRenderTool
)
from core.recovery import RecoveryManager
from core.observability import audit_logger
from modules.events import EventBus, Event, EventType, ConditionWatcher
from modules.scheduler import (
    Clock,
    SystemClock,
    MockClock,
    PersistentScheduler,
    JobQueue,
    ScheduledJob,
    ScheduleType,
    JobStatus,
    JobPriority,
    MissedSchedulePolicy
)
from modules.notifications import NotificationManager, NotificationSeverity, Notification
from modules.autonomous import (
    AutonomousMode,
    AutonomousModeManager,
    AutonomousBudget,
    QuietHoursManager,
    DailyQueueSynthesizer,
    ProactiveMaintenance
)
from modules.goals import Goal, GoalDomain, GoalParser, AmbiguityLevel
from modules.planning import (
    HierarchicalPlanner,
    PlanValidator,
    PlanValidationResult,
    PlanCost,
    DecisionRecord,
    DecisionRegistry,
    PlanPreview
)
from modules.replanning import AdaptiveReplanner, PlanVersion, PlanningFailureType
from modules.context import ContextManager, ContextCompactor, CompactSummary
from modules.workspace import PersistentTask
from modules.world_model import WorldModel, Modality, Observation, TemporalStatus, WorldState

class ZaraEngine:
    def __init__(
        self,
        workspace_root: str = str(BASE_DIR),
        use_docker: bool = False,
        enable_voice: bool = ENABLE_VOICE,
        on_step_update: Optional[Callable[[str, PlanStep], None]] = None,
        max_steps: int = MAX_STEPS,
        max_retries_per_step: int = MAX_RETRIES_PER_STEP,
        max_total_retries: int = MAX_TOTAL_RETRIES,
        max_execution_time_seconds: int = MAX_EXECUTION_TIME_SECONDS,
        max_research_queries: Optional[int] = None,
        max_sources: Optional[int] = None,
        max_pages: Optional[int] = None,
        max_research_time_seconds: Optional[int] = None,
        project_manager: Optional[Any] = None,
        clock: Optional[Clock] = None,
        event_bus: Optional[EventBus] = None,
        scheduler: Optional[PersistentScheduler] = None,
        notifications: Optional[NotificationManager] = None,
        autonomous: Optional[AutonomousModeManager] = None,
        world_model: Optional[WorldModel] = None
    ):
        self.workspace_root = Path(workspace_root).resolve()
        self.use_docker = use_docker
        self.on_step_update = on_step_update
        self.max_steps = max_steps
        self.max_retries_per_step = max_retries_per_step
        self.max_total_retries = max_total_retries
        self.max_execution_time_seconds = max_execution_time_seconds
        self.max_research_queries = max_research_queries or MAX_RESEARCH_QUERIES
        self.max_sources = max_sources or MAX_SOURCES
        self.max_pages = max_pages or MAX_PAGES
        self.max_research_time_seconds = max_research_time_seconds or MAX_RESEARCH_TIME_SECONDS
        self.project_manager = project_manager

        # Subsystems
        self.brain = LLMRouter()
        self.memory = MemoryStore()
        self.memory_extractor = MemoryExtractor()
        self.execution = ExecutionEngine(str(self.workspace_root), use_docker=use_docker)
        self.coding = CodingModule(str(self.workspace_root))
        self.debugging = DebuggingModule()
        self.research = ResearchEngine()
        self.voice = VoiceSynthesizer(enabled=enable_voice)
        self._voice_controller = None
        self.security = SecurityModule()
        self.job_hunter = JobHunterModule()
        self.orchestrator = TaskOrchestrator()
        self.verification = VerificationEngine(self.workspace_root)
        self.recovery = RecoveryManager()
        self.self_improvement = SelfImprovementEvaluator(self.memory)
        self.vision = VisionModule(self.brain)
        self.cyber_lab = CyberLabManager()
        self.blender = BlenderModule()

        # Phase 10: Event Bus, Scheduler, Notifications & Autonomous Subsystems
        self.clock = clock or SystemClock()
        self.event_bus = event_bus or EventBus()
        self.scheduler = scheduler or PersistentScheduler(clock=self.clock)
        self.notifications = notifications or NotificationManager(voice_synthesizer=self.voice)
        self.autonomous = autonomous or AutonomousModeManager()
        self.daily_queue = DailyQueueSynthesizer(scheduler=self.scheduler, project_manager=self.project_manager)
        self.maintenance = ProactiveMaintenance(project_manager=self.project_manager, event_bus=self.event_bus)

        # Phase 11: Goal Understanding, Planning, Decisions & Context
        self.decision_registry = DecisionRegistry()
        self.context_manager = ContextManager(project_id="default")
        self.adaptive_replanner = AdaptiveReplanner(project_id="default")

        # Phase 12: Multimodal Perception & Unified World Model
        self.world_model = world_model or WorldModel(workspace_root=str(self.workspace_root), event_bus=self.event_bus)

        # Initialize Tool Registry
        self.tools = ToolRegistry()
        self._register_default_tools()
        self._register_phase11_event_handlers()

    def _register_phase11_event_handlers(self) -> None:
        """Register event listeners for autonomous adaptive replanning."""
        if hasattr(self, "event_bus") and self.event_bus:
            def on_task_failed(event: Event) -> None:
                # Log or notify failure event
                pass
            self.event_bus.subscribe(EventType.TASK_FAILED, on_task_failed)

    @property
    def voice_controller(self):
        """Lazy access to bidirectional VoiceInteractionController."""
        if self._voice_controller is None:
            from modules.voice_controller import VoiceInteractionController
            self._voice_controller = VoiceInteractionController(self)
        return self._voice_controller

    def set_voice_controller(self, controller) -> None:
        """Explicitly set custom or mock voice controller."""
        self._voice_controller = controller

    def _register_default_tools(self) -> None:
        self.tools.register(ReadFileTool(self.workspace_root))
        self.tools.register(WriteFileTool(self.workspace_root))
        self.tools.register(PatchFileTool(self.workspace_root))
        self.tools.register(ListDirTool(self.workspace_root))
        self.tools.register(TerminalExecutionTool(self.workspace_root, use_docker=self.use_docker))
        self.tools.register(TestRunnerTool(self.workspace_root))
        self.tools.register(WebSearchTool(self.research))
        self.tools.register(BrowserOpenTool(self.research))
        self.tools.register(ExtractContentTool(self.research))
        self.tools.register(FollowLinkTool(self.research))
        self.tools.register(CollectSourceTool())
        self.tools.register(BrowserTool(self.research))
        self.tools.register(MacOSNotificationTool())
        self.tools.register(MacOSClipboardTool())
        self.tools.register(MacOSScreenshotTool())
        self.tools.register(MouseMoveTool())
        self.tools.register(MouseClickTool())
        self.tools.register(KeyboardTypeTool())
        self.tools.register(KeyboardHotkeyTool())
        self.tools.register(ApplicationLaunchTool())
        self.tools.register(ApplicationCloseTool())
        self.tools.register(ActiveWindowTool())
        # Domain Tools: Cybersecurity Lab
        self.tools.register(CyberLabScanTool(self.cyber_lab))
        self.tools.register(CyberWebAuditTool(self.cyber_lab))
        self.tools.register(CyberSQLTestTool(self.cyber_lab))
        self.tools.register(CyberExploitCheckTool(self.cyber_lab))
        # Domain Tools: Blender Autonomous 3D
        self.tools.register(BlenderScriptTool(self.blender))
        self.tools.register(BlenderExecuteTool(self.blender))
        self.tools.register(BlenderInspectTool(self.blender))
        self.tools.register(BlenderRenderTool(self.blender))

    def _record_event(
        self,
        context: TaskContext,
        event: str,
        step_id: Optional[int] = None,
        tool: Optional[str] = None,
        status: Optional[str] = None,
        duration_ms: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> None:
        entry = {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "step_id": step_id,
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
            **(extra or {})
        }
        context.events.append(entry)
        audit_extra = dict(extra or {})
        if status:
            audit_extra["status"] = status
        if duration_ms is not None:
            audit_extra["duration_ms"] = duration_ms
        audit_logger.log_event(
            event_type=event,
            action=tool or event,
            step_id=step_id,
            tool=tool,
            duration_seconds=(duration_ms / 1000.0) if duration_ms else 0.0,
            extra=audit_extra
        )
        if self.project_manager and getattr(self.project_manager, "journal", None):
            try:
                self.project_manager.journal.append(
                    event_type=event,
                    task_id=f"step_{step_id}" if step_id is not None else getattr(context, "task", None),
                    payload={"tool": tool, "status": status, **(extra or {})}
                )
            except Exception:
                pass

        # Publish to Phase 10 Event Bus
        if hasattr(self, "event_bus") and self.event_bus:
            try:
                ev_type = EventType.TASK_COMPLETED if event == "task_completed" else (
                    EventType.TASK_FAILED if event == "task_failed" else (
                        EventType.APPROVAL_PENDING if "approval" in event else EventType.CUSTOM
                    )
                )
                self.event_bus.publish(Event(
                    type=ev_type,
                    source="engine",
                    task_id=getattr(context, "task", None),
                    payload={"event": event, "tool": tool, "status": status, **(extra or {})}
                ))
            except Exception:
                pass

    def set_project_manager(self, pm) -> None:
        """Set persistent project manager for workspace-bound operations."""
        self.project_manager = pm
        proj_id = pm.project.project_id if pm and getattr(pm, "project", None) else "default"
        self.context_manager = ContextManager(project_id=proj_id)
        self.adaptive_replanner = AdaptiveReplanner(project_id=proj_id)
        if hasattr(self, "daily_queue"):
            self.daily_queue.project_manager = pm
        if hasattr(self, "maintenance"):
            self.maintenance.project_manager = pm
        if pm and hasattr(self, "world_model") and self.world_model:
            if hasattr(pm, "load_world_state"):
                saved_world = pm.load_world_state()
                if saved_world:
                    try:
                        self.world_model.current_state = WorldState.from_dict(saved_world)
                    except Exception:
                        pass
            if getattr(pm, "project", None):
                self.world_model.observe(Observation(
                    modality=Modality.PROJECT,
                    source="workspace_set_project",
                    payload={"project_id": pm.project.project_id, "name": pm.project.name, "status": pm.project.status.value},
                    project_id=pm.project.project_id,
                    trusted=True
                ))

    # -------------------------------------------------------------
    # Phase 11: Goal Understanding, Planning & Adaptive Replanning
    # -------------------------------------------------------------
    def understand_goal(self, raw_request: str, project_id: Optional[str] = None) -> Goal:
        """Transform unstructured user request into structured Goal model."""
        return GoalParser.parse_goal(raw_request, project_id=project_id)

    def plan_goal(
        self,
        goal: Goal,
        project_id: Optional[str] = None,
        custom_tasks: Optional[List[PersistentTask]] = None
    ) -> Tuple[List[PersistentTask], PlanValidationResult, PlanCost]:
        """Generate hierarchical plan, validate quality and safety, estimate cost, and persist."""
        proj_id = project_id or (self.project_manager.project.project_id if self.project_manager and self.project_manager.project else "proj-default")
        world_state = self.world_model.current_state if hasattr(self, "world_model") and self.world_model else None
        relevant_memories = []
        if hasattr(self.memory, "retrieve"):
            try:
                relevant_memories = self.memory.retrieve(
                    query=goal.desired_outcome or goal.normalized_goal,
                    project_id=proj_id,
                    limit=5
                )
            except Exception:
                relevant_memories = []
        tasks = custom_tasks if custom_tasks is not None else HierarchicalPlanner.create_hierarchical_plan(
            goal, proj_id, world_state=world_state, relevant_memories=relevant_memories
        )
        budget = self.project_manager.project.budget if self.project_manager and self.project_manager.project else None

        # Scope validation for cybersecurity
        allowed_scopes = None
        if hasattr(self, "cyber_lab") and self.cyber_lab:
            allowed_scopes = [t.host for t in self.cyber_lab.scope.list_targets()] + [t.target_id for t in self.cyber_lab.scope.list_targets()]

        validation = PlanValidator.validate(
            goal=goal,
            tasks=tasks,
            budget=budget,
            allowed_scopes=allowed_scopes
        )
        cost = HierarchicalPlanner.estimate_cost(goal, tasks)

        # Initialize plan version
        self.adaptive_replanner.initialize_plan(goal, tasks, budget)

        # Persist to workspace if project manager active
        if self.project_manager:
            current_v = self.adaptive_replanner.get_current_version()
            self.project_manager.save_planning_state(
                goal=goal.to_dict(),
                current_plan=current_v.to_dict() if current_v else None,
                plan_history=[v.to_dict() for v in self.adaptive_replanner.history]
            )

        return tasks, validation, cost

    def preview_plan(
        self,
        goal: Goal,
        tasks: List[PersistentTask],
        cost: PlanCost,
        validation: PlanValidationResult
    ) -> str:
        """Render concise human-readable preview of plan."""
        return PlanPreview.render(goal, tasks, cost, validation)

    def record_decision(
        self,
        question: str,
        options: List[str],
        selected_option: str,
        rationale_summary: str,
        task_id: Optional[str] = None,
        evidence: Optional[str] = None
    ) -> DecisionRecord:
        """Log concise operational decision record."""
        proj_id = self.project_manager.project.project_id if self.project_manager and self.project_manager.project else "default"
        rec = self.decision_registry.record(
            project_id=proj_id,
            question=question,
            options=options,
            selected_option=selected_option,
            rationale_summary=rationale_summary,
            task_id=task_id,
            evidence=evidence
        )
        if self.project_manager:
            self.project_manager.record_decision(
                question=question,
                options=options,
                selected_option=selected_option,
                rationale_summary=rationale_summary,
                task_id=task_id,
                evidence=evidence
            )
        return rec

    def replan_failed_task(
        self,
        goal: Goal,
        failed_task: PersistentTask,
        diagnosis: Optional[Diagnosis] = None
    ) -> Tuple[Optional[PlanVersion], str]:
        """Perform adaptive replanning after a task failure."""
        budget = self.project_manager.project.budget if self.project_manager and self.project_manager.project else None
        new_version, message = self.adaptive_replanner.replan(
            goal=goal,
            failed_task=failed_task,
            diagnosis=diagnosis,
            budget=budget
        )
        if new_version:
            # Record decision about replanning
            self.record_decision(
                question=f"Task '{failed_task.title}' failed ({failed_task.error or 'error'}). How to proceed?",
                options=["Abort", "Retry blindly", "Adaptive replan with remediation"],
                selected_option="Adaptive replan with remediation",
                rationale_summary=new_version.reason_for_change,
                task_id=failed_task.id
            )
            if self.project_manager:
                self.project_manager.save_planning_state(
                    goal=goal.to_dict(),
                    current_plan=new_version.to_dict(),
                    plan_history=[v.to_dict() for v in self.adaptive_replanner.history]
                )
        return new_version, message

    def compact_context(
        self,
        goal: Optional[Goal] = None,
        task_context: Optional[TaskContext] = None
    ) -> CompactSummary:
        """Deterministically compact task history and state into compact summary."""
        proj_id = self.project_manager.project.project_id if self.project_manager and self.project_manager.project else "default"
        tasks = self.project_manager.dag.list_tasks() if self.project_manager and self.project_manager.dag else []
        artifacts = self.project_manager.artifacts.list_artifacts() if self.project_manager and self.project_manager.artifacts else []
        decisions = self.decision_registry.list_by_project(proj_id)

        summary = ContextCompactor.compact(
            project_id=proj_id,
            goal=goal,
            tasks=tasks,
            artifacts=artifacts,
            decisions=decisions,
            task_context=task_context
        )
        self.context_manager.add_summary(summary)
        if self.project_manager:
            self.project_manager.save_compact_summary(summary.to_dict())
        return summary

    def set_clock(self, clock: Clock) -> None:
        """Inject mock or custom clock across engine and subsystems."""
        self.clock = clock
        if hasattr(self, "scheduler") and self.scheduler:
            self.scheduler.clock = clock

    def perceive(self, task: str, tag: str = "dev") -> TaskContext:
        """Read task, query memory for prior lessons, and inspect repo state."""
        self.voice.speak(f"Perceiving task: {task[:60]}")
        past_lessons_raw = self.memory.search_lessons(f"{task} {tag}", limit=3)
        past_lessons = [
            f"[{entry['header']}] Lesson: {entry['lesson']}" for entry in past_lessons_raw if entry.get("lesson")
        ]

        # Phase 14 Advanced Memory Retrieval
        proj_id = self.project_manager.project.project_id if self.project_manager and getattr(self.project_manager, "project", None) else None
        relevant_memories = []
        if hasattr(self.memory, "retrieve"):
            try:
                relevant_memories = self.memory.retrieve(f"{task} {tag}", project_id=proj_id, limit=5)
                for mem in relevant_memories:
                    past_lessons.append(f"[{mem.type.value}] {mem.content}")
            except Exception:
                relevant_memories = []

        context = TaskContext(
            task=task,
            tag=tag,
            working_dir=str(self.workspace_root),
            past_lessons=past_lessons,
            relevant_memories=relevant_memories,
            start_time=time.time()
        )
        self._record_event(context, "task_started", extra={"task": task, "tag": tag})
        audit_logger.log_event("LOOP_PERCEIVE", action="perceive", extra={"task": task, "tag": tag})

        if hasattr(self, "world_model") and self.world_model:
            proj_id = self.project_manager.project.project_id if self.project_manager and getattr(self.project_manager, "project", None) else None
            self.world_model.observe(Observation(
                modality=Modality.TASK,
                source="engine_perceive",
                payload={"name": task, "status": "ACTIVE"},
                project_id=proj_id,
                trusted=True
            ))

        return context

    # 2. PLAN
    def plan(self, context: TaskContext, custom_steps: Optional[List[PlanStep]] = None) -> List[PlanStep]:
        """Break task into verifiable steps with clear success criteria using LLM Brain."""
        if custom_steps:
            if len(custom_steps) > self.max_steps:
                context.steps = custom_steps[:self.max_steps]
            else:
                context.steps = custom_steps
            self._record_event(context, "plan_created", extra={"step_count": len(context.steps)})
            return context.steps

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
            self._record_event(context, "plan_created", extra={"step_count": len(context.steps)})
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
            self._record_event(context, "plan_created", extra={"step_count": len(context.steps)})
            return context.steps

        # Build dynamic tool descriptions from registered tools
        tools_info = []
        for t in self.tools.list_tools():
            params = t["parameters"].get("properties", {})
            req = t["parameters"].get("required", [])
            tools_info.append(
                f"- {t['name']}: {t['description']} (arguments: {list(params.keys())}, required: {req})"
            )
        available_tools_str = "\n".join(tools_info)

        def _validate_and_build_steps(plan_data: Any) -> Tuple[List[PlanStep], Optional[str]]:
            if not isinstance(plan_data, dict) or "steps" not in plan_data or not isinstance(plan_data["steps"], list):
                return [], "Plan response does not contain a valid 'steps' list."
            if not plan_data["steps"]:
                return [], "Plan response contains an empty 'steps' list."

            if len(plan_data["steps"]) > self.max_steps:
                return [], f"Plan exceeds maximum allowed steps ({len(plan_data['steps'])} > {self.max_steps})."

            parsed_steps: List[PlanStep] = []
            for i, s in enumerate(plan_data["steps"]):
                if not isinstance(s, dict):
                    return [], f"Step {i+1} is not a valid object."

                # Tool selection
                tool_name = s.get("tool")
                if not tool_name and s.get("action_type") in ("code", "execute", "test"):
                    legacy_map = {"code": "write_file", "execute": "terminal_execute", "test": "terminal_execute"}
                    tool_name = legacy_map.get(s["action_type"])

                if not tool_name:
                    return [], f"Step {i+1} does not specify a tool."

                tool_obj = self.tools.get(tool_name)
                if not tool_obj:
                    return [], f"Step {i+1} specifies unknown tool '{tool_name}'."

                # Extract and validate arguments
                args = s.get("arguments")
                if args is None:
                    args = s.get("payload", {})
                if not isinstance(args, dict):
                    return [], f"Step {i+1} arguments must be a dictionary."

                # Ensure required arguments exist according to tool schema
                is_valid, val_err = tool_obj.validate_inputs(args)
                if not is_valid:
                    return [], f"Step {i+1} argument validation failed for tool '{tool_name}': {val_err}"

                # Never allow natural language tasks to be passed directly as commands
                if tool_name == "terminal_execute":
                    cmd = args.get("command", "").strip()
                    if not cmd:
                        return [], f"Step {i+1} terminal_execute requires a non-empty 'command'."
                    if cmd == context.task.strip():
                        return [], f"Step {i+1} attempts to execute the natural-language task prompt as a shell command."

                # Parse dependencies
                raw_deps = s.get("dependencies", [])
                dep_ids: List[int] = []
                if isinstance(raw_deps, list):
                    for d in raw_deps:
                        try:
                            dep_ids.append(int(d))
                        except (ValueError, TypeError):
                            pass

                step_id = s.get("id", i + 1)
                title = s.get("title", f"Step {step_id}: {tool_name}")
                description = s.get("description", title)
                success_condition = s.get("success_condition", "Tool execution succeeds with exit code 0")
                target = str(args.get("path") or args.get("command") or tool_name)

                parsed_steps.append(PlanStep(
                    id=step_id,
                    title=title,
                    action_type=ActionType.TOOL,
                    description=description,
                    target=target,
                    payload=dict(args),
                    tool=tool_name,
                    arguments=dict(args),
                    dependencies=dep_ids,
                    success_condition=success_condition
                ))

            return parsed_steps, None

        # 1. Primary planning prompt
        plan_prompt = PLANNING_PROMPT_TEMPLATE.format(
            task=context.task,
            context=f"Working directory: {context.working_dir}",
            past_lessons="\n".join(context.past_lessons) if context.past_lessons else "None",
            available_tools=available_tools_str
        )
        plan_data = self.brain.generate_structured(plan_prompt)
        steps, err_msg = _validate_and_build_steps(plan_data)

        # 2. If invalid, attempt one safe recovery call with stronger prompt
        if not steps:
            recovery_prompt = (
                f"CRITICAL RECOVERY: Your previous plan was rejected ({err_msg}).\n"
                f"Task: {context.task}\n"
                f"Available Registered Tools:\n{available_tools_str}\n\n"
                f"You MUST produce a valid JSON object with 'steps' array of valid tool calls.\n"
                f"DO NOT execute natural language as a shell command.\n"
                f"Each step must specify a registered 'tool' and valid 'arguments'.\n"
            )
            recovery_data = self.brain.generate_structured(recovery_prompt)
            steps, err_msg = _validate_and_build_steps(recovery_data)

        # 3. If STILL invalid, STOP safely - never fall back to shell execution!
        if not steps:
            context.steps = []
            context.is_completed = False
            context.requires_human_input = True
            context.blocker_reason = "LLM planner returned no valid executable plan; refusing to interpret natural language as a shell command."
            audit_logger.log_event(
                "PLAN_REJECTED",
                action="plan",
                error=context.blocker_reason,
                extra={"task": context.task, "last_validation_error": err_msg}
            )
            return []

        context.steps = steps
        self._record_event(context, "plan_created", extra={"step_count": len(steps)})
        audit_logger.log_event("LOOP_PLAN", action="plan", extra={"step_count": len(steps)})
        return steps

    # 3. ACT
    def act(self, step: PlanStep, context: TaskContext) -> ExecutionResult:
        """Execute exactly one step at a time."""
        step.status = StepStatus.RUNNING
        step.attempts += 1
        self._notify_step("ACT", step)

        tool_ident = step.tool or (
            step.action_type.value if hasattr(step.action_type, "value") else str(step.action_type)
        )
        self._record_event(context, "tool_selected", step_id=step.id, tool=tool_ident)
        start_t = time.time()
        self._record_event(context, "tool_started", step_id=step.id, tool=tool_ident)

        if self.project_manager and getattr(self.project_manager, "project", None):
            self.project_manager.project.budget.record(tools=1)

        result: ExecutionResult
        raw_return_val = None

        # 1. Preferred execution via ToolRegistry
        if step.action_type == ActionType.TOOL or step.tool:
            tool_name = step.tool
            if not tool_name:
                result = ExecutionResult(success=False, exit_code=1, stdout="", stderr="Step missing tool name")
            else:
                tool = self.tools.get(tool_name)
                if not tool:
                    result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Tool '{tool_name}' not found in registry")
                else:
                    args = step.arguments or step.payload
                    is_valid, val_err = tool.validate_inputs(args)
                    if not is_valid:
                        result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Validation failed: {val_err}")
                    elif tool_name == "terminal_execute" and args.get("command", "").strip() == context.task.strip():
                        result = ExecutionResult(success=False, exit_code=1, stdout="", stderr="Refusing to execute natural language prompt as shell command.")
                    elif tool_name == "web_search" and len(context.research_queries) >= self.max_research_queries:
                        result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Exceeded maximum research queries budget ({self.max_research_queries})")
                    elif tool_name in ("browser_open", "browser_scrape") and len(context.opened_urls) >= self.max_pages:
                        result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Exceeded maximum pages budget ({self.max_pages})")
                    elif (tool_name in ("web_search", "browser_open", "browser_scrape", "extract_content", "follow_link")) and (time.time() - context.start_time) > self.max_research_time_seconds:
                        result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Exceeded maximum research time limit ({self.max_research_time_seconds}s)")
                    else:
                        # Pre-execution static validation if executing a Python script
                        cmd = args.get("command", "").strip() if tool_name == "terminal_execute" else ""
                        static_err = None
                        if tool_name == "terminal_execute" and cmd:
                            py_match = re.search(r'(?:python3?|pytest)\s+([a-zA-Z0-9_\-./]+\.py)', cmd)
                            if py_match:
                                target_file = py_match.group(1)
                                target_path = self.workspace_root / target_file
                                if target_path.exists():
                                    is_valid, err_msg = self.coding.validate_static(target_file)
                                    if not is_valid:
                                        static_err = err_msg

                        if static_err:
                            result = ExecutionResult(
                                success=False,
                                exit_code=1,
                                stdout="",
                                stderr=f"Pre-execution static validation failed:\n{static_err}",
                                duration_seconds=0.0,
                                command=cmd
                            )
                        else:
                            # Pre-action Staleness Refresh Check
                            if hasattr(self, "world_model") and self.world_model:
                                if tool_name in ("mouse_click", "mouse_move", "keyboard_type"):
                                    if self.world_model.get_staleness(Modality.SCREEN) in (TemporalStatus.STALE, TemporalStatus.UNKNOWN):
                                        ss_tool = self.tools.get("screenshot_capture")
                                        if ss_tool:
                                            ss_res = ss_tool.execute()
                                            if ss_res.success and ss_res.data and isinstance(ss_res.data, dict):
                                                self.world_model.observe(Observation(
                                                    modality=Modality.SCREEN,
                                                    source="refresh_probe",
                                                    payload=ss_res.data,
                                                    trusted=False
                                                ))

                            tool_res = self.tools.execute(tool_name, args, task_id=context.task[:30])
                            raw_return_val = tool_res.data

                            if isinstance(tool_res.data, dict):
                                stdout = str(tool_res.data.get("stdout", ""))
                                stderr = str(tool_res.data.get("stderr", "")) or (tool_res.error or "")
                                exit_code = tool_res.data.get("exit_code", 0 if tool_res.success else 1)
                            else:
                                stdout = str(tool_res.data) if (tool_res.data is not None and tool_res.success) else ""
                                stderr = tool_res.error or ("" if tool_res.success else "Tool execution failed")
                                exit_code = 0 if tool_res.success else 1

                            result = ExecutionResult(
                                success=tool_res.success,
                                exit_code=exit_code,
                                stdout=stdout,
                                stderr=stderr,
                                duration_seconds=tool_res.duration_seconds,
                                command=args.get("command") if tool_name == "terminal_execute" else None
                            )

        # Legacy ActionType handlers for backward compatibility
        elif step.action_type == ActionType.CODE:
            file_path = step.payload.get("file_path", step.target)
            content = step.payload.get("content", "")
            success, err = self.coding.write_file(file_path, content)
            raw_return_val = {"file_path": file_path, "success": success}
            if success:
                result = ExecutionResult(success=True, exit_code=0, stdout=f"Wrote file {file_path}", stderr="")
            else:
                result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=err or "Code write failed")

        elif step.action_type in (ActionType.EXECUTE, ActionType.TEST):
            command = step.payload.get("command", step.target)
            if command.strip() == context.task.strip():
                result = ExecutionResult(success=False, exit_code=1, stdout="", stderr="Refusing to execute natural language task as shell command.")
            else:
                result = self.execution.execute(command, task_id=context.task[:30])
                raw_return_val = {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code}

        elif step.action_type == ActionType.SECURITY_AUDIT:
            target = step.payload.get("target", "127.0.0.1")
            try:
                findings = self.security.run_authorized_port_scan(target)
                raw_return_val = findings
                result = ExecutionResult(success=True, exit_code=0, stdout=str(findings), stderr="")
            except ScopeViolationError as e:
                result = ExecutionResult(success=False, exit_code=-1, stdout="", stderr=str(e))

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
            raw_return_val = {"draft_path": draft_path}
            result = ExecutionResult(
                success=True,
                exit_code=0,
                stdout=f"Application drafted and queued at {draft_path} for human approval.",
                stderr=""
            )
        else:
            result = ExecutionResult(success=False, exit_code=1, stdout="", stderr=f"Unknown action type {step.action_type}")

        duration_s = time.time() - start_t
        duration_ms = duration_s * 1000.0

        # Build structured observation
        step.observation = {
            "tool": tool_ident,
            "arguments": dict(step.arguments or step.payload or {}),
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_value": raw_return_val,
            "exit_code": result.exit_code,
            "duration_seconds": duration_s,
            "error": result.stderr if not result.success else None,
            "timestamp": datetime.now().isoformat()
        }

        # Phase 12: Ingest observation into Unified World Model
        if hasattr(self, "world_model") and self.world_model:
            try:
                proj_id = self.project_manager.project.project_id if self.project_manager and getattr(self.project_manager, "project", None) else None
                task_id = f"step_{step.id}"
                args_dict = dict(step.arguments or step.payload or {})

                modality = Modality.EVENT
                obs_payload = dict(args_dict)
                trusted = False
                source = f"tool_{tool_ident}"

                if tool_ident == "terminal_execute" or step.action_type in (ActionType.EXECUTE, ActionType.TEST):
                    modality = Modality.TERMINAL
                    obs_payload.update({
                        "command": args_dict.get("command") or step.target,
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "status": "COMPLETED" if result.success else "FAILED"
                    })
                elif tool_ident in ("screenshot_capture", "mouse_click", "mouse_move", "keyboard_type", "active_window"):
                    modality = Modality.SCREEN
                    if getattr(context, "current_gui_state", None):
                        obs_payload.update(context.current_gui_state.to_dict())
                elif tool_ident in ("web_search", "browser_open", "browser_scrape", "extract_content", "follow_link"):
                    modality = Modality.BROWSER
                    obs_payload.update({
                        "url": args_dict.get("url"),
                        "query": args_dict.get("query"),
                        "result_summary": result.stdout[:200]
                    })
                elif tool_ident in ("write_file", "patch_file", "read_file") or step.action_type == ActionType.CODE:
                    modality = Modality.FILESYSTEM
                    obs_payload.update({
                        "path": args_dict.get("path") or args_dict.get("file_path") or step.target,
                        "state": "MODIFIED" if result.success else "ERROR"
                    })
                elif "blender" in tool_ident:
                    modality = Modality.BLENDER
                    obs_payload.update({
                        "tool": tool_ident,
                        "render_status": "COMPLETED" if "render" in tool_ident and result.success else "PENDING"
                    })
                elif "cyber" in tool_ident or step.action_type == ActionType.SECURITY_AUDIT:
                    modality = Modality.CYBER
                    obs_payload.update({
                        "target": args_dict.get("target") or step.target,
                        "authorized": False  # Strictly preserve authorization boundary
                    })

                prev_state_dict = self.world_model.current_state.to_dict() if self.world_model.current_state else {}
                self.world_model.observe(Observation(
                    modality=modality,
                    source=source,
                    payload=obs_payload,
                    project_id=proj_id,
                    task_id=task_id,
                    confidence=1.0 if result.success else 0.5,
                    trusted=trusted
                ))

                diff = self.world_model.diff(WorldState.from_dict(prev_state_dict), self.world_model.current_state)
                if diff.get("has_changes") and hasattr(self, "event_bus") and self.event_bus:
                    self.event_bus.publish(Event(
                        type=EventType.WORLD_STATE_CHANGED,
                        source="world_model",
                        project_id=proj_id,
                        task_id=task_id,
                        payload=diff
                    ))
                    if "active_app" in diff.get("changes", {}):
                        self.event_bus.publish(Event(
                            type=EventType.APP_CHANGED,
                            source="world_model",
                            project_id=proj_id,
                            task_id=task_id,
                            payload=diff["changes"]["active_app"]
                        ))
            except Exception as e:
                audit_logger.log_event("world_model_observation_error", {"error": str(e)})

        if not result.success:
            err_lower = (result.stderr or "").lower()
            if "not found in registry" in err_lower or "missing tool name" in err_lower:
                step.failure_type = FailureType.TOOL_VALIDATION_FAILURE.value
            elif "validation failed" in err_lower:
                step.failure_type = FailureType.TOOL_VALIDATION_FAILURE.value
            elif "timed out" in err_lower:
                step.failure_type = FailureType.TIMEOUT.value
            elif "scopeviolation" in err_lower or "permission" in err_lower:
                step.failure_type = FailureType.PERMISSION_FAILURE.value
            else:
                step.failure_type = FailureType.COMMAND_FAILURE.value

        # Update context tracking for files and tests
        args = step.arguments or step.payload
        if tool_ident == "write_file":
            p = args.get("path")
            if p and result.success:
                if p not in context.files_created and p not in context.files_modified:
                    context.files_created.append(p)
                elif p in context.files_created and p not in context.files_modified:
                    context.files_modified.append(p)
        elif tool_ident == "patch_file":
            p = args.get("path")
            if p and result.success and p not in context.files_modified:
                context.files_modified.append(p)
        elif tool_ident == "read_file":
            p = args.get("path")
            if p and p not in context.files_inspected:
                context.files_inspected.append(p)
        elif tool_ident == "terminal_execute":
            cmd = args.get("command", "")
            if any(term in cmd.lower() for term in ["test", "unittest", "pytest"]):
                if cmd not in context.tests_executed:
                    context.tests_executed.append(cmd)
        elif tool_ident == "run_tests":
            tp = args.get("test_path", "tests")
            if tp not in context.tests_executed:
                context.tests_executed.append(tp)
        elif tool_ident == "web_search":
            q = args.get("query")
            if q and q not in context.research_queries:
                context.research_queries.append(q)
            if isinstance(raw_return_val, dict) and "results" in raw_return_val:
                for r in raw_return_val["results"]:
                    sid = f"source_{len(context.sources)+1:02d}"
                    src = ResearchSource(
                        source_id=sid,
                        url=r.get("url", ""),
                        title=r.get("title", ""),
                        domain=r.get("domain", ""),
                        relevant_excerpt=r.get("snippet", ""),
                        reliability=r.get("reliability", "primary"),
                        is_authoritative=r.get("is_authoritative", False)
                    )
                    context.add_source(src)
        elif tool_ident in ("browser_open", "browser_scrape"):
            u = args.get("url")
            if u:
                if result.success and u not in context.opened_urls:
                    context.opened_urls.append(u)
                elif not result.success and u not in context.failed_sources:
                    context.failed_sources.append(u)
                if isinstance(raw_return_val, dict) and result.success:
                    sid = f"source_{len(context.sources)+1:02d}"
                    src = ResearchSource(
                        source_id=sid,
                        url=raw_return_val.get("url", u),
                        title=raw_return_val.get("title", u),
                        domain=raw_return_val.get("domain", ""),
                        relevant_excerpt=raw_return_val.get("content", "")[:300],
                        reliability=raw_return_val.get("reliability", "primary"),
                        is_authoritative=raw_return_val.get("is_authoritative", False)
                    )
                    context.add_source(src)
        elif tool_ident == "extract_content":
            if isinstance(raw_return_val, dict) and "evidence" in raw_return_val:
                for ev_dict in raw_return_val["evidence"]:
                    context.add_evidence(
                        ResearchEvidence(
                            claim=ev_dict.get("claim", ""),
                            evidence=ev_dict.get("evidence", ""),
                            source_id=ev_dict.get("source_id", "source_01"),
                            confidence=ev_dict.get("confidence", 0.9),
                            verified=ev_dict.get("verified", True)
                        )
                    )
        elif tool_ident == "collect_source":
            if isinstance(raw_return_val, dict):
                src = ResearchSource(
                    source_id=raw_return_val.get("source_id", f"source_{len(context.sources)+1:02d}"),
                    url=raw_return_val.get("url", ""),
                    title=raw_return_val.get("title", ""),
                    domain=raw_return_val.get("domain", ""),
                    relevant_excerpt=raw_return_val.get("relevant_excerpt", ""),
                    reliability=raw_return_val.get("reliability", "primary"),
                    is_authoritative=raw_return_val.get("is_authoritative", False)
                )
                context.add_source(src)

        self._record_event(
            context,
            "tool_finished",
            step_id=step.id,
            tool=tool_ident,
            status="success" if result.success else "failed",
            duration_ms=duration_ms,
            extra={"exit_code": result.exit_code}
        )

        return result

    # 4. VERIFY
    def verify(self, step: PlanStep, result: ExecutionResult, context: Optional[TaskContext] = None) -> bool:
        """Verify real check against expected success condition with structured evidence."""
        self._notify_step("VERIFY", step)
        if context:
            self._record_event(context, "verification_started", step_id=step.id)

        step.actual_output = result.stdout or result.stderr
        evidence: List[str] = []

        if not result.success or result.exit_code != 0:
            evidence.append(f"Command execution failed with exit code {result.exit_code}: {result.stderr or 'Error'}")
            step.error_message = result.stderr or f"Exit code {result.exit_code}"
            step.status = StepStatus.FAILED
            step.verification = {"verified": False, "evidence": evidence}
            if not step.failure_type:
                step.failure_type = FailureType.COMMAND_FAILURE.value
            if context:
                self._record_event(context, "verification_finished", step_id=step.id, status="failed", extra={"evidence": evidence})
            return False

        evidence.append(f"Tool executed successfully with exit code 0 (duration: {result.duration_seconds:.2f}s)")
        args = step.arguments or step.payload

        # 1. Evidence check for file creation (write_file)
        if step.tool == "write_file" or step.action_type == ActionType.CODE:
            file_path = args.get("path") or args.get("file_path") or step.target
            if file_path:
                target_file = (self.workspace_root / file_path).resolve()
                if not target_file.exists():
                    evidence.append(f"Expected file '{file_path}' does not exist on disk.")
                    step.error_message = f"Verification failed: Expected file '{file_path}' does not exist on disk."
                    step.status = StepStatus.FAILED
                    step.verification = {"verified": False, "evidence": evidence}
                    step.failure_type = FailureType.VERIFICATION_FAILURE.value
                    if context:
                        self._record_event(context, "verification_finished", step_id=step.id, status="failed", extra={"evidence": evidence})
                    return False
                else:
                    evidence.append(f"File '{file_path}' exists on disk ({target_file.stat().st_size} bytes)")

        # 2. Evidence check for expected output in condition
        cond = (step.success_condition or "").strip()
        if cond and result.stdout:
            # Check for explicitly quoted expected output strings, e.g. prints 'Hello from ZARA'
            quoted = re.findall(r"['\"]([^'\"]+)['\"]", cond)
            for expected_str in quoted:
                if any(kw in cond.lower() for kw in ["print", "output", "contain", "return", "equal"]):
                    if expected_str not in result.stdout:
                        evidence.append(f"Verification failed: Output does not contain expected substring '{expected_str}'.")
                        step.error_message = (
                            f"Verification failed: Output does not contain expected substring '{expected_str}'. "
                            f"Actual stdout: {result.stdout.strip()}"
                        )
                        step.status = StepStatus.FAILED
                        step.verification = {"verified": False, "evidence": evidence}
                        step.failure_type = FailureType.VERIFICATION_FAILURE.value
                        if context:
                            self._record_event(context, "verification_finished", step_id=step.id, status="failed", extra={"evidence": evidence})
                        return False
                    else:
                        evidence.append(f"Output matched expected criterion: '{expected_str}'")

        # 3. Additional verification command if specified
        verify_cmd = args.get("verify_command")
        if verify_cmd:
            verify_res = self.execution.execute(verify_cmd)
            if not verify_res.success or verify_res.exit_code != 0:
                evidence.append(f"Verification check failed ({verify_cmd}): {verify_res.stderr}")
                step.error_message = f"Verification check failed ({verify_cmd}): {verify_res.stderr}"
                step.status = StepStatus.FAILED
                step.verification = {"verified": False, "evidence": evidence}
                step.failure_type = FailureType.VERIFICATION_FAILURE.value
                if context:
                    self._record_event(context, "verification_finished", step_id=step.id, status="failed", extra={"evidence": evidence})
                return False
            else:
                evidence.append(f"Verification check command succeeded: {verify_cmd}")

        if step.tool == "read_file":
            evidence.append(f"Read file content successfully ({len(result.stdout)} characters)")
        elif step.tool == "list_dir":
            evidence.append("Directory listing retrieved successfully")

        step.verification = {"verified": True, "evidence": evidence}
        step.status = StepStatus.PASSED
        if context:
            self._record_event(context, "verification_finished", step_id=step.id, status="passed", extra={"evidence": evidence})

        if self.project_manager and getattr(self.project_manager, "artifacts", None):
            try:
                if step.tool in ("write_file", "patch_file") or step.action_type == ActionType.CODE:
                    fpath = args.get("path") or args.get("file_path") or step.target
                    if fpath:
                        self.project_manager.artifacts.register(
                            rel_or_abs_path=fpath,
                            task_id=f"step_{step.id}",
                            project_id=self.project_manager.project.project_id if self.project_manager.project else "proj",
                            artifact_type="code"
                        )
            except Exception:
                pass

        return True

    # 5. DIAGNOSE & RETRY
    def diagnose_and_retry(self, step: PlanStep, result: ExecutionResult, context: TaskContext) -> bool:
        """Diagnose failure, formulate targeted hypothesis, and retry up to limits."""
        previous_attempts: List[Dict[str, Any]] = []

        while step.attempts < self.max_retries_per_step:
            if self.project_manager and getattr(self.project_manager, "project", None):
                self.project_manager.project.budget.record(retries=1)
            if context.total_retries >= self.max_total_retries:
                step.status = StepStatus.BLOCKED
                context.requires_human_input = True
                context.blocker_reason = (
                    f"Total retry budget exceeded ({context.total_retries} >= {self.max_total_retries}). Escalating to user."
                )
                self._record_event(context, "retry_budget_exceeded", step_id=step.id, extra={"total_retries": context.total_retries})
                return False

            context.total_retries += 1
            current_tool = step.tool or (
                step.action_type.value if hasattr(step.action_type, "value") else str(step.action_type)
            )
            current_args = dict(step.arguments or step.payload)
            previous_attempts.append({
                "attempt": step.attempts,
                "tool": current_tool,
                "arguments": current_args,
                "exit_code": result.exit_code,
                "error": result.stderr or result.stdout or step.error_message
            })

            self._notify_step(f"DIAGNOSE (Attempt {step.attempts}/{self.max_retries_per_step})", step)
            self._record_event(context, "diagnosis_started", step_id=step.id, extra={"attempt": step.attempts})
            error_output = result.stderr or result.stdout or step.error_message or "Step failed without error output"

            diagnosis = self.debugging.diagnose_failure(
                step_title=step.title,
                expected_condition=step.success_condition,
                error_output=error_output,
                attempt=step.attempts,
                llm_router=self.brain,
                step=step,
                task=context.task,
                previous_attempts=previous_attempts
            )
            context.diagnoses.append(diagnosis)
            self._record_event(context, "diagnosis_finished", step_id=step.id, extra={"hypothesis": diagnosis.hypothesis})

            # Apply targeted fix
            new_tool = diagnosis.corrected_tool or step.tool
            new_args = dict(step.arguments or step.payload)
            has_targeted_change = False

            if diagnosis.corrected_arguments:
                new_args.update(diagnosis.corrected_arguments)
                has_targeted_change = True

            fix = diagnosis.proposed_fix or {}
            if fix.get("action") == "fix_syntax" and fix.get("file") and fix.get("new_content"):
                self.coding.write_file(fix["file"], fix["new_content"])
                context.files_modified.append(fix["file"])
                context.patches_applied.append(fix)
                has_targeted_change = True
            elif fix.get("action") in ("patch_file", "patch_code") and fix.get("file"):
                old = fix.get("old") or fix.get("old_str", "")
                new = fix.get("new") or fix.get("new_str", "")
                if old:
                    self.coding.patch_file(fix["file"], old, new)
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
            elif fix.get("action") == "fix_implementation_logic" and fix.get("file"):
                if fix.get("new_content"):
                    self.coding.write_file(fix["file"], fix["new_content"])
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
                elif fix.get("patch"):
                    p = fix["patch"]
                    self.coding.patch_file(fix["file"], p.get("old", ""), p.get("new", ""))
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
            elif fix.get("action") == "fix_runtime_error" and fix.get("file"):
                if fix.get("new_content"):
                    self.coding.write_file(fix["file"], fix["new_content"])
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
                elif fix.get("patch"):
                    p = fix["patch"]
                    self.coding.patch_file(fix["file"], p.get("old", ""), p.get("new", ""))
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
            elif fix.get("action") == "fix_import" and fix.get("file"):
                if fix.get("new_content"):
                    self.coding.write_file(fix["file"], fix["new_content"])
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
                elif fix.get("patch"):
                    p = fix["patch"]
                    self.coding.patch_file(fix["file"], p.get("old", ""), p.get("new", ""))
                    context.files_modified.append(fix["file"])
                    context.patches_applied.append(fix)
                    has_targeted_change = True
            elif fix.get("action") == "create_file" and fix.get("file"):
                self.coding.write_file(fix["file"], "# Auto-created by ZARA diagnostic\n")
                context.files_created.append(fix["file"])
                context.patches_applied.append(fix)
                has_targeted_change = True
            elif step.payload.get("retry_patch"):
                patch = step.payload["retry_patch"]
                self.coding.patch_file(patch["file"], patch["old"], patch["new"])
                context.files_modified.append(patch["file"])
                context.patches_applied.append(patch)
                has_targeted_change = True

            # Loop detection: detect repeated identical attempts
            is_duplicate = False
            for past in previous_attempts:
                if past["tool"] == new_tool and past["arguments"] == new_args and not has_targeted_change:
                    is_duplicate = True
                    break

            if is_duplicate:
                audit_logger.log_event(
                    "RETRY_DUPLICATE_PREVENTED",
                    action="diagnose",
                    extra={"tool": new_tool, "args": new_args, "attempt": step.attempts}
                )
                self._record_event(context, "retry_duplicate_prevented", step_id=step.id)
                step.status = StepStatus.BLOCKED
                context.requires_human_input = True
                context.blocker_reason = (
                    f"Step '{step.title}' produced identical failed action ({new_tool}); "
                    f"stopping useless retry loop after attempt {step.attempts}."
                )
                return False

            # Update step parameters
            step.tool = new_tool
            step.arguments = new_args
            step.payload = new_args

            # Retry ACT & VERIFY
            self._record_event(context, "retry_started", step_id=step.id, tool=new_tool, extra={"attempt": step.attempts})
            result = self.act(step, context)
            if self.verify(step, result, context=context):
                return True

        # Exceeded max retries
        step.status = StepStatus.BLOCKED
        context.requires_human_input = True
        context.blocker_reason = (
            f"Step '{step.title}' failed after {step.attempts} attempts. "
            f"Last error: {step.error_message}. Escalating to user."
        )
        self._record_event(context, "step_blocked", step_id=step.id, extra={"attempts": step.attempts, "error": step.error_message})
        self.voice.speak("Step failed multiple times. User review required.")
        return False

    # 6. REFLECT
    def reflect(self, context: TaskContext) -> Reflection:
        """Synthesize concise 1-3 line lesson learned."""
        total_steps = len(context.steps)
        approach = f"Executed {total_steps} planned steps with rigorous automated verification."
        if context.diagnoses:
            approach += f" Encountered and addressed {len(context.diagnoses)} intermediate errors."
        if context.sources:
            approach += f" Researched {len(context.sources)} web sources with prompt-injection filtering."

        if context.is_completed:
            result = f"All {total_steps} steps passed verification criteria."
            if context.sources and context.evidence:
                lesson = f"Synthesized research on '{context.task[:60]}' with {len(context.evidence)} verified claims."
            else:
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
    def persist(self, reflection: Reflection, project_id: Optional[str] = None) -> None:
        """Append reflection to memory/zara_log.md and extract structured memories."""
        self.memory.append_reflection(reflection)
        if hasattr(self, "memory_extractor") and self.memory_extractor:
            try:
                pid = project_id or (self.project_manager.project.project_id if self.project_manager and getattr(self.project_manager, "project", None) else None)
                status = "completed" if "passed" in reflection.result.lower() else "failed"
                err = reflection.lesson if status == "failed" else None
                candidates = self.memory_extractor.extract_from_task_result(
                    task_id=f"refl-{uuid.uuid4().hex[:6]}",
                    goal=reflection.task,
                    result={"status": status, "summary": reflection.result, "error": err},
                    project_id=pid
                )
                for item in candidates:
                    self.memory.store_memory(item)
            except Exception:
                pass

    # 8. CONTINUE OR REPORT (Full Loop)
    def run_task(
        self,
        task: str,
        tag: str = "dev",
        steps: Optional[List[PlanStep]] = None
    ) -> Dict[str, Any]:
        """Full autonomous state machine loop."""
        # 0. Check Project Budget if running within a ProjectManager
        if self.project_manager and getattr(self.project_manager, "project", None):
            exceeded, reason = self.project_manager.project.budget.is_exceeded()
            if exceeded:
                context = self.perceive(task, tag)
                context.is_completed = False
                context.requires_human_input = True
                context.blocker_reason = f"Project budget exceeded: {reason}"
                self._record_event(context, "budget_exceeded", extra={"reason": reason})
                reflection = self.reflect(context)
                self.persist(reflection)
                return {
                    "task": context.task,
                    "status": "BLOCKED",
                    "steps_total": 0,
                    "steps_passed": 0,
                    "steps_skipped": 0,
                    "steps_failed": 0,
                    "blocker_reason": context.blocker_reason,
                    "reflection": reflection.to_markdown(),
                    "past_lessons_used": len(context.past_lessons),
                    "total_retries": 0,
                    "events_count": len(context.events)
                }

        # 1. PERCEIVE
        context = self.perceive(task, tag)

        # 2. PLAN
        self.plan(context, custom_steps=steps)

        # If planning produced no steps (e.g. invalid plan refused shell execution)
        if not context.steps:
            context.is_completed = False
            reflection = self.reflect(context)
            self.persist(reflection)
            self._record_event(context, "task_failed", extra={"reason": context.blocker_reason})
            return {
                "task": context.task,
                "status": "BLOCKED",
                "steps_total": 0,
                "steps_passed": 0,
                "steps_skipped": 0,
                "steps_failed": 0,
                "blocker_reason": context.blocker_reason or "No valid plan generated",
                "reflection": reflection.to_markdown(),
                "past_lessons_used": len(context.past_lessons),
                "total_retries": 0,
                "events_count": len(context.events)
            }

        # Step 3 -> 4 -> 5 Loop
        for i, step in enumerate(context.steps):
            context.current_step_index = i

            # Check execution time budget
            elapsed = time.time() - context.start_time
            if elapsed > self.max_execution_time_seconds:
                step.status = StepStatus.SKIPPED
                step.failure_type = FailureType.TIMEOUT.value
                context.is_completed = False
                context.requires_human_input = True
                context.blocker_reason = f"Task execution time exceeded limit ({elapsed:.1f}s > {self.max_execution_time_seconds}s)."
                self._record_event(context, "task_timeout", extra={"elapsed": elapsed})
                break

            # Check step dependencies
            prereq_failed = False
            failed_dep_id = None
            if step.dependencies:
                for dep_id in step.dependencies:
                    dep_step = next((s for s in context.steps if s.id == dep_id), None)
                    if not dep_step or dep_step.status != StepStatus.PASSED:
                        prereq_failed = True
                        failed_dep_id = dep_id
                        break

            if prereq_failed:
                step.status = StepStatus.SKIPPED
                step.failure_type = FailureType.DEPENDENCY_FAILURE.value
                step.error_message = f"Dependency step {failed_dep_id} did not pass verification."
                self._record_event(
                    context,
                    "step_skipped",
                    step_id=step.id,
                    status="skipped",
                    extra={"failed_dependency": failed_dep_id}
                )
                continue

            result = self.act(step, context)

            is_verified = self.verify(step, result, context=context)
            if not is_verified:
                success_after_retry = self.diagnose_and_retry(step, result, context)
                if not success_after_retry:
                    # Mark all downstream steps that depend on the failed step as skipped
                    for remaining_step in context.steps[i + 1:]:
                        if step.id in remaining_step.dependencies or any(
                            s.id in remaining_step.dependencies and s.status == StepStatus.SKIPPED
                            for s in context.steps
                        ):
                            remaining_step.status = StepStatus.SKIPPED
                            remaining_step.failure_type = FailureType.DEPENDENCY_FAILURE.value
                            remaining_step.error_message = f"Prerequisite step {step.id} failed."
                            self._record_event(
                                context,
                                "step_skipped",
                                step_id=remaining_step.id,
                                status="skipped",
                                extra={"failed_dependency": step.id}
                            )
                    break

            # Save checkpoint after each verified step for crash recovery
            self.recovery.save_checkpoint(context)
            if self.project_manager and getattr(self.project_manager, "project", None):
                try:
                    self.project_manager.create_checkpoint(
                        task_id=f"step_{step.id}",
                        state_snapshot={"current_step_index": i, "task": context.task},
                        completed_steps=[{"id": s.id, "title": s.title, "status": s.status.value} for s in context.steps[:i+1]],
                        pending_steps=[{"id": s.id, "title": s.title, "status": s.status.value} for s in context.steps[i+1:]],
                        verification=step.verification
                    )
                except Exception:
                    pass

        # Check completion
        context.is_completed = bool(context.steps) and all(s.status == StepStatus.PASSED for s in context.steps)

        # Persist pending approval ticket if human confirmation is pending
        if getattr(context, "pending_confirmation", None) and self.project_manager:
            try:
                ticket_dict = context.pending_confirmation.to_dict() if hasattr(context.pending_confirmation, "to_dict") else vars(context.pending_confirmation)
                self.project_manager.request_approval(ticket_dict)
            except Exception:
                pass

        # Record project budget elapsed time and passed steps
        if self.project_manager and getattr(self.project_manager, "project", None):
            try:
                elapsed = time.time() - context.start_time
                passed_steps = sum(1 for s in context.steps if s.status == StepStatus.PASSED)
                self.project_manager.project.budget.record(steps=passed_steps, exec_time=elapsed)
                self.project_manager.save_manifest()
            except Exception:
                pass

        if context.is_completed:
            self._record_event(context, "task_completed", status="success")
        else:
            self._record_event(context, "task_failed", status="failed", extra={"reason": context.blocker_reason})

        # Research Report Synthesis if research occurred
        if (context.sources or "research" in context.task.lower()) and not context.research_report:
            self.research.synthesize_report(context.task, context)

        # 6. REFLECT
        reflection = self.reflect(context)

        # 7. PERSIST
        self.persist(reflection)

        # Phase 12: Persist normalized world state to project workspace if active
        if self.project_manager and hasattr(self.project_manager, "save_world_state") and hasattr(self, "world_model") and self.world_model:
            try:
                self.project_manager.save_world_state(self.world_model.current_state.to_dict())
            except Exception:
                pass

        # Self-improvement evaluation
        self.self_improvement.evaluate_task(context)

        # 8. REPORT
        summary = {
            "task": context.task,
            "status": "COMPLETED" if context.is_completed else "BLOCKED",
            "steps_total": len(context.steps),
            "steps_passed": sum(1 for s in context.steps if s.status == StepStatus.PASSED),
            "steps_skipped": sum(1 for s in context.steps if s.status == StepStatus.SKIPPED),
            "steps_failed": sum(1 for s in context.steps if s.status in (StepStatus.FAILED, StepStatus.BLOCKED)),
            "blocker_reason": context.blocker_reason,
            "reflection": reflection.to_markdown(),
            "past_lessons_used": len(context.past_lessons),
            "total_retries": context.total_retries,
            "events_count": len(context.events),
            "diff_summary": context.get_diff_summary(),
            "research_report": context.research_report.to_markdown() if context.research_report else None,
            "sources_count": len(context.sources),
            "evidence_count": len(context.evidence)
        }

        if context.is_completed:
            self.voice.speak("Task verified and completed successfully.")
        else:
            self.voice.speak("Task execution paused. Action requires human input.")

        return summary

    def _notify_step(self, stage: str, step: PlanStep) -> None:
        if self.on_step_update:
            self.on_step_update(stage, step)

    def execute_task(self, task: str, tag: str = "dev", steps: Optional[List[PlanStep]] = None) -> Dict[str, Any]:
        """Convenience alias for run_task."""
        return self.run_task(task=task, tag=tag, steps=steps)

    def autonomous_tick(self, clock_time: Optional[float] = None) -> Dict[str, Any]:
        """
        Heartbeat for proactive autonomy: processes due scheduled tasks,
        maintains persistent queues, verifies security target scope,
        gates critical actions behind human confirmation tickets,
        and strictly enforces resource budgets.
        """
        if clock_time is not None and hasattr(self.clock, "set_time"):
            import datetime as _dt_mod
            new_dt = _dt_mod.datetime.fromtimestamp(clock_time, tz=_dt_mod.timezone.utc)
            self.clock.set_time(new_dt)

        # 1. Mode Gate: OFF vs ON
        if not self.autonomous.is_enabled():
            return {
                "status": "PAUSED_AUTONOMOUS_OFF",
                "reason": "Autonomous execution is disabled (AUTONOMOUS MODE: OFF).",
                "executed_jobs": [],
                "budget": self.autonomous.budget.to_dict()
            }

        # 2. Daily Resource Budget Gate
        can_run, budget_reason = self.autonomous.can_execute_autonomously()
        if not can_run:
            self.notifications.notify(
                title="Autonomous Mode Paused",
                message=f"Autonomous execution paused: {budget_reason}",
                severity=NotificationSeverity.WARNING
            )
            return {
                "status": "PAUSED_BY_BUDGET",
                "reason": budget_reason,
                "executed_jobs": [],
                "budget": self.autonomous.budget.to_dict()
            }

        now_dt = self.clock.now()
        is_quiet = self.autonomous.quiet_hours.is_quiet_hours(now_dt)
        if not is_quiet:
            self.notifications.flush_quiet_hours_queue()

        # 3. Startup Recovery for Missed Schedules
        self.scheduler.recover_missed_schedules()

        due_jobs = self.scheduler.get_due_jobs()
        executed_jobs = []

        for job in due_jobs:
            # Quiet Hours Policy: Defer non-critical jobs during quiet hours
            if is_quiet and job.priority != JobPriority.CRITICAL:
                continue

            can_run, budget_reason = self.autonomous.can_execute_autonomously()
            if not can_run:
                break

            # Safety Gate 1: Cybersecurity Target Scope Verification
            if job.capability == "cybersecurity" or any(kw in (job.name + " " + str(job.action_payload)).lower() for kw in ["scan", "exploit", "audit", "nmap", "sql"]):
                target = job.action_payload.get("target") or job.metadata.get("target")
                if target:
                    is_auth, target_obj, reason = self.cyber_lab.scope.verify_target(target)
                    if not is_auth:
                        self.scheduler.mark_job_failed(job.job_id, error=f"ScopeViolation: {reason}")
                        self.notifications.notify(
                            title="Cybersecurity Scope Violation",
                            message=f"Job {job.job_id} cancelled: {reason}",
                            severity=NotificationSeverity.CRITICAL
                        )
                        continue

            # Safety Gate 2: Human Confirmation Ticket Verification
            if job.metadata.get("requires_approval") or job.action_payload.get("requires_approval") or job.priority == JobPriority.CRITICAL:
                if not job.metadata.get("approved", False):
                    job.status = JobStatus.WAITING_APPROVAL
                    self.scheduler.save()
                    ticket = {
                        "ticket_id": f"ticket_{job.job_id}",
                        "job_id": job.job_id,
                        "title": job.name,
                        "action": job.action_payload.get("task") or job.name,
                        "status": "PENDING"
                    }
                    if self.project_manager:
                        self.project_manager.request_approval(ticket)
                    self.notifications.notify(
                        title="Scheduled Job Awaiting Approval",
                        message=f"Job '{job.name}' ({job.job_id}) requires human confirmation.",
                        severity=NotificationSeverity.WARNING,
                        is_quiet_hours=is_quiet
                    )
                    continue

            # Execute Scheduled Job
            self.scheduler.mark_job_running(job.job_id)
            self.event_bus.publish(Event(
                type=EventType.SCHEDULED_JOB_TRIGGERED,
                source="scheduler",
                payload={"job_id": job.job_id, "name": job.name}
            ))

            task_str = job.action_payload.get("task") or job.name
            custom_steps = job.action_payload.get("steps")

            # Phase 11 Proactive Planning Pipeline:
            # SCHEDULE -> GOAL UNDERSTANDING -> PLAN VALIDATION -> BUDGET CHECK -> SAFETY CHECK -> EXECUTION
            goal = self.understand_goal(task_str)
            if goal.ambiguity_level in (AmbiguityLevel.HIGH, AmbiguityLevel.CRITICAL) and not custom_steps:
                self.scheduler.mark_job_failed(job.job_id, error=f"AmbiguousGoal: {goal.clarification_question or 'High ambiguity'}")
                self.notifications.notify(
                    title="Scheduled Job Ambiguous",
                    message=f"Job '{job.name}' requires clarification: {goal.clarification_question}",
                    severity=NotificationSeverity.WARNING,
                    is_quiet_hours=is_quiet
                )
                executed_jobs.append({"job_id": job.job_id, "status": "FAILED", "reason": "AmbiguousGoal"})
                continue

            start_t = time.time()
            result = self.execute_task(task_str, steps=custom_steps)
            duration = time.time() - start_t

            self.autonomous.budget.record(
                runs=1,
                tool_calls=result.get("steps_total", 1),
                runtime_seconds=duration,
                retries=result.get("total_retries", 0)
            )
            self.autonomous.save()

            if result.get("status") == "COMPLETED":
                self.scheduler.mark_job_completed(job.job_id)
                self.event_bus.publish(Event(
                    type=EventType.TASK_COMPLETED,
                    source="scheduler",
                    payload={"job_id": job.job_id, "status": "COMPLETED"}
                ))
                self.notifications.notify(
                    title="Scheduled Job Succeeded",
                    message=f"Job '{job.name}' completed successfully.",
                    severity=NotificationSeverity.INFO,
                    is_quiet_hours=is_quiet
                )
                executed_jobs.append({"job_id": job.job_id, "status": "COMPLETED", "result": result})
            else:
                self.scheduler.mark_job_failed(job.job_id, error=result.get("blocker_reason") or "Failed")
                self.event_bus.publish(Event(
                    type=EventType.TASK_FAILED,
                    source="scheduler",
                    payload={"job_id": job.job_id, "reason": result.get("blocker_reason")}
                ))
                self.notifications.notify(
                    title="Scheduled Job Failed",
                    message=f"Job '{job.name}' failed: {result.get('blocker_reason')}",
                    severity=NotificationSeverity.WARNING,
                    is_quiet_hours=is_quiet
                )
                executed_jobs.append({"job_id": job.job_id, "status": "FAILED", "result": result})

        self.event_bus.publish(Event(
            type=EventType.AUTONOMOUS_TICK,
            source="engine",
            payload={"executed_count": len(executed_jobs), "due_count": len(due_jobs)}
        ))

        return {
            "status": "OK",
            "executed_jobs": executed_jobs,
            "due_jobs_count": len(due_jobs),
            "budget": self.autonomous.budget.to_dict()
        }

    def close(self) -> None:
        """Cleanly close underlying memory store and resources."""
        if hasattr(self, "memory") and hasattr(self.memory, "close"):
            self.memory.close()


