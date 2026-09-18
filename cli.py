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
        "project": cmd_project
    }
    commands[args.command](args)

if __name__ == "__main__":
    main()
