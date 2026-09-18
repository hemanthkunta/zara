"""Tests for ZARA Phase 11 - Adaptive Replanning, Plan Versioning & Loop Bounds."""

import unittest
from core.state import Diagnosis, StepStatus
from modules.goals import Goal, GoalDomain, GoalParser
from modules.replanning import AdaptiveReplanner, PlanVersion, PlanningFailureType
from modules.workspace import PersistentTask, ProjectBudget


class TestReplanning(unittest.TestCase):
    """Test suite for adaptive replanning, plan versioning, failure taxonomy, and replan limits."""

    def setUp(self):
        self.goal = GoalParser.parse_goal("Build and test the procedural tree generator")
        self.replanner = AdaptiveReplanner(
            project_id="proj-replan-01",
            max_revisions=4,
            max_depth=3,
            max_adaptive_retries=2,
        )
        self.t1 = PersistentTask(
            id="t1",
            project_id="proj-replan-01",
            title="Generate tree mesh",
            capability="coding",
            verification={"method": "ast_validation"},
        )
        self.t2 = PersistentTask(
            id="t2",
            project_id="proj-replan-01",
            title="Run tests",
            capability="debugging",
            dependencies=["t1"],
            verification={"method": "run_tests"},
        )
        self.v1, self.val1 = self.replanner.initialize_plan(self.goal, [self.t1, self.t2])

    def test_01_initial_plan_version(self):
        """Initial plan is registered as version 1 with no parent."""
        self.assertEqual(self.v1.version, 1)
        self.assertIsNone(self.v1.parent_plan_id)
        self.assertEqual(len(self.replanner.history), 1)

    def test_02_failure_classification_taxonomy(self):
        """Unified failure taxonomy correctly classifies various error signals."""
        f_auth = AdaptiveReplanner.classify_failure("Target scope violation: external host forbidden")
        self.assertEqual(f_auth, PlanningFailureType.AUTHORIZATION_FAILURE)

        f_safety = AdaptiveReplanner.classify_failure("Blocked command: destructive rm -rf /")
        self.assertEqual(f_safety, PlanningFailureType.SAFETY_BLOCK)

        f_res = AdaptiveReplanner.classify_failure("Resource exceeded: runtime exceeded budget")
        self.assertEqual(f_res, PlanningFailureType.RESOURCE_EXCEEDED)

        f_cap = AdaptiveReplanner.classify_failure("Tool not found: unsupported capability")
        self.assertEqual(f_cap, PlanningFailureType.MISSING_CAPABILITY)

        f_ver = AdaptiveReplanner.classify_failure("Verification failed: expected artifact missing")
        self.assertEqual(f_ver, PlanningFailureType.VERIFICATION_FAILURE)

        f_exec = AdaptiveReplanner.classify_failure("SyntaxError: invalid syntax at line 42")
        self.assertEqual(f_exec, PlanningFailureType.EXECUTION_FAILURE)

    def test_03_failure_driven_replan_creates_v2(self):
        """Execution failure triggers adaptive replanning and generates a validated Plan v2."""
        failed_task = PersistentTask.from_dict(self.t1.to_dict())
        failed_task.status = StepStatus.FAILED
        failed_task.error = "SyntaxError: unexpected EOF while parsing"

        diag = Diagnosis(
            attempt=1,
            failure_reason="SyntaxError in script",
            hypothesis="Missing closing parenthesis",
            proposed_fix={"action": "Repair syntax error"}
        )

        v2, status = self.replanner.replan(
            goal=self.goal,
            failed_task=failed_task,
            diagnosis=diag
        )
        self.assertEqual(status, "SUCCESS")
        self.assertIsNotNone(v2)
        self.assertEqual(v2.version, 2)
        self.assertEqual(v2.parent_plan_id, self.v1.plan_id)
        self.assertEqual(len(self.replanner.history), 2)
        # Historical plan v1 is preserved
        self.assertEqual(self.replanner.history[0].version, 1)
        # A repair step was inserted before the retried task
        self.assertTrue(any("repair" in t.id for t in v2.tasks))

    def test_04_alternate_capability_fallback(self):
        """Missing capability triggers adaptation by falling back to general capability."""
        replanner = AdaptiveReplanner(project_id="proj-replan-02")
        special_task = PersistentTask(
            id="t_special",
            project_id="proj-replan-02",
            title="Custom hardware acceleration",
            capability="special_hardware",
            verification={"method": "check"}
        )
        replanner.initialize_plan(self.goal, [special_task])

        special_task.status = StepStatus.FAILED
        special_task.error = "Unsupported capability: special_hardware tool not found"

        v2, status = replanner.replan(
            goal=self.goal,
            failed_task=special_task,
            available_capabilities={"coding", "debugging", "general"}
        )
        self.assertEqual(status, "SUCCESS")
        # Task capability adapted to general
        adapted_task = [t for t in v2.tasks if t.id == "t_special"][0]
        self.assertEqual(adapted_task.capability, "general")

    def test_05_safety_and_authorization_blocks_automatic_replan(self):
        """Safety or scope violations halt execution and refuse automatic replanning."""
        auth_task = PersistentTask.from_dict(self.t1.to_dict())
        auth_task.status = StepStatus.FAILED
        auth_task.error = "CyberLabScope unauthorized target scope violation"

        v2, status = self.replanner.replan(self.goal, auth_task)
        self.assertIsNone(v2)
        self.assertIn("BLOCKED", status)
        self.assertIn("AUTHORIZATION_FAILURE", status)

    def test_06_plan_revision_limit_enforced(self):
        """When plan reaches maximum configured revisions, further replanning is BLOCKED."""
        # Max revisions configured to 4 in setUp
        failed_task = PersistentTask.from_dict(self.t1.to_dict())
        failed_task.status = StepStatus.FAILED
        failed_task.error = "SyntaxError on attempt"

        # Advance to revision 4
        for i in range(1, 4):
            failed_task.error = f"SyntaxError attempt {i}"
            v, msg = self.replanner.replan(self.goal, failed_task)
            self.assertIsNotNone(v)

        # 5th attempt should be blocked
        failed_task.error = "SyntaxError attempt 4"
        v_blocked, msg = self.replanner.replan(self.goal, failed_task)
        self.assertIsNone(v_blocked)
        self.assertIn("BLOCKED: Maximum plan revisions limit reached", msg)

    def test_07_replan_loop_protection(self):
        """Repeated identical failures without progress trigger loop protection."""
        failed_task = PersistentTask.from_dict(self.t1.to_dict())
        failed_task.status = StepStatus.FAILED
        failed_task.error = "ExactSameUnresolvableError repeating indefinitely"

        # 1st replan
        v2, status = self.replanner.replan(self.goal, failed_task)
        self.assertEqual(status, "SUCCESS")

        # 2nd replan with exact same signature
        v3, status = self.replanner.replan(self.goal, failed_task)
        self.assertEqual(status, "SUCCESS")

        # 3rd replan exceeds max_adaptive_retries=2
        v_blocked, status = self.replanner.replan(self.goal, failed_task)
        self.assertIsNone(v_blocked)
        self.assertIn("BLOCKED: Replan loop detected", status)

    def test_08_plan_version_serialization_roundtrip(self):
        """PlanVersion accurately serializes to and deserializes from dictionary manifests."""
        v_dict = self.v1.to_dict()
        restored = PlanVersion.from_dict(v_dict)
        self.assertEqual(restored.plan_id, self.v1.plan_id)
        self.assertEqual(restored.version, self.v1.version)
        self.assertEqual(len(restored.tasks), len(self.v1.tasks))
        self.assertEqual(restored.reason_for_change, self.v1.reason_for_change)


if __name__ == "__main__":
    unittest.main()
