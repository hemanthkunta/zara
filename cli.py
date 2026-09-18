"""
ZARA Command-Line Interface (CLI): Interactive console for ZARA Autonomous Agent.
Supports run, chat (conversational mode), gui, tools, memory, recover, and test.
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path
from core.engine import ZaraEngine
from core.conversation import ConversationalSession
from core.state import PlanStep, StepStatus, ActionType
from core.recovery import RecoveryManager
from modules.memory import MemoryStore
from modules.voice import VoiceSynthesizer
from config.settings import MEMORY_FILE, ENABLE_VOICE, UI_HOST, UI_PORT

class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def print_banner():
    banner = f"""
{Colors.CYAN}{Colors.BOLD}
  ███████╗ █████╗ ██████╗  █████╗ 
  ╚══███╔╝██╔══██╗██╔══██╗██╔══██╗
    ███╔╝ ███████║██████╔╝███████║
   ███╔╝  ██╔══██║██╔══██╗██╔══██║
  ███████╗██║  ██║██║  ██║██║  ██║
  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝
  Autonomous Personal Engineering & Research Agent
  Looping Engine • File-based Self-Learning • Voice Feedback
{Colors.END}"""
    print(banner)

def step_callback(stage: str, step: PlanStep):
    if "ACT" in stage:
        print(f"  {Colors.BLUE}► [{stage}]{Colors.END} Step {step.id}: {step.title}")
    elif "VERIFY" in stage:
        print(f"  {Colors.CYAN}✔ [{stage}]{Colors.END} Checking: '{step.success_condition}'")
    elif "DIAGNOSE" in stage:
        print(f"  {Colors.YELLOW}⚠ [{stage}]{Colors.END} Analyzing failure on step {step.id}...")
    elif "FAILED" in stage:
        print(f"  {Colors.RED}✘ [{stage}]{Colors.END} {step.error_message}")

def cmd_run(args):
    print_banner()
    print(f"{Colors.BOLD}Task:{Colors.END} {args.task}")
    print(f"{Colors.BOLD}Category/Tag:{Colors.END} {args.tag}\n")

    engine = ZaraEngine(
        use_docker=args.docker,
        enable_voice=(not args.no_voice and ENABLE_VOICE),
        on_step_update=step_callback
    )

    print(f"{Colors.GREEN}[PERCEIVE]{Colors.END} Loading context and past lessons from memory...")
    summary = engine.run_task(args.task, tag=args.tag)

    print(f"\n{Colors.BOLD}=== ZARA TASK REPORT ==={Colors.END}")
    status_color = Colors.GREEN if summary["status"] == "COMPLETED" else Colors.RED
    print(f"Status: {status_color}{summary['status']}{Colors.END}")
    print(f"Steps Passed: {summary['steps_passed']} / {summary['steps_total']}")
    if summary.get("blocker_reason"):
        print(f"{Colors.RED}Blocker: {summary['blocker_reason']}{Colors.END}")

    print(f"\n{Colors.BOLD}Self-Learning Memory Reflection Appended:{Colors.END}")
    print(summary["reflection"])

def cmd_chat(args):
    print_banner()
    print(f"{Colors.GREEN}Entering Conversational Mode with ZARA. Type 'exit' or 'quit' to end.{Colors.END}\n")

    engine = ZaraEngine(
        use_docker=args.docker,
        enable_voice=(not args.no_voice and ENABLE_VOICE),
        on_step_update=step_callback
    )
    session = ConversationalSession(engine)

    while True:
        try:
            user_input = input(f"{Colors.BOLD}You > {Colors.END}").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print(f"{Colors.CYAN}ZARA: Goodbye! Session saved.{Colors.END}")
                break

            reply = session.process_user_input(user_input)
            print(f"{Colors.CYAN}{Colors.BOLD}ZARA >{Colors.END} {reply}\n")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.CYAN}Session ended.{Colors.END}")
            break

def cmd_tools(args):
    engine = ZaraEngine(enable_voice=False)
    tools_list = engine.tools.list_tools()
    print(f"\n{Colors.CYAN}{Colors.BOLD}ZARA REGISTERED TOOLS ({len(tools_list)} tools):{Colors.END}\n")
    for t in tools_list:
        risk_color = Colors.GREEN if t["risk_level"] == "LOW" else (Colors.YELLOW if t["risk_level"] == "MEDIUM" else Colors.RED)
        print(f"• {Colors.BOLD}{t['name']}{Colors.END} [{risk_color}{t['risk_level']}{Colors.END}]")
        print(f"  {t['description']}")
        print(f"  Parameters: {list(t['parameters'].get('properties', {}).keys())}\n")

def cmd_recover(args):
    recovery = RecoveryManager()
    checkpoints = recovery.list_checkpoints()
    print(f"\n{Colors.CYAN}{Colors.BOLD}ZARA TASK RECOVERY & CHECKPOINTS:{Colors.END}\n")
    if not checkpoints:
        print("No active checkpoints found.")
        return
    for i, c in enumerate(checkpoints):
        status = "COMPLETED" if c["completed"] else "INCOMPLETE"
        color = Colors.GREEN if c["completed"] else Colors.YELLOW
        print(f"[{i+1}] {c['task']} — {color}{status}{Colors.END} (Step {c['current_step']}/{c['total_steps']})")
        print(f"    Saved: {c['checkpoint_time']} | File: {c['file']}")

def cmd_gui(args):
    print(f"{Colors.CYAN}Launching ZARA Desktop GUI...{Colors.END}")
    from gui.app import launch_gui
    launch_gui()

def cmd_memory(args):
    store = MemoryStore()
    try:
        if getattr(args, "stats", False):
            stats = store.get_stats()
            print(f"\n{Colors.CYAN}{Colors.BOLD}=== ZARA Memory Subsystem Stats ==={Colors.END}")
            print(f"Total Memories: {stats.total_memories}")
            print(f"Active Memories: {stats.active_memories}")
            print(f"Conflicts Recorded: {stats.conflict_count}")
            print(f"Average Confidence: {stats.average_confidence:.2f}")
            print(f"\n{Colors.BOLD}By Scope:{Colors.END}")
            for sc, cnt in stats.by_scope.items():
                print(f"  - {sc}: {cnt}")
            print(f"\n{Colors.BOLD}By Type:{Colors.END}")
            for tp, cnt in stats.by_type.items():
                print(f"  - {tp}: {cnt}")
            print("-" * 50)
            return

        if getattr(args, "conflicts", False):
            confs = store.get_conflicts()
            print(f"\n{Colors.YELLOW}{Colors.BOLD}=== Recorded Memory Conflicts ({len(confs)}) ==={Colors.END}")
            if not confs:
                print("No memory conflicts recorded.")
                return
            for c in confs:
                print(f"[{c.conflict_id}] Status: {c.status.value} (Type: {c.conflict_type})")
                print(f"  Description: {c.description}")
                print(f"  Item A: {c.item_a_id} | Item B: {c.item_b_id}")
                if c.resolution_note:
                    print(f"  Resolution: {c.resolution_note}")
                print("-" * 50)
            return

        if getattr(args, "export", None):
            export_path = Path(args.export)
            items = store.retrieve(query="", limit=500, min_confidence=0.0)
            data = [i.to_dict() for i in items]
            export_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"{Colors.GREEN}Successfully exported {len(data)} memories to {export_path}{Colors.END}")
            return

        if getattr(args, "recent", False):
            items = store.retrieve(query="", limit=10, min_confidence=0.0)
            print(f"\n{Colors.CYAN}{Colors.BOLD}=== Recent Memories ({len(items)}) ==={Colors.END}\n")
            for m in items:
                print(f"[{m.type.value}] ({m.scope.value}) Conf: {m.confidence:.2f} | Imp: {m.importance:.2f}")
                print(f"  {m.content}")
                print("-" * 50)
            return

        if args.query:
            print(f"\n{Colors.CYAN}Searching ZARA Memory for:{Colors.END} '{args.query}'\n")
            from modules.memory import MemoryScope, MemoryType
            scope_enum = None
            if getattr(args, "scope", None):
                try:
                    scope_enum = MemoryScope(args.scope.upper())
                except ValueError:
                    pass
            type_enum = None
            if getattr(args, "type", None):
                try:
                    type_enum = MemoryType(args.type.upper())
                except ValueError:
                    pass
            proj_id = getattr(args, "project", None)

            # Advanced hybrid retrieval
            adv_results = store.retrieve(
                query=args.query,
                project_id=proj_id,
                scope=scope_enum,
                memory_type=type_enum,
                limit=5
            )
            if adv_results:
                print(f"{Colors.GREEN}Structured Long-Term Memories ({len(adv_results)}):{Colors.END}")
                for m in adv_results:
                    print(f"[{m.type.value}] ({m.scope.value}) Conf: {m.confidence:.2f} | Imp: {m.importance:.2f}")
                    print(f"  {m.content}")
                    print("-" * 50)

            # Legacy reflection search
            results = store.search_lessons(args.query, limit=5)
            if results:
                print(f"\n{Colors.BLUE}Past Execution Reflections ({len(results)}):{Colors.END}")
                for r in results:
                    print(f"{Colors.BOLD}{r['header']}{Colors.END}")
                    if r.get("approach"):
                        print(f"  - Approach: {r['approach']}")
                    if r.get("result"):
                        print(f"  - Result: {r['result']}")
                    if r.get("lesson"):
                        print(f"  - Lesson: {r['lesson']}")
                    print("-" * 50)
            if not adv_results and not results:
                print("No matching memories or lessons found.")
        else:
            print(f"\n{Colors.CYAN}Reading all entries in {MEMORY_FILE}:{Colors.END}\n")
            entries = store.get_all_entries()
            for e in entries:
                print(e)
                print("-" * 50)
    finally:
        store.close()

def cmd_voice(args):
    print_banner()
    print(f"{Colors.CYAN}{Colors.BOLD}Starting ZARA Voice Mode.{Colors.END}")
    print(f"{Colors.GREEN}Say 'ZARA, <command>' or type input. Say 'Stop' or 'Cancel' to abort.{Colors.END}\n")

    from modules.voice_controller import VoiceInteractionController
    from modules.voice import MockSTTProvider, MockTTSProvider, NativeMacOSTTSProvider, LocalSTTProvider

    engine = ZaraEngine(
        use_docker=args.docker,
        enable_voice=not args.no_tts,
        on_step_update=step_callback
    )

    stt = MockSTTProvider() if args.mock else (LocalSTTProvider() if LocalSTTProvider().is_available() else MockSTTProvider())
    tts = MockTTSProvider() if (args.mock or args.no_tts) else NativeMacOSTTSProvider()
    controller = VoiceInteractionController(
        engine=engine,
        stt_provider=stt,
        tts_provider=tts,
        wake_word=args.wake_word,
        require_wake_word=args.require_wake
    )

    print(f"Voice interface active. State: {controller.current_state.value}")
    while True:
        try:
            user_input = input(f"{Colors.BOLD}Voice Input (spoken or simulated) > {Colors.END}").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print(f"{Colors.CYAN}ZARA: Exiting voice mode.{Colors.END}")
                break

            result = controller.process_utterance(user_input)
            print(f"{Colors.CYAN}{Colors.BOLD}ZARA (Spoken) >{Colors.END} {result.get('verbal_summary') or result.get('response')}\n")
        except (KeyboardInterrupt, EOFError):
            print(f"\n{Colors.CYAN}Voice mode exited.{Colors.END}")
            break

def cmd_voice_test(args):
    print(f"{Colors.CYAN}Testing ZARA Voice Output (Samantha / Female Voice)...{Colors.END}")
    voice = VoiceSynthesizer(enabled=True)
    voice.speak("Greetings. I am ZARA, your autonomous engineering and research agent. Voice interface is online.", async_mode=False)
    print(f"{Colors.GREEN}Voice test completed.{Colors.END}")

def cmd_project(args):
    from modules.workspace import ProjectManager, discover_projects
    from config.settings import PROJECTS_DIR

    action = getattr(args, "project_action", None) or "list"

    def _resolve_project(target: Optional[str]) -> Optional[ProjectManager]:
        if not target:
            # Check current directory
            if (Path.cwd() / ".zara" / "project.json").exists():
                return ProjectManager.load(Path.cwd())
            return None
        # Check by direct path
        target_path = Path(target).resolve()
        if (target_path / ".zara" / "project.json").exists():
            return ProjectManager.load(target_path)
        # Check by subdirectory under PROJECTS_DIR
        cand = PROJECTS_DIR / target
        if (cand / ".zara" / "project.json").exists():
            return ProjectManager.load(cand)
        # Search all discovered
        for p in discover_projects():
            if p.get("id") == target or p.get("name") == target:
                return ProjectManager.load(Path(p["path"]))
        return None

    if action == "create":
        name = args.name
        path = Path(args.path).resolve() if getattr(args, "path", None) else (PROJECTS_DIR / name).resolve()
        mgr = ProjectManager.create(name=name, workspace_path=path, description=getattr(args, "desc", "") or "")
        print(f"{Colors.GREEN}✔ Project '{mgr.project.name}' created at {mgr.workspace_path} (ID: {mgr.project.project_id}){Colors.END}")
    elif action == "list":
        projects = discover_projects()
        if not projects:
            print("No persistent projects found.")
        else:
            print(f"\n{Colors.BOLD}=== ZARA PERSISTENT PROJECTS ==={Colors.END}")
            for p in projects:
                print(f"  • {Colors.CYAN}{p['name']}{Colors.END} [{p['id']}] - Status: {p['status']} ({p['path']})")
            print()
    elif action == "status":
        mgr = _resolve_project(getattr(args, "target", None))
        if not mgr:
            print(f"{Colors.RED}Project not found.{Colors.END}")
            return
        status = mgr.get_status()
        print(f"\n{Colors.BOLD}ZARA PROJECT{Colors.END}")
        print("────────────────────────────")
        print(f"Name: {status['name']}")
        print(f"ID: {status['project_id']}")
        print(f"Status: {status['status'].upper()}")
        print(f"Workspace: {status['workspace_path']}")
        print(f"\nProgress:")
        print(f"{status['tasks_passed']} / {status['tasks_total']} tasks complete")
        print(f"\nArtifacts:\n{status['artifacts_count']}")
        print(f"\nCheckpoints:\n{status['checkpoints_count']}")
        budget = status['budget']
        print(f"\nBudget:\nSteps: {budget['steps_taken']} / {budget['max_steps']} | Retries: {budget['retries_used']} / {budget['max_retries']}")
        print(f"Tool Calls: {budget['tool_calls']} / {budget['max_tool_calls']}")
        print()
    elif action == "pause":
        mgr = _resolve_project(getattr(args, "target", None))
        if not mgr:
            print(f"{Colors.RED}Project not found.{Colors.END}")
            return
        mgr.pause_project()
        print(f"{Colors.YELLOW}Project '{mgr.project.name}' paused.{Colors.END}")
    elif action == "resume":
        mgr = _resolve_project(getattr(args, "target", None))
        if not mgr:
            print(f"{Colors.RED}Project not found.{Colors.END}")
            return
        res = mgr.resume_project()
        print(f"{Colors.GREEN}Project '{mgr.project.name}' resumed. Status: {res['status']}{Colors.END}")
    elif action == "cancel":
        mgr = _resolve_project(getattr(args, "target", None))
        if not mgr:
            print(f"{Colors.RED}Project not found.{Colors.END}")
            return
        mgr.cancel_project()
        print(f"{Colors.RED}Project '{mgr.project.name}' cancelled.{Colors.END}")
    elif action == "recover":
        mgr = _resolve_project(getattr(args, "target", None))
        if not mgr:
            print(f"{Colors.RED}Project not found.{Colors.END}")
            return
        rec = mgr.recover_project()
        print(f"{Colors.CYAN}Recovery complete: {rec['classification']} - {rec['action']}{Colors.END}")
    else:
        print(f"Unknown project action: {action}")

def cmd_schedule(args):
    from modules.scheduler import PersistentScheduler, ScheduleType, JobPriority
    scheduler = PersistentScheduler()
    action = getattr(args, "schedule_action", None) or "list"

    if action == "list":
        jobs = scheduler.list_jobs()
        if not jobs:
            print("No scheduled jobs found.")
        else:
            print(f"\n{Colors.BOLD}=== ZARA SCHEDULED JOBS ==={Colors.END}")
            for j in jobs:
                status_color = Colors.GREEN if j.status.value == "scheduled" else (
                    Colors.YELLOW if j.status.value == "running" else Colors.RED
                )
                print(f"  • {Colors.CYAN}{j.name}{Colors.END} [{j.job_id}] - {status_color}{j.status.value.upper()}{Colors.END} ({j.schedule_type.value}) Next: {j.next_run or 'None'} Priority: {j.priority.value}")
            print()
    elif action == "create":
        stype = ScheduleType(args.type)
        priority = JobPriority(args.priority) if hasattr(args, "priority") and args.priority else JobPriority.NORMAL
        job = scheduler.schedule_job(
            name=args.name,
            schedule_type=stype,
            cron_expression=getattr(args, "cron", None),
            interval_seconds=float(args.interval) if getattr(args, "interval", None) else None,
            priority=priority,
            action_payload={"task": args.task}
        )
        print(f"{Colors.GREEN}✔ Scheduled job '{job.name}' created with ID: {job.job_id} (Next run: {job.next_run}){Colors.END}")
    elif action == "status":
        job = scheduler.get_job(args.job_id)
        if not job:
            print(f"{Colors.RED}Job '{args.job_id}' not found.{Colors.END}")
        else:
            print(f"\n{Colors.BOLD}JOB: {job.name}{Colors.END} [{job.job_id}]")
            print(f"Status: {job.status.value.upper()} | Type: {job.schedule_type.value}")
            print(f"Next Run: {job.next_run or 'None'} | Last Run: {job.last_run or 'Never'}")
            print(f"Runs Completed: {job.runs_completed} / {job.max_runs or 'unlimited'}")
            print(f"Priority: {job.priority.value} | Retries Used: {job.retries_used}")
            print()
    elif action == "pause":
        if scheduler.pause_job(args.job_id):
            print(f"{Colors.YELLOW}Job '{args.job_id}' paused.{Colors.END}")
        else:
            print(f"{Colors.RED}Failed to pause job '{args.job_id}'.{Colors.END}")
    elif action == "resume":
        if scheduler.resume_job(args.job_id):
            print(f"{Colors.GREEN}Job '{args.job_id}' resumed.{Colors.END}")
        else:
            print(f"{Colors.RED}Failed to resume job '{args.job_id}'.{Colors.END}")
    elif action == "cancel":
        if scheduler.cancel_job(args.job_id):
            print(f"{Colors.RED}Job '{args.job_id}' cancelled.{Colors.END}")
        else:
            print(f"{Colors.RED}Failed to cancel job '{args.job_id}'.{Colors.END}")

def cmd_queue(args):
    from modules.scheduler import PersistentScheduler
    from modules.autonomous import DailyQueueSynthesizer
    action = getattr(args, "queue_action", None) or "list"
    scheduler = PersistentScheduler()
    synthesizer = DailyQueueSynthesizer(scheduler=scheduler)

    if action == "list":
        items = synthesizer.synthesize()
        if not items:
            print("Queue is empty. No ready items.")
        else:
            print(f"\n{Colors.BOLD}=== ZARA PRIORITIZED WORK QUEUE ==={Colors.END}")
            for idx, it in enumerate(items, 1):
                p_color = Colors.RED if it["priority"] == "critical" else (
                    Colors.YELLOW if it["priority"] == "high" else Colors.CYAN
                )
                print(f"  {idx}. [{it['source']}] {it['title']} ({p_color}{it['priority'].upper()}{Colors.END}) - {it['status']}")
            print()
    elif action == "pause":
        print(f"{Colors.YELLOW}Queue execution paused.{Colors.END}")
    elif action == "resume":
        print(f"{Colors.GREEN}Queue execution active.{Colors.END}")

def cmd_autonomous(args):
    from modules.autonomous import AutonomousModeManager
    mgr = AutonomousModeManager()
    action = getattr(args, "auto_action", None) or "status"

    if action == "status":
        print(f"\n{Colors.BOLD}=== ZARA AUTONOMOUS INTELLIGENCE ==={Colors.END}")
        mode_color = Colors.GREEN if mgr.is_enabled() else Colors.RED
        print(f"Autonomous Mode: {mode_color}{mgr.mode.value}{Colors.END}")
        b = mgr.budget
        print(f"Daily Budget:")
        print(f"  Runs: {b.runs_used} / {b.max_runs}")
        print(f"  Tool Calls: {b.tool_calls_used} / {b.max_tool_calls}")
        print(f"  Runtime: {b.runtime_seconds_used:.1f}s / {b.max_runtime_seconds:.1f}s")
        print(f"  Retries: {b.retries_used} / {b.max_retries}")
        print(f"Quiet Hours:")
        is_quiet = mgr.quiet_hours.is_quiet_hours()
        q_color = Colors.YELLOW if is_quiet else Colors.CYAN
        print(f"  Currently Quiet Hours: {q_color}{is_quiet}{Colors.END}")
        print()
    elif action in ("on", "enable"):
        mgr.enable()
        print(f"{Colors.GREEN}✔ Autonomous Mode ENABLED.{Colors.END}")
    elif action in ("off", "disable"):
        mgr.disable()
        print(f"{Colors.YELLOW}✔ Autonomous Mode DISABLED.{Colors.END}")

def cmd_plan(args):
    from modules.workspace import ProjectManager, discover_projects, PersistentTask
    from config.settings import PROJECTS_DIR
    from modules.planning import PlanValidator
    from modules.goals import Goal

    action = getattr(args, "plan_action", None) or "status"
    target = getattr(args, "project", None) or getattr(args, "target", None)

    def _resolve_project(target: Optional[str]) -> Optional[ProjectManager]:
        if not target:
            if (Path.cwd() / ".zara" / "project.json").exists():
                return ProjectManager.load(Path.cwd())
            return None
        target_path = Path(target).resolve()
        if (target_path / ".zara" / "project.json").exists():
            return ProjectManager.load(target_path)
        cand = PROJECTS_DIR / target
        if (cand / ".zara" / "project.json").exists():
            return ProjectManager.load(cand)
        for p in discover_projects():
            if p.get("id") == target or p.get("name") == target:
                return ProjectManager.load(Path(p["path"]))
        return None

    mgr = _resolve_project(target)
    if not mgr:
        print(f"{Colors.RED}Project not found or no target workspace specified.{Colors.END}")
        return

    planning_state = mgr.load_planning_state()
    goal_data = planning_state.get("goal")
    current_plan = planning_state.get("current_plan")
    history = planning_state.get("plan_history", [])

    if action in ("status", None):
        print(f"\n{Colors.BOLD}=== ZARA PLAN STATUS ==={Colors.END}")
        print(f"Project: {mgr.project.name} [{mgr.project.project_id}]")
        if goal_data:
            print(f"Goal: {goal_data.get('normalized_goal')}")
            print(f"Domain: {goal_data.get('domain')} | Ambiguity: {goal_data.get('ambiguity_level')}")
            print(f"Desired Outcome: {goal_data.get('desired_outcome')}")
        else:
            print("No structured goal registered.")
        if current_plan:
            print(f"\nActive Plan Version: {current_plan.get('version')} ({current_plan.get('plan_id')})")
            print(f"Reason: {current_plan.get('reason_for_change')}")
            print("Tasks:")
            for idx, t in enumerate(current_plan.get("tasks", []), start=1):
                print(f"  {idx}. [{t.get('capability', 'general').upper()}] {t.get('title')} ({t.get('status')})")
        else:
            print("No active plan registered.")
        print()

    elif action == "history":
        print(f"\n{Colors.BOLD}=== ZARA PLAN HISTORY ==={Colors.END}")
        print(f"Project: {mgr.project.name} [{mgr.project.project_id}]")
        if not history:
            print("No plan revision history found.")
        else:
            for p in history:
                parent = f" -> parent: {p.get('parent_plan_id')}" if p.get('parent_plan_id') else ""
                print(f"  • Plan v{p.get('version')} [{p.get('plan_id')}]{parent}")
                print(f"    Reason: {p.get('reason_for_change')}")
                print(f"    Tasks: {len(p.get('tasks', []))} | Created: {p.get('created_at')}")
        print()

    elif action == "validate":
        print(f"\n{Colors.BOLD}=== ZARA PLAN VALIDATION ==={Colors.END}")
        if not current_plan or not goal_data:
            print(f"{Colors.YELLOW}No plan or goal registered to validate.{Colors.END}")
            return
        goal = Goal.from_dict(goal_data)
        tasks = [PersistentTask.from_dict(t) for t in current_plan.get("tasks", [])]
        validation = PlanValidator.validate(goal=goal, tasks=tasks, budget=mgr.project.budget)
        if validation.valid:
            print(f"{Colors.GREEN}✔ Plan is VALID{Colors.END}")
        else:
            print(f"{Colors.RED}✘ Plan is INVALID{Colors.END}")
            for err in validation.errors:
                print(f"  ! {err}")
        if validation.warnings:
            print("Warnings:")
            for w in validation.warnings:
                print(f"  * {w}")
        if validation.required_approvals:
            print("Required Approvals:")
            for a in validation.required_approvals:
                print(f"  [APPROVAL] {a}")
        print()

    elif action == "approve":
        print(f"\n{Colors.BOLD}=== ZARA PLAN APPROVAL ==={Colors.END}")
        if mgr.pending_approval_ticket:
            ticket_id = mgr.pending_approval_ticket.get("ticket_id")
            mgr.resolve_approval(ticket_id=ticket_id, approved=True)
            print(f"{Colors.GREEN}✔ Pending plan/ticket approved successfully.{Colors.END}")
        else:
            print(f"{Colors.YELLOW}No pending approval tickets for this project.{Colors.END}")
        print()

def cmd_decisions(args):
    from modules.workspace import ProjectManager, discover_projects
    from config.settings import PROJECTS_DIR, DECISIONS_LOG_FILE
    from modules.planning import DecisionRegistry, DecisionRecord

    target = getattr(args, "project", None)
    registry = DecisionRegistry(DECISIONS_LOG_FILE)

    if target:
        def _resolve_project(target: Optional[str]) -> Optional[ProjectManager]:
            if not target:
                if (Path.cwd() / ".zara" / "project.json").exists():
                    return ProjectManager.load(Path.cwd())
                return None
            target_path = Path(target).resolve()
            if (target_path / ".zara" / "project.json").exists():
                return ProjectManager.load(target_path)
            cand = PROJECTS_DIR / target
            if (cand / ".zara" / "project.json").exists():
                return ProjectManager.load(cand)
            for p in discover_projects():
                if p.get("id") == target or p.get("name") == target:
                    return ProjectManager.load(Path(p["path"]))
            return None

        mgr = _resolve_project(target)
        if mgr:
            proj_id = mgr.project.project_id
            decisions = [d for d in registry.decisions if d.project_id == proj_id] or [
                DecisionRecord.from_dict(d) for d in mgr.list_decisions()
            ]
        else:
            decisions = [d for d in registry.decisions if d.project_id == target]
    else:
        decisions = registry.decisions

    print(f"\n{Colors.BOLD}=== ZARA OPERATIONAL DECISION RECORDS ==={Colors.END}")
    if not decisions:
        print("No decision records found.")
    else:
        for d in decisions:
            print(f"  • [{d.timestamp[:19]}] {Colors.CYAN}{d.question}{Colors.END}")
            print(f"    Selected: {Colors.GREEN}{d.selected_option}{Colors.END}")
            print(f"    Rationale: {d.rationale_summary}")
            if d.evidence:
                print(f"    Evidence: {d.evidence}")
    print()

def cmd_test(args):
    print(f"{Colors.CYAN}Running ZARA test suite...{Colors.END}")
    subprocess.run(["python3", "-m", "unittest", "discover", "tests", "-v"])

def cmd_world(args):
    """Inspect and manage ZARA Unified Multimodal World Model."""
    from modules.world_model import WorldModel, Modality, TemporalStatus, WorldState
    from modules.workspace import ProjectManager, discover_projects
    from config.settings import PROJECTS_DIR

    action = getattr(args, "world_action", None) or "status"
    target = getattr(args, "project", None) or getattr(args, "target", None)

    workspace_path = Path.cwd()
    if target:
        cand = Path(target).resolve()
        if (cand / ".zara").exists():
            workspace_path = cand
        elif (PROJECTS_DIR / target / ".zara").exists():
            workspace_path = PROJECTS_DIR / target

    pm = None
    if (workspace_path / ".zara" / "project.json").exists():
        try:
            pm = ProjectManager.load(workspace_path)
        except Exception:
            pass

    wm = WorldModel(workspace_root=str(workspace_path))
    if pm and hasattr(pm, "load_world_state"):
        saved = pm.load_world_state()
        if saved:
            wm.current_state = WorldState.from_dict(saved)

    if action in ("status", None):
        print(f"\n{Colors.BOLD}=== ZARA WORLD STATE ==={Colors.END}")
        active_app = wm.get_active_app() or "Desktop / None"
        active_win = wm.get_active_window() or "None"
        active_proj = wm.get_active_project() or (pm.project.name if pm and pm.project else "None")
        active_task = wm.get_active_task() or "None"
        term_proc = (wm.current_state.terminal_state or {}).get("command") or "None"
        last_obs = wm.current_state.timestamp or "Never"
        conf = wm.current_state.confidence
        conf_str = f"{conf:.2f}" if isinstance(conf, float) else str(conf)

        print(f"Active App:        {Colors.CYAN}{active_app}{Colors.END}")
        print(f"Active Window:     {Colors.CYAN}{active_win}{Colors.END}")
        print(f"Project:           {Colors.GREEN}{active_proj}{Colors.END}")
        print(f"Task:              {Colors.YELLOW}{active_task}{Colors.END}")
        print(f"Terminal:          {term_proc}")
        print(f"Entities Count:    {len(wm.entities)}")
        print(f"Relations Count:   {len(wm.relationships)}")
        print(f"Last Observation:  {last_obs}")
        print(f"Confidence:        {Colors.BOLD}{conf_str}{Colors.END}")
        print(f"\nModality Freshness:")
        for m in [Modality.SCREEN, Modality.FILESYSTEM, Modality.BROWSER, Modality.BLENDER, Modality.CYBER, Modality.TERMINAL]:
            staleness = wm.get_staleness(m).value.upper()
            color = Colors.GREEN if staleness == "CURRENT" else (Colors.YELLOW if staleness == "RECENT" else Colors.RED)
            print(f"  • {m.value.capitalize():<12}: {color}{staleness}{Colors.END}")
        print()

    elif action == "snapshot":
        snap = wm.create_snapshot(active_project=pm.project.project_id if pm and pm.project else None)
        if pm and hasattr(pm, "save_world_snapshot"):
            snap_file = pm.save_world_snapshot(snap)
            print(f"{Colors.GREEN}World snapshot created and saved: {snap.snapshot_id} -> {snap_file.name}{Colors.END}")
        else:
            print(f"{Colors.GREEN}World snapshot created in memory: {snap.snapshot_id}{Colors.END}")

    elif action == "diff":
        diff_res = wm.get_world_diff()
        print(f"\n{Colors.BOLD}=== ZARA WORLD STATE DIFF ==={Colors.END}")
        if not diff_res.get("has_changes"):
            print("No changes between previous and current world states.")
        else:
            print(f"Total Changes: {diff_res.get('changes_count')}")
            for k, v in diff_res.get("changes", {}).items():
                print(f"  • {k}: {v.get('previous')} -> {v.get('current')}")
        print()

    elif action == "refresh":
        print(f"{Colors.CYAN}Refreshing world state modalities...{Colors.END}")
        wm.refresh()
        print(f"{Colors.GREEN}World state refreshed.{Colors.END}")

def cmd_ui(args):
    import urllib.request
    import json
    import webbrowser

    host = getattr(args, "host", None) or UI_HOST
    port = getattr(args, "port", None) or UI_PORT
    action = getattr(args, "ui_action", None)

    if action == "status":
        print(f"\n{Colors.CYAN}{Colors.BOLD}=== ZARA COMMAND CENTER UI STATUS ==={Colors.END}")
        url = f"http://{host}:{port}/api/health"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZARA-CLI"})
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                print(f"Status:   {Colors.GREEN}{data.get('status', 'RUNNING').upper()}{Colors.END}")
                print(f"Endpoint: {Colors.CYAN}http://{host}:{port}{Colors.END}")
                print(f"Clients:  {data.get('connected_clients', 0)}")
                print(f"Uptime:   {data.get('uptime_seconds', 0):.1f}s\n")
                return
        except Exception as e:
            print(f"Status:   {Colors.RED}STOPPED / UNREACHABLE{Colors.END}")
            print(f"Target:   http://{host}:{port}")
            print(f"Detail:   {e}\n")
            return

    print_banner()
    print(f"{Colors.GREEN}{Colors.BOLD}Starting ZARA Unified Command Center UI...{Colors.END}")
    print(f"Local Server: {Colors.CYAN}http://{host}:{port}{Colors.END}")
    print(f"Press Ctrl+C to shutdown.\n")

    if getattr(args, "open", False):
        try:
            webbrowser.open(f"http://{host}:{port}")
        except Exception:
            pass

    import uvicorn
    from ui.server import create_ui_app
    app = create_ui_app()
    uvicorn.run(app, host=host, port=port, log_level="info")

def cmd_workers(args):
    """Inspect and manage multi-agent parallel workers and resource locks (Phase 15)."""
    from modules.workers import WorkstreamOrchestrator, WorkerStatus
    from modules.resource_locking import ResourceManager

    action = getattr(args, "workers_action", None) or "status"
    engine = ZaraEngine()

    try:
        orch = engine.workstream_orchestrator
        rm = engine.resource_manager

        if action == "status":
            metrics = orch.get_metrics()
            print(f"\n{Colors.BOLD}=== ZARA MULTI-AGENT WORKERS ==={Colors.END}")
            print(f"Total Workers:       {metrics['total_workers']}")
            print(f"Active (Running):    {Colors.GREEN}{metrics['active_workers']}{Colors.END}")
            print(f"Completed:           {Colors.CYAN}{metrics['completed_workers']}{Colors.END}")
            print(f"Failed:              {Colors.RED}{metrics['failed_workers']}{Colors.END}")
            print(f"Waiting / Blocked:   {Colors.YELLOW}{metrics['waiting_workers']}{Colors.END}")
            print(f"Active Locks:        {metrics['active_locks']}")
            print(f"Concurrency Limit:   {metrics['max_concurrency_limit']}")
            print(f"Success Rate:        {int(metrics['success_rate'] * 100)}%\n")

        elif action == "list":
            st_filter = None
            if getattr(args, "status", None):
                try:
                    st_filter = WorkerStatus(args.status.lower())
                except Exception:
                    pass
            workers = orch.list_workers(
                project_id=getattr(args, "project", None),
                status=st_filter
            )
            print(f"\n{Colors.BOLD}=== REGISTERED WORKERS ({len(workers)}) ==={Colors.END}")
            if not workers:
                print("No registered workers found.")
            for w in workers:
                st_color = Colors.GREEN if w.status == WorkerStatus.COMPLETED else (
                    Colors.YELLOW if w.status == WorkerStatus.RUNNING else (
                        Colors.RED if w.status == WorkerStatus.FAILED else Colors.CYAN
                    )
                )
                print(f"[{w.worker_id}] {w.worker_type.value.upper():<12} | Status: {st_color}{w.status.value.upper()}{Colors.END} | Task: {w.task_id}")
            print()

        elif action == "inspect":
            wid = getattr(args, "worker_id", "")
            w = orch.get_worker(wid)
            if not w:
                print(f"{Colors.RED}Worker '{wid}' not found.{Colors.END}")
                return
            print(f"\n{Colors.BOLD}=== WORKER: {w.worker_id} ==={Colors.END}")
            print(f"Type:         {w.worker_type.value}")
            print(f"Task ID:      {w.task_id}")
            print(f"Project ID:   {w.project_id}")
            print(f"Status:       {w.status.value}")
            print(f"Capabilities: {', '.join(w.capabilities)}")
            print(f"Created:      {w.created_at}")
            print(f"Started:      {w.started_at or 'N/A'}")
            print(f"Completed:    {w.completed_at or 'N/A'}")
            print(f"Error:        {w.error or 'None'}")
            print(f"Budget:       runtime: {w.budget.current_runtime:.1f}s / {w.budget.max_runtime:.1f}s, tool calls: {w.budget.current_tool_calls} / {w.budget.max_tool_calls}")
            print()

        elif action == "pause":
            wid = getattr(args, "worker_id", "")
            ok = orch.pause_worker(wid)
            if ok:
                print(f"{Colors.GREEN}Worker '{wid}' paused.{Colors.END}")
            else:
                print(f"{Colors.RED}Failed to pause worker '{wid}' (not found or not active).{Colors.END}")

        elif action == "resume":
            wid = getattr(args, "worker_id", "")
            ok = orch.resume_worker(wid)
            if ok:
                print(f"{Colors.GREEN}Worker '{wid}' resumed.{Colors.END}")
            else:
                print(f"{Colors.RED}Failed to resume worker '{wid}' (not found or not paused).{Colors.END}")

        elif action == "cancel":
            wid = getattr(args, "worker_id", "")
            ok = orch.cancel_worker(wid)
            if ok:
                print(f"{Colors.GREEN}Worker '{wid}' cancelled and locks released.{Colors.END}")
            else:
                print(f"{Colors.RED}Failed to cancel worker '{wid}' (not found).{Colors.END}")

        elif action == "locks":
            locks = rm.get_locks()
            print(f"\n{Colors.BOLD}=== ACTIVE RESOURCE LOCKS ({len(locks)}) ==={Colors.END}")
            if not locks:
                print("No active resource locks.")
            for l in locks:
                print(f"[{l.lock_id}] {l.resource_type.value.upper()}: {l.resource_target} | Mode: {l.mode.value.upper()} | Worker: {l.worker_id}")
            print()

        elif action == "graph":
            print(f"\n{Colors.BOLD}=== WORKSTREAM TASK DAG ==={Colors.END}")
            if engine.project_manager and hasattr(engine.project_manager, "dag") and engine.project_manager.dag:
                tasks = engine.project_manager.dag.list_tasks()
                for t in tasks:
                    deps = f"<- ({', '.join(t.dependencies)})" if t.dependencies else "(root)"
                    print(f"Task {t.id} [{t.capability.upper()}]: {t.title} {deps}")
            else:
                print("No persistent DAG loaded in current workspace.")
            print()
    finally:
        engine.close()

def cmd_models(args):
    """Inspect and manage AI models, providers, health, and routing (Phase 16)."""
    from modules.model_router import ModelRouter, ModelRequest

    action = getattr(args, "models_action", None) or "status"
    engine = ZaraEngine()

    try:
        router = engine.model_router

        if action == "status":
            st = router.get_status()
            print(f"\n{Colors.BOLD}=== ZARA AI MODEL ROUTER ==={Colors.END}")
            print(f"Active Provider:     {Colors.GREEN}{st['active_provider']}{Colors.END}")
            print(f"Active Model:        {st['active_model']}")
            print(f"Router Status:       {Colors.GREEN}{st['status']}{Colors.END}")
            print(f"Registered Models:   {st['models_count']}")
            metrics = st.get("metrics", {})
            print(f"Requests Total:      {metrics.get('requests_total', 0)}")
            print(f"Requests Succeeded:  {Colors.GREEN}{metrics.get('requests_successful', 0)}{Colors.END}")
            print(f"Requests Failed:     {Colors.RED}{metrics.get('requests_failed', 0)}{Colors.END}")
            print(f"Failovers:           {Colors.YELLOW}{metrics.get('failovers_total', 0)}{Colors.END}")
            print(f"Retries:             {metrics.get('retries_total', 0)}\n")

        elif action == "list":
            provider_filter = getattr(args, "provider", None)
            models = router.registry.list_models(provider=provider_filter)
            print(f"\n{Colors.BOLD}=== REGISTERED AI MODELS ({len(models)}) ==={Colors.END}")
            for m in models:
                avail_color = Colors.GREEN if m.availability.value in ("available", "healthy") else Colors.CYAN
                caps_str = ", ".join(c.value for c in m.capabilities)
                print(f"[{m.provider:<10}] {m.model_id:<28} | Avail: {avail_color}{m.availability.value.upper():<10}{Colors.END} | Window: {m.context_window:<8} | Caps: {caps_str}")
            print()

        elif action == "health":
            print(f"\n{Colors.BOLD}=== MODEL PROVIDERS HEALTH ==={Colors.END}")
            for prov_name in router.providers:
                h = router.health_tracker.get_health(prov_name)
                h_color = Colors.GREEN if h["status"] in ("healthy", "configured", "unknown") else Colors.RED
                print(f"Provider: {prov_name:<12} | Status: {h_color}{h['status'].upper():<12}{Colors.END} | Latency: {h['avg_latency_ms']:.1f}ms | Errors: {h['error_count']}")
            print()

        elif action == "routing":
            tasks = ["general_qa", "coding", "debugging", "research", "vision", "cyber_lab", "synthesis"]
            print(f"\n{Colors.BOLD}=== AI MODEL ROUTING TABLE ==={Colors.END}")
            for t in tasks:
                sel = router.route(ModelRequest(task_type=t))
                print(f"Task: {t:<15} -> Provider: {sel.provider:<10} Model: {sel.model_id:<26} ({sel.reason})")
            print()

        elif action == "circuit-breakers":
            print(f"\n{Colors.BOLD}=== CIRCUIT BREAKERS ==={Colors.END}")
            for name, cb in router.circuit_breakers.items():
                cb_dict = cb.to_dict()
                cb_color = Colors.GREEN if cb_dict["state"] == "healthy" else (
                    Colors.YELLOW if cb_dict["state"] in ("degraded", "half_open") else Colors.RED
                )
                print(f"Provider: {name:<12} | State: {cb_color}{cb_dict['state'].upper():<10}{Colors.END} | Failures: {cb_dict['failure_count']}/{cb_dict['failure_threshold']}")
            print()

        elif action == "discover":
            models = router.registry.discover_models()
            print(f"\n{Colors.GREEN}Model discovery complete. Found {len(models)} models across configured providers.{Colors.END}\n")

        elif action == "test":
            prov_name = getattr(args, "provider", "mock") or "mock"
            prov = router.providers.get(prov_name)
            if not prov:
                print(f"{Colors.RED}Provider '{prov_name}' not found.{Colors.END}")
                return
            h = prov.health()
            if h.get("available"):
                print(f"{Colors.GREEN}Provider '{prov_name}' is operational. Latency: {h.get('latency_ms', 0)}ms{Colors.END}")
            else:
                print(f"{Colors.YELLOW}Provider '{prov_name}' is not currently available: {h.get('error', 'unknown')}{Colors.END}")

    finally:
        engine.close()

def cmd_learning(args):
    from modules.evaluation import StrategyStatus, ProposalRisk, ProposalStatus, ExperimentStatus
    action = getattr(args, "learning_action", "status") or "status"
    engine = ZaraEngine(enable_voice=False)
    eval_mgr = engine.evaluation_manager
    try:
        if action == "status":
            stats = eval_mgr.get_stats()
            print(f"\n{Colors.BOLD}=== ZARA SELF-IMPROVEMENT & LEARNING STATUS ==={Colors.END}")
            print(f"Tasks Evaluated:         {stats.get('tasks_evaluated', 0)}")
            print(f"Success Rate:            {stats.get('success_rate', 1.0) * 100:.1f}%")
            print(f"Avg Overall Score:       {stats.get('average_overall_score', 0.0):.2f}")
            print(f"Learning Candidates:     {stats.get('learning_candidates_count', 0)}")
            print(f"Validated Strategies:    {stats.get('validated_strategies_count', 0)} / {stats.get('total_strategies_count', 0)}")
            print(f"Pending Proposals:       {stats.get('pending_proposals_count', 0)}")
            print(f"Active Experiments:      {stats.get('active_experiments_count', 0)}")
            print(f"Deployed Versions:       {stats.get('deployed_versions_count', 0)}")
            print(f"Rolled Back Versions:    {stats.get('rolled_back_count', 0)}")
            print()

        elif action == "stats":
            stats = eval_mgr.get_stats()
            print(f"\n{Colors.BOLD}=== AGGREGATE LEARNING METRICS ==={Colors.END}")
            for k, v in stats.items():
                print(f"  • {k.replace('_', ' ').title()}: {v}")
            print()

        elif action == "lessons":
            cands = list(eval_mgr.learning_candidates.values())
            ftype = getattr(args, "type", None)
            if ftype:
                cands = [c for c in cands if c.memory_type.upper() == ftype.upper()]
            print(f"\n{Colors.BOLD}=== LEARNED LESSONS ({len(cands)}) ==={Colors.END}")
            if not cands:
                print("No lessons recorded.")
            for c in cands[-15:]:
                color = Colors.YELLOW if c.memory_type == "ERROR_PATTERN" else Colors.GREEN
                print(f"  [{c.candidate_id}] {color}{c.memory_type}{Colors.END} (Conf: {c.confidence:.2f})")
                print(f"    {c.lesson}")
            print()

        elif action == "strategies":
            domain = getattr(args, "domain", None)
            status_filter = getattr(args, "status", None)
            st_enum = StrategyStatus(status_filter.upper()) if status_filter else None
            strats = eval_mgr.strategy_registry.list_strategies(status=st_enum, domain=domain)
            print(f"\n{Colors.BOLD}=== STRATEGY LIBRARY ({len(strats)}) ==={Colors.END}")
            if not strats:
                print("No strategies found.")
            for s in strats:
                tag = Colors.GREEN if s.status == StrategyStatus.VALIDATED else (Colors.YELLOW if s.status == StrategyStatus.EXPERIMENTAL else Colors.RED)
                print(f"  [{s.strategy_id}] {Colors.BOLD}{s.name}{Colors.END} — {tag}{s.status.value}{Colors.END} (v{s.version})")
                print(f"    {s.description}")
                print(f"    Evidence: {s.evidence_count} | Success Rate: {s.success_rate * 100:.1f}% | Conf: {s.confidence:.2f}")
            print()

        elif action == "proposals":
            props = list(eval_mgr.proposals.values())
            risk_filter = getattr(args, "risk", None)
            if risk_filter:
                props = [p for p in props if p.risk.value.upper() == risk_filter.upper()]
            print(f"\n{Colors.BOLD}=== IMPROVEMENT PROPOSALS ({len(props)}) ==={Colors.END}")
            if not props:
                print("No proposals found.")
            for p in props:
                rc = Colors.RED if p.risk in (ProposalRisk.HIGH, ProposalRisk.CRITICAL) else (Colors.YELLOW if p.risk == ProposalRisk.MEDIUM else Colors.GREEN)
                print(f"  [{p.proposal_id}] {Colors.BOLD}{p.title}{Colors.END}")
                print(f"    Risk: {rc}{p.risk.value}{Colors.END} | Status: {p.status.value} | Type: {p.change_type.value}")
                print(f"    Benefit: {p.expected_benefit}")
                if p.rejection_reason:
                    print(f"    {Colors.RED}Rejection Reason: {p.rejection_reason}{Colors.END}")
            print()

        elif action == "experiments":
            exps = list(eval_mgr.experiments.values())
            print(f"\n{Colors.BOLD}=== ACTIVE & COMPLETED EXPERIMENTS ({len(exps)}) ==={Colors.END}")
            if not exps:
                print("No experiments found.")
            for e in exps:
                st_color = Colors.GREEN if e.status == ExperimentStatus.COMPLETED else (Colors.YELLOW if e.status == ExperimentStatus.RUNNING else Colors.RED)
                print(f"  [{e.experiment_id}] {st_color}{e.status.value}{Colors.END} — {e.hypothesis}")
                print(f"    Sample: {e.sample_size}/{e.target_sample_size}")
                if e.metrics:
                    print(f"    Metrics: {e.metrics}")
            print()

        elif action == "evaluations":
            evals = list(eval_mgr.evaluations.values())
            print(f"\n{Colors.BOLD}=== RECENT TASK EVALUATIONS ({len(evals)}) ==={Colors.END}")
            if not evals:
                print("No evaluations found.")
            for ev in evals[-10:]:
                res_color = Colors.GREEN if ev.task_success else Colors.RED
                print(f"  [{ev.evaluation_id}] Task: {ev.task_id} — {res_color}{'SUCCESS' if ev.task_success else 'FAILED'}{Colors.END} (Score: {ev.overall_score:.2f})")
                print(f"    Correctness: {ev.quality_score:.2f} | Efficiency: {ev.efficiency_score:.2f} | Reliability: {ev.reliability_score:.2f} | Safety: {ev.safety_score:.2f}")
            print()

        elif action == "inspect":
            target_id = getattr(args, "id", None)
            if not target_id:
                print(f"{Colors.RED}Please provide an ID to inspect.{Colors.END}")
                return
            if target_id in eval_mgr.evaluations:
                print(json.dumps(eval_mgr.evaluations[target_id].to_dict(), indent=2))
            elif target_id in eval_mgr.proposals:
                print(json.dumps(eval_mgr.proposals[target_id].to_dict(), indent=2))
            elif target_id in eval_mgr.strategy_registry.strategies:
                print(json.dumps(eval_mgr.strategy_registry.strategies[target_id].to_dict(), indent=2))
            elif target_id in eval_mgr.experiments:
                print(json.dumps(eval_mgr.experiments[target_id].to_dict(), indent=2))
            elif target_id in eval_mgr.versions:
                print(json.dumps(eval_mgr.versions[target_id].to_dict(), indent=2))
            else:
                print(f"{Colors.RED}Entity with ID '{target_id}' not found.{Colors.END}")

        elif action == "approve":
            target_id = getattr(args, "id", None)
            if not target_id:
                print(f"{Colors.RED}Please provide a proposal ID to approve.{Colors.END}")
                return
            ok = eval_mgr.approve_proposal(target_id, approved_by="cli_user")
            if ok:
                print(f"{Colors.GREEN}✔ Proposal '{target_id}' approved successfully.{Colors.END}")
            else:
                print(f"{Colors.RED}✘ Cannot approve proposal '{target_id}' (may be critical, already rejected, or not found).{Colors.END}")

        elif action == "reject":
            target_id = getattr(args, "id", None)
            reason = getattr(args, "reason", "Rejected via CLI") or "Rejected via CLI"
            if not target_id:
                print(f"{Colors.RED}Please provide a proposal ID to reject.{Colors.END}")
                return
            ok = eval_mgr.reject_proposal(target_id, reason=reason)
            if ok:
                print(f"{Colors.YELLOW}Proposal '{target_id}' rejected.{Colors.END}")
            else:
                print(f"{Colors.RED}Proposal '{target_id}' not found.{Colors.END}")

        elif action == "rollback":
            target_id = getattr(args, "id", None)
            if not target_id:
                print(f"{Colors.RED}Please provide a version or proposal ID to rollback.{Colors.END}")
                return
            ok = eval_mgr.rollback(target_id)
            if ok:
                print(f"{Colors.GREEN}✔ Rollback for '{target_id}' completed successfully.{Colors.END}")
            else:
                print(f"{Colors.RED}✘ Rollback failed: target '{target_id}' not found.{Colors.END}")

    finally:
        engine.close()

def main():
    parser = argparse.ArgumentParser(description="ZARA Autonomous Agent CLI")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_p = subparsers.add_parser("run", help="Run a task through ZARA's autonomous loop")
    run_p.add_argument("task", type=str, help="Task description or instruction")
    run_p.add_argument("--tag", type=str, default="general", help="Task category tag")
    run_p.add_argument("--docker", action="store_true", help="Run in Docker sandbox")
    run_p.add_argument("--no-voice", action="store_true", help="Disable TTS voice")

    # chat command
    chat_p = subparsers.add_parser("chat", help="Interactive conversational session with ZARA")
    chat_p.add_argument("--docker", action="store_true", help="Run in Docker sandbox")
    chat_p.add_argument("--no-voice", action="store_true", help="Disable TTS voice")

    # voice command
    voice_p = subparsers.add_parser("voice", help="Interactive voice mode with ZARA")
    voice_p.add_argument("--docker", action="store_true", help="Run in Docker sandbox")
    voice_p.add_argument("--no-tts", action="store_true", help="Disable audio speech output")
    voice_p.add_argument("--mock", action="store_true", help="Use mock STT/TTS providers")
    voice_p.add_argument("--wake-word", type=str, default="ZARA", help="Custom wake word")
    voice_p.add_argument("--require-wake", action="store_true", help="Strictly require wake word to activate")

    # tools command
    subparsers.add_parser("tools", help="List all registered tools and permission levels")

    # recover command
    subparsers.add_parser("recover", help="List and inspect task checkpoints")

    # gui command
    subparsers.add_parser("gui", help="Launch native desktop GUI")

    # memory command
    mem_p = subparsers.add_parser("memory", help="Inspect or search ZARA's self-learning memory log")
    mem_p.add_argument("query", type=str, nargs="?", default="", help="Search query")
    mem_p.add_argument("--stats", action="store_true", help="Display memory statistics")
    mem_p.add_argument("--conflicts", action="store_true", help="List detected memory conflicts")
    mem_p.add_argument("--recent", action="store_true", help="Show recent memories")
    mem_p.add_argument("--project", type=str, default=None, help="Filter by project ID")
    mem_p.add_argument("--scope", type=str, default=None, help="Filter by scope (GLOBAL, USER, PROJECT, TASK, SESSION)")
    mem_p.add_argument("--type", type=str, default=None, help="Filter by memory type")
    mem_p.add_argument("--export", type=str, default=None, help="Export memories to file path")

    # voice-test command
    subparsers.add_parser("voice-test", help="Test female TTS voice synthesis")

    # test command
    subparsers.add_parser("test", help="Execute unit and integration test suite")

    # project command
    proj_p = subparsers.add_parser("project", help="Manage persistent autonomous projects and workspaces")
    proj_sub = proj_p.add_subparsers(dest="project_action", help="Project operations")

    create_p = proj_sub.add_parser("create", help="Create a new persistent project")
    create_p.add_argument("name", type=str, help="Project name")
    create_p.add_argument("--path", type=str, default="", help="Custom project path")
    create_p.add_argument("--desc", type=str, default="", help="Project description")

    proj_sub.add_parser("list", help="List all persistent projects")

    status_p = proj_sub.add_parser("status", help="Show project status and metrics")
    status_p.add_argument("target", type=str, nargs="?", default="", help="Project ID, name, or path")

    pause_p = proj_sub.add_parser("pause", help="Pause active project")
    pause_p.add_argument("target", type=str, nargs="?", default="", help="Project ID, name, or path")

    resume_p = proj_sub.add_parser("resume", help="Resume paused project")
    resume_p.add_argument("target", type=str, nargs="?", default="", help="Project ID, name, or path")

    cancel_p = proj_sub.add_parser("cancel", help="Cancel project and halt remaining tasks")
    cancel_p.add_argument("target", type=str, nargs="?", default="", help="Project ID, name, or path")

    recover_p = proj_sub.add_parser("recover", help="Recover interrupted project from checkpoint")
    recover_p.add_argument("target", type=str, nargs="?", default="", help="Project ID, name, or path")

    # schedule command
    sched_p = subparsers.add_parser("schedule", help="Manage persistent scheduled jobs")
    sched_sub = sched_p.add_subparsers(dest="schedule_action", help="Schedule operations")
    sched_sub.add_parser("list", help="List scheduled jobs")

    s_create = sched_sub.add_parser("create", help="Schedule a new job")
    s_create.add_argument("name", type=str, help="Job name")
    s_create.add_argument("--type", type=str, default="once", choices=["once", "interval", "hourly", "daily", "weekly", "monthly", "cron"], help="Schedule type")
    s_create.add_argument("--task", type=str, required=True, help="Task to run")
    s_create.add_argument("--cron", type=str, help="Cron expression")
    s_create.add_argument("--interval", type=float, help="Interval seconds")
    s_create.add_argument("--priority", type=str, default="normal", choices=["low", "normal", "high", "critical"], help="Priority")

    s_status = sched_sub.add_parser("status", help="Get status of scheduled job")
    s_status.add_argument("job_id", type=str, help="Job ID")

    s_pause = sched_sub.add_parser("pause", help="Pause scheduled job")
    s_pause.add_argument("job_id", type=str, help="Job ID")

    s_resume = sched_sub.add_parser("resume", help="Resume scheduled job")
    s_resume.add_argument("job_id", type=str, help="Job ID")

    s_cancel = sched_sub.add_parser("cancel", help="Cancel scheduled job")
    s_cancel.add_argument("job_id", type=str, help="Job ID")

    # jobs alias
    subparsers.add_parser("jobs", parents=[sched_p], add_help=False)

    # queue command
    queue_p = subparsers.add_parser("queue", help="Inspect and control prioritized work queue")
    queue_sub = queue_p.add_subparsers(dest="queue_action", help="Queue operations")
    queue_sub.add_parser("list", help="List prioritized daily queue items")
    queue_sub.add_parser("pause", help="Pause queue processing")
    queue_sub.add_parser("resume", help="Resume queue processing")

    # autonomous command
    auto_p = subparsers.add_parser("autonomous", help="Configure autonomous mode, quiet hours, and daily budgets")
    auto_sub = auto_p.add_subparsers(dest="auto_action", help="Autonomous mode operations")
    auto_sub.add_parser("status", help="Show autonomous mode status and resource budgets")
    auto_sub.add_parser("on", help="Enable autonomous mode")
    auto_sub.add_parser("off", help="Disable autonomous mode")

    # plan command
    plan_p = subparsers.add_parser("plan", help="Inspect, validate, and manage hierarchical project plans")
    plan_sub = plan_p.add_subparsers(dest="plan_action", help="Plan operations")
    p_status = plan_sub.add_parser("status", help="Show plan status and goal understanding")
    p_status.add_argument("project", type=str, nargs="?", default="", help="Project name, ID, or path")
    p_history = plan_sub.add_parser("history", help="Show plan revision history")
    p_history.add_argument("project", type=str, nargs="?", default="", help="Project name, ID, or path")
    p_validate = plan_sub.add_parser("validate", help="Validate plan quality and safety")
    p_validate.add_argument("project", type=str, nargs="?", default="", help="Project name, ID, or path")
    p_approve = plan_sub.add_parser("approve", help="Approve plan or pending ticket")
    p_approve.add_argument("project", type=str, nargs="?", default="", help="Project name, ID, or path")

    # decisions command
    dec_p = subparsers.add_parser("decisions", help="View persistent operational decision records")
    dec_p.add_argument("project", type=str, nargs="?", default="", help="Optional project name, ID, or path")

    # world command
    world_p = subparsers.add_parser("world", help="Inspect, diff, snapshot, and refresh multimodal world model")
    world_sub = world_p.add_subparsers(dest="world_action", help="World model operations")
    w_status = world_sub.add_parser("status", help="Show active world state, app, window, and freshness")
    w_status.add_argument("project", type=str, nargs="?", default="", help="Optional project name, ID, or path")
    w_snapshot = world_sub.add_parser("snapshot", help="Create and persist a world snapshot")
    w_snapshot.add_argument("project", type=str, nargs="?", default="", help="Optional project name, ID, or path")
    w_diff = world_sub.add_parser("diff", help="Show differences between previous and current world states")
    w_diff.add_argument("project", type=str, nargs="?", default="", help="Optional project name, ID, or path")
    w_refresh = world_sub.add_parser("refresh", help="Force refresh stale modalities")
    w_refresh.add_argument("project", type=str, nargs="?", default="", help="Optional project name, ID, or path")

    # ui command
    ui_p = subparsers.add_parser("ui", help="Launch ZARA Unified Command Center & Control UI")
    ui_p.add_argument("ui_action", nargs="?", default="start", choices=["start", "status"], help="UI action: start (default) or status")
    ui_p.add_argument("--port", type=int, default=UI_PORT, help="Port to bind UI server (default 8420)")
    ui_p.add_argument("--host", type=str, default=UI_HOST, help="Host interface to bind (default 127.0.0.1)")
    ui_p.add_argument("--open", action="store_true", help="Automatically open Command Center UI in web browser")

    # workers command (Phase 15)
    workers_p = subparsers.add_parser("workers", help="Inspect and control multi-agent parallel workers and locks")
    workers_sub = workers_p.add_subparsers(dest="workers_action", help="Worker operations")

    wk_status = workers_sub.add_parser("status", help="Show worker metrics and active status")
    wk_list = workers_sub.add_parser("list", help="List all registered workers")
    wk_list.add_argument("--project", type=str, default=None, help="Filter by project ID")
    wk_list.add_argument("--status", type=str, default=None, help="Filter by worker status")

    wk_inspect = workers_sub.add_parser("inspect", help="Inspect detailed worker state")
    wk_inspect.add_argument("worker_id", type=str, help="Worker ID to inspect")

    wk_pause = workers_sub.add_parser("pause", help="Pause an active worker")
    wk_pause.add_argument("worker_id", type=str, help="Worker ID to pause")

    wk_resume = workers_sub.add_parser("resume", help="Resume a paused worker")
    wk_resume.add_argument("worker_id", type=str, help="Worker ID to resume")

    wk_cancel = workers_sub.add_parser("cancel", help="Cancel a worker and release locks")
    wk_cancel.add_argument("worker_id", type=str, help="Worker ID to cancel")

    wk_locks = workers_sub.add_parser("locks", help="List active resource locks")
    wk_graph = workers_sub.add_parser("graph", help="Display workstream task DAG")

    # models command (Phase 16)
    models_p = subparsers.add_parser("models", help="Inspect and control AI model router, providers, and failover")
    models_sub = models_p.add_subparsers(dest="models_action", help="Model router operations")

    models_sub.add_parser("status", help="Show active provider, model, and router metrics")
    m_list = models_sub.add_parser("list", help="List registered models and capabilities")
    m_list.add_argument("--provider", type=str, default=None, help="Filter by provider")

    models_sub.add_parser("health", help="Show provider health, latency, and error counts")
    models_sub.add_parser("routing", help="Display task-to-model routing table")
    models_sub.add_parser("circuit-breakers", help="Inspect circuit breaker states")
    models_sub.add_parser("discover", help="Discover available models from environment")

    m_test = models_sub.add_parser("test", help="Test operational health of a provider")
    m_test.add_argument("provider", type=str, nargs="?", default="mock", help="Provider name to test (default: mock)")

    # learning command (Phase 17)
    learning_p = subparsers.add_parser("learning", help="Inspect and control self-improvement, strategies, and learning")
    learning_sub = learning_p.add_subparsers(dest="learning_action", help="Learning operations")

    learning_sub.add_parser("status", help="Show learning subsystem status, success rates, and counts")
    learning_sub.add_parser("stats", help="Show aggregate learning metrics")

    l_lessons = learning_sub.add_parser("lessons", help="List learned lesson candidates")
    l_lessons.add_argument("--type", type=str, default=None, help="Filter by memory type (ERROR_PATTERN, SUCCESS_PATTERN, USER_FEEDBACK)")

    l_strats = learning_sub.add_parser("strategies", help="List strategy library")
    l_strats.add_argument("--domain", type=str, default=None, help="Filter by applicable domain")
    l_strats.add_argument("--status", type=str, default=None, help="Filter by status (EXPERIMENTAL, VALIDATED, DEPRECATED, BLOCKED)")

    l_props = learning_sub.add_parser("proposals", help="List improvement proposals")
    l_props.add_argument("--risk", type=str, default=None, help="Filter by risk (LOW, MEDIUM, HIGH, CRITICAL)")

    learning_sub.add_parser("experiments", help="List active and completed experiments")
    learning_sub.add_parser("evaluations", help="List recent task evaluations")

    l_inspect = learning_sub.add_parser("inspect", help="Inspect entity details (evaluation, proposal, strategy, experiment)")
    l_inspect.add_argument("id", type=str, help="Entity ID to inspect")

    l_approve = learning_sub.add_parser("approve", help="Approve an improvement proposal")
    l_approve.add_argument("id", type=str, help="Proposal ID to approve")

    l_reject = learning_sub.add_parser("reject", help="Reject an improvement proposal")
    l_reject.add_argument("id", type=str, help="Proposal ID to reject")
    l_reject.add_argument("--reason", type=str, default="Rejected via CLI", help="Rejection reason")

    l_rollback = learning_sub.add_parser("rollback", help="Rollback an improvement proposal or version")
    l_rollback.add_argument("id", type=str, help="Proposal or Version ID to rollback")

    args = parser.parse_args()

    # Default to chat if no command provided
    if not args.command:
        # If user runs ./zara.py with no args, open conversational chat!
        args.docker = False
        args.no_voice = False
        cmd_chat(args)
        return

    commands = {
        "run": cmd_run,
        "chat": cmd_chat,
        "voice": cmd_voice,
        "tools": cmd_tools,
        "recover": cmd_recover,
        "gui": cmd_gui,
        "memory": cmd_memory,
        "voice-test": cmd_voice_test,
        "test": cmd_test,
        "project": cmd_project,
        "schedule": cmd_schedule,
        "jobs": cmd_schedule,
        "queue": cmd_queue,
        "autonomous": cmd_autonomous,
        "plan": cmd_plan,
        "decisions": cmd_decisions,
        "world": cmd_world,
        "ui": cmd_ui,
        "workers": cmd_workers,
        "models": cmd_models,
        "learning": cmd_learning
    }
    commands[args.command](args)

if __name__ == "__main__":
    main()
