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

def cmd_voice_test(args):
    print(f"{Colors.CYAN}Testing ZARA Voice Output (Samantha / Female Voice)...{Colors.END}")
    voice = VoiceSynthesizer(enabled=True)
    voice.speak("Greetings. I am ZARA, your autonomous engineering and research agent. Voice interface is online.", async_mode=False)
    print(f"{Colors.GREEN}Voice test completed.{Colors.END}")

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
        "tools": cmd_tools,
        "recover": cmd_recover,
        "gui": cmd_gui,
        "memory": cmd_memory,
        "voice-test": cmd_voice_test,
        "test": cmd_test
    }
    commands[args.command](args)

if __name__ == "__main__":
    main()
