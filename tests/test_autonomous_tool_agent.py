"""
Tests for ZARA Phase 2: Autonomous Tool-Using Agent with Dynamic Selection,
Observation Capture, Dependency Gating, Verification Evidence, and Task Budgets.
Tests A through J.
"""
import unittest
import tempfile
import shutil
import time
from pathlib import Path
from typing import List

from config.settings import (
    FailureType,
    MAX_STEPS,
    MAX_RETRIES_PER_STEP,
    MAX_TOTAL_RETRIES,
    MAX_EXECUTION_TIME_SECONDS
)
from core.state import PlanStep, StepStatus, ActionType, ExecutionResult, TaskContext
from core.engine import ZaraEngine
from brain.providers.mock import MockLLMProvider

class TestAutonomousToolAgent(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.engine = ZaraEngine(workspace_root=str(self.workspace), enable_voice=False)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # TEST A: Autonomous File Creation, Execution, and Evidence Verification
    # -------------------------------------------------------------------------
    def test_a_autonomous_file_creation_execution_and_evidence(self):
        task = "Create a file called auto_demo.py that prints 'Autonomous ZARA Active', run the file, verify that the output is correct, and report what you did."
        summary = self.engine.run_task(task)

        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(summary["steps_total"], 2)
        self.assertEqual(summary["steps_passed"], 2)

        # Check file was written to disk
        created_file = self.workspace / "auto_demo.py"
        self.assertTrue(created_file.exists())
        self.assertIn("Autonomous ZARA Active", created_file.read_text())

        # Check structured observations on steps
        step1 = self.engine.orchestrator # steps in context
        # Check step 1 observation
        # Let's inspect checkpoint / context
        # We can also verify via engine plan & act directly:
        context = self.engine.perceive(task)
        steps = self.engine.plan(context)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].tool, "write_file")
        self.assertEqual(steps[1].tool, "terminal_execute")

        res1 = self.engine.act(steps[0], context)
        self.assertTrue(res1.success)
        self.assertIsNotNone(steps[0].observation)
        self.assertEqual(steps[0].observation["tool"], "write_file")
        self.assertTrue(steps[0].observation["success"])

        ver1 = self.engine.verify(steps[0], res1, context=context)
        self.assertTrue(ver1)
        self.assertTrue(steps[0].verification["verified"])
        self.assertTrue(len(steps[0].verification["evidence"]) > 0)

        res2 = self.engine.act(steps[1], context)
        self.assertTrue(res2.success)
        self.assertIn("Autonomous ZARA Active", res2.stdout)
        self.assertIsNotNone(steps[1].observation)
        self.assertEqual(steps[1].observation["exit_code"], 0)

        ver2 = self.engine.verify(steps[1], res2, context=context)
        self.assertTrue(ver2)
        self.assertTrue(steps[1].verification["verified"])
        # Check that events were recorded
        event_types = [e["event"] for e in context.events]
        self.assertIn("task_started", event_types)
        self.assertIn("plan_created", event_types)
        self.assertIn("tool_selected", event_types)
        self.assertIn("tool_started", event_types)
        self.assertIn("tool_finished", event_types)
        self.assertIn("verification_started", event_types)
        self.assertIn("verification_finished", event_types)

    # -------------------------------------------------------------------------
    # TEST B: Self-Correction on Intentional Syntax Error
    # -------------------------------------------------------------------------
    def test_b_self_correction_on_syntax_error(self):
        task = "Create broken_syntax.py with a syntax error, run it, diagnose and repair it."
        summary = self.engine.run_task(task)

        self.assertEqual(summary["status"], "COMPLETED")
        # File should have been repaired by the diagnosis fix
        repaired_file = self.workspace / "broken_syntax.py"
        self.assertTrue(repaired_file.exists())
        self.assertIn("Fixed syntax successfully", repaired_file.read_text())

    # -------------------------------------------------------------------------
    # TEST C: Multi-Step Task with Dependency Tracking and Skipping
    # -------------------------------------------------------------------------
    def test_c_multi_step_dependency_tracking_and_skipping(self):
        # Subtest 1: Happy path when step 1 succeeds
        task = "Create two files with helper module and main application consumer, and execute it."
        summary = self.engine.run_task(task)
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(summary["steps_total"], 3)
        self.assertEqual(summary["steps_passed"], 3)
        self.assertEqual(summary["steps_skipped"], 0)

        # Subtest 2: When step 1 fails, step 2 and step 3 must be skipped
        failing_step1 = PlanStep(
            id=1,
            title="Failing prerequisite",
            action_type=ActionType.TOOL,
            description="Command guaranteed to fail",
            target="false",
            payload={"command": "exit 1"},
            tool="terminal_execute",
            arguments={"command": "exit 1"},
            dependencies=[],
            success_condition="Exits with 0"
        )
        dependent_step2 = PlanStep(
            id=2,
            title="Dependent step 2",
            action_type=ActionType.TOOL,
            description="Should be skipped because step 1 failed",
            target="echo step2",
            payload={"command": "echo step2"},
            tool="terminal_execute",
            arguments={"command": "echo step2"},
            dependencies=[1],
            success_condition="Exits with 0"
        )

        engine = ZaraEngine(workspace_root=str(self.workspace), enable_voice=False, max_retries_per_step=1)
        summary_dep = engine.run_task("Task with failing prerequisite", steps=[failing_step1, dependent_step2])
        self.assertEqual(summary_dep["status"], "BLOCKED")
        self.assertEqual(summary_dep["steps_skipped"], 1)
        self.assertEqual(dependent_step2.status, StepStatus.SKIPPED)
        self.assertEqual(dependent_step2.failure_type, FailureType.DEPENDENCY_FAILURE.value)

    # -------------------------------------------------------------------------
    # TEST D: Dynamic Tool Selection - File Reading & Observation
    # -------------------------------------------------------------------------
    def test_d_dynamic_tool_selection_read_file(self):
        # Create a sample file
        doc_path = self.workspace / "sample_info.txt"
        doc_path.write_text("ZARA autonomous tool agent specification v2.0")

        task = "Read the file sample_info.txt and inspect its content."
        context = self.engine.perceive(task)
        steps = self.engine.plan(context)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].tool, "read_file")
        self.assertEqual(steps[0].arguments.get("path"), "sample_info.txt")

        result = self.engine.act(steps[0], context)
        self.assertTrue(result.success)
        self.assertIn("ZARA autonomous tool agent", result.stdout)
        self.assertIsNotNone(steps[0].observation)
        self.assertEqual(steps[0].observation["tool"], "read_file")

        verified = self.engine.verify(steps[0], result, context=context)
        self.assertTrue(verified)
        self.assertTrue(steps[0].verification["verified"])

    # -------------------------------------------------------------------------
    # TEST E: Dynamic Tool Selection - Directory Listing
    # -------------------------------------------------------------------------
    def test_e_dynamic_tool_selection_list_dir(self):
        (self.workspace / "module1.py").write_text("# mod1")
        (self.workspace / "module2.py").write_text("# mod2")

        task = "List python files in the directory."
        context = self.engine.perceive(task)
        steps = self.engine.plan(context)

        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].tool, "list_dir")

        result = self.engine.act(steps[0], context)
        self.assertTrue(result.success)
        self.assertIn("module1.py", result.stdout)
        self.assertIn("module2.py", result.stdout)

        verified = self.engine.verify(steps[0], result, context=context)
        self.assertTrue(verified)
        self.assertTrue(steps[0].verification["verified"])

    # -------------------------------------------------------------------------
    # TEST F: Tool Failure Handling - Invalid / Missing Tool
    # -------------------------------------------------------------------------
    def test_f_invalid_tool_fails_safely_with_classification(self):
        invalid_step = PlanStep(
            id=1,
            title="Use non-existent tool",
            action_type=ActionType.TOOL,
            description="Calling an unregistered tool",
            target="fake",
            payload={},
            tool="nonexistent_magic_tool",
            arguments={},
            dependencies=[],
            success_condition="Should fail"
        )
        context = self.engine.perceive("Run nonexistent tool task")
        res = self.engine.act(invalid_step, context)

        self.assertFalse(res.success)
        self.assertEqual(invalid_step.failure_type, FailureType.TOOL_VALIDATION_FAILURE.value)
        self.assertIsNotNone(invalid_step.observation)
        self.assertFalse(invalid_step.observation["success"])

        verified = self.engine.verify(invalid_step, res, context=context)
        self.assertFalse(verified)
        self.assertFalse(invalid_step.verification["verified"])

    # -------------------------------------------------------------------------
    # TEST G: Diagnosis Produces Changed Action on Retry
    # -------------------------------------------------------------------------
    def test_g_diagnosis_produces_changed_action(self):
        from unittest.mock import patch
        from core.state import Diagnosis

        step = PlanStep(
            id=1,
            title="Execute bad command",
            action_type=ActionType.TOOL,
            description="Command fails initially",
            target="test",
            payload={"command": "false"},
            tool="terminal_execute",
            arguments={"command": "false"},
            dependencies=[],
            success_condition="Exits with 0"
        )
        context = self.engine.perceive("Task needing diagnosis")
        res = self.engine.act(step, context)
        self.assertFalse(res.success)
        self.assertEqual(step.attempts, 1)

        # Mock diagnosis to produce a changed action (corrected argument)
        def mock_diag(*args, **kwargs):
            return Diagnosis(
                attempt=1,
                failure_reason="Exit code 1",
                hypothesis="Command was 'false'; changing command to echo success",
                proposed_fix={"action": "fix_command"},
                root_cause_category="command",
                corrected_arguments={"command": "echo 'Diagnosis corrected'"}
            )

        with patch.object(self.engine.debugging, "diagnose_failure", side_effect=mock_diag):
            success = self.engine.diagnose_and_retry(step, res, context)
            self.assertTrue(success)
            self.assertEqual(step.attempts, 2)
            self.assertEqual(step.arguments["command"], "echo 'Diagnosis corrected'")
            self.assertEqual(step.status, StepStatus.PASSED)

    # -------------------------------------------------------------------------
    # TEST H: Configurable Task Budgets Enforced
    # -------------------------------------------------------------------------
    def test_h_budget_limits_enforced(self):
        # 1. MAX_STEPS budget enforcement
        custom_engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False,
            max_steps=2,
            max_total_retries=2,
            max_execution_time_seconds=1.0
        )

        steps = [
            PlanStep(id=i, title=f"Step {i}", action_type=ActionType.TOOL, description="", target="", payload={}, tool="list_dir", arguments={"path": "."}, dependencies=[])
            for i in range(1, 6)
        ]
        context = custom_engine.perceive("Task with 5 steps")
        planned = custom_engine.plan(context, custom_steps=steps)
        self.assertLessEqual(len(planned), 2)

        # 2. MAX_TOTAL_RETRIES budget enforcement
        failing_step = PlanStep(
            id=1,
            title="Step that always fails",
            action_type=ActionType.TOOL,
            description="",
            target="",
            payload={"command": "exit 1"},
            tool="terminal_execute",
            arguments={"command": "exit 1"},
            dependencies=[]
        )
        context = custom_engine.perceive("Task exceeding total retries")
        res = custom_engine.act(failing_step, context)
        retried = custom_engine.diagnose_and_retry(failing_step, res, context)
        self.assertFalse(retried)
        self.assertLessEqual(context.total_retries, custom_engine.max_total_retries)

        # 3. Execution time timeout
        slow_engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False,
            max_execution_time_seconds=0.01
        )
        # Artificial delay before task execution
        time.sleep(0.05)
        summary_timeout = slow_engine.run_task("Timeout task")
        # Should have stopped or skipped
        self.assertEqual(summary_timeout["status"], "BLOCKED")

    # -------------------------------------------------------------------------
    # TEST I: Sequential Tasks Clean State Isolation
    # -------------------------------------------------------------------------
    def test_i_sequential_tasks_clean_state_isolation(self):
        summary1 = self.engine.run_task("Create a file called task1.txt with prints 'Task1'", tag="run1")
        self.assertEqual(summary1["status"], "COMPLETED")
        self.assertEqual(summary1["steps_passed"], 1)

        summary2 = self.engine.run_task("Create a file called task2.txt with prints 'Task2'", tag="run2")
        self.assertEqual(summary2["status"], "COMPLETED")
        self.assertEqual(summary2["steps_passed"], 1)

        # Confirm isolation between runs
        file1 = self.workspace / "task1.txt"
        file2 = self.workspace / "task2.txt"
        self.assertTrue(file1.exists())
        self.assertTrue(file2.exists())
        self.assertIn("Task1", file1.read_text())
        self.assertIn("Task2", file2.read_text())

    # -------------------------------------------------------------------------
    # TEST J: Memory Retrieval Before Planning Loads Past Lessons
    # -------------------------------------------------------------------------
    def test_j_memory_retrieval_before_planning(self):
        from core.state import Reflection
        # Pre-seed memory with a lesson
        reflection = Reflection(
            task="Optimize database indexing",
            tag="database",
            approach="Created targeted composite index on (user_id, created_at)",
            result="Query duration dropped from 250ms to 4ms",
            lesson="Always index foreign keys and filter columns together for sorting queries"
        )
        self.engine.persist(reflection)

        # Perceive a related database task
        context = self.engine.perceive("Optimize database query for slow user orders", tag="database")
        self.assertTrue(len(context.past_lessons) > 0)
        self.assertTrue(any("index" in l.lower() for l in context.past_lessons))

if __name__ == "__main__":
    unittest.main()
