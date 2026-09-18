"""Tests for ZARA Phase 11 - Context Management, Deterministic Compaction & Safety Integration."""

import unittest
from pathlib import Path
import tempfile
import shutil
import time

from core.engine import ZaraEngine
from core.state import PlanStep, ActionType, StepStatus, TaskContext, Diagnosis
from modules.goals import Goal, GoalDomain, GoalParser, AmbiguityLevel
from modules.planning import HierarchicalPlanner, PlanValidator, PlanCost, DecisionRegistry
from modules.context import ContextManager, ContextCompactor, ContextTier, CompactSummary
from modules.workspace import ProjectManager, PersistentTask, ProjectBudget, ArtifactRecord
from modules.events import EventBus, Event, EventType
from modules.scheduler import MockClock, PersistentScheduler, ScheduledJob


class TestContextManagement(unittest.TestCase):
    """Test suite for tiered context management, deterministic compaction, and integrated safety."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.workspace_dir = self.temp_dir / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.pm = ProjectManager.create("test-proj", self.workspace_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_tiered_context_separation(self):
        """ContextManager separates GLOBAL, PROJECT, TASK, and STEP context tiers."""
        cm = ContextManager(project_id="p1")
        goal = GoalParser.parse_goal("Write code to implement neural network trainer")
        task = PersistentTask(id="t1", project_id="p1", title="Init weights", capability="coding")
        step = PlanStep(id=1, title="Write code", action_type=ActionType.CODE, description="desc", target="model.py")

        assembled = cm.assemble_context(goal=goal, current_task=task, current_step=step)
        self.assertIn("current_step", assembled)
        self.assertIn("current_task", assembled)
        self.assertIn("goal", assembled)
        self.assertEqual(assembled["current_step"]["target"], "model.py")
        self.assertEqual(assembled["goal"]["domain"], GoalDomain.CODING.value)

    def test_02_context_prioritization(self):
        """Context assembly prioritizes current step and task above general history."""
        cm = ContextManager(project_id="p1")
        task = PersistentTask(id="t1", project_id="p1", title="Task 1", capability="coding")
        step = PlanStep(id=1, title="Step 1", action_type=ActionType.CODE, description="desc", target="main.py")

        # Add a compact summary to history
        summary = CompactSummary(summary_id="s1", project_id="p1", current_state="Halfway done")
        cm.add_summary(summary)

        assembled = cm.assemble_context(goal=None, current_task=task, current_step=step)
        # Verify both priority 1 (step/task) and priority 5 (summary) exist and are distinguishable
        self.assertEqual(assembled["current_step"]["title"], "Step 1")
        self.assertEqual(assembled["latest_summary"]["current_state"], "Halfway done")

    def test_03_deterministic_context_compaction(self):
        """ContextCompactor deterministically extracts important facts, state, decisions, and pending work."""
        goal = GoalParser.parse_goal("Build secure authentication service")
        tasks = [
            PersistentTask(id="t1", project_id="p1", title="Create user table", capability="coding", status=StepStatus.PASSED),
            PersistentTask(id="t2", project_id="p1", title="Add password hash", capability="coding", status=StepStatus.PENDING),
        ]
        artifacts = [
            ArtifactRecord(artifact_id="a1", project_id="p1", task_id="t1", path="auth/models.py", type="code", size=120, checksum="abc", created_at="now", modified_at="now")
        ]
        decisions = [
            self.pm.record_decision(
                question="Hash algorithm",
                options=["bcrypt", "argon2id"],
                selected_option="argon2id",
                rationale_summary="Selected Argon2id for password hashing"
            )
        ]
        from modules.planning import DecisionRecord
        dec_records = [DecisionRecord.from_dict(d) for d in decisions]

        compact = ContextCompactor.compact(
            project_id="p1",
            goal=goal,
            tasks=tasks,
            artifacts=artifacts,
            decisions=dec_records
        )
        self.assertIn("1/2 tasks completed successfully", compact.current_state)
        self.assertTrue(any("auth/models.py" in f for f in compact.important_facts))
        self.assertTrue(any("argon2id" in d for d in compact.decisions))
        self.assertTrue(any("Add password hash" in p for p in compact.pending_work))

        # Markdown representation
        md = compact.to_markdown()
        self.assertIn("Context Summary", md)
        self.assertIn("Current State", md)

    def test_04_compact_summary_persistence(self):
        """Compact summaries are durably persisted to project workspace."""
        summary_data = {
            "summary_id": "s-test",
            "project_id": self.pm.project.project_id,
            "timestamp": "2026-09-18T12:00:00Z",
            "important_facts": ["Database migrated"],
            "decisions": ["Used Postgres"],
            "current_state": "All tests passing",
            "pending_work": []
        }
        self.pm.save_compact_summary(summary_data)
        loaded = self.pm.list_compact_summaries()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["summary_id"], "s-test")

    def test_05_cybersecurity_scope_requirement(self):
        """Cybersecurity planning strictly enforces target allowlisting."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        # Plan for unauthorized external target
        bad_goal = GoalParser.parse_goal("Conduct a vulnerability scan of unauthorized-external-target.com")
        tasks, val, cost = engine.plan_goal(bad_goal)
        self.assertFalse(val.valid)
        self.assertTrue(any("unauthorized" in err.lower() or "scope" in err.lower() for err in val.errors))

    def test_06_cybersecurity_authorized_target_succeeds(self):
        """Cybersecurity planning for authorized target passes validation."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        good_goal = GoalParser.parse_goal("Conduct a security assessment of DVWA at http://127.0.0.1:8080/dvwa")
        tasks, val, cost = engine.plan_goal(good_goal)
        self.assertTrue(val.valid)
        self.assertTrue(len(tasks) >= 3)
        self.assertTrue(any(t.capability == "cyber_lab" for t in tasks))

    def test_07_destructive_command_blocked_in_planning(self):
        """Dangerous destructive patterns in goals or tasks are caught by safety checks."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        is_valid, reason = engine.execution.validate_command("rm -rf / --no-preserve-root")
        self.assertFalse(is_valid)
        self.assertIn("blocked", (reason or "").lower())

    def test_08_blender_planning_and_verification(self):
        """Blender planning produces procedural script and render verification steps."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        goal = engine.understand_goal("Create a realistic forest environment in Blender")
        tasks, val, cost = engine.plan_goal(goal)

        self.assertTrue(val.valid)
        self.assertTrue(any(t.capability == "blender" for t in tasks))
        self.assertTrue(any(t.capability == "vision" for t in tasks))

    def test_09_proactive_scheduled_planning_pipeline(self):
        """Scheduled tasks pass through Goal Understanding and Ambiguity gates."""
        import datetime as _dt
        from modules.scheduler import ScheduleType
        initial_dt = _dt.datetime(2026, 9, 18, 9, 0, 0, tzinfo=_dt.timezone.utc)
        clock = MockClock(initial_time=initial_dt)
        scheduler = PersistentScheduler(clock=clock)
        engine = ZaraEngine(workspace_root=str(self.workspace_dir), clock=clock, scheduler=scheduler)
        engine.set_project_manager(self.pm)
        engine.autonomous.enable()

        # Add ambiguous job with no steps
        scheduler.schedule_job(
            name="deploy",
            schedule_type=ScheduleType.ONCE,
            run_at=initial_dt,
            action_payload={"task": "deploy"}
        )

        tick_result = engine.autonomous_tick(clock_time=initial_dt.timestamp() + 5.0)
        self.assertEqual(tick_result["status"], "OK")
        self.assertEqual(len(tick_result["executed_jobs"]), 1)
        self.assertEqual(tick_result["executed_jobs"][0]["status"], "FAILED")
        self.assertEqual(tick_result["executed_jobs"][0]["reason"], "AmbiguousGoal")

    def test_10_restart_recovery_preserves_planning_and_decisions(self):
        """Engine and ProjectManager reload persisted planning state and decisions across restarts."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        goal = engine.understand_goal("Implement database cache layer")
        engine.plan_goal(goal)
        engine.record_decision(
            question="Select cache backend",
            options=["Redis", "Memcached", "In-Memory LRU"],
            selected_option="In-Memory LRU",
            rationale_summary="Zero external daemon dependencies"
        )

        # Simulate restart: create new ProjectManager instance from workspace
        restarted_pm = ProjectManager.load(self.workspace_dir)
        self.assertIsNotNone(restarted_pm)
        state = restarted_pm.load_planning_state()
        self.assertIsNotNone(state.get("goal"))
        self.assertEqual(state["goal"]["normalized_goal"].lower(), "implement database cache layer")

        decisions = restarted_pm.list_decisions()
        self.assertTrue(len(decisions) >= 1)
        self.assertEqual(decisions[-1]["selected_option"], "In-Memory LRU")

    def test_11_event_triggered_replanning_subscription(self):
        """EventBus delivers TASK_FAILED events without trigger storms."""
        bus = EventBus()
        events_received = []

        def handle_fail(ev: Event):
            events_received.append(ev)

        bus.subscribe(EventType.TASK_FAILED, handle_fail)
        bus.publish(Event(type=EventType.TASK_FAILED, source="test", payload={"reason": "Timeout"}))

        self.assertEqual(len(events_received), 1)
        self.assertEqual(events_received[0].payload["reason"], "Timeout")

    def test_12_evidence_based_planning_research_citations(self):
        """Research planning mandates verified evidence and citation validation."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        goal = engine.understand_goal("Research the latest autonomous agent planning architectures")
        tasks, val, cost = engine.plan_goal(goal)

        self.assertTrue(val.valid)
        self.assertEqual(goal.domain, GoalDomain.RESEARCH)
        self.assertTrue(any(t.capability == "research" for t in tasks))
        self.assertTrue(any("citation" in str(crit.verification_method).lower() for crit in goal.success_criteria))

    def test_13_plan_approval_ticket_integration(self):
        """High-impact cybersecurity plans register required approvals and can be resolved."""
        engine = ZaraEngine(workspace_root=str(self.workspace_dir))
        engine.set_project_manager(self.pm)

        goal = engine.understand_goal("Conduct a security assessment of DVWA at http://127.0.0.1:8080/dvwa")
        tasks, val, cost = engine.plan_goal(goal)

        self.assertTrue(val.valid)
        self.assertTrue(len(val.required_approvals) > 0)
        self.assertIn("Cybersecurity assessment plan authorization", val.required_approvals)

        # Request and resolve approval
        ticket = {
            "ticket_id": "ticket-cyber-01",
            "title": "DVWA security assessment plan",
            "status": "PENDING"
        }
        self.pm.request_approval(ticket)
        self.assertIsNotNone(self.pm.pending_approval_ticket)

        self.pm.resolve_approval("ticket-cyber-01", approved=True)
        self.assertIsNone(self.pm.pending_approval_ticket)


if __name__ == "__main__":
    unittest.main()
