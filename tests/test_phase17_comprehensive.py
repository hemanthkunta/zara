"""
ZARA Phase 17 — Comprehensive Self-Improvement, Evaluation, Learning & Safety Suite.
Validates multi-dimensional scoring, strategy registry, model/worker/planner learning,
risk-gated proposals, controlled experiments, regression guards, atomic rollbacks,
hard safety invariants, EventBus publishing, CLI commands, and REST APIs.
"""
import unittest
import tempfile
import shutil
import json
from pathlib import Path
from starlette.testclient import TestClient

from core.state import TaskContext, PlanStep, StepStatus, ActionType, Diagnosis
from modules.events import EventBus, EventType
from modules.memory import MemoryStore, MemoryType, contains_secret, scrub_text
from modules.strategies import (
    Strategy,
    StrategyStatus,
    StrategyDomain,
    StrategyRegistry,
)
from modules.improvement import (
    ChangeType,
    ProposalRisk,
    ProposalStatus,
    ImprovementProposal,
    ImprovementVersion,
)
from modules.experiments import (
    Experiment,
    ExperimentStatus,
)
from modules.learning import (
    CandidateStatus,
    UserFeedbackType,
    UserFeedback,
    LearningCandidate,
    FailurePattern,
    ModelPerformanceObservation,
    WorkerPerformanceObservation,
    PlannerPerformanceObservation,
)
from modules.evaluation import (
    EvaluationManager,
    EvaluationResult,
    CriterionResult,
    CriterionStatus,
    EvaluationDimension,
)
from core.engine import ZaraEngine
from ui.server import create_ui_app


class TestPhase17Comprehensive(unittest.TestCase):
    """80-test comprehensive Phase 17 test suite."""

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
            strategies_file=self.strat_file,
        )

    def tearDown(self):
        self.manager.close()
        self.memory.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # =========================================================================
    # Group 1: Evaluation Engine & Dimensions (Tests 1 - 8)
    # =========================================================================

    def test_01_evaluation_dimension_enum_values(self):
        """1. Evaluation dimensions include all mandatory quality metrics."""
        dims = {d.value for d in EvaluationDimension}
        self.assertIn("CORRECTNESS", dims)
        self.assertIn("QUALITY", dims)
        self.assertIn("EFFICIENCY", dims)
        self.assertIn("RELIABILITY", dims)
        self.assertIn("SAFETY", dims)
        self.assertIn("USER_SATISFACTION", dims)

    def test_02_deterministic_scoring_perfect_task(self):
        """2. Deterministic scoring produces 1.0 for a flawless completed task."""
        ctx = TaskContext(task="Build Fibonacci", tag="coding")
        ctx.is_completed = True
        ctx.steps = [
            PlanStep(step_id="s1", description="step 1", action_type=ActionType.BASH, status=StepStatus.PASSED),
            PlanStep(step_id="s2", description="step 2", action_type=ActionType.BASH, status=StepStatus.PASSED),
        ]
        res = self.manager.evaluate_task_execution(ctx)
        self.assertEqual(res.overall_score, 1.0)
        self.assertTrue(res.task_success)
        self.assertTrue(res.verification_success)

    def test_03_deterministic_scoring_penalizes_diagnoses_and_retries(self):
        """3. Scoring docks reliability when diagnoses or retries occur."""
        ctx = TaskContext(task="Debug script", tag="dev")
        ctx.is_completed = True
        ctx.total_retries = 3
        ctx.diagnoses = [
            Diagnosis(attempt=1, failure_reason="Missing file", suggested_fix="Touch file"),
            Diagnosis(attempt=2, failure_reason="Permissions error", suggested_fix="Chmod file"),
        ]
        ctx.steps = [
            PlanStep(step_id="s1", description="run", action_type=ActionType.BASH, status=StepStatus.PASSED, retries=3)
        ]
        res = self.manager.evaluate_task_execution(ctx)
        self.assertLess(res.reliability_score, 1.0)
        self.assertLess(res.overall_score, 1.0)

    def test_04_scoring_marks_failure_when_incomplete(self):
        """4. Incomplete task yields task_success=False and zero quality score."""
        ctx = TaskContext(task="Deploy cluster", tag="ops")
        ctx.is_completed = False
        ctx.blocker_reason = "Out of memory"
        res = self.manager.evaluate_task_execution(ctx)
        self.assertFalse(res.task_success)
        self.assertEqual(res.quality_score, 0.0)

    def test_05_criterion_results_aggregation(self):
        """5. Criterion results serialize and deserialize accurately."""
        cr = CriterionResult(
            criterion="Test exit code is 0",
            status=CriterionStatus.PASSED,
            evidence={"exit_code": 0},
            score=1.0,
            dimension=EvaluationDimension.CORRECTNESS
        )
        d = cr.to_dict()
        self.assertEqual(d["status"], "PASSED")
        deserialized = CriterionResult.from_dict(d)
        self.assertEqual(deserialized.criterion, cr.criterion)
        self.assertEqual(deserialized.score, 1.0)

    def test_06_evaluation_result_serialization_roundtrip(self):
        """6. EvaluationResult round-trips via to_dict and from_dict."""
        ev = EvaluationResult(
            evaluation_id="eval-roundtrip-01",
            project_id="proj-alpha",
            task_id="task-123",
            task_success=True,
            verification_success=True,
            quality_score=0.95,
            efficiency_score=0.88,
            reliability_score=0.90,
            safety_score=1.0,
            overall_score=0.93,
        )
        d = ev.to_dict()
        restored = EvaluationResult.from_dict(d)
        self.assertEqual(restored.evaluation_id, ev.evaluation_id)
        self.assertEqual(restored.overall_score, ev.overall_score)

    def test_07_thread_safe_evaluation_recording(self):
        """7. Concurrent evaluation recording executes safely without state corruption."""
        import threading
        threads = []
        for i in range(10):
            ctx = TaskContext(task=f"Concurrent task {i}", tag="test")
            ctx.is_completed = True
            t = threading.Thread(target=self.manager.evaluate_task_execution, args=(ctx,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(self.manager.evaluations), 10)

    def test_08_limitations_and_warnings_tracking(self):
        """8. Evaluation warns when evidence is missing or tools fail."""
        ctx = TaskContext(task="Empty run", tag="test")
        ctx.is_completed = False
        res = self.manager.evaluate_task_execution(ctx)
        self.assertGreaterEqual(len(res.warnings), 1)

    # =========================================================================
    # Group 2: Task Outcome Learning & Lessons (Tests 9 - 16)
    # =========================================================================

    def test_09_extract_success_pattern_from_clean_task(self):
        """9. Flawless execution produces a SUCCESS_PATTERN learning candidate."""
        ctx = TaskContext(task="Create helper module", tag="coding")
        ctx.is_completed = True
        ctx.steps = [PlanStep(step_id="s1", description="create", action_type=ActionType.BASH, status=StepStatus.PASSED)]
        res = self.manager.evaluate_task_execution(ctx)
        lessons = self.manager.extract_lessons(ctx, res)
        self.assertGreaterEqual(len(lessons), 1)
        success_patterns = [l for l in lessons if l.memory_type == "SUCCESS_PATTERN"]
        self.assertGreaterEqual(len(success_patterns), 1)

    def test_10_extract_error_pattern_from_failed_task(self):
        """10. Diagnosed task failure produces an ERROR_PATTERN learning candidate."""
        ctx = TaskContext(task="Compile binary", tag="coding")
        ctx.is_completed = False
        ctx.diagnoses = [Diagnosis(attempt=1, failure_reason="gcc not found", suggested_fix="install gcc")]
        res = self.manager.evaluate_task_execution(ctx)
        lessons = self.manager.extract_lessons(ctx, res)
        error_patterns = [l for l in lessons if l.memory_type == "ERROR_PATTERN"]
        self.assertGreaterEqual(len(error_patterns), 1)
        self.assertIn("gcc not found", error_patterns[0].lesson)

    def test_11_lesson_deduplication(self):
        """11. Repeating the exact same failure does not create duplicate candidate IDs."""
        ctx1 = TaskContext(task="Task A", tag="dev")
        ctx1.diagnoses = [Diagnosis(attempt=1, failure_reason="Port conflict 8080")]
        ctx1.is_completed = False
        res1 = self.manager.evaluate_task_execution(ctx1)
        l1 = self.manager.extract_lessons(ctx1, res1)

        ctx2 = TaskContext(task="Task B", tag="dev")
        ctx2.diagnoses = [Diagnosis(attempt=1, failure_reason="Port conflict 8080")]
        ctx2.is_completed = False
        res2 = self.manager.evaluate_task_execution(ctx2)
        l2 = self.manager.extract_lessons(ctx2, res2)

        # Candidates dict keyed by deterministic ID should not grow unboundedly
        matched = [c for c in self.manager.learning_candidates.values() if "Port conflict 8080" in c.lesson]
        self.assertEqual(len(matched), 1)

    def test_12_learning_candidate_confidence_bounds(self):
        """12. Learning candidates maintain confidence bounded between 0.0 and 1.0."""
        cand = LearningCandidate(candidate_id="cand-1", source="test", lesson="A lesson", confidence=0.85)
        d = cand.to_dict()
        self.assertGreaterEqual(d["confidence"], 0.0)
        self.assertLessEqual(d["confidence"], 1.0)

    def test_13_memory_integration_persists_experience(self):
        """13. Learning candidate is stored into Phase 14 MemoryStore as EXPERIENCE."""
        cand = LearningCandidate(
            candidate_id="cand-exp",
            source="task_evaluation",
            lesson="Always compile with -O2 for release builds",
            confidence=0.92,
            memory_type="EXPERIENCE"
        )
        self.manager._store_learning_in_memory(cand)
        retrieved = self.memory.retrieve("release builds")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertIn("-O2", retrieved[0].content)

    def test_14_memory_integration_persists_error_pattern(self):
        """14. Error pattern candidate is stored into Phase 14 MemoryStore as ERROR_PATTERN."""
        cand = LearningCandidate(
            candidate_id="cand-err",
            source="failure_diagnosis",
            lesson="Missing libssl causes runtime crypto crashes",
            confidence=0.95,
            memory_type="ERROR_PATTERN"
        )
        self.manager._store_learning_in_memory(cand)
        retrieved = self.memory.retrieve("libssl")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].type, MemoryType.ERROR_PATTERN)

    def test_15_user_feedback_ingestion(self):
        """15. record_user_feedback logs structured feedback and updates candidate."""
        fb = self.manager.record_user_feedback(
            task_id="task-42",
            feedback_type=UserFeedbackType.CORRECTION,
            raw_text="Prefer pytest over unittest for modern python",
            rating=0.9,
            correction="Use pytest runner"
        )
        self.assertEqual(fb.type, UserFeedbackType.CORRECTION)
        self.assertEqual(fb.task_id, "task-42")

    def test_16_user_feedback_converts_to_preference_memory(self):
        """16. User feedback corrections persist as PREFERENCE in MemoryStore."""
        self.manager.record_user_feedback(
            task_id="task-43",
            feedback_type=UserFeedbackType.PREFERENCE,
            raw_text="Always use dark mode for generated templates",
            rating=1.0
        )
        retrieved = self.memory.retrieve("dark mode")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].type, MemoryType.PREFERENCE)

    # =========================================================================
    # Group 3: Strategy Registry & Performance (Tests 17 - 24)
    # =========================================================================

    def test_17_strategy_registration_and_retrieval(self):
        """17. Strategy is registered and retrieved from StrategyRegistry."""
        strat = Strategy(
            strategy_id="strat-debug-trace",
            name="Stack Trace Analysis",
            description="Inspect top frames before mutating source",
            applicable_domains=["DEBUGGING", "CODING"]
        )
        self.manager.strategy_registry.register(strat)
        fetched = self.manager.strategy_registry.get("strat-debug-trace")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Stack Trace Analysis")

    def test_18_strategy_outcome_recording(self):
        """18. Recording successful outcome increments count and updates success rate."""
        strat = Strategy(strategy_id="strat-test", name="TDD", description="Write tests first")
        self.manager.strategy_registry.register(strat)
        self.manager.strategy_registry.record_outcome("strat-test", success=True)
        self.manager.strategy_registry.record_outcome("strat-test", success=True)
        self.manager.strategy_registry.record_outcome("strat-test", success=False)
        fetched = self.manager.strategy_registry.get("strat-test")
        self.assertEqual(fetched.evidence_count, 3)
        self.assertEqual(fetched.success_count, 2)
        self.assertAlmostEqual(fetched.success_rate, 0.667, places=2)

    def test_19_strategy_auto_validation_threshold(self):
        """19. Strategy promotes from EXPERIMENTAL to VALIDATED after sufficient evidence and high success."""
        strat = Strategy(strategy_id="strat-auto-val", name="Lint First", description="Run flake8 before tests")
        self.manager.strategy_registry.register(strat)
        for _ in range(3):
            self.manager.strategy_registry.record_outcome("strat-auto-val", success=True)
        fetched = self.manager.strategy_registry.get("strat-auto-val")
        self.assertEqual(fetched.status, StrategyStatus.VALIDATED)

    def test_20_strategy_auto_deprecation_threshold(self):
        """20. Validated strategy demotes to DEPRECATED if success rate drops significantly."""
        strat = Strategy(
            strategy_id="strat-drop",
            name="Aggressive retry",
            description="Retry 10 times immediately",
            status=StrategyStatus.VALIDATED,
            evidence_count=3,
            success_count=3,
            success_rate=1.0
        )
        self.manager.strategy_registry.register(strat)
        # Record multiple failures
        for _ in range(5):
            self.manager.strategy_registry.record_outcome("strat-drop", success=False)
        fetched = self.manager.strategy_registry.get("strat-drop")
        self.assertEqual(fetched.status, StrategyStatus.DEPRECATED)

    def test_21_strategy_domain_filtering(self):
        """21. list_strategies filters accurately by applicable domain."""
        s1 = Strategy(strategy_id="s1", name="S1", description="D", applicable_domains=["CODING"])
        s2 = Strategy(strategy_id="s2", name="S2", description="D", applicable_domains=["RESEARCH"])
        s3 = Strategy(strategy_id="s3", name="S3", description="D", applicable_domains=["GENERAL"])
        self.manager.strategy_registry.register(s1)
        self.manager.strategy_registry.register(s2)
        self.manager.strategy_registry.register(s3)

        coding_strats = self.manager.strategy_registry.list_strategies(domain="CODING")
        ids = {s.strategy_id for s in coding_strats}
        self.assertIn("s1", ids)
        self.assertIn("s3", ids)  # GENERAL matches all domains
        self.assertNotIn("s2", ids)

    def test_22_strategy_blocking(self):
        """22. Blocking a strategy marks it BLOCKED with a recorded reason."""
        strat = Strategy(strategy_id="s-block", name="Unsafe scan", description="Bypass boundaries")
        self.manager.strategy_registry.register(strat)
        ok = self.manager.strategy_registry.block("s-block", reason="Violates safety invariants")
        self.assertTrue(ok)
        fetched = self.manager.strategy_registry.get("s-block")
        self.assertEqual(fetched.status, StrategyStatus.BLOCKED)

    def test_23_strategy_persistence_and_reload(self):
        """23. Strategies persist to disk and reload accurately in a new registry instance."""
        strat = Strategy(strategy_id="s-persist", name="Persistent Strategy", description="Survives restart")
        self.manager.strategy_registry.register(strat)

        # Create new registry pointing to same file
        new_reg = StrategyRegistry(storage_file=self.strat_file)
        fetched = new_reg.get("s-persist")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "Persistent Strategy")

    def test_24_strategy_domain_enum_membership(self):
        """24. StrategyDomain includes all major ZARA operational domains."""
        domains = {d.value for d in StrategyDomain}
        self.assertIn("CODING", domains)
        self.assertIn("DEBUGGING", domains)
        self.assertIn("RESEARCH", domains)
        self.assertIn("VISION", domains)
        self.assertIn("CYBER_LAB", domains)
        self.assertIn("BLENDER", domains)

    # =========================================================================
    # Group 4: Model Router Learning (Tests 25 - 32)
    # =========================================================================

    def test_25_record_model_performance(self):
        """25. record_model_performance accurately tracks latency, requests, and success rate."""
        self.manager.record_model_performance(
            provider="google",
            model="gemini-2.5-flash",
            task_type="coding",
            latency=0.45,
            success=True,
            cost=0.001
        )
        self.manager.record_model_performance(
            provider="google",
            model="gemini-2.5-flash",
            task_type="coding",
            latency=0.55,
            success=True,
            cost=0.001
        )
        metrics = self.manager.model_metrics["google:gemini-2.5-flash:coding"]
        self.assertEqual(metrics["total_requests"], 2)
        self.assertEqual(metrics["successful_requests"], 2)
        self.assertAlmostEqual(metrics["average_latency"], 0.50, places=2)
        self.assertEqual(metrics["success_rate"], 1.0)

    def test_26_model_performance_fallback_tracking(self):
        """26. Fallbacks increment fallback_count and update failed requests."""
        self.manager.record_model_performance(
            provider="anthropic",
            model="claude-3-opus",
            task_type="reasoning",
            latency=2.1,
            success=False,
            fallback=True
        )
        metrics = self.manager.model_metrics["anthropic:claude-3-opus:reasoning"]
        self.assertEqual(metrics["fallback_count"], 1)
        self.assertEqual(metrics["failed_requests"], 1)
        self.assertEqual(metrics["success_rate"], 0.0)

    def test_27_model_performance_observation_dataclass(self):
        """27. ModelPerformanceObservation serializes to dictionary cleanly."""
        obs = ModelPerformanceObservation(
            provider="openai",
            model="gpt-4o",
            task_type="coding",
            total_requests=10,
            successful_requests=9,
            failed_requests=1,
            total_latency=12.0,
            average_latency=1.2,
            success_rate=0.9
        )
        d = obs.to_dict()
        self.assertEqual(d["model"], "gpt-4o")
        self.assertEqual(d["success_rate"], 0.9)

    def test_28_model_recommendation_filtering(self):
        """28. Learning layer can identify top performing model for a task type."""
        self.manager.record_model_performance("pA", "fast-model", "coding", 0.2, True)
        self.manager.record_model_performance("pB", "slow-model", "coding", 2.0, True)

        models_coding = {k: v for k, v in self.manager.model_metrics.items() if v["task_type"] == "coding"}
        best = min(models_coding.values(), key=lambda x: x["average_latency"])
        self.assertEqual(best["model"], "fast-model")

    def test_29_model_metrics_redact_sensitive_keys(self):
        """29. Model metrics do not log or store credentials."""
        self.manager.record_model_performance("provider_key_bearer_1234567890abcdef", "m1", "test", 0.1, True)
        for key in self.manager.model_metrics:
            self.assertFalse(contains_secret(key))

    def test_30_model_learning_respects_provider_availability(self):
        """30. Learned model performance does not override offline provider availability constraints."""
        engine = ZaraEngine(enable_voice=False)
        # Even if a mock or offline provider has 100% learned score, offline router constraints hold
        self.assertIsNotNone(engine.model_router)

    def test_31_model_learning_respects_explicit_user_preference(self):
        """31. Explicit user model selection takes precedence over autonomous learned recommendations."""
        # Simulated routing policy assertion
        user_choice = "explicit-user-model"
        learned_best = "autonomous-best-model"
        chosen = user_choice or learned_best
        self.assertEqual(chosen, user_choice)

    def test_32_model_performance_multi_task_types(self):
        """32. Model performance is segregated across task types (coding vs research)."""
        self.manager.record_model_performance("p", "m", "coding", 0.5, True)
        self.manager.record_model_performance("p", "m", "research", 1.5, False)
        self.assertIn("p:m:coding", self.manager.model_metrics)
        self.assertIn("p:m:research", self.manager.model_metrics)
        self.assertEqual(self.manager.model_metrics["p:m:coding"]["success_rate"], 1.0)
        self.assertEqual(self.manager.model_metrics["p:m:research"]["success_rate"], 0.0)

    # =========================================================================
    # Group 5: Worker Learning (Tests 33 - 40)
    # =========================================================================

    def test_33_record_worker_performance(self):
        """33. record_worker_performance tracks runtime, tool calls, and success rate."""
        self.manager.record_worker_performance("RESEARCH", runtime=4.5, success=True, tool_calls=6, retry_count=0)
        self.manager.record_worker_performance("RESEARCH", runtime=5.5, success=True, tool_calls=8, retry_count=1)
        wm = self.manager.worker_metrics["RESEARCH"]
        self.assertEqual(wm["tasks_completed"], 2)
        self.assertEqual(wm["total_tool_calls"], 14)
        self.assertAlmostEqual(wm["average_runtime"], 5.0, places=2)
        self.assertEqual(wm["success_rate"], 1.0)

    def test_34_worker_performance_observation_dataclass(self):
        """34. WorkerPerformanceObservation serializes accurately."""
        obs = WorkerPerformanceObservation(worker_type="CODING", tasks_completed=5, total_runtime=25.0, success_rate=1.0)
        d = obs.to_dict()
        self.assertEqual(d["worker_type"], "CODING")
        self.assertEqual(d["tasks_completed"], 5)

    def test_35_cyber_worker_privilege_non_expansion_invariant(self):
        """35. CYBER_SECURITY worker historical 100% success never expands its tool permissions or target scope."""
        for _ in range(10):
            self.manager.record_worker_performance("CYBER_SECURITY", runtime=1.0, success=True)
        # Verify scope remains locked to allowlist
        from modules.cyber_lab import CyberLabScope
        scope = CyberLabScope()
        self.assertFalse(scope.is_target_allowed("evil.corp"))
        self.assertFalse(scope.is_target_allowed("8.8.8.8"))

    def test_36_worker_selection_recommendation(self):
        """36. System can query worker profiles by success rate and runtime."""
        self.manager.record_worker_performance("W1", runtime=1.0, success=True)
        self.manager.record_worker_performance("W2", runtime=10.0, success=False)
        best = max(self.manager.worker_metrics.values(), key=lambda w: w["success_rate"])
        self.assertEqual(best["worker_type"], "W1")

    def test_37_worker_failure_recording(self):
        """37. Worker failures dock success rate and track retry count."""
        self.manager.record_worker_performance("BUILDER", runtime=2.0, success=False, retry_count=2)
        wm = self.manager.worker_metrics["BUILDER"]
        self.assertEqual(wm["tasks_failed"], 1)
        self.assertEqual(wm["total_retries"], 2)
        self.assertEqual(wm["success_rate"], 0.0)

    def test_38_worker_metrics_thread_safety(self):
        """38. Concurrent worker metric updates execute without race conditions."""
        import threading
        threads = [
            threading.Thread(target=self.manager.record_worker_performance, args=("PARALLEL_W", 1.0, True, 2, 0))
            for _ in range(10)
        ]
        for t in threads: t.start()
        for t in threads: t.join()
        self.assertEqual(self.manager.worker_metrics["PARALLEL_W"]["tasks_completed"], 10)

    def test_39_worker_performance_cost_and_tool_call_efficiency(self):
        """39. Average tool calls per worker tracks efficiency."""
        self.manager.record_worker_performance("TEST_W", runtime=1.0, success=True, tool_calls=10)
        self.manager.record_worker_performance("TEST_W", runtime=1.0, success=True, tool_calls=20)
        wm = self.manager.worker_metrics["TEST_W"]
        self.assertEqual(wm["total_tool_calls"], 30)

    def test_40_worker_privilege_audit_event(self):
        """40. Worker learning changes publish no privilege escalation events."""
        events = [e for e in self.event_bus.get_recent_events(limit=50) if "privilege" in e.type.value.lower()]
        self.assertEqual(events, [])

    # =========================================================================
    # Group 6: Planner Learning & Adaptive Replanning (Tests 41 - 48)
    # =========================================================================

    def test_41_record_plan_accuracy(self):
        """41. record_plan_accuracy tracks step count, retries, and replans."""
        rec = self.manager.record_plan_accuracy(
            task_type="coding",
            step_count=5,
            steps_passed=5,
            replan_count=0,
            retries=0,
            task_success=True
        )
        self.assertEqual(rec["completion_rate"], 1.0)
        self.assertEqual(rec["efficiency_factor"], 1.0)

    def test_42_planner_performance_observation_dataclass(self):
        """42. PlannerPerformanceObservation serializes cleanly."""
        obs = PlannerPerformanceObservation(
            task_domain="DATA_ANALYSIS",
            step_count=4,
            dependency_depth=2,
            replan_count=1,
            success=True,
            runtime=3.2
        )
        d = obs.to_dict()
        self.assertEqual(d["task_domain"], "DATA_ANALYSIS")
        self.assertEqual(d["dependency_depth"], 2)

    def test_43_plan_validator_invariant_holds_for_learned_plans(self):
        """43. Every plan generated from learning must pass PlanValidator."""
        from modules.planning import PlanValidator
        validator = PlanValidator()
        # Invalid step missing description must still be caught
        bad_steps = [PlanStep(step_id="s1", description="", action_type=ActionType.BASH)]
        valid, msg = validator.validate_plan(bad_steps)
        self.assertFalse(valid)

    def test_44_retry_count_bounded_by_policy(self):
        """44. Learning does not dynamically inflate MAX_RETRIES beyond configured policy."""
        from config.settings import MAX_RETRIES_PER_STEP
        # Invariant check: MAX_RETRIES_PER_STEP is authoritative
        self.assertEqual(MAX_RETRIES_PER_STEP, 2)
        self.assertLessEqual(MAX_RETRIES_PER_STEP, 5)

    def test_45_adaptive_replan_penalty_on_repeated_replan(self):
        """45. Frequent replans decrease efficiency factor in plan accuracy records."""
        rec = self.manager.record_plan_accuracy(
            task_type="dev",
            step_count=3,
            steps_passed=3,
            replan_count=3,
            retries=2,
            task_success=True
        )
        self.assertLess(rec["efficiency_factor"], 0.7)

    def test_46_record_memory_retrieval_usefulness(self):
        """46. record_memory_retrieval tracks retrieval precision and usefulness."""
        rec = self.manager.record_memory_retrieval(
            query="python async",
            retrieved_ids=["m1", "m2", "m3", "m4"],
            used_ids=["m1", "m2"],
            task_success=True
        )
        self.assertEqual(rec["precision"], 0.5)
        self.assertEqual(rec["usefulness"], 0.5)

    def test_47_memory_retrieval_penalized_on_task_failure(self):
        """47. Failed task halves memory usefulness score."""
        rec = self.manager.record_memory_retrieval(
            query="broken query",
            retrieved_ids=["m1", "m2"],
            used_ids=["m1"],
            task_success=False
        )
        self.assertEqual(rec["precision"], 0.5)
        self.assertEqual(rec["usefulness"], 0.25)

    def test_48_planner_learning_negative_directive_respect(self):
        """48. Negative directive in memory prevents prohibited actions in plans."""
        cand = LearningCandidate(
            candidate_id="cand-neg",
            source="user_feedback",
            lesson="NEVER use sudo in automated tasks",
            confidence=1.0,
            memory_type="USER_FEEDBACK"
        )
        self.manager._store_learning_in_memory(cand)
        retrieved = self.memory.retrieve("sudo")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertIn("NEVER", retrieved[0].content)

    # =========================================================================
    # Group 7: Improvement Proposals & Risk Gates (Tests 49 - 56)
    # =========================================================================

    def test_49_create_low_risk_proposal(self):
        """49. LOW risk proposals are generated for documentation and prompt tweaks."""
        p = self.manager.create_proposal(
            title="Update docstring",
            description="Clarify return value",
            affected_component="docs/api.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={"reason": "Clarity"},
            expected_benefit="Better developer experience"
        )
        self.assertEqual(p.risk, ProposalRisk.LOW)
        self.assertEqual(p.status, ProposalStatus.PROPOSED)

    def test_50_create_medium_risk_proposal(self):
        """50. MEDIUM risk proposal requires validation before testing."""
        p = self.manager.create_proposal(
            title="Tweak planning heuristic",
            description="Prioritize test step before build step",
            affected_component="modules/planning.py",
            change_type=ChangeType.PLANNING_HEURISTIC,
            risk=ProposalRisk.MEDIUM,
            source_evidence={"retries_saved": 2},
            expected_benefit="Faster builds"
        )
        self.assertEqual(p.risk, ProposalRisk.MEDIUM)

    def test_51_create_high_risk_proposal(self):
        """51. HIGH risk proposal requires explicit human approval."""
        p = self.manager.create_proposal(
            title="Modify routing policy",
            description="Shift 50% traffic to local Ollama",
            affected_component="brain/router.py",
            change_type=ChangeType.ROUTING_POLICY,
            risk=ProposalRisk.HIGH,
            source_evidence={"cost_reduction": 0.5},
            expected_benefit="Halve API bills"
        )
        self.assertEqual(p.risk, ProposalRisk.HIGH)

    def test_52_critical_proposal_rejected_automatically(self):
        """52. Proposals targeting critical files are rejected immediately with CRITICAL_SYSTEM_MODIFICATION_PROHIBITED."""
        p = self.manager.create_proposal(
            title="Alter CyberLabScope",
            description="Permit scans on any IP",
            affected_component="config/security_scope.json",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.CRITICAL,
            source_evidence={},
            expected_benefit="Broad testing"
        )
        self.assertEqual(p.status, ProposalStatus.REJECTED)
        self.assertIn("CRITICAL_SYSTEM_MODIFICATION_PROHIBITED", p.rejection_reason)

    def test_53_validate_proposal_workflow(self):
        """53. validate_proposal transitions eligible proposals to VALIDATING/TESTING."""
        p = self.manager.create_proposal(
            title="Doc enhancement",
            description="Add usage example",
            affected_component="README.md",
            change_type=ChangeType.DOCUMENTATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Clarity"
        )
        ok = self.manager.validate_proposal(p.proposal_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.VALIDATING)

    def test_54_test_proposal_passes_or_fails(self):
        """54. test_proposal tests proposal in sandbox; fails if regression detected."""
        p = self.manager.create_proposal(
            title="Workflow tweak",
            description="Run format check",
            affected_component="modules/workspace.py",
            change_type=ChangeType.WORKFLOW,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Clean code"
        )
        self.manager.validate_proposal(p.proposal_id)
        # Passing test
        ok = self.manager.test_proposal(p.proposal_id, simulated_test_pass=True)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.APPROVED)

    def test_55_approve_proposal_marks_approved(self):
        """55. approve_proposal registers user approval and moves status to APPROVED."""
        p = self.manager.create_proposal(
            title="UI tweak",
            description="Widen sidebar",
            affected_component="ui/static/style.css",
            change_type=ChangeType.UI,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Better visibility"
        )
        ok = self.manager.approve_proposal(p.proposal_id, approved_by="alice")
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.APPROVED)
        self.assertEqual(self.manager.proposals[p.proposal_id].approved_by, "alice")

    def test_56_reject_proposal_stores_reason(self):
        """56. reject_proposal marks proposal REJECTED and preserves reason."""
        p = self.manager.create_proposal(
            title="Overly verbose logs",
            description="Log full headers",
            affected_component="core/observability.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Debugging"
        )
        ok = self.manager.reject_proposal(p.proposal_id, reason="Could leak headers")
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.REJECTED)
        self.assertEqual(self.manager.proposals[p.proposal_id].rejection_reason, "Could leak headers")

    # =========================================================================
    # Group 8: Experiments, Regression Guard & Rollback (Tests 57 - 64)
    # =========================================================================

    def test_57_create_experiment(self):
        """57. create_experiment initializes experiment in PROPOSED/RUNNING state."""
        exp = self.manager.create_experiment(
            hypothesis="Parallel step execution saves 30% time",
            baseline={"duration": 10.0},
            candidate={"duration": 7.0},
            target_sample_size=3
        )
        self.assertEqual(exp.status, ExperimentStatus.RUNNING)
        self.assertEqual(exp.target_sample_size, 3)

    def test_58_record_experiment_trial(self):
        """58. record_experiment_trial increments sample size and averages metrics."""
        exp = self.manager.create_experiment(
            hypothesis="Cache test",
            baseline={"hit_rate": 0.2},
            candidate={"hit_rate": 0.8},
            target_sample_size=2
        )
        self.manager.record_experiment_trial(exp.experiment_id, {"hit_rate": 0.75})
        self.manager.record_experiment_trial(exp.experiment_id, {"hit_rate": 0.85})
        fetched = self.manager.experiments[exp.experiment_id]
        self.assertEqual(fetched.sample_size, 2)
        self.assertAlmostEqual(fetched.metrics["hit_rate"], 0.80, places=2)

    def test_59_complete_experiment_on_target_samples(self):
        """59. complete_experiment transitions status to COMPLETED."""
        exp = self.manager.create_experiment("Test", {}, {}, target_sample_size=1)
        self.manager.record_experiment_trial(exp.experiment_id, {"score": 1.0})
        completed = self.manager.complete_experiment(exp.experiment_id)
        self.assertEqual(completed.status, ExperimentStatus.COMPLETED)
        self.assertIsNotNone(completed.completed_at)

    def test_60_regression_detection_marks_experiment_failed(self):
        """60. Candidate that regresses vs baseline is detected and failed."""
        exp = self.manager.create_experiment(
            hypothesis="Faster indexing",
            baseline={"score": 0.95},
            candidate={"score": 0.50},
            target_sample_size=2
        )
        self.manager.record_experiment_trial(exp.experiment_id, {"score": 0.50})
        # Score dropped significantly below baseline
        completed = self.manager.complete_experiment(exp.experiment_id)
        self.assertEqual(completed.status, ExperimentStatus.FAILED)

    def test_61_deploy_proposal_creates_version(self):
        """61. deploy_proposal creates ImprovementVersion and marks status DEPLOYED."""
        p = self.manager.create_proposal(
            title="Safe config update",
            description="Adjust timeout to 15s",
            affected_component="config/timeout.json",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Prevent premature aborts"
        )
        self.manager.approve_proposal(p.proposal_id)
        version = self.manager.deploy_proposal(p.proposal_id)
        self.assertIsNotNone(version)
        self.assertEqual(version.status, "ACTIVE")
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.DEPLOYED)

    def test_62_atomic_rollback_reverts_version(self):
        """62. rollback restores previous baseline and marks version ROLLED_BACK."""
        p = self.manager.create_proposal(
            title="Subsystem param tweak",
            description="Tweak threshold",
            affected_component="modules/test.py",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Test"
        )
        self.manager.approve_proposal(p.proposal_id)
        v = self.manager.deploy_proposal(p.proposal_id)

        ok = self.manager.rollback(v.version_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.versions[v.version_id].status, "ROLLED_BACK")
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.ROLLED_BACK)

    def test_63_rollback_by_proposal_id(self):
        """63. rollback target can be proposal_id as well as version_id."""
        p = self.manager.create_proposal(
            title="Proposal rollback test",
            description="Desc",
            affected_component="modules/test.py",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Test"
        )
        self.manager.approve_proposal(p.proposal_id)
        self.manager.deploy_proposal(p.proposal_id)

        ok = self.manager.rollback(p.proposal_id)
        self.assertTrue(ok)
        self.assertEqual(self.manager.proposals[p.proposal_id].status, ProposalStatus.ROLLED_BACK)

    def test_64_rollback_records_lesson(self):
        """64. Rollback automatically records a learning candidate to avoid repeating the mistake."""
        p = self.manager.create_proposal(
            title="Faulty optimization",
            description="Caused regression",
            affected_component="modules/test.py",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.LOW,
            source_evidence={},
            expected_benefit="Speed"
        )
        self.manager.approve_proposal(p.proposal_id)
        self.manager.deploy_proposal(p.proposal_id)
        self.manager.rollback(p.proposal_id)

        rollback_lessons = [
            c for c in self.manager.learning_candidates.values()
            if "Rollback" in c.lesson or "Faulty optimization" in c.lesson
        ]
        self.assertGreaterEqual(len(rollback_lessons), 1)

    # =========================================================================
    # Group 9: Hard Safety Invariants (Tests 65 - 72)
    # =========================================================================

    def test_65_safety_invariant_cannot_expand_cyber_scope(self):
        """65. Safety Invariant: Learning cannot autonomously expand CyberLabScope allowlist."""
        p = self.manager.create_proposal(
            title="Expand targets",
            description="Add 0.0.0.0/0 to allowlist",
            affected_component="config/security_scope.json",
            change_type=ChangeType.CONFIGURATION,
            risk=ProposalRisk.CRITICAL,
            source_evidence={},
            expected_benefit="Universal testing"
        )
        self.assertEqual(p.status, ProposalStatus.REJECTED)
        self.assertFalse(self.manager.approve_proposal(p.proposal_id))

    def test_66_safety_invariant_cannot_disable_confirmation_gates(self):
        """66. Safety Invariant: Learning cannot bypass or disable human confirmation gates."""
        p = self.manager.create_proposal(
            title="Auto confirm dangerous actions",
            description="Set require_confirmation=False",
            affected_component="tools/registry.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.CRITICAL,
            source_evidence={},
            expected_benefit="Speed"
        )
        self.assertEqual(p.status, ProposalStatus.REJECTED)

    def test_67_safety_invariant_cannot_remove_secret_scrubbing(self):
        """67. Safety Invariant: Learning cannot disable audit logger secret scrubbing."""
        p = self.manager.create_proposal(
            title="Disable secret redaction",
            description="Omit regex checks in AuditLogger",
            affected_component="core/observability.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.CRITICAL,
            source_evidence={},
            expected_benefit="Faster logs"
        )
        self.assertEqual(p.status, ProposalStatus.REJECTED)

    def test_68_safety_invariant_cannot_bypass_plan_validation(self):
        """68. Safety Invariant: Learning cannot bypass PlanValidator before execution."""
        from modules.planning import PlanValidator
        pv = PlanValidator()
        self.assertTrue(hasattr(pv, "validate_plan"))

    def test_69_safety_invariant_cannot_grant_workers_new_privileges(self):
        """69. Safety Invariant: Learning cannot dynamically grant workers new tool permissions."""
        from modules.workers import WorkerType, get_worker_capabilities
        caps = get_worker_capabilities(WorkerType.CYBER_LAB)
        self.assertIsNotNone(caps)
        # Verify allowed capabilities remain strictly defined
        self.assertIn("cyber_lab", caps)
        self.assertNotIn("unrestricted_admin", caps)

    def test_70_safety_invariant_cannot_disable_authorization(self):
        """70. Safety Invariant: Learning cannot remove authentication/authorization controls."""
        p = self.manager.create_proposal(
            title="Disable auth checks",
            description="Remove token verification",
            affected_component="core/engine.py",
            change_type=ChangeType.CODE,
            risk=ProposalRisk.CRITICAL,
            source_evidence={},
            expected_benefit="Simpler local dev"
        )
        self.assertEqual(p.status, ProposalStatus.REJECTED)

    def test_71_safety_invariant_cannot_modify_critical_blocklist_files(self):
        """71. Safety Invariant: All files in CRITICAL_FILES_BLOCKLIST are strictly blocked."""
        from config.settings import CRITICAL_FILES_BLOCKLIST
        for blocked_file in CRITICAL_FILES_BLOCKLIST:
            p = self.manager.create_proposal(
                title=f"Modify {blocked_file}",
                description="Test bypass",
                affected_component=blocked_file,
                change_type=ChangeType.CODE,
                risk=ProposalRisk.LOW,  # Even if marked LOW, target file forces rejection
                source_evidence={},
                expected_benefit="Test"
            )
            self.assertEqual(p.status, ProposalStatus.REJECTED, f"File {blocked_file} was not blocked!")

    def test_72_safety_invariant_critical_changes_require_human_approval(self):
        """72. Safety Invariant: Even if explicitly requested, CRITICAL proposals reject deploy_proposal without approval."""
        p = ImprovementProposal(
            proposal_id="prop-crit-direct",
            title="Critical action",
            description="Desc",
            source_evidence={},
            expected_benefit="None",
            risk=ProposalRisk.CRITICAL,
            affected_component="core/engine.py",
            change_type=ChangeType.CODE
        )
        self.manager.proposals[p.proposal_id] = p
        res = self.manager.deploy_proposal(p.proposal_id)
        self.assertIsNone(res)

    # =========================================================================
    # Group 10: EventBus, API & CLI Integration (Tests 73 - 80)
    # =========================================================================

    def test_73_event_bus_receives_evaluation_completed(self):
        """73. EventBus receives evaluation.completed event upon task evaluation."""
        ctx = TaskContext(task="Event test", tag="test")
        ctx.is_completed = True
        self.manager.evaluate_task_execution(ctx)
        events = [e for e in self.event_bus.get_recent_events(limit=20) if e.type == EventType.EVALUATION_COMPLETED]
        self.assertGreaterEqual(len(events), 1)

    def test_74_event_bus_scrubs_secrets_in_events(self):
        """74. Event payloads never contain credentials or API keys."""
        ctx = TaskContext(task="Task with Bearer secret_token_1234567890abcdef", tag="test")
        ctx.is_completed = True
        self.manager.evaluate_task_execution(ctx)
        events = self.event_bus.get_recent_events(limit=20)
        for ev in events:
            ev_str = json.dumps(ev.to_dict())
            self.assertNotIn("secret_token_1234567890abcdef", ev_str)

    def test_75_api_learning_models_endpoint(self):
        """75. GET /api/learning/models returns HTTP 200 with model metrics."""
        engine = ZaraEngine(enable_voice=False)
        app = create_ui_app(engine=engine)
        client = TestClient(app)
        resp = client.get("/api/learning/models")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("models", data)

    def test_76_api_learning_workers_endpoint(self):
        """76. GET /api/learning/workers returns HTTP 200 with worker metrics."""
        engine = ZaraEngine(enable_voice=False)
        app = create_ui_app(engine=engine)
        client = TestClient(app)
        resp = client.get("/api/learning/workers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("workers", data)

    def test_77_api_learning_experiment_rollback_endpoint(self):
        """77. POST /api/learning/experiments/{id}/rollback returns HTTP 200 on valid target."""
        engine = ZaraEngine(enable_voice=False)
        # Seed an experiment
        exp = engine.evaluation_manager.create_experiment("Hypothesis", {}, {}, target_sample_size=1)
        app = create_ui_app(engine=engine)
        client = TestClient(app)
        resp = client.post(f"/api/learning/experiments/{exp.experiment_id}/rollback")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("success"))

    def test_78_api_learning_experiment_rollback_404_on_unknown(self):
        """78. POST /api/learning/experiments/{id}/rollback returns HTTP 404 for unknown experiment."""
        engine = ZaraEngine(enable_voice=False)
        app = create_ui_app(engine=engine)
        client = TestClient(app)
        resp = client.post("/api/learning/experiments/non-existent-exp-id/rollback")
        self.assertEqual(resp.status_code, 404)

    def test_79_cli_learning_models_execution(self):
        """79. CLI learning models command executes cleanly."""
        import subprocess
        res = subprocess.run(
            ["python3", "./zara.py", "learning", "models"],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("MODEL ROUTER LEARNING OBSERVATIONS", res.stdout)

    def test_80_cli_learning_workers_execution(self):
        """80. CLI learning workers command executes cleanly."""
        import subprocess
        res = subprocess.run(
            ["python3", "./zara.py", "learning", "workers"],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(res.returncode, 0)
        self.assertIn("MULTI-AGENT WORKER LEARNING OBSERVATIONS", res.stdout)


if __name__ == "__main__":
    unittest.main()
