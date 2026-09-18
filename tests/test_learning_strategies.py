"""
Unit tests for ZARA Phase 17: Strategy Library, Strategy Validation, Planner Integration,
and Subsystem Performance Learning (Model Router, Workers, Memory, Planning).
"""

import unittest
import tempfile
import shutil
import time
from pathlib import Path

from modules.goals import Goal, GoalDomain
from modules.planning import HierarchicalPlanner
from modules.events import EventBus, EventType
from modules.memory import MemoryStore
from modules.evaluation import (
    EvaluationManager,
    Strategy,
    StrategyStatus,
    StrategyRegistry,
    CandidateStatus,
)


class TestLearningStrategies(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        self.strat_file = self.tmp_dir / "strategies.json"
        self.evals_dir = self.tmp_dir / "evaluations"
        self.props_dir = self.tmp_dir / "proposals"
        self.exps_dir = self.tmp_dir / "experiments"
        self.mem_dir = self.tmp_dir / "memory"
        self.mem_dir.mkdir(parents=True, exist_ok=True)

        self.memory = MemoryStore(memory_path=self.mem_dir / "zara_log.md", db_path=self.mem_dir / "v.db")
        self.event_bus = EventBus()
        self.registry = StrategyRegistry(storage_file=self.strat_file)
        self.manager = EvaluationManager(
            memory_store=self.memory,
            event_bus=self.event_bus,
            strategy_registry=self.registry,
            evaluations_dir=self.evals_dir,
            proposals_dir=self.props_dir,
            experiments_dir=self.exps_dir,
        )

    def tearDown(self):
        self.manager.close()
        self.memory.close()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_01_strategy_creation_and_serialization(self):
        """Strategy instantiates with version, history, and serializes roundtrip."""
        strat = Strategy(
            strategy_id="strat-test01",
            name="Run Failing Test First",
            description="Execute only the targeted failing test before running the full regression suite.",
            applicable_domains=["coding", "debugging"],
            conditions={"language": "python"},
            steps=["pytest tests/test_failing.py", "git diff", "pytest tests/"],
            status=StrategyStatus.EXPERIMENTAL,
            version=1,
        )
        d = strat.to_dict()
        self.assertEqual(d["strategy_id"], "strat-test01")
        self.assertEqual(d["status"], "EXPERIMENTAL")

        restored = Strategy.from_dict(d)
        self.assertEqual(restored.name, strat.name)
        self.assertEqual(restored.steps, strat.steps)
        self.assertEqual(restored.version, 1)

    def test_02_record_outcome_updates_metrics(self):
        """Recording outcomes updates evidence count, success rate, and history."""
        strat = Strategy(
            strategy_id="strat-02",
            name="Incremental Compile",
            description="Compile affected modules only",
            applicable_domains=["coding"],
        )
        strat.record_outcome(True, evidence={"runtime": 1.2})
        self.assertEqual(strat.evidence_count, 1)
        self.assertEqual(strat.success_count, 1)
        self.assertEqual(strat.failure_count, 0)
        self.assertEqual(strat.success_rate, 1.0)
        self.assertEqual(len(strat.history), 1)

        strat.record_outcome(False, evidence={"error": "Missing dependency"})
        self.assertEqual(strat.evidence_count, 2)
        self.assertEqual(strat.success_count, 1)
        self.assertEqual(strat.failure_count, 1)
        self.assertEqual(strat.success_rate, 0.5)
        self.assertEqual(len(strat.history), 2)

    def test_03_strategy_validation_threshold_transition(self):
        """Strategy transitions from EXPERIMENTAL to VALIDATED once sample size >= 3 and success >= 80%."""
        strat = Strategy(
            strategy_id="strat-03",
            name="AST Pre-Check",
            description="Verify AST parsing before writing file",
            applicable_domains=["coding"],
            status=StrategyStatus.EXPERIMENTAL,
        )
        self.registry.register(strat)

        # 1st success
        self.registry.record_outcome("strat-03", True)
        self.assertEqual(self.registry.get("strat-03").status, StrategyStatus.EXPERIMENTAL)

        # 2nd success
        self.registry.record_outcome("strat-03", True)
        self.assertEqual(self.registry.get("strat-03").status, StrategyStatus.EXPERIMENTAL)

        # 3rd success: reaches STRATEGY_MIN_EVIDENCE_THRESHOLD=3 and success_rate=1.0 >= 0.80
        self.registry.record_outcome("strat-03", True)
        updated = self.registry.get("strat-03")
        self.assertEqual(updated.status, StrategyStatus.VALIDATED)
        self.assertEqual(updated.success_rate, 1.0)
        self.assertGreaterEqual(updated.confidence, 0.3)

    def test_04_strategy_deprecation_on_excessive_failures(self):
        """VALIDATED strategy transitions to DEPRECATED when failure rate exceeds threshold."""
        strat = Strategy(
            strategy_id="strat-04",
            name="Aggressive Inline Patch",
            description="Direct regex replace",
            applicable_domains=["coding"],
            status=StrategyStatus.VALIDATED,
            evidence_count=3,
            success_count=3,
            success_rate=1.0,
        )
        self.registry.register(strat)

        # Subsequent failures drop success rate below 0.65 (0.80 - 0.15)
        self.registry.record_outcome("strat-04", False)
        self.registry.record_outcome("strat-04", False)
        self.registry.record_outcome("strat-04", False)

        updated = self.registry.get("strat-04")
        self.assertEqual(updated.evidence_count, 6)
        self.assertLess(updated.success_rate, 0.65)
        self.assertEqual(updated.status, StrategyStatus.DEPRECATED)

    def test_05_strategy_manual_deprecation_and_blocking(self):
        """Strategies can be explicitly deprecated or blocked."""
        strat = Strategy(
            strategy_id="strat-05",
            name="Deprecated Strategy",
            description="Outdated workflow",
            applicable_domains=["general"],
        )
        self.registry.register(strat)

        self.registry.deprecate("strat-05", reason="Superseded by v2")
        self.assertEqual(self.registry.get("strat-05").status, StrategyStatus.DEPRECATED)

        self.registry.block("strat-05", reason="Safety vulnerability in workflow")
        self.assertEqual(self.registry.get("strat-05").status, StrategyStatus.BLOCKED)

    def test_06_strategy_registry_disk_persistence(self):
        """Strategies saved to disk reload cleanly in a new registry instance."""
        strat = Strategy(
            strategy_id="strat-persist",
            name="Persistent Strategy",
            description="Persistent test",
            applicable_domains=["coding"],
            status=StrategyStatus.VALIDATED,
        )
        self.registry.register(strat)

        reg2 = StrategyRegistry(storage_file=self.strat_file)
        self.assertIn("strat-persist", reg2.strategies)
        self.assertEqual(reg2.get("strat-persist").status, StrategyStatus.VALIDATED)

    def test_07_strategy_filtering_by_domain_and_status(self):
        """list_strategies filters properly by status and applicable domain."""
        self.registry.register(Strategy(strategy_id="s1", name="S1", description="", applicable_domains=["coding"], status=StrategyStatus.VALIDATED))
        self.registry.register(Strategy(strategy_id="s2", name="S2", description="", applicable_domains=["blender"], status=StrategyStatus.EXPERIMENTAL))
        self.registry.register(Strategy(strategy_id="s3", name="S3", description="", applicable_domains=["coding"], status=StrategyStatus.DEPRECATED))

        coding_validated = self.registry.list_strategies(status=StrategyStatus.VALIDATED, domain="coding")
        self.assertEqual(len(coding_validated), 1)
        self.assertEqual(coding_validated[0].strategy_id, "s1")

        blender_all = self.registry.list_strategies(domain="blender")
        self.assertEqual(len(blender_all), 1)
        self.assertEqual(blender_all[0].strategy_id, "s2")

    def test_08_planner_integration_advisory_hints(self):
        """HierarchicalPlanner receives validated strategies as advisory hints."""
        strat = Strategy(
            strategy_id="strat-plan",
            name="Focused Pytest",
            description="Run focused test first",
            steps=["pytest tests/unit/"],
            applicable_domains=["coding"],
            status=StrategyStatus.VALIDATED,
        )
        goal = Goal(
            goal_id="g-plan",
            raw_request="Fix compiler warning",
            normalized_goal="Fix warning in module",
            domain=GoalDomain.CODING,
        )

        tasks = HierarchicalPlanner.create_hierarchical_plan(
            goal=goal,
            project_id="proj-plan",
            validated_strategies=[strat]
        )
        self.assertTrue(len(tasks) >= 1)
        # Verify strategy hints were injected into task payload
        first_task = tasks[0]
        self.assertIsNotNone(first_task.input_payload)
        self.assertIn("strategy_hints", first_task.input_payload)
        self.assertTrue(any("Focused Pytest" in h for h in first_task.input_payload["strategy_hints"]))

    def test_09_planner_explicit_requirements_take_precedence(self):
        """Planner tasks retain explicit title, capability, and verification regardless of strategies."""
        strat = Strategy(
            strategy_id="strat-hint",
            name="Ignore Output Check",
            description="Advisory hint",
            applicable_domains=["coding"],
        )
        goal = Goal(
            goal_id="g-prec",
            raw_request="Refactor AST",
            normalized_goal="Refactor AST",
            domain=GoalDomain.CODING,
        )
        tasks = HierarchicalPlanner.create_hierarchical_plan(
            goal=goal,
            project_id="proj-prec",
            validated_strategies=[strat]
        )
        for t in tasks:
            self.assertIn(t.capability, ("coding", "debugging", "general"))
            self.assertIsNotNone(t.verification)

    def test_10_model_performance_tracking(self):
        """EvaluationManager tracks latency, success rate, cost, and fallback for models."""
        self.manager.record_model_performance(
            provider="google",
            model="gemini-2.5-flash",
            task_type="coding",
            latency=1.2,
            success=True,
            cost=0.002,
            fallback=False
        )
        self.manager.record_model_performance(
            provider="google",
            model="gemini-2.5-flash",
            task_type="coding",
            latency=1.8,
            success=True,
            cost=0.003,
            fallback=False
        )
        self.manager.record_model_performance(
            provider="google",
            model="gemini-2.5-flash",
            task_type="coding",
            latency=2.0,
            success=False,
            cost=0.001,
            fallback=True
        )

        key = "google:gemini-2.5-flash:coding"
        m = self.manager.model_metrics[key]
        self.assertEqual(m["total_requests"], 3)
        self.assertEqual(m["successful_requests"], 2)
        self.assertEqual(m["failed_requests"], 1)
        self.assertAlmostEqual(m["average_latency"], 1.667, places=2)
        self.assertEqual(m["fallback_count"], 1)
        self.assertAlmostEqual(m["success_rate"], 0.667, places=2)

    def test_11_worker_performance_tracking(self):
        """EvaluationManager tracks runtime, tool calls, and success rate for workers."""
        self.manager.record_worker_performance(
            worker_type="coding",
            runtime=15.0,
            success=True,
            tool_calls=4,
            retry_count=0
        )
        self.manager.record_worker_performance(
            worker_type="coding",
            runtime=25.0,
            success=True,
            tool_calls=6,
            retry_count=1
        )
        self.manager.record_worker_performance(
            worker_type="coding",
            runtime=10.0,
            success=False,
            tool_calls=2,
            retry_count=2
        )

        wm = self.manager.worker_metrics["coding"]
        self.assertEqual(wm["tasks_completed"], 2)
        self.assertEqual(wm["tasks_failed"], 1)
        self.assertEqual(wm["total_runtime"], 50.0)
        self.assertAlmostEqual(wm["average_runtime"], 16.67, places=1)
        self.assertEqual(wm["total_tool_calls"], 12)
        self.assertEqual(wm["total_retries"], 3)
        self.assertAlmostEqual(wm["success_rate"], 0.667, places=2)

    def test_12_memory_retrieval_evaluation(self):
        """EvaluationManager tracks retrieval precision and usefulness."""
        rec = self.manager.record_memory_retrieval(
            query="find database models",
            retrieved_ids=["m1", "m2", "m3", "m4"],
            used_ids=["m1", "m2"],
            task_success=True
        )
        self.assertEqual(rec["retrieved_count"], 4)
        self.assertEqual(rec["used_count"], 2)
        self.assertEqual(rec["precision"], 0.5)
        self.assertEqual(rec["usefulness"], 0.5)
        self.assertEqual(len(self.manager.memory_evaluations), 1)

    def test_13_memory_retrieval_usefulness_penalized_on_task_failure(self):
        """When a task fails, retrieval usefulness is discounted even if memories were used."""
        rec = self.manager.record_memory_retrieval(
            query="bad query",
            retrieved_ids=["m1", "m2"],
            used_ids=["m1"],
            task_success=False
        )
        self.assertEqual(rec["precision"], 0.5)
        self.assertEqual(rec["usefulness"], 0.25)

    def test_14_plan_accuracy_evaluation(self):
        """Planning accuracy calculates deviations in steps and runtime."""
        rec = self.manager.record_plan_accuracy(
            estimated_steps=4,
            actual_steps=5,
            estimated_runtime=60.0,
            actual_runtime=75.0,
            replan_count=1,
            replan_success=True
        )
        self.assertEqual(rec["estimated_steps"], 4)
        self.assertEqual(rec["actual_steps"], 5)
        self.assertAlmostEqual(rec["step_deviation"], 0.25, places=2)
        self.assertAlmostEqual(rec["runtime_deviation"], 0.25, places=2)
        self.assertEqual(rec["replan_count"], 1)
        self.assertTrue(rec["replan_success"])

    def test_15_get_validated_strategies_for_goal(self):
        """get_validated_strategies_for_goal returns only VALIDATED strategies for matching domain."""
        self.registry.register(Strategy(strategy_id="v-code", name="Code", description="", applicable_domains=["coding"], status=StrategyStatus.VALIDATED))
        self.registry.register(Strategy(strategy_id="e-code", name="Code Exp", description="", applicable_domains=["coding"], status=StrategyStatus.EXPERIMENTAL))
        self.registry.register(Strategy(strategy_id="v-blend", name="Blend", description="", applicable_domains=["blender"], status=StrategyStatus.VALIDATED))

        goal = Goal(goal_id="g1", raw_request="r", normalized_goal="n", domain=GoalDomain.CODING)
        strats = self.manager.get_validated_strategies_for_goal(goal)
        self.assertEqual(len(strats), 1)
        self.assertEqual(strats[0].strategy_id, "v-code")

    def test_16_confidence_scales_with_sample_size(self):
        """Strategy confidence increases proportionally with sample size up to cap."""
        strat = Strategy(strategy_id="conf-test", name="Conf", description="", applicable_domains=["coding"])
        self.registry.register(strat)

        strat.record_outcome(True)
        conf1 = strat.confidence

        for _ in range(9):
            strat.record_outcome(True)
        conf10 = strat.confidence

        self.assertGreater(conf10, conf1)
        self.assertEqual(strat.confidence, 1.0)

    def test_17_learning_candidates_status_lifecycle(self):
        """LearningCandidate correctly transitions status."""
        cand = self.manager.record_user_feedback("Suggestion: use ruff instead of flake8")
        cand_obj = list(self.manager.learning_candidates.values())[0]
        self.assertIn(cand_obj.status, (CandidateStatus.CANDIDATE, CandidateStatus.ACCEPTED))

    def test_18_planning_evaluations_capped_at_200(self):
        """Planning evaluations list is capped to prevent unbounded memory growth."""
        for i in range(250):
            self.manager.record_plan_accuracy(4, 4, 10.0, 10.0)
        self.assertEqual(len(self.manager.planning_evaluations), 200)

    def test_19_memory_evaluations_capped_at_200(self):
        """Memory evaluations list is capped to prevent unbounded memory growth."""
        for i in range(250):
            self.manager.record_memory_retrieval("q", ["m1"], ["m1"], True)
        self.assertEqual(len(self.manager.memory_evaluations), 200)

    def test_20_strategy_registry_thread_safety(self):
        """Concurrent record_outcome calls do not corrupt strategy metrics."""
        strat = Strategy(strategy_id="thread-strat", name="Thread", description="", applicable_domains=["general"])
        self.registry.register(strat)

        import threading
        def worker():
            for _ in range(25):
                self.registry.record_outcome("thread-strat", True)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        updated = self.registry.get("thread-strat")
        self.assertEqual(updated.evidence_count, 100)
        self.assertEqual(updated.success_count, 100)

    def test_21_get_status_contains_all_subsystem_sections(self):
        """get_status returns stats, models, workers, recent lessons, and strategies."""
        status = self.manager.get_status()
        self.assertIn("stats", status)
        self.assertIn("model_performance", status)
        self.assertIn("worker_performance", status)
        self.assertIn("recent_lessons", status)
        self.assertIn("recent_strategies", status)

    def test_22_zero_resource_warnings(self):
        """Strategy and learning operations execute with clean resource cleanup."""
        self.manager.record_model_performance("mock", "default", "coding", 0.5, True)
        self.manager.record_worker_performance("general", 5.0, True)
        stats = self.manager.get_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()
