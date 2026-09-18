"""Tests for ZARA Phase 11 - Hierarchical Planning, Quality Checks, Cost Estimation & Decisions."""

import unittest
from pathlib import Path
import tempfile
import shutil

from modules.goals import AmbiguityLevel, Goal, GoalDomain, GoalParser
from modules.planning import (
    DecisionRecord,
    DecisionRegistry,
    HierarchicalPlanner,
    PlanCost,
    PlanPreview,
    PlanValidationResult,
    PlanValidator,
)
from modules.workspace import PersistentTask, ProjectBudget


class TestPlanning(unittest.TestCase):
    """Test suite for hierarchical planning, plan validation, cost modeling, decision records, and preview."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.decisions_file = self.temp_dir / "decisions.jsonl"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_hierarchical_decomposition_coding(self):
        """HierarchicalPlanner decomposes coding goals into ordered, parent-child linked tasks."""
        goal = GoalParser.parse_goal("Implement a binary search tree in bst.py with unit tests")
        tasks = HierarchicalPlanner.create_hierarchical_plan(goal, "proj-code-01")

        self.assertEqual(len(tasks), 3)
        self.assertEqual(tasks[0].capability, "coding")
        self.assertEqual(tasks[1].parent_id, tasks[0].id)
        self.assertIn(tasks[0].id, tasks[1].dependencies)
        self.assertEqual(tasks[2].capability, "debugging")
        self.assertIn(tasks[1].id, tasks[2].dependencies)

    def test_02_hierarchical_decomposition_blender(self):
        """HierarchicalPlanner builds inspection, script, headless render, and vision tasks for Blender."""
        goal = GoalParser.parse_goal("Create a realistic forest environment in Blender")
        tasks = HierarchicalPlanner.create_hierarchical_plan(goal, "proj-blender-01")

        self.assertEqual(len(tasks), 4)
        capabilities = [t.capability for t in tasks]
        self.assertEqual(capabilities, ["blender", "blender", "blender", "vision"])
        self.assertIn(tasks[2].id, tasks[3].dependencies)

    def test_03_dependency_validation_valid(self):
        """Valid linear or DAG dependencies pass cycle detection and validation."""
        goal = GoalParser.parse_goal("Implement utility module")
        t1 = PersistentTask(id="t1", project_id="p", title="Task 1", capability="coding", verification={"method": "check"})
        t2 = PersistentTask(id="t2", project_id="p", title="Task 2", capability="coding", dependencies=["t1"], verification={"method": "check"})
        result = PlanValidator.validate(goal, [t1, t2])
        self.assertTrue(result.valid)
        self.assertEqual(len(result.errors), 0)

    def test_04_dependency_validation_cycle_detection(self):
        """Cycle detection catches circular dependencies and reports validation error."""
        goal = GoalParser.parse_goal("Implement circular module")
        t1 = PersistentTask(id="t1", project_id="p", title="Task 1", capability="coding", dependencies=["t2"])
        t2 = PersistentTask(id="t2", project_id="p", title="Task 2", capability="coding", dependencies=["t1"])
        result = PlanValidator.validate(goal, [t1, t2])
        self.assertFalse(result.valid)
        self.assertTrue(any("Cycle detected" in err for err in result.errors))

    def test_05_dependency_validation_missing_dependency(self):
        """Referencing non-existent dependency produces a validation error."""
        goal = GoalParser.parse_goal("Implement module")
        t1 = PersistentTask(id="t1", project_id="p", title="Task 1", capability="coding", dependencies=["t_ghost"])
        result = PlanValidator.validate(goal, [t1])
        self.assertFalse(result.valid)
        self.assertTrue(any("non-existent task 't_ghost'" in err for err in result.errors))

    def test_06_capability_selection_and_rationale(self):
        """Capability selection returns domain-appropriate capabilities with explicit rationale."""
        blender_caps = HierarchicalPlanner.select_capabilities(GoalDomain.BLENDER)
        self.assertEqual(blender_caps[0][0], "blender")
        self.assertIn("3D", blender_caps[0][1])

        cyber_caps = HierarchicalPlanner.select_capabilities(GoalDomain.CYBERSECURITY)
        self.assertEqual(cyber_caps[0][0], "cyber_lab")

    def test_07_plan_validator_missing_capability(self):
        """Tasks requiring an unavailable capability fail validation."""
        goal = GoalParser.parse_goal("Implement module")
        t1 = PersistentTask(id="t1", project_id="p", title="Quantum computation", capability="quantum_core")
        result = PlanValidator.validate(goal, [t1])
        self.assertFalse(result.valid)
        self.assertTrue(any("requires unavailable capability: 'quantum_core'" in err for err in result.errors))

    def test_08_plan_validator_budget_overflow(self):
        """Plans exceeding configured project budget fail validation."""
        goal = GoalParser.parse_goal("Implement massive module")
        budget = ProjectBudget(max_steps=2)
        tasks = [
            PersistentTask(id=f"t{i}", project_id="p", title=f"Task {i}", capability="coding", verification={"method": "check"})
            for i in range(5)
        ]
        result = PlanValidator.validate(goal, tasks, budget=budget)
        self.assertFalse(result.valid)
        self.assertTrue(any("exceeding maximum step budget" in err for err in result.errors))

    def test_09_resource_estimation_and_plan_cost(self):
        """HierarchicalPlanner accurately computes estimated steps, tool calls, runtime, and confidence."""
        goal = GoalParser.parse_goal("Research quantum computing breakthroughs")
        tasks = HierarchicalPlanner.create_hierarchical_plan(goal, "proj-res")
        cost = HierarchicalPlanner.estimate_cost(goal, tasks)

        self.assertEqual(cost.estimated_steps, len(tasks))
        self.assertTrue(cost.estimated_tool_calls > 0)
        self.assertTrue(cost.estimated_runtime > 0)
        self.assertTrue(0.0 <= cost.confidence <= 1.0)

        # Serialization
        cost_dict = cost.to_dict()
        restored_cost = PlanCost.from_dict(cost_dict)
        self.assertEqual(restored_cost.estimated_steps, cost.estimated_steps)

    def test_10_decision_registry_persistent_records(self):
        """DecisionRegistry records operational choices without storing hidden chain-of-thought."""
        reg = DecisionRegistry(self.decisions_file)
        rec = reg.record(
            project_id="proj-dec-01",
            question="Select tree generation method",
            options=["Easy Tree Addon", "Procedural Geometry Script"],
            selected_option="Procedural Geometry Script",
            rationale_summary="Easy Tree add-on was unavailable in headless environment; procedural fallback selected.",
            task_id="task-3"
        )
        self.assertTrue(rec.decision_id.startswith("dec-"))
        self.assertEqual(rec.selected_option, "Procedural Geometry Script")
        # Ensure file was written
        self.assertTrue(self.decisions_file.exists())

        # Load into new registry instance
        reg2 = DecisionRegistry(self.decisions_file)
        loaded = reg2.get(rec.decision_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.rationale_summary, rec.rationale_summary)

    def test_11_plan_preview_rendering(self):
        """PlanPreview renders a structured, auditable human-readable preview without hidden reasoning."""
        goal = GoalParser.parse_goal("Build and test the security audit tool")
        tasks = HierarchicalPlanner.create_hierarchical_plan(goal, "proj-prev")
        cost = HierarchicalPlanner.estimate_cost(goal, tasks)
        val = PlanValidator.validate(goal, tasks)

        preview_text = PlanPreview.render(goal, tasks, cost, val)
        self.assertIn("ZARA PLAN PREVIEW", preview_text)
        self.assertIn("Goal:", preview_text)
        self.assertIn("Steps:", preview_text)
        self.assertIn("Estimated Steps:", preview_text)

    def test_12_cybersecurity_plan_scope_validation(self):
        """Cybersecurity plan with unauthorized external target fails scope validation."""
        goal = Goal(
            goal_id="g1",
            raw_request="Audit target",
            normalized_goal="Audit target",
            domain=GoalDomain.CYBERSECURITY,
            desired_outcome="Conduct audit"
        )
        t1 = PersistentTask(
            id="t1",
            project_id="p",
            title="Scan target",
            capability="cyber_lab",
            input_payload={"target": "http://malicious-external-site.com"},
            verification={"method": "scope_check"}
        )
        result = PlanValidator.validate(goal, [t1], allowed_scopes=["127.0.0.1", "localhost", "dvwa"])
        self.assertFalse(result.valid)
        self.assertTrue(any("unauthorized external host" in err for err in result.errors))

    def test_13_plan_validator_ambiguity_rejection(self):
        """Goals with unresolved HIGH or CRITICAL ambiguity fail plan validation."""
        vague_goal = Goal(
            goal_id="g_vague",
            raw_request="deploy",
            normalized_goal="deploy",
            domain=GoalDomain.GENERAL,
            ambiguity_level=AmbiguityLevel.CRITICAL,
            clarification_needed=True,
            clarification_question="What application should be deployed?"
        )
        t1 = PersistentTask(id="t1", project_id="p", title="Deploy", capability="general")
        result = PlanValidator.validate(vague_goal, [t1])
        self.assertFalse(result.valid)
        self.assertTrue(any("unresolved ambiguity" in err for err in result.errors))
        self.assertIn("What application should be deployed?", result.missing_information)

    def test_14_plan_cost_confidence_scaling(self):
        """PlanCost confidence scales down when requirements contain ambiguity."""
        goal_clear = GoalParser.parse_goal("Implement quicksort in Python with 0 failures")
        tasks_clear = HierarchicalPlanner.create_hierarchical_plan(goal_clear, "p1")
        cost_clear = HierarchicalPlanner.estimate_cost(goal_clear, tasks_clear)

        goal_vague = GoalParser.parse_goal("Build a quick tool")
        tasks_vague = HierarchicalPlanner.create_hierarchical_plan(goal_vague, "p2")
        cost_vague = HierarchicalPlanner.estimate_cost(goal_vague, tasks_vague)

        self.assertGreater(cost_clear.confidence, cost_vague.confidence)


if __name__ == "__main__":
    unittest.main()
