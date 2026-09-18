"""
Unit tests for ZARA Phase 17: Core Task Evaluation, Multi-Dimensional Scoring,
Success Criteria Checking, User Feedback Ingestion, and Evidence Hierarchy.
"""

import unittest
import tempfile
import shutil
import time
from pathlib import Path

from core.state import TaskContext, PlanStep, StepStatus, ActionType, Diagnosis
from modules.goals import Goal, GoalDomain, SuccessCriterion
from modules.events import EventBus, EventType
from modules.memory import MemoryStore, MemoryType
from modules.evaluation import (
    EvaluationManager,
    EvaluationResult,
    CriterionResult,
    CriterionStatus,
    UserFeedback,
    UserFeedbackType,
    CandidateStatus,
)


class TestEvaluationCore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.evals_dir = self.tmp_dir / "evaluations"
        self.props_dir = self.tmp_dir / "proposals"
        self.exps_dir = self.tmp_dir / "experiments"
        self.strat_file = self.tmp_dir / "strategies.json"
        self.mem_dir = self.tmp_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(memory_path=self.mem_dir / "zara_log.md", db_path=self.mem_dir / "v.db")
        self.event_bus = EventBus()
        self.manager = EvaluationManager(
            memory_store=self.memory,
            event_bus=self.event_bus,
            evaluations_dir=self.evals_dir,
            proposals_dir=self.props_dir,
            experiments_dir=self.exps_dir,
        )

    def tearDown(self):
        self.manager.close()
        self.memory.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_evaluation_result_creation_and_serialization(self):
        """EvaluationResult correctly instantiates, serializes and deserializes."""
        result = EvaluationResult(
            evaluation_id="eval-test01",
            project_id="proj-1",
            task_id="task-1",
            task_success=True,
            verification_success=True,
            quality_score=0.92,
            efficiency_score=0.85,
            safety_score=1.0,
            reliability_score=0.90,
            overall_score=0.91,
            evidence={"tests": 5},
        )
        d = result.to_dict()
        self.assertEqual(d["evaluation_id"], "eval-test01")
        self.assertEqual(d["overall_score"], 0.91)
        self.assertTrue(d["task_success"])

        restored = EvaluationResult.from_dict(d)
        self.assertEqual(restored.evaluation_id, "eval-test01")
        self.assertEqual(restored.quality_score, 0.92)

    def test_02_multi_dimensional_scoring_clean_success(self):
        """Clean successful task achieves high correctness, quality, efficiency, and safety."""
        ctx = TaskContext(task="Clean build task", tag="coding")
        ctx.steps = [
            PlanStep(id=1, title="Compile", action_type=ActionType.CODE, description="Compile source", target="src", status=StepStatus.PASSED),
            PlanStep(id=2, title="Test", action_type=ActionType.TEST, description="Run tests", target="tests", status=StepStatus.PASSED),
        ]
        ctx.is_completed = True
        ctx.start_time = time.time() - 2.0  # 2s elapsed

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertTrue(eval_res.task_success)
        self.assertTrue(eval_res.verification_success)
        self.assertEqual(eval_res.safety_score, 1.0)
        self.assertGreaterEqual(eval_res.quality_score, 0.8)
        self.assertGreaterEqual(eval_res.overall_score, 0.8)

    def test_03_multi_dimensional_scoring_penalizes_diagnoses(self):
        """Quality and efficiency scores are penalized when multiple diagnostic failures occur."""
        ctx = TaskContext(task="Buggy task", tag="coding")
        ctx.steps = [
            PlanStep(id=1, title="Run", action_type=ActionType.EXECUTE, description="Run script", target="main.py", status=StepStatus.PASSED),
        ]
        ctx.diagnoses = [
            Diagnosis(attempt=1, failure_reason="IndexError", hypothesis="out of bounds", proposed_fix={"action": "patch"}),
            Diagnosis(attempt=2, failure_reason="TypeError", hypothesis="mismatched type", proposed_fix={"action": "cast"}),
        ]
        ctx.total_retries = 2
        ctx.is_completed = True

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertLess(eval_res.quality_score, 0.8)
        self.assertLess(eval_res.efficiency_score, 0.7)

    def test_04_safety_score_zero_on_security_intercept(self):
        """Security intercept drops safety score to 0.0."""
        ctx = TaskContext(task="Attack scan", tag="cyber")
        ctx.events = [{"type": "scope_violation", "message": "Target evil.corp is forbidden"}]
        ctx.is_completed = False
        ctx.blocker_reason = "Scope violation"

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertEqual(eval_res.safety_score, 0.0)
        self.assertFalse(eval_res.task_success)
        self.assertTrue(any("Safety intercept" in w for w in eval_res.warnings))

    def test_05_success_criteria_checking_passed(self):
        """Goal success criteria verified when task execution matches assertion."""
        goal = Goal(
            goal_id="g-1",
            raw_request="Write unit tests",
            normalized_goal="Write comprehensive test suite",
            domain=GoalDomain.CODING,
            success_criteria=[
                SuccessCriterion(id="sc-1", description="Tests executed and passing", verification_method="run_tests", required=True),
            ]
        )
        ctx = TaskContext(task="Write unit tests")
        ctx.steps = [PlanStep(id=1, title="Run tests", action_type=ActionType.TEST, description="Run test suite", target="tests", status=StepStatus.PASSED)]
        ctx.tests_executed = ["test_foo.py"]
        ctx.is_completed = True

        eval_res = self.manager.evaluate_task_execution(ctx, goal=goal)
        self.assertTrue(eval_res.task_success)
        self.assertEqual(len(eval_res.criteria_results), 1)
        self.assertEqual(eval_res.criteria_results[0].status, CriterionStatus.PASSED)

    def test_06_success_criteria_failure_blocks_task_success(self):
        """When a required success criterion fails, task_success is False even if steps ran."""
        goal = Goal(
            goal_id="g-2",
            raw_request="Create scene render",
            normalized_goal="Create 3D scene rendering",
            domain=GoalDomain.BLENDER,
            success_criteria=[
                SuccessCriterion(id="sc-2", description="Scene artifact created", verification_method="file_exists", required=True)
            ]
        )
        ctx = TaskContext(task="Render scene")
        ctx.is_completed = True
        ctx.files_created = []
        ctx.files_modified = []

        eval_res = self.manager.evaluate_task_execution(ctx, goal=goal)
        self.assertFalse(eval_res.task_success)
        self.assertEqual(eval_res.criteria_results[0].status, CriterionStatus.FAILED)

    def test_07_user_feedback_positive_ingestion(self):
        """Positive feedback is classified and saved as USER_FEEDBACK memory."""
        fb = self.manager.record_user_feedback("Great job! That worked perfectly.")
        self.assertEqual(fb.type, UserFeedbackType.POSITIVE)
        self.assertIn("great job", fb.raw_text.lower())

        # Check retrieval in memory
        results = self.memory.retrieve("feedback")
        self.assertTrue(len(results) >= 1)
        self.assertIn("User feedback (POSITIVE)", results[0].content)

    def test_08_user_feedback_correction_ingestion(self):
        """Correction feedback creates structured correction memory."""
        fb = self.manager.record_user_feedback("That's wrong. Instead, use pytest rather than unittest.")
        self.assertIn(fb.type, (UserFeedbackType.NEGATIVE, UserFeedbackType.CORRECTION))
        self.assertIsNotNone(fb.raw_text)

    def test_09_user_feedback_rating_normalization(self):
        """Ratings 1-10 are normalized to 0.0-1.0 float scale."""
        fb = self.manager.record_user_feedback("Rating for last task", rating=8.5)
        self.assertEqual(fb.type, UserFeedbackType.RATING)
        self.assertAlmostEqual(fb.rating, 0.85, places=2)

    def test_10_user_satisfaction_influences_overall_score(self):
        """Explicit user satisfaction score is incorporated into overall score calculation."""
        ctx = TaskContext(task="Assisted task")
        ctx.steps = [PlanStep(id=1, title="step", action_type=ActionType.CODE, description="step", target="t", status=StepStatus.PASSED)]
        ctx.is_completed = True

        fb = UserFeedback(feedback_id="fb-1", type=UserFeedbackType.RATING, raw_text="5/10", rating=0.5)
        eval_res = self.manager.evaluate_task_execution(ctx, user_feedback=fb)
        self.assertIsNotNone(eval_res.user_satisfaction)
        self.assertEqual(eval_res.user_satisfaction, 0.5)

    def test_11_failure_learning_generates_error_pattern(self):
        """Task failure diagnoses generate ERROR_PATTERN learning candidates and memories."""
        ctx = TaskContext(task="Compile Cython extension", tag="coding")
        ctx.diagnoses = [
            Diagnosis(
                attempt=1,
                failure_reason="gcc: error: missing numpy headers",
                hypothesis="include_dirs missing numpy.get_include()",
                proposed_fix={"action": "import numpy and add to include_dirs"},
                confidence=0.90,
                failure_type="COMPILATION_ERROR",
                root_cause="Missing include directory"
            )
        ]
        ctx.is_completed = True

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertTrue(len(self.manager.learning_candidates) >= 1)

        cand = list(self.manager.learning_candidates.values())[0]
        self.assertEqual(cand.memory_type, "ERROR_PATTERN")
        self.assertIn("COMPILATION_ERROR", cand.lesson)

        # Check retrieval in memory
        mems = self.memory.retrieve("Missing include directory")
        self.assertTrue(len(mems) >= 1)
        self.assertIn("Missing include directory", mems[0].content)

    def test_12_success_learning_generates_success_pattern(self):
        """High-scoring task generates SUCCESS_PATTERN memory."""
        ctx = TaskContext(task="Refactor models", tag="refactor")
        ctx.steps = [
            PlanStep(id=1, title="Inspect", action_type=ActionType.CODE, description="Inspect", target="src", status=StepStatus.PASSED),
            PlanStep(id=2, title="Write diff", action_type=ActionType.CODE, description="Write diff", target="src", status=StepStatus.PASSED),
        ]
        ctx.is_completed = True

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertGreaterEqual(eval_res.overall_score, 0.85)

        mems = self.memory.retrieve("Successful workflow")
        self.assertTrue(len(mems) >= 1)
        self.assertIn("Successful workflow", mems[0].content)

    def test_13_objective_evidence_hierarchy(self):
        """Objective verification results take precedence over subjective opinion."""
        ctx = TaskContext(task="Objective test")
        ctx.steps = [PlanStep(id=1, title="step 1", action_type=ActionType.TEST, description="step 1", target="tests", status=StepStatus.PASSED)]
        ctx.tests_executed = ["test_core.py"]
        ctx.is_completed = True

        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertTrue(eval_res.verification_success)
        self.assertEqual(eval_res.evidence["tests_run"], ["test_core.py"])

    def test_14_evaluation_persistence_to_disk(self):
        """Evaluations are saved to disk in JSON format and reloadable."""
        ctx = TaskContext(task="Persistence test")
        ctx.is_completed = True
        eval_res = self.manager.evaluate_task_execution(ctx)

        eval_file = self.evals_dir / f"{eval_res.evaluation_id}.json"
        self.assertTrue(eval_file.exists())

        mgr2 = EvaluationManager(
            memory_store=self.memory,
            evaluations_dir=self.evals_dir,
            proposals_dir=self.props_dir,
            experiments_dir=self.exps_dir
        )
        self.assertIn(eval_res.evaluation_id, mgr2.evaluations)
        mgr2.close()

    def test_15_eventbus_publishing_on_evaluation(self):
        """Evaluation emits EVALUATION_STARTED and EVALUATION_COMPLETED events."""
        events_received = []
        self.event_bus.subscribe(EventType.EVALUATION_STARTED, lambda ev: events_received.append(ev))
        self.event_bus.subscribe(EventType.EVALUATION_COMPLETED, lambda ev: events_received.append(ev))

        ctx = TaskContext(task="Event test")
        ctx.is_completed = True
        self.manager.evaluate_task_execution(ctx)

        self.assertEqual(len(events_received), 2)
        self.assertEqual(events_received[0].type, EventType.EVALUATION_STARTED)
        self.assertEqual(events_received[1].type, EventType.EVALUATION_COMPLETED)

    def test_16_secret_redaction_in_feedback(self):
        """Secrets in user feedback are scrubbed before storage."""
        secret_prompt = "Never use API key sk-abcdef123456789012345678 in public code."
        fb = self.manager.record_user_feedback(secret_prompt)
        self.assertNotIn("sk-abcdef123456789012345678", fb.raw_text)
        self.assertIn("[REDACTED", fb.raw_text)

    def test_17_efficiency_score_scaling(self):
        """High retries significantly depress efficiency score."""
        ctx = TaskContext(task="Retry heavy task")
        ctx.total_retries = 6
        ctx.is_completed = True
        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertLess(eval_res.efficiency_score, 0.4)

    def test_18_reliability_score_partial_steps(self):
        """Task with 1 failed step out of 2 has lower reliability."""
        ctx = TaskContext(task="Partially failing task")
        ctx.steps = [
            PlanStep(id=1, title="Step 1", action_type=ActionType.CODE, description="Step 1", target="src", status=StepStatus.PASSED),
            PlanStep(id=2, title="Step 2", action_type=ActionType.CODE, description="Step 2", target="src", status=StepStatus.FAILED),
        ]
        ctx.is_completed = False
        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertLess(eval_res.reliability_score, 0.6)

    def test_19_empty_context_evaluation_safety(self):
        """Empty context executes safely without ZeroDivisionError."""
        ctx = TaskContext(task="")
        eval_res = self.manager.evaluate_task_execution(ctx)
        self.assertIsNotNone(eval_res.evaluation_id)
        self.assertFalse(eval_res.task_success)
        self.assertTrue(0.0 <= eval_res.overall_score <= 1.0)

    def test_20_criterion_result_serialization_roundtrip(self):
        """CriterionResult serialization roundtrip."""
        cr = CriterionResult(
            criterion="Code compiles",
            status=CriterionStatus.PASSED,
            evidence="exit code 0",
            confidence=0.98,
            required=True
        )
        d = cr.to_dict()
        cr2 = CriterionResult.from_dict(d)
        self.assertEqual(cr2.criterion, "Code compiles")
        self.assertEqual(cr2.status, CriterionStatus.PASSED)
        self.assertEqual(cr2.confidence, 0.98)

    def test_21_user_feedback_preference_extraction(self):
        """Explicit preferences create PREFERENCE feedback."""
        fb = self.manager.record_user_feedback("My preference is to always run tests with -v")
        self.assertEqual(fb.type, UserFeedbackType.PREFERENCE)
        self.assertIn("tests with -v", fb.correction)

    def test_22_get_stats_aggregates_evaluations(self):
        """get_stats returns correct totals and success rate."""
        ctx1 = TaskContext(task="T1")
        ctx1.is_completed = True
        self.manager.evaluate_task_execution(ctx1)

        ctx2 = TaskContext(task="T2")
        ctx2.is_completed = False
        self.manager.evaluate_task_execution(ctx2)

        stats = self.manager.get_stats()
        self.assertEqual(stats["tasks_evaluated"], 2)
        self.assertEqual(stats["tasks_successful"], 1)
        self.assertEqual(stats["success_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
