"""
Unit tests for ZARA Phase 10: Persistent Scheduler & Priority Job Queue.
Tests cover deterministic mock clock, cron validation, schedule calculation,
persistence and reload, priority ordering, pause/resume/cancel,
missed schedule recovery, and job queue crash recovery.
"""
import os
import json
import shutil
import tempfile
import unittest
import datetime
from pathlib import Path

from modules.scheduler import (
    Clock,
    SystemClock,
    MockClock,
    ScheduleType,
    JobStatus,
    JobPriority,
    MissedSchedulePolicy,
    ScheduledJob,
    QueueItem,
    validate_cron_expression,
    calculate_next_run,
    PersistentScheduler,
    JobQueue
)


class TestPersistentScheduler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="zara_test_sched_")
        self.schedules_file = Path(self.temp_dir) / "schedules.json"
        self.queue_file = Path(self.temp_dir) / "queue.json"
        self.clock = MockClock(datetime.datetime(2026, 9, 18, 10, 0, 0, tzinfo=datetime.timezone.utc))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_mock_clock_advancement(self):
        """Mock clock advances deterministically without time.sleep."""
        t0 = self.clock.now()
        self.assertEqual(t0.hour, 10)
        self.assertEqual(t0.minute, 0)

        t1 = self.clock.advance(seconds=30, minutes=15)
        self.assertEqual(t1.hour, 10)
        self.assertEqual(t1.minute, 15)
        self.assertEqual(t1.second, 30)

        self.clock.advance(hours=2)
        self.assertEqual(self.clock.now().hour, 12)

    def test_cron_validation(self):
        """Valid and invalid cron expressions are correctly verified."""
        valid, _ = validate_cron_expression("0 9 * * 1-5")
        self.assertTrue(valid)

        valid, _ = validate_cron_expression("*/15 * * * *")
        self.assertTrue(valid)

        valid, _ = validate_cron_expression("0 0 1 * *")
        self.assertTrue(valid)

        # Invalid field count
        valid, err = validate_cron_expression("* * *")
        self.assertFalse(valid)
        self.assertIn("5 fields", err)

        # Invalid minute out of range
        valid, err = validate_cron_expression("65 * * * *")
        self.assertFalse(valid)

    def test_calculate_next_run_once_and_interval(self):
        """Schedule calculations for ONCE and INTERVAL types."""
        now = self.clock.now()
        target_time = now + datetime.timedelta(hours=2)

        job_once = ScheduledJob(
            job_id="test_once",
            name="Once Job",
            schedule_type=ScheduleType.ONCE,
            run_at=target_time.isoformat()
        )
        next_dt = calculate_next_run(job_once, now)
        self.assertEqual(next_dt, target_time)

        job_interval = ScheduledJob(
            job_id="test_interval",
            name="Interval Job",
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=300
        )
        next_dt = calculate_next_run(job_interval, now)
        self.assertEqual(next_dt, now + datetime.timedelta(seconds=300))

    def test_calculate_next_run_cron(self):
        """Cron calculation finds the next matching timestamp."""
        # Current time: 2026-09-18 10:00:00 (Friday)
        now = self.clock.now()
        job_cron = ScheduledJob(
            job_id="test_cron",
            name="Hourly at 30 min",
            schedule_type=ScheduleType.CRON,
            cron_expression="30 * * * *"
        )
        next_dt = calculate_next_run(job_cron, now)
        self.assertIsNotNone(next_dt)
        self.assertEqual(next_dt.hour, 10)
        self.assertEqual(next_dt.minute, 30)

    def test_scheduler_persistence_and_reload(self):
        """Jobs persisted to disk can be accurately loaded by a new scheduler instance."""
        sched1 = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        job = sched1.schedule_job(
            name="Database Backup",
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=3600,
            priority=JobPriority.HIGH,
            action_payload={"task": "backup_db"}
        )
        self.assertTrue(self.schedules_file.exists())

        # Reload from new instance
        sched2 = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        loaded_job = sched2.get_job(job.job_id)
        self.assertIsNotNone(loaded_job)
        self.assertEqual(loaded_job.name, "Database Backup")
        self.assertEqual(loaded_job.priority, JobPriority.HIGH)
        self.assertEqual(loaded_job.action_payload.get("task"), "backup_db")

    def test_get_due_jobs_priority_order(self):
        """Due jobs are sorted with highest priority first."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        now = self.clock.now()

        j_low = sched.schedule_job("Low Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.LOW)
        j_crit = sched.schedule_job("Critical Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.CRITICAL)
        j_norm = sched.schedule_job("Normal Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.NORMAL)
        j_high = sched.schedule_job("High Job", ScheduleType.ONCE, run_at=now, priority=JobPriority.HIGH)

        due = sched.get_due_jobs()
        self.assertEqual(len(due), 4)
        self.assertEqual(due[0].priority, JobPriority.CRITICAL)
        self.assertEqual(due[1].priority, JobPriority.HIGH)
        self.assertEqual(due[2].priority, JobPriority.NORMAL)
        self.assertEqual(due[3].priority, JobPriority.LOW)

    def test_job_completion_lifecycle(self):
        """Single-run job completes and recurring job recalculates next run."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        now = self.clock.now()

        # Once job
        once_job = sched.schedule_job("Single Run", ScheduleType.ONCE, run_at=now)
        sched.mark_job_running(once_job.job_id)
        self.assertEqual(sched.get_job(once_job.job_id).status, JobStatus.RUNNING)
        sched.mark_job_completed(once_job.job_id)
        self.assertEqual(sched.get_job(once_job.job_id).status, JobStatus.COMPLETED)
        self.assertIsNone(sched.get_job(once_job.job_id).next_run)

        # Interval job
        interval_job = sched.schedule_job("Recurring Run", ScheduleType.INTERVAL, interval_seconds=60)
        sched.mark_job_running(interval_job.job_id)
        sched.mark_job_completed(interval_job.job_id)
        updated = sched.get_job(interval_job.job_id)
        self.assertEqual(updated.status, JobStatus.SCHEDULED)
        self.assertEqual(updated.runs_completed, 1)
        self.assertIsNotNone(updated.next_run)

    def test_pause_resume_and_cancel_job(self):
        """Jobs can be paused, resumed, and cancelled safely."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        job = sched.schedule_job("Togglable Job", ScheduleType.INTERVAL, interval_seconds=120)

        # Pause
        self.assertTrue(sched.pause_job(job.job_id))
        self.assertEqual(sched.get_job(job.job_id).status, JobStatus.PAUSED)
        self.assertEqual(len(sched.get_due_jobs()), 0)

        # Resume
        self.assertTrue(sched.resume_job(job.job_id))
        self.assertEqual(sched.get_job(job.job_id).status, JobStatus.SCHEDULED)

        # Cancel
        self.assertTrue(sched.cancel_job(job.job_id))
        self.assertEqual(sched.get_job(job.job_id).status, JobStatus.CANCELLED)
        self.assertFalse(sched.get_job(job.job_id).enabled)
        self.assertEqual(len(sched.get_due_jobs()), 0)

    def test_retry_backoff_on_failure(self):
        """Failed jobs back off until reaching maximum retry budget."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        job = sched.schedule_job("Failing Job", ScheduleType.INTERVAL, interval_seconds=60)

        # First failure -> retried
        sched.mark_job_failed(job.job_id, error="Transient network drop")
        j = sched.get_job(job.job_id)
        self.assertEqual(j.retries_used, 1)
        self.assertEqual(j.status, JobStatus.SCHEDULED)

        # Second failure -> retried
        sched.mark_job_failed(job.job_id, error="Timeout")
        j = sched.get_job(job.job_id)
        self.assertEqual(j.retries_used, 2)
        self.assertEqual(j.status, JobStatus.SCHEDULED)

        # Third failure -> reaches max_retries (default 2), marked FAILED
        sched.mark_job_failed(job.job_id, error="Terminal failure")
        j = sched.get_job(job.job_id)
        self.assertEqual(j.status, JobStatus.FAILED)
        self.assertIsNone(j.next_run)

    def test_missed_schedule_recovery_policies(self):
        """Recovery accurately enforces RUN_NOW, SKIP, RESCHEDULE, and REQUIRES_USER_DECISION policies."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        past_time = self.clock.now() - datetime.timedelta(hours=5)

        j_run_now = sched.schedule_job(
            "Missed Run Now", ScheduleType.INTERVAL, interval_seconds=3600,
            run_at=past_time, missed_policy=MissedSchedulePolicy.RUN_NOW
        )
        j_run_now.next_run = past_time.isoformat()

        j_skip = sched.schedule_job(
            "Missed Skip", ScheduleType.INTERVAL, interval_seconds=3600,
            run_at=past_time, missed_policy=MissedSchedulePolicy.SKIP
        )
        j_skip.next_run = past_time.isoformat()

        j_resched = sched.schedule_job(
            "Missed Reschedule", ScheduleType.INTERVAL, interval_seconds=3600,
            run_at=past_time, missed_policy=MissedSchedulePolicy.RESCHEDULE
        )
        j_resched.next_run = past_time.isoformat()

        j_approval = sched.schedule_job(
            "Missed Approval", ScheduleType.INTERVAL, interval_seconds=3600,
            run_at=past_time, missed_policy=MissedSchedulePolicy.REQUIRES_USER_DECISION
        )
        j_approval.next_run = past_time.isoformat()

        sched.save()

        # Run recovery
        actions = sched.recover_missed_schedules()
        self.assertEqual(len(actions), 4)

        self.assertEqual(sched.get_job(j_run_now.job_id).next_run, past_time.isoformat())
        self.assertNotEqual(sched.get_job(j_skip.job_id).next_run, past_time.isoformat())
        self.assertNotEqual(sched.get_job(j_resched.job_id).next_run, past_time.isoformat())
        self.assertEqual(sched.get_job(j_approval.job_id).status, JobStatus.WAITING_APPROVAL)

    def test_job_queue_priority_and_crash_recovery(self):
        """JobQueue pops items strictly in priority order and resets abandoned in-flight tasks."""
        jq = JobQueue(queue_file=self.queue_file)

        it_low = jq.enqueue("job_1", "Low item", JobPriority.LOW, "dev")
        it_crit = jq.enqueue("job_2", "Crit item", JobPriority.CRITICAL, "sec")
        it_high = jq.enqueue("job_3", "High item", JobPriority.HIGH, "blender")

        # Highest priority item popped first
        top = jq.pop()
        self.assertIsNotNone(top)
        self.assertEqual(top.item_id, it_crit.item_id)
        top.status = "RUNNING"
        jq._save()

        # Simulate crash & recovery by loading a fresh instance
        jq2 = JobQueue(queue_file=self.queue_file)
        # Recovered item should be reset from RUNNING back to READY
        recovered = jq2.peek()
        self.assertEqual(recovered.item_id, it_crit.item_id)
        self.assertEqual(recovered.status, "READY")

    def test_hourly_weekly_monthly_schedule_calculations(self):
        """Next run calculation correctly handles HOURLY, WEEKLY, and MONTHLY schedule types."""
        now = self.clock.now()

        # Hourly
        j_hourly = ScheduledJob("j_hr", "Hourly Job", schedule_type=ScheduleType.HOURLY)
        next_hr = calculate_next_run(j_hourly, now)
        self.assertEqual(next_hr.hour, now.hour + 1)
        self.assertEqual(next_hr.minute, 0)

        # Weekly
        j_weekly = ScheduledJob("j_wk", "Weekly Job", schedule_type=ScheduleType.WEEKLY, metadata={"day_of_week": 6}) # Sunday
        next_wk = calculate_next_run(j_weekly, now)
        self.assertGreater(next_wk, now)

        # Monthly
        j_monthly = ScheduledJob("j_mo", "Monthly Job", schedule_type=ScheduleType.MONTHLY, metadata={"day": 1})
        next_mo = calculate_next_run(j_monthly, now)
        self.assertGreater(next_mo, now)

    def test_job_queue_pause_and_resume(self):
        """Paused job queue yields no items until resumed."""
        jq = JobQueue(queue_file=self.queue_file)
        jq.enqueue("job_p1", "Paused Test", JobPriority.HIGH)

        # Pause queue
        jq.pause()
        self.assertTrue(jq.is_paused)
        self.assertIsNone(jq.pop())

        # Resume queue
        jq.resume()
        self.assertFalse(jq.is_paused)
        popped = jq.pop()
        self.assertIsNotNone(popped)
        self.assertEqual(popped.job_id, "job_p1")

    def test_job_queue_mark_completed_and_failed(self):
        """Queue items transition correctly through completion and failure retries."""
        jq = JobQueue(queue_file=self.queue_file)
        item = jq.enqueue("job_stat", "Status Test", JobPriority.NORMAL)

        # Mark failed with attempts < max_attempts -> returns to READY
        item.attempts = 1
        jq.mark_failed(item.item_id, max_attempts=3)
        self.assertEqual(jq.items[item.item_id].status, "READY")

        # Mark failed with attempts >= max_attempts -> transitions to FAILED
        item.attempts = 3
        jq.mark_failed(item.item_id, max_attempts=3)
        self.assertEqual(jq.items[item.item_id].status, "FAILED")

        # Mark completed
        jq.mark_completed(item.item_id)
        self.assertEqual(jq.items[item.item_id].status, "COMPLETED")

    def test_cancel_nonexistent_job(self):
        """Attempting to cancel an unknown job id gracefully returns False without error."""
        sched = PersistentScheduler(schedules_file=self.schedules_file, clock=self.clock)
        self.assertFalse(sched.cancel_job("non_existent_id"))


if __name__ == "__main__":
    unittest.main()

