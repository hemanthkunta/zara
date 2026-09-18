"""
Comprehensive regression tests for ZARA's tool-aware natural-language planning and execution loop.
Validates Requirements 1-12:
1. Natural-language task does NOT become a shell command.
2. Valid LLM structured plan is accepted.
3. Invalid LLM plan is rejected.
4. Unknown tool is rejected.
5. Missing tool arguments are rejected.
6. write_file plan executes correctly.
7. terminal_execute plan executes correctly.
8. run_tests plan executes correctly.
9. Failed command produces diagnosis.
10. Diagnosis changes the retry action.
11. Identical failed actions are not blindly repeated.
12. Successful verification completes the task.
13. Existing safety restrictions still work.
14. End-to-end regression test for hello_zara task.
"""
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine import ZaraEngine
from core.state import PlanStep, ActionType, StepStatus, TaskContext, ExecutionResult, Diagnosis
from tools.base import ToolResult

class TestNaturalLanguagePlanning(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_nl_test_")
        self.workspace = Path(self.temp_dir)
        self.engine = ZaraEngine(workspace_root=str(self.workspace), enable_voice=False)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_1_natural_language_task_does_not_become_shell_command(self):
        """Verify that when LLM plan generation fails, natural language is NEVER executed as shell command."""
        # Mock brain to return completely invalid data
        self.engine.brain.generate_structured = MagicMock(return_value=None)

        task = "Create a file called hello_zara.py that prints 'Hello from ZARA' and run it"
        result = self.engine.run_task(task)

        # Must be BLOCKED with clear message, NOT executed as a shell command
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("refusing to interpret natural language as a shell command", result["blocker_reason"])
        self.assertEqual(result["steps_total"], 0)

    def test_2_valid_llm_structured_plan_accepted(self):
        """Verify valid structured JSON plan from LLM is validated and accepted into PlanSteps."""
        mock_plan = {
            "steps": [
                {
                    "id": 1,
                    "title": "Create Python file",
                    "description": "Write code to file",
                    "tool": "write_file",
                    "arguments": {
                        "path": "hello.py",
                        "content": "print('hello')"
                    },
                    "success_condition": "File written"
                },
                {
                    "id": 2,
                    "title": "Execute script",
                    "description": "Run the python file",
                    "tool": "terminal_execute",
                    "arguments": {
                        "command": "python3 hello.py"
                    },
                    "success_condition": "Prints hello"
                }
            ]
        }
        self.engine.brain.generate_structured = MagicMock(return_value=mock_plan)
        context = TaskContext(task="Write and run hello.py", tag="dev", working_dir=str(self.workspace))
        steps = self.engine.plan(context)

        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].tool, "write_file")
        self.assertEqual(steps[0].arguments["path"], "hello.py")
        self.assertEqual(steps[1].tool, "terminal_execute")
        self.assertEqual(steps[1].arguments["command"], "python3 hello.py")

    def test_3_invalid_llm_plan_rejected(self):
        """Verify malformed plans that fail recovery are cleanly rejected without fallback to shell."""
        # Returns empty list or malformed object
        self.engine.brain.generate_structured = MagicMock(return_value={"not_steps": []})
        context = TaskContext(task="Arbitrary task", tag="dev", working_dir=str(self.workspace))
        steps = self.engine.plan(context)

        self.assertEqual(steps, [])
        self.assertIn("refusing to interpret natural language", context.blocker_reason)

    def test_4_unknown_tool_rejected(self):
        """Verify plan specifying unregistered tools is rejected."""
        mock_plan = {
            "steps": [
                {
                    "id": 1,
                    "title": "Malicious or fake tool",
                    "tool": "non_existent_exploit_tool",
                    "arguments": {"foo": "bar"}
                }
            ]
        }
        self.engine.brain.generate_structured = MagicMock(return_value=mock_plan)
        context = TaskContext(task="Execute fake tool", tag="dev", working_dir=str(self.workspace))
        steps = self.engine.plan(context)

        self.assertEqual(steps, [])
        self.assertTrue(context.requires_human_input)

    def test_5_missing_tool_arguments_rejected(self):
        """Verify tool calls missing required schema arguments are rejected."""
        # write_file requires 'path' and 'content'
        mock_plan = {
            "steps": [
                {
                    "id": 1,
                    "title": "Incomplete write",
                    "tool": "write_file",
                    "arguments": {"path": "only_path.py"}  # missing 'content'
                }
            ]
        }
        self.engine.brain.generate_structured = MagicMock(return_value=mock_plan)
        context = TaskContext(task="Incomplete step", tag="dev", working_dir=str(self.workspace))
        steps = self.engine.plan(context)

        self.assertEqual(steps, [])
        self.assertTrue(context.requires_human_input)

    def test_6_write_file_plan_executes_correctly(self):
        """Verify a write_file step successfully creates the file on disk."""
        step = PlanStep(
            id=1,
            title="Write test file",
            action_type=ActionType.TOOL,
            description="Write script",
            target="test_sample.py",
            tool="write_file",
            arguments={"path": "test_sample.py", "content": "print('from test')"}
        )
        context = TaskContext(task="Test write", tag="dev", working_dir=str(self.workspace))
        res = self.engine.act(step, context)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)
        self.assertTrue((self.workspace / "test_sample.py").exists())
        self.assertEqual((self.workspace / "test_sample.py").read_text().strip(), "print('from test')")

    def test_7_terminal_execute_plan_executes_correctly(self):
        """Verify a terminal_execute step runs within workspace safely and captures output."""
        step = PlanStep(
            id=1,
            title="Execute echo",
            action_type=ActionType.TOOL,
            description="Run echo",
            target="echo test",
            tool="terminal_execute",
            arguments={"command": "echo 'ENGINE_NL_TEST'"}
        )
        context = TaskContext(task="Echo test", tag="dev", working_dir=str(self.workspace))
        res = self.engine.act(step, context)
        self.assertTrue(res.success)
        self.assertIn("ENGINE_NL_TEST", res.stdout)

    def test_8_run_tests_plan_executes_correctly(self):
        """Verify run_tests tool runs test discover."""
        # Create a mini test file inside workspace
        test_dir = self.workspace / "tests"
        test_dir.mkdir(parents=True, exist_ok=True)
        (test_dir / "test_dummy.py").write_text(
            "import unittest\nclass DummyTest(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n"
        )

        step = PlanStep(
            id=1,
            title="Run mini tests",
            action_type=ActionType.TOOL,
            description="Execute test runner",
            target="tests",
            tool="run_tests",
            arguments={"test_path": "tests"}
        )
        context = TaskContext(task="Run tests", tag="dev", working_dir=str(self.workspace))
        res = self.engine.act(step, context)
        self.assertTrue(res.success)
        self.assertEqual(res.exit_code, 0)

    def test_9_failed_command_produces_diagnosis(self):
        """Verify failing execution generates a structured Diagnosis with hypothesis and root cause."""
        step = PlanStep(
            id=1,
            title="Run non-existent script",
            action_type=ActionType.TOOL,
            description="Run missing python script",
            target="python3 missing_script.py",
            tool="terminal_execute",
            arguments={"command": "python3 missing_script.py"},
            success_condition="Exits with return code 0"
        )
        context = TaskContext(task="Run missing script", tag="dev", working_dir=str(self.workspace))
        context.steps = [step]

        result = self.engine.act(step, context)
        self.assertFalse(result.success)

        # Call diagnose_and_retry
        self.engine.diagnose_and_retry(step, result, context)
        self.assertGreaterEqual(len(context.diagnoses), 1)
        diag = context.diagnoses[0]
        self.assertIsNotNone(diag.hypothesis)
        self.assertIsNotNone(diag.root_cause_category)

    def test_10_diagnosis_changes_retry_action(self):
        """Verify that when diagnosis provides corrected arguments, retry executes the corrected action."""
        step = PlanStep(
            id=1,
            title="Execute bad command",
            action_type=ActionType.TOOL,
            description="Run command with typo",
            target="echo typo",
            tool="terminal_execute",
            arguments={"command": "python3 -c 'invalid syntax'"},
            success_condition="Exits with return code 0"
        )
        context = TaskContext(task="Typo test", tag="dev", working_dir=str(self.workspace))

        # Mock diagnosis to provide corrected command on attempt 1
        def mock_diag(*args, **kwargs):
            return Diagnosis(
                attempt=1,
                failure_reason="SyntaxError",
                hypothesis="Command had invalid syntax",
                proposed_fix={"action": "fix_command"},
                root_cause_category="command",
                corrected_arguments={"command": "python3 -c 'print(\"corrected\")'"}
            )

        with patch.object(self.engine.debugging, "diagnose_failure", side_effect=mock_diag):
            result = self.engine.act(step, context)
            success = self.engine.diagnose_and_retry(step, result, context)
            self.assertTrue(success)
            self.assertEqual(step.arguments["command"], "python3 -c 'print(\"corrected\")'")
            self.assertEqual(step.status, StepStatus.PASSED)

    def test_11_identical_failed_actions_not_repeated(self):
        """Verify that repeated identical actions are detected and do NOT blindly loop 5 times."""
        step = PlanStep(
            id=1,
            title="Failing step",
            action_type=ActionType.TOOL,
            description="Failing action",
            target="failing",
            tool="terminal_execute",
            arguments={"command": "false"},
            success_condition="Exits with 0"
        )
        context = TaskContext(task="Loop test", tag="dev", working_dir=str(self.workspace))

        # Diagnosis provides NO change to arguments or tool
        def unhelpful_diag(*args, **kwargs):
            return Diagnosis(
                attempt=kwargs.get("attempt", 1),
                failure_reason="command exited with 1",
                hypothesis="Still broken",
                proposed_fix={},
                root_cause_category="command"
            )

        with patch.object(self.engine.debugging, "diagnose_failure", side_effect=unhelpful_diag):
            result = self.engine.act(step, context)
            success = self.engine.diagnose_and_retry(step, result, context)
            self.assertFalse(success)
            # Must have stopped early (at attempt 1) rather than repeating all 5 attempts blindly
            self.assertLess(step.attempts, 5)
            self.assertIn("stopping useless retry loop", context.blocker_reason)

    def test_12_successful_verification_completes_task(self):
        """Verify that evidence-based verification correctly validates output condition."""
        step = PlanStep(
            id=1,
            title="Verify Greeting",
            action_type=ActionType.TOOL,
            description="Prints greeting",
            target="echo greeting",
            tool="terminal_execute",
            arguments={"command": "echo 'Hello from ZARA'"},
            success_condition="Output prints 'Hello from ZARA' and exits with return code 0"
        )
        context = TaskContext(task="Greeting", tag="dev", working_dir=str(self.workspace))
        result = self.engine.act(step, context)
        verified = self.engine.verify(step, result)
        self.assertTrue(verified)
        self.assertEqual(step.status, StepStatus.PASSED)

    def test_13_existing_safety_restrictions_preserved(self):
        """Verify destructive commands and path traversals remain blocked in tool execution."""
        # 1. Destructive command blocking
        step_dangerous = PlanStep(
            id=1,
            title="Dangerous command",
            action_type=ActionType.TOOL,
            description="rm -rf /",
            target="rm",
            tool="terminal_execute",
            arguments={"command": "rm -rf /"}
        )
        context = TaskContext(task="Safety check", tag="dev", working_dir=str(self.workspace))
        res = self.engine.act(step_dangerous, context)
        self.assertFalse(res.success)
        self.assertIn("SAFETY INTERCEPTOR", res.stderr)

        # 2. Path traversal blocking in write_file
        step_traversal = PlanStep(
            id=2,
            title="Path traversal",
            action_type=ActionType.TOOL,
            description="Escape workspace",
            target="../../outside.txt",
            tool="write_file",
            arguments={"path": "../../outside.txt", "content": "bad"}
        )
        res_traversal = self.engine.act(step_traversal, context)
        self.assertFalse(res_traversal.success)
        self.assertIn("Path traversal detected", res_traversal.stderr)

    def test_14_end_to_end_hello_zara_regression(self):
        """
        Requirement 12 End-to-End Regression Test:
        Task: "Create hello_zara.py that prints 'Hello from ZARA', run it, verify the output, and report the result."
        """
        task = "Create a file called hello_zara.py that prints 'Hello from ZARA', run the file, verify that the output is correct, and report what you did."
        summary = self.engine.run_task(task)

        # 1. Summary status must be COMPLETED
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertGreaterEqual(summary["steps_passed"], 2)

        # 2. hello_zara.py must exist on disk and contain print statement
        hello_file = self.workspace / "hello_zara.py"
        self.assertTrue(hello_file.exists(), "hello_zara.py was not created on disk")
        content = hello_file.read_text()
        self.assertIn("Hello from ZARA", content)

        # 3. Reflection must be populated
        self.assertIn("Completed", summary["reflection"])

if __name__ == "__main__":
    unittest.main()
