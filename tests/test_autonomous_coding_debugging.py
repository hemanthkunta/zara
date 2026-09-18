"""
Tests for ZARA Phase 3: Autonomous Coding and Debugging Agent.
Tests A through J covering:
- Test A: Project creation and pre-execution static validation
- Test B: Test generation and automated test discovery
- Test C: Intentional bug diagnosis and targeted repair
- Test D: Syntax error interception before shell run
- Test E: Runtime error (traceback) diagnosis and repair
- Test F: Import error diagnosis and targeted resolution
- Test G: Regression protection across test suites
- Test H: Unrelated file safety and isolation
- Test I: Bounded retries and change diff summary
- Test J: Memory reuse across debugging sessions
"""
import unittest
import tempfile
import shutil
import hashlib
from pathlib import Path

from config.settings import MAX_RETRIES_PER_STEP
from core.state import PlanStep, StepStatus, ActionType, ExecutionResult, TaskContext, Reflection
from core.engine import ZaraEngine


class TestAutonomousCodingDebugging(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.engine = ZaraEngine(workspace_root=str(self.workspace), enable_voice=False)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # TEST A: Basic Project Creation & Pre-Execution Static Validation
    # -------------------------------------------------------------------------
    def test_a_project_creation_and_static_validation(self):
        """Verify calculator creation, static AST validation, and execution."""
        task = "Create a python calculator with add, subtract, multiply, and divide"
        summary = self.engine.run_task(task)

        self.assertEqual(summary["status"], "COMPLETED")
        calc_file = self.workspace / "calculator.py"
        self.assertTrue(calc_file.exists())

        # Static validation check
        is_valid, err = self.engine.coding.validate_static("calculator.py")
        self.assertTrue(is_valid)
        self.assertIsNone(err)

        # Inspect project check
        inspection = self.engine.coding.inspect_project()
        self.assertIn("calculator.py", inspection["python_files"])
        self.assertEqual(inspection["primary_language"], "python")

        # Verify operations
        res = self.engine.tools.execute(
            "terminal_execute",
            {"command": 'python3 -c "import calculator; assert calculator.add(2, 3) == 5; assert calculator.subtract(5, 2) == 3; assert calculator.multiply(3, 4) == 12; assert calculator.divide(10, 2) == 5.0"'}
        )
        self.assertTrue(res.success)

    # -------------------------------------------------------------------------
    # TEST B: Test Generation & Automated Discovery
    # -------------------------------------------------------------------------
    def test_b_test_generation_and_discovery(self):
        """Verify test creation, test discovery, and automated execution."""
        calc_code = (
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n\n"
            "def multiply(a, b):\n    return a * b\n\n"
            "def divide(a, b):\n"
            "    if b == 0:\n"
            "        raise ValueError('Cannot divide by zero')\n"
            "    return a / b\n"
        )
        (self.workspace / "calculator.py").write_text(calc_code, encoding="utf-8")

        test_code = (
            "import unittest\n"
            "from calculator import add, subtract, multiply, divide\n\n"
            "class TestCalculator(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
            "    def test_subtract(self):\n"
            "        self.assertEqual(subtract(5, 2), 3)\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n"
            "    def test_divide(self):\n"
            "        self.assertEqual(divide(10, 2), 5)\n"
            "        with self.assertRaises(ValueError):\n"
            "            divide(1, 0)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        (self.workspace / "test_calculator.py").write_text(test_code, encoding="utf-8")

        # Test discovery
        discovered = self.engine.coding.discover_tests("calculator")
        self.assertIn("test_calculator.py", discovered)

        # Execute tests via run_tests tool
        res = self.engine.tools.execute(
            "run_tests",
            {"test_path": "test_calculator.py"}
        )
        self.assertTrue(res.success)
        output = res.data.get("output", "")
        self.assertIn("ran 4 tests", output.lower())

    # -------------------------------------------------------------------------
    # TEST C: Intentional Bug Diagnosis and Targeted Repair
    # -------------------------------------------------------------------------
    def test_c_intentional_bug_diagnosis_and_repair(self):
        """Verify detection of logic assertion failure, structured diagnosis, and repair."""
        # Buggy calculator: multiply does addition
        calc_code = (
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n\n"
            "def multiply(a, b):\n    return a + b\n\n"
            "def divide(a, b):\n    return a / b\n"
        )
        (self.workspace / "calculator.py").write_text(calc_code, encoding="utf-8")

        test_code = (
            "import unittest\n"
            "from calculator import multiply\n\n"
            "class TestCalculator(unittest.TestCase):\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        (self.workspace / "test_calculator.py").write_text(test_code, encoding="utf-8")

        # Run test - expect failure
        res = self.engine.tools.execute(
            "terminal_execute",
            {"command": "python3 -m unittest test_calculator.py"}
        )
        self.assertFalse(res.success)
        stderr_output = res.data.get("stderr", "") if res.data else res.error
        self.assertIn("AssertionError", stderr_output)

        exec_res = ExecutionResult(
            success=False,
            exit_code=1,
            stdout="",
            stderr=stderr_output
        )

        # Diagnose failure
        step = PlanStep(
            id=1,
            title="Run calculator tests",
            action_type=ActionType.TOOL,
            description="Run unit test suite for calculator",
            target="python3 -m unittest test_calculator.py",
            tool="terminal_execute",
            arguments={"command": "python3 -m unittest test_calculator.py"},
            success_condition="All tests pass"
        )
        diagnosis = self.engine.debugging.diagnose_failure(
            step=step,
            error_output=exec_res.stderr,
            llm_router=self.engine.brain
        )

        self.assertEqual(diagnosis.failure_type, "assertion_failure")
        self.assertIn("multiply", diagnosis.root_cause.lower())
        self.assertEqual(diagnosis.affected_file, "calculator.py")
        self.assertGreaterEqual(diagnosis.confidence, 0.8)

        # Run repair through engine diagnose_and_retry
        context = self.engine.perceive("Fix failing calculator test")
        repaired = self.engine.diagnose_and_retry(step, exec_res, context)
        self.assertTrue(repaired)

        # Verify repaired file passes test
        res_after = self.engine.tools.execute(
            "terminal_execute",
            {"command": "python3 -m unittest test_calculator.py"}
        )
        self.assertTrue(res_after.success)
        self.assertIn("calculator.py", context.files_modified)
        self.assertTrue(any(p.get("file") == "calculator.py" for p in context.patches_applied))

    # -------------------------------------------------------------------------
    # TEST D: Syntax Error Static Validation Interception and Repair
    # -------------------------------------------------------------------------
    def test_d_syntax_error_static_validation_and_repair(self):
        """Verify pre-execution static validation stops shell execution and repairs syntax."""
        broken_code = (
            "def broken_func(\n"
            "    print('Missing closing parenthesis')\n\n"
            "if __name__ == '__main__':\n"
            "    broken_func()\n"
        )
        (self.workspace / "broken_syntax.py").write_text(broken_code, encoding="utf-8")

        # 1. Direct static validation
        is_valid, err = self.engine.coding.validate_static("broken_syntax.py")
        self.assertFalse(is_valid)
        self.assertIn("syntax error", err.lower())

        # 2. Engine act intercepts before shell execution
        step = PlanStep(
            id=1,
            title="Execute broken script",
            action_type=ActionType.TOOL,
            description="Run broken syntax script",
            target="python3 broken_syntax.py",
            tool="terminal_execute",
            arguments={"command": "python3 broken_syntax.py"},
            success_condition="Output contains 'Fixed syntax successfully' and exit code is 0"
        )
        context = self.engine.perceive("Run broken syntax file")
        result = self.engine.act(step, context)

        self.assertFalse(result.success)
        self.assertIn("static validation failed", result.stderr.lower())

        # 3. Diagnosis and repair
        repaired = self.engine.diagnose_and_retry(step, result, context)
        self.assertTrue(repaired)

        # 4. Verify fixed file runs and passes static validation
        is_valid_after, _ = self.engine.coding.validate_static("broken_syntax.py")
        self.assertTrue(is_valid_after)

        result_after = self.engine.act(step, context)
        self.assertTrue(result_after.success)
        self.assertIn("Fixed syntax successfully", result_after.stdout)

    # -------------------------------------------------------------------------
    # TEST E: Runtime Error Diagnosis and Repair
    # -------------------------------------------------------------------------
    def test_e_runtime_error_diagnosis_and_repair(self):
        """Verify ZeroDivisionError traceback parsing, diagnosis, and repair."""
        buggy_code = (
            "def compute(x):\n"
            "    return x / 0\n\n"
            "if __name__ == '__main__':\n"
            "    print(compute(10))\n"
        )
        (self.workspace / "runtime_bug.py").write_text(buggy_code, encoding="utf-8")

        step = PlanStep(
            id=1,
            title="Execute runtime bug script",
            action_type=ActionType.TOOL,
            description="Run script with zero division bug",
            target="python3 runtime_bug.py",
            tool="terminal_execute",
            arguments={"command": "python3 runtime_bug.py"},
            success_condition="Script runs without error"
        )
        context = self.engine.perceive("Fix runtime division by zero")
        res = self.engine.act(step, context)

        self.assertFalse(res.success)
        self.assertIn("ZeroDivisionError", res.stderr)

        diagnosis = self.engine.debugging.diagnose_failure(
            step=step,
            error_output=res.stderr,
            llm_router=self.engine.brain
        )
        self.assertEqual(diagnosis.failure_type, "runtime_error")
        self.assertEqual(diagnosis.affected_file, "runtime_bug.py")

        repaired = self.engine.diagnose_and_retry(step, res, context)
        self.assertTrue(repaired)

        # Re-run step
        res_after = self.engine.act(step, context)
        self.assertTrue(res_after.success)

    # -------------------------------------------------------------------------
    # TEST F: Import Error Diagnosis and Targeted Repair
    # -------------------------------------------------------------------------
    def test_f_import_error_diagnosis_and_repair(self):
        """Verify ModuleNotFoundError diagnosis and local import statement correction."""
        calc_code = "def add(a, b):\n    return a + b\n"
        (self.workspace / "calculator.py").write_text(calc_code, encoding="utf-8")

        consumer_code = (
            "from wrong_module import add\n\n"
            "if __name__ == '__main__':\n"
            "    print(f'Sum: {add(4, 6)}')\n"
        )
        (self.workspace / "consumer.py").write_text(consumer_code, encoding="utf-8")

        step = PlanStep(
            id=1,
            title="Run consumer script",
            action_type=ActionType.TOOL,
            description="Run consumer script importing add",
            target="python3 consumer.py",
            tool="terminal_execute",
            arguments={"command": "python3 consumer.py"},
            success_condition="Output contains Sum: 10"
        )
        context = self.engine.perceive("Fix import error in consumer")
        res = self.engine.act(step, context)

        self.assertFalse(res.success)
        self.assertTrue("ModuleNotFoundError" in res.stderr or "ImportError" in res.stderr)

        diagnosis = self.engine.debugging.diagnose_failure(
            step=step,
            error_output=res.stderr,
            llm_router=self.engine.brain
        )
        self.assertEqual(diagnosis.failure_type, "import_error")
        self.assertEqual(diagnosis.affected_file, "consumer.py")

        repaired = self.engine.diagnose_and_retry(step, res, context)
        self.assertTrue(repaired)

        res_after = self.engine.act(step, context)
        self.assertTrue(res_after.success)
        self.assertIn("Sum: 10", res_after.stdout)

    # -------------------------------------------------------------------------
    # TEST G: Regression Protection Across Test Suites
    # -------------------------------------------------------------------------
    def test_g_regression_protection(self):
        """Verify that adding a new feature and tests preserves existing tests."""
        calc_code = (
            "def add(a, b):\n    return a + b\n\n"
            "def subtract(a, b):\n    return a - b\n"
        )
        (self.workspace / "calculator.py").write_text(calc_code, encoding="utf-8")

        test_code = (
            "import unittest\n"
            "from calculator import add, subtract\n\n"
            "class TestCalc(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
            "    def test_subtract(self):\n"
            "        self.assertEqual(subtract(5, 2), 3)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        (self.workspace / "test_calculator.py").write_text(test_code, encoding="utf-8")

        # Initial test execution passes
        res1 = self.engine.tools.execute(
            "terminal_execute",
            {"command": "python3 -m unittest test_calculator.py"}
        )
        self.assertTrue(res1.success)

        # Add new feature 'multiply' without breaking existing functions
        updated_calc = calc_code + "\ndef multiply(a, b):\n    return a * b\n"
        (self.workspace / "calculator.py").write_text(updated_calc, encoding="utf-8")

        updated_test = (
            "import unittest\n"
            "from calculator import add, subtract, multiply\n\n"
            "class TestCalc(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
            "    def test_subtract(self):\n"
            "        self.assertEqual(subtract(5, 2), 3)\n"
            "    def test_multiply(self):\n"
            "        self.assertEqual(multiply(3, 4), 12)\n\n"
            "if __name__ == '__main__':\n"
            "    unittest.main()\n"
        )
        (self.workspace / "test_calculator.py").write_text(updated_test, encoding="utf-8")

        # Run full suite
        res2 = self.engine.tools.execute(
            "terminal_execute",
            {"command": "python3 -m unittest discover -s . -p 'test_*.py'"}
        )
        self.assertTrue(res2.success)
        self.assertIn("ran 3 tests", res2.data.get("stderr", "").lower() + res2.data.get("stdout", "").lower())

    # -------------------------------------------------------------------------
    # TEST H: Unrelated-File Protection
    # -------------------------------------------------------------------------
    def test_h_unrelated_file_protection(self):
        """Verify that edits to target files leave unrelated files strictly untouched."""
        unrelated_path = self.workspace / "unrelated_secret.py"
        unrelated_content = "# Secret core logic that must not change\nSECRET_KEY = 'zara_phase_3_guard'\n"
        unrelated_path.write_text(unrelated_content, encoding="utf-8")
        original_hash = hashlib.sha256(unrelated_content.encode("utf-8")).hexdigest()

        # Execute task that creates and edits calculator.py
        task = "Create a python calculator with add, subtract, multiply, and divide"
        summary = self.engine.run_task(task)
        self.assertEqual(summary["status"], "COMPLETED")

        # Check unrelated file remained pristine
        current_content = unrelated_path.read_text(encoding="utf-8")
        current_hash = hashlib.sha256(current_content.encode("utf-8")).hexdigest()
        self.assertEqual(original_hash, current_hash)
        self.assertEqual(unrelated_content, current_content)

        # Verify diff_summary in task output does not include unrelated file
        diff_summary = summary.get("diff_summary", {})
        all_diff_files = (
            diff_summary.get("created", []) +
            diff_summary.get("modified", []) +
            diff_summary.get("deleted", [])
        )
        self.assertNotIn("unrelated_secret.py", all_diff_files)

    # -------------------------------------------------------------------------
    # TEST I: Bounded Retry Limit and Diff Summary
    # -------------------------------------------------------------------------
    def test_i_bounded_retry_limit_and_diff_summary(self):
        """Verify retry budget bounds execution and diff summary captures all changes."""
        context = self.engine.perceive("Unfixable task")
        context.files_created.append("new_module.py")
        context.files_modified.append("existing_module.py")
        context.patches_applied.append("existing_module.py")
        context.tests_discovered.append("test_existing.py")
        context.tests_executed.append("test_existing.py")

        step = PlanStep(
            id=1,
            title="Always failing step",
            action_type=ActionType.TOOL,
            description="Step that continually fails",
            target="failing_tool",
            tool="terminal_execute",
            arguments={"command": "invalid_unknown_tool_cmd"},
            success_condition="Impossible"
        )
        step.attempts = MAX_RETRIES_PER_STEP

        res = ExecutionResult(success=False, exit_code=1, stdout="", stderr="Non-recoverable system error")
        retried = self.engine.diagnose_and_retry(step, res, context)
        self.assertFalse(retried)

        diff = context.get_diff_summary()
        self.assertEqual(diff["created"], ["new_module.py"])
        self.assertEqual(diff["modified"], ["existing_module.py"])
        self.assertEqual(diff["fixes"], ["existing_module.py"])
        self.assertEqual(diff["tests_run"], ["test_existing.py"])

    # -------------------------------------------------------------------------
    # TEST J: Memory Reuse Across Debugging Sessions
    # -------------------------------------------------------------------------
    def test_j_memory_reuse_across_debugging_sessions(self):
        """Verify that lessons stored in prior debugging tasks are retrieved during perception."""
        # 1. Store a debugging lesson
        reflection = Reflection(
            task="Debug calculator arithmetic multiplication operator",
            tag="debugging",
            approach="Examined calculator.py and found + operator in multiply function",
            result="Replaced + with * and verified unit tests pass",
            lesson="Check operator symbols inside arithmetic functions when assertion errors occur"
        )
        self.engine.persist(reflection)

        # 2. Perceive a related subsequent task
        subsequent_context = self.engine.perceive(
            "Debug calculator multiply arithmetic issue",
            tag="debugging"
        )

        # 3. Assert lesson was loaded into context.past_lessons
        self.assertTrue(len(subsequent_context.past_lessons) > 0)
        found_lesson = any("operator" in l.lower() or "arithmetic" in l.lower() for l in subsequent_context.past_lessons)
        self.assertTrue(found_lesson)


if __name__ == "__main__":
    unittest.main()
