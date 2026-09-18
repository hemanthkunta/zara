"""
Unit and Integration tests for ZARA Autonomous Agent.
Compatible with standard library unittest and pytest.
"""
import unittest
import tempfile
import shutil
from pathlib import Path

from config.settings import BLOCKED_COMMAND_PATTERNS
from core.state import PlanStep, ActionType, StepStatus, Reflection
from core.engine import ZaraEngine
from modules.memory import MemoryStore
from modules.execution import ExecutionEngine
from modules.coding import CodingModule
from modules.debugging import DebuggingModule
from modules.security import SecurityModule, ScopeViolationError
from modules.job_hunter import JobHunterModule
from modules.voice import VoiceSynthesizer
from modules.orchestrator import TaskOrchestrator

class TestZaraCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_test_")
        self.workspace = Path(self.temp_dir)
        self.memory_file = self.workspace / "memory" / "zara_log.md"
        self.memory_file.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_destructive_command_blocking(self):
        """Verify that destructive/dangerous commands are rejected by ExecutionEngine."""
        engine = ExecutionEngine(str(self.workspace))
        dangerous_commands = [
            "rm -rf /",
            "rm -rf ~",
            "DROP DATABASE production;",
            "git push origin main --force",
            ":(){ :|:& };:"
        ]
        for cmd in dangerous_commands:
            is_safe, reason = engine.validate_command(cmd)
            self.assertFalse(is_safe, f"Command '{cmd}' should have been blocked")
            result = engine.execute(cmd)
            self.assertFalse(result.success)
            self.assertIn("SAFETY INTERCEPTOR", result.stderr)

    def test_safe_command_execution(self):
        """Verify normal safe command executes and returns output."""
        engine = ExecutionEngine(str(self.workspace))
        result = engine.execute("echo 'ZARA-VERIFY'")
        self.assertTrue(result.success)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("ZARA-VERIFY", result.stdout)

    def test_memory_append_and_search(self):
        """Verify appending and searching past lessons in the self-learning memory log."""
        mem = MemoryStore(self.memory_file)
        reflection = Reflection(
            task="Refactor async worker",
            tag="architecture",
            approach="Used bounded asyncio queues",
            result="Latency dropped by 40%",
            lesson="Always cap queue size to prevent memory leaks during spikes"
        )
        mem.append_reflection(reflection)

        results = mem.search_lessons("memory leaks queues")
        self.assertGreater(len(results), 0)
        self.assertIn("Always cap queue size", results[0]["lesson"])

    def test_coding_module_syntax_validation(self):
        """Verify coding module detects and rejects syntax errors in Python files."""
        coding = CodingModule(str(self.workspace))

        # Valid Python
        ok, err = coding.write_file("valid.py", "def greet():\n    return 'hello'\n")
        self.assertTrue(ok)
        self.assertIsNone(err)

        # Invalid Python syntax
        ok, err = coding.write_file("invalid.py", "def broken_syntax(:\n")
        self.assertFalse(ok)
        self.assertIn("syntax error", err.lower())

    def test_debugging_diagnosis(self):
        """Verify debugging module correctly categorizes errors and hypotheses."""
        diag = DebuggingModule.diagnose_failure(
            step_title="Run test suite",
            expected_condition="Tests pass",
            error_output="ModuleNotFoundError: No module named 'rich'",
            attempt=1
        )
        self.assertIn("rich", diag.hypothesis)
        self.assertEqual(diag.proposed_fix.get("action"), "install_dependency")

    def test_security_scope_guard(self):
        """Verify security module allows pre-approved scope and blocks unauthorized targets."""
        scope_file = self.workspace / "scope.json"
        scope_file.write_text('{"allowed_hosts": ["localhost", "127.0.0.1"]}')
        sec = SecurityModule(scope_file)

        # Authorized target
        allowed, msg = sec.verify_target("localhost")
        self.assertTrue(allowed)

        # Unauthorized target
        allowed, msg = sec.verify_target("https://unauthorized-bank.com")
        self.assertFalse(allowed)
        self.assertIn("TARGET SCOPE VIOLATION", msg)

        with self.assertRaises(ScopeViolationError):
            sec.plan_security_audit("evilcorp.org", "port_scan")

    def test_job_application_draft_queue(self):
        """Verify job applications are drafted into the review queue and never auto-submitted."""
        queue_dir = self.workspace / "job_queue"
        hunter = JobHunterModule(queue_dir)

        draft_file = hunter.draft_application(
            job_id="lead-01",
            company="Acme Corp",
            role="Staff AI Engineer",
            job_description="Build autonomous agents",
            candidate_profile={"name": "Alex", "skills": "Python, Multi-Agent Systems"}
        )

        self.assertTrue(draft_file.exists())
        content = draft_file.read_text()
        self.assertIn("HUMAN REVIEW REQUIRED", content)
        self.assertIn("Staff AI Engineer", content)

        pending = hunter.list_pending_applications()
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["status"], "pending_human_approval")

    def test_voice_sanitization(self):
        """Verify voice module sanitizes markdown and technical noise for speech."""
        voice = VoiceSynthesizer(enabled=False)
        clean = voice._sanitize_text("Task **PASSED** with `exit code 0`. Link: https://example.com")
        self.assertEqual(clean, "Task PASSED with exit code 0. Link: link")

    def test_full_zara_engine_loop(self):
        """Verify end-to-end ZARA loop: Perceive -> Plan -> Act -> Verify -> Reflect -> Persist."""
        engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False
        )
        # Override memory store path to temp workspace
        engine.memory = MemoryStore(self.memory_file)

        task_steps = [
            PlanStep(
                id=1,
                title="Create hello file",
                action_type=ActionType.CODE,
                description="Write hello.py",
                target="hello.py",
                payload={"file_path": "hello.py", "content": "print('HELLO FROM ZARA')\n"},
                success_condition="File hello.py written successfully"
            ),
            PlanStep(
                id=2,
                title="Execute hello script",
                action_type=ActionType.EXECUTE,
                description="Run python3 hello.py",
                target="python3 hello.py",
                payload={"command": "python3 hello.py"},
                success_condition="Output contains HELLO FROM ZARA"
            )
        ]

        summary = engine.run_task(
            task="Build and run hello.py",
            tag="unit_test",
            steps=task_steps
        )

        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(summary["steps_passed"], 2)
        self.assertEqual(summary["steps_total"], 2)

        # Verify memory reflection was persisted
        log_content = self.memory_file.read_text()
        self.assertIn("Build and run hello.py", log_content)
        self.assertIn("unit_test", log_content)

if __name__ == "__main__":
    unittest.main()
