"""
Unit tests for ZARA Phase 10: Proactive Intelligence, Scheduling & Event-Driven Autonomy.
Tests cover Autonomous Mode (ON/OFF), scheduled task execution, safety approval gates,
cybersecurity target scope gating, daily budget limits, quiet hours policy,
notification queuing & flushing, daily queue synthesis, and proactive maintenance.
"""
import os
import json
import shutil
import tempfile
import unittest
import datetime
from pathlib import Path

from core.engine import ZaraEngine
from core.state import PlanStep, StepStatus, ActionType
from modules.events import EventBus, Event, EventType
from modules.scheduler import (
    MockClock,
    PersistentScheduler,
    ScheduleType,
    JobStatus,
    JobPriority,
    MissedSchedulePolicy
)
from modules.notifications import NotificationManager, NotificationSeverity, Notification
from modules.autonomous import (
    AutonomousMode,
    AutonomousModeManager,
    AutonomousBudget,
    QuietHoursManager,
    DailyQueueSynthesizer,
    ProactiveMaintenance
)
from modules.workspace import ProjectManager


class TestAutonomousMode(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_test_auto_")
        self.schedules_file = Path(self.temp_dir) / "schedules.json"
        self.events_file = Path(self.temp_dir) / "events.jsonl"
        self.notifs_file = Path(self.temp_dir) / "notifications.jsonl"
        self.auto_config = Path(self.temp_dir) / "autonomous_config.json"

        # Mock clock set to 2026-09-18 10:00:00 UTC (normal business hours)
        self.clock = MockClock(datetime.datetime(2026, 9, 18, 10, 0, 0, tzinfo=datetime.timezone.utc))
        self.bus = EventBus(events_file=self.events_file)
        self.scheduler = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        self.notifications = NotificationManager(notifications_file=self.notifs_file)
        self.autonomous = AutonomousModeManager(config_file=self.auto_config, initial_mode=AutonomousMode.ON)

        self.engine = ZaraEngine(
            workspace_root=self.temp_dir,
            enable_voice=False,
            clock=self.clock,
            event_bus=self.bus,
            scheduler=self.scheduler,
            notifications=self.notifications,
            autonomous=self.autonomous
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_autonomous_mode_off_prevents_execution(self):
        """When Autonomous Mode is OFF, autonomous_tick does not execute scheduled tasks."""
        self.autonomous.disable()
        self.assertFalse(self.autonomous.is_enabled())

        # Schedule a due job
        now = self.clock.now()
        job = self.scheduler.schedule_job(
            name="Echo Task",
            schedule_type=ScheduleType.ONCE,
            run_at=now,
            action_payload={"task": "echo 'Hello'"}
        )

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "PAUSED_AUTONOMOUS_OFF")
        self.assertEqual(len(res["executed_jobs"]), 0)

        # Job remains scheduled
        self.assertEqual(self.scheduler.get_job(job.job_id).status, JobStatus.SCHEDULED)

    def test_autonomous_mode_on_executes_due_jobs(self):
        """When Autonomous Mode is ON, autonomous_tick executes due scheduled jobs."""
        self.autonomous.enable()
        self.assertTrue(self.autonomous.is_enabled())

        now = self.clock.now()
        test_file = Path(self.temp_dir) / "auto_test.txt"
        job = self.scheduler.schedule_job(
            name="Write File Job",
            schedule_type=ScheduleType.ONCE,
            run_at=now,
            action_payload={"task": f"Create a file called auto_test.txt with prints 'Autonomous test success'"}
        )

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(res["executed_jobs"]), 1)
        self.assertEqual(res["executed_jobs"][0]["job_id"], job.job_id)

        # Job completed and file exists
        self.assertEqual(self.scheduler.get_job(job.job_id).status, JobStatus.COMPLETED)
        self.assertTrue(test_file.exists())

        # Budget recorded usage
        self.assertEqual(self.autonomous.budget.runs_used, 1)

    def test_approval_gate_blocks_high_risk_tasks(self):
        """Scheduled jobs requiring human approval transition to WAITING_APPROVAL without auto-executing."""
        now = self.clock.now()
        job = self.scheduler.schedule_job(
            name="Dangerous Action",
            schedule_type=ScheduleType.ONCE,
            run_at=now,
            priority=JobPriority.CRITICAL,
            action_payload={"task": "rm -rf /some/path", "requires_approval": True}
        )

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(res["executed_jobs"]), 0)

        # Job is waiting approval, not executed
        updated = self.scheduler.get_job(job.job_id)
        self.assertEqual(updated.status, JobStatus.WAITING_APPROVAL)

        # Notification dispatched
        notifs = self.notifications.history
        self.assertTrue(any("Awaiting Approval" in n.title for n in notifs))

    def test_cybersecurity_scope_safety_gate(self):
        """Autonomous cybersecurity tasks are blocked if target is not authorized in scope."""
        now = self.clock.now()
        # Unauthorized target not in allowlist
        unauth_target = "evil.corp"
        job = self.scheduler.schedule_job(
            name="Port Scan Target",
            schedule_type=ScheduleType.ONCE,
            run_at=now,
            capability="cybersecurity",
            action_payload={"task": f"cyber_scan target='{unauth_target}'", "target": unauth_target}
        )

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(res["executed_jobs"]), 0)

        # Job marked failed with ScopeViolation
        j = self.scheduler.get_job(job.job_id)
        self.assertEqual(j.status, JobStatus.FAILED)

        # Critical notification dispatched
        self.assertTrue(any(n.severity == NotificationSeverity.CRITICAL for n in self.notifications.history))

    def test_resource_budget_limits_pause_execution(self):
        """When daily budget limits are exhausted, autonomous execution pauses."""
        # Set max_runs to 2
        self.autonomous.budget.max_runs = 2
        self.autonomous.budget.runs_used = 2
        self.assertTrue(self.autonomous.budget.is_exhausted())

        can_run, reason = self.autonomous.can_execute_autonomously()
        self.assertFalse(can_run)
        self.assertIn("PAUSED_BY_BUDGET", reason)

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "PAUSED_BY_BUDGET")

    def test_quiet_hours_notification_queuing_and_flushing(self):
        """Non-critical notifications are queued during quiet hours and flushed when quiet hours end."""
        # Quiet hours from 23:00 to 07:00
        qm = QuietHoursManager("23:00", "07:00")

        # 02:00 -> within quiet hours
        t_quiet = datetime.datetime(2026, 9, 18, 2, 0, 0)
        self.assertTrue(qm.is_quiet_hours(t_quiet))

        # 14:00 -> outside quiet hours
        t_active = datetime.datetime(2026, 9, 18, 14, 0, 0)
        self.assertFalse(qm.is_quiet_hours(t_active))

        # Notify INFO during quiet hours -> queued
        notif_info = self.notifications.notify(
            title="Nightly Summary",
            message="All systems nominal",
            severity=NotificationSeverity.INFO,
            is_quiet_hours=True
        )
        self.assertTrue(notif_info.queued_for_quiet_hours)
        self.assertEqual(self.notifications.get_pending_count(), 1)

        # Notify CRITICAL during quiet hours -> bypasses queue immediately
        notif_crit = self.notifications.notify(
            title="Security Alert",
            message="Unauthorized port access",
            severity=NotificationSeverity.CRITICAL,
            is_quiet_hours=True
        )
        self.assertFalse(notif_crit.queued_for_quiet_hours)
        self.assertTrue(notif_crit.delivered)

        # Flush queue when quiet hours expire
        flushed = self.notifications.flush_quiet_hours_queue()
        self.assertEqual(len(flushed), 1)
        self.assertEqual(flushed[0].title, "Nightly Summary")
        self.assertEqual(self.notifications.get_pending_count(), 0)

    def test_daily_queue_synthesizer(self):
        """Synthesizer aggregates scheduled jobs and workspace DAG tasks by priority."""
        now = self.clock.now()
        self.scheduler.schedule_job("Normal Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.NORMAL)
        self.scheduler.schedule_job("Urgent Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.HIGH)

        synthesizer = DailyQueueSynthesizer(scheduler=self.scheduler)
        items = synthesizer.synthesize()

        self.assertEqual(len(items), 2)
        # Highest priority first
        self.assertEqual(items[0]["title"], "Urgent Job")
        self.assertEqual(items[1]["title"], "Normal Job")

    def test_proactive_maintenance_inspects_project_health(self):
        """Proactive maintenance identifies pending approvals and missing artifacts."""
        pm = ProjectManager.create("Maintenance Project", Path(self.temp_dir), "Proactive test")
        pm.request_approval({"ticket_id": "t1", "action_id": "act_test", "risk": "HIGH"})

        # Register artifact that does not exist
        missing_file = Path(self.temp_dir) / "ghost.txt"
        pm.artifacts.register_artifact("Ghost File", str(missing_file), "test")

        maint = ProactiveMaintenance(project_manager=pm, event_bus=self.bus)
        report = maint.check_project_health()

        self.assertEqual(report["issues_count"], 2)
        types = [issue["type"] for issue in report["issues"]]
        self.assertIn("PENDING_APPROVAL", types)
        self.assertIn("MISSING_ARTIFACT", types)

    def test_shutdown_persistence_and_reload(self):
        """Autonomous state and scheduler persist across engine restarts."""
        # Modify budget
        self.autonomous.budget.record(runs=3, tool_calls=12, runtime_seconds=45.0)
        self.autonomous.save()

        # Reload
        new_auto = AutonomousModeManager(config_file=self.auto_config)
        self.assertEqual(new_auto.budget.runs_used, 3)
        self.assertEqual(new_auto.budget.tool_calls_used, 12)
        self.assertEqual(new_auto.budget.runtime_seconds_used, 45.0)

    def test_quiet_hours_overnight_boundary_accuracy(self):
        """Boundary minutes around overnight quiet hours window (23:00 to 07:00) are accurate."""
        qm = QuietHoursManager("23:00", "07:00")

        # 22:59 -> outside quiet hours
        self.assertFalse(qm.is_quiet_hours(datetime.datetime(2026, 9, 18, 22, 59, 0)))
        # 23:00 -> inside quiet hours
        self.assertTrue(qm.is_quiet_hours(datetime.datetime(2026, 9, 18, 23, 0, 0)))
        # 06:59 -> inside quiet hours
        self.assertTrue(qm.is_quiet_hours(datetime.datetime(2026, 9, 18, 6, 59, 0)))
        # 07:00 -> outside quiet hours
        self.assertFalse(qm.is_quiet_hours(datetime.datetime(2026, 9, 18, 7, 0, 0)))

    def test_budget_to_from_dict_and_exhaustion(self):
        """AutonomousBudget serializes, deserializes, and detects exhaustion accurately."""
        b = AutonomousBudget(max_runs=5, max_tool_calls=20)
        self.assertFalse(b.is_exhausted())

        b.record(runs=5, tool_calls=10)
        self.assertTrue(b.is_exhausted())

        d = b.to_dict()
        b2 = AutonomousBudget.from_dict(d)
        self.assertEqual(b2.runs_used, 5)
        self.assertEqual(b2.tool_calls_used, 10)
        self.assertTrue(b2.is_exhausted())

    def test_maintenance_with_no_active_project(self):
        """ProactiveMaintenance returns no_active_project when project_manager has no project."""
        maint = ProactiveMaintenance(project_manager=None)
        res = maint.check_project_health()
        self.assertEqual(res["status"], "no_active_project")

    def test_tick_advances_mock_clock_when_provided(self):
        """Passing clock_time to autonomous_tick updates the engine's mock clock."""
        target_ts = datetime.datetime(2026, 9, 18, 15, 30, 0, tzinfo=datetime.timezone.utc).timestamp()
        res = self.engine.autonomous_tick(clock_time=target_ts)
        self.assertEqual(res["status"], "OK")
        self.assertEqual(self.clock.now().hour, 15)
        self.assertEqual(self.clock.now().minute, 30)

    def test_scheduled_job_with_custom_steps(self):
        """Scheduled job with pre-defined plan steps executes without invoking LLM planning."""
        now = self.clock.now()
        out_file = Path(self.temp_dir) / "custom_steps_test.txt"

        custom_step = PlanStep(
            id=1,
            title="Write Output File",
            description="Direct write",
            tool="write_file",
            action_type=ActionType.TOOL,
            target="custom_steps_test.txt",
            arguments={"path": "custom_steps_test.txt", "content": "direct custom steps execution"},
            success_condition="File custom_steps_test.txt exists on disk"
        )

        job = self.scheduler.schedule_job(
            name="Explicit Steps Task",
            schedule_type=ScheduleType.ONCE,
            run_at=now,
            action_payload={"task": "Run custom steps", "steps": [custom_step]}
        )

        res = self.engine.autonomous_tick()
        self.assertEqual(res["status"], "OK")
        self.assertEqual(len(res["executed_jobs"]), 1)
        self.assertTrue(out_file.exists())
        self.assertIn("direct custom steps execution", out_file.read_text())


if __name__ == "__main__":
    unittest.main()

