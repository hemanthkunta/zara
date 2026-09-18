"""
ZARA Command-Line Interface (CLI): Interactive console for ZARA Autonomous Agent.
Supports run, chat (conversational mode), gui, tools, memory, recover, and test.
"""
import sys
import argparse
import subprocess
from pathlib import Path
from core.engine import ZaraEngine
from core.conversation import ConversationalSession
from core.state import PlanStep, StepStatus, ActionType
from core.recovery import RecoveryManager
from modules.memory import MemoryStore
from modules.voice import VoiceSynthesizer
from config.settings import MEMORY_FILE, ENABLE_VOICE

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
    if args.query:
        print(f"\n{Colors.CYAN}Searching ZARA Memory for:{Colors.END} '{args.query}'\n")
        results = store.search_lessons(args.query, limit=5)
        if not results:
            print("No matching past lessons found.")
            return
        for r in results:
            print(f"{Colors.BOLD}{r['header']}{Colors.END}")
            if r.get("approach"):
                print(f"  - Approach: {r['approach']}")
            if r.get("result"):
                print(f"  - Result: {r['result']}")
            if r.get("lesson"):
                print(f"  - Lesson: {r['lesson']}")
            print("-" * 50)
    else:
        print(f"\n{Colors.CYAN}Reading all entries in {MEMORY_FILE}:{Colors.END}\n")
        entries = store.get_all_entries()
        for e in entries:
            print(e)
            print("-" * 50)

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
        "decisions": cmd_decisions
    }
    commands[args.command](args)

if __name__ == "__main__":
    main()
