"""
Phase 8: Comprehensive Tests for Persistent Autonomous Workspace & Long-Running Projects.
Covers Tests A through W and Scenarios 1 through 5.
Runs under: python3 -W error::ResourceWarning
"""
import os
import sys
import json
import time
import datetime
import shutil
import tempfile
import unittest
from pathlib import Path

from config.settings import BASE_DIR, RiskLevel
from core.state import TaskContext, PlanStep, StepStatus, ActionType, PendingConfirmation
from core.engine import ZaraEngine
from modules.workspace import (
    ProjectManager,
    PersistentProject,
    PersistentTask,
    PersistentDAG,
    ArtifactRegistry,
    ProjectJournal,
    TaskWatchdog,
    ProjectStatus,
    RecoveryClassification,
    TaskHealth,
    ProjectBudget,
    discover_projects
)


class TestPersistentWorkspace(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="zara_test_workspace_")).resolve()
        self.project_name = "Autonomous Test Project"
        self.project_desc = "Testing ZARA Phase 8 persistence capabilities"

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # A. Project Creation
    def test_a_project_creation(self):
        mgr = ProjectManager.create(
            name=self.project_name,
            workspace_path=self.test_dir,
            description=self.project_desc
        )
        self.assertIsNotNone(mgr.project)
        self.assertEqual(mgr.project.name, self.project_name)
        self.assertEqual(mgr.project.status, ProjectStatus.CREATED)
        self.assertTrue((self.test_dir / ".zara" / "project.json").exists())

        # Reload
        reloaded = ProjectManager.load(self.test_dir)
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded.project.project_id, mgr.project.project_id)
        self.assertEqual(reloaded.project.name, self.project_name)

    # B. Manifest Persistence
    def test_b_manifest_persistence(self):
        mgr = ProjectManager.create(
            name="Manifest Test",
            workspace_path=self.test_dir,
            description="Testing atomic manifest persistence",
            metadata={"priority": "high", "domain": "engineering"}
        )
        # Update metadata and save
        mgr.project.metadata["stage"] = "beta"
        mgr.save_manifest()

        raw_json = json.loads((self.test_dir / ".zara" / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(raw_json["metadata"]["stage"], "beta")
        self.assertEqual(raw_json["version"], "1.0")

    # C. Task Persistence
    def test_c_task_persistence(self):
        mgr = ProjectManager.create(name="Task Test", workspace_path=self.test_dir)
        task = mgr.create_task(
            title="Setup virtualenv",
            description="Create isolated environment",
            capability="terminal",
            input_payload={"command": "python -m venv venv"}
        )
        self.assertEqual(task.status, StepStatus.PENDING)

        # Reload DAG
        reloaded_dag = PersistentDAG(mgr.tasks_file, mgr.project.project_id)
        loaded_task = reloaded_dag.get_task(task.id)
        self.assertIsNotNone(loaded_task)
        self.assertEqual(loaded_task.title, "Setup virtualenv")
        self.assertEqual(loaded_task.capability, "terminal")

    # D. DAG Persistence & Topological Sort
    def test_d_dag_persistence(self):
        mgr = ProjectManager.create(name="DAG Test", workspace_path=self.test_dir)
        t_a = mgr.create_task(title="Task A")
        t_b = mgr.create_task(title="Task B", dependencies=[t_a.id])
        t_c = mgr.create_task(title="Task C", dependencies=[t_a.id])
        t_d = mgr.create_task(title="Task D", dependencies=[t_b.id, t_c.id])

        # Ready tasks should only be Task A
        ready = mgr.dag.get_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].id, t_a.id)

        # Complete Task A
        mgr.complete_task(t_a.id, verification={"verified": True})
        ready = mgr.dag.get_ready_tasks()
        self.assertEqual(len(ready), 2)
        ready_ids = {t.id for t in ready}
        self.assertEqual(ready_ids, {t_b.id, t_c.id})

        # Topological sort
        sorted_tasks = mgr.dag.topological_sort()
        self.assertEqual(len(sorted_tasks), 4)
        sorted_ids = [t.id for t in sorted_tasks]
        self.assertTrue(sorted_ids.index(t_a.id) < sorted_ids.index(t_b.id))
        self.assertTrue(sorted_ids.index(t_a.id) < sorted_ids.index(t_c.id))
        self.assertTrue(sorted_ids.index(t_b.id) < sorted_ids.index(t_d.id))

    # E. Checkpoint Creation
    def test_e_checkpoint_creation(self):
        mgr = ProjectManager.create(name="Checkpoint Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Compile Asset")
        ckpt = mgr.create_checkpoint(
            task_id=task.id,
            state_snapshot={"step_index": 2},
            completed_steps=[{"id": 1, "title": "step 1", "status": "passed"}],
            pending_steps=[{"id": 2, "title": "step 2", "status": "pending"}],
            verification={"verified": True}
        )
        self.assertTrue((mgr.checkpoints_dir / f"checkpoint_{ckpt.checkpoint_id}.json").exists())

        loaded = mgr.load_checkpoint(ckpt.checkpoint_id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.task_id, task.id)
        self.assertEqual(len(loaded.completed_steps), 1)
        self.assertEqual(len(loaded.pending_steps), 1)

    # F. Resume from Checkpoint
    def test_f_resume(self):
        mgr = ProjectManager.create(name="Resume Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Deploy Service")
        mgr.start_task(task.id)
        mgr.create_checkpoint(
            task_id=task.id,
            state_snapshot={"progress": 50},
            completed_steps=[{"id": 1, "status": "passed"}],
            pending_steps=[{"id": 2, "status": "pending"}]
        )
        mgr.pause_project("Simulated interruption")

        # Resume
        res = mgr.resume_project()
        self.assertEqual(res["status"], "ACTIVE")
        self.assertEqual(mgr.project.status, ProjectStatus.ACTIVE)

    # G. Crash Recovery
    def test_g_crash_recovery(self):
        mgr = ProjectManager.create(name="Crash Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Crunch Data")
        mgr.start_task(task.id)
        mgr.create_checkpoint(
            task_id=task.id,
            state_snapshot={"status": "processing"},
            completed_steps=[{"id": 1, "title": "init", "status": "passed"}],
            pending_steps=[{"id": 2, "title": "process", "status": "pending"}]
        )

        # Simulate crash: reload brand new manager from disk without clean exit
        crashed_mgr = ProjectManager.load(self.test_dir)
        rec = crashed_mgr.recover_project()
        self.assertEqual(rec["classification"], RecoveryClassification.SAFE_RESUME.value)
        self.assertEqual(crashed_mgr.project.status, ProjectStatus.ACTIVE)

    # H. Completed-Task Protection (No Redundant Re-runs)
    def test_h_completed_task_protection(self):
        mgr = ProjectManager.create(name="Idempotent Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="One-Time Setup")
        mgr.start_task(task.id)
        mgr.complete_task(task.id, output_result={"result": "done"})

        # Subsequent query for ready tasks should NOT include completed task
        ready = mgr.dag.get_ready_tasks()
        self.assertEqual(len(ready), 0)

    # I. Idempotency on Repeated Recovery
    def test_i_idempotency(self):
        mgr = ProjectManager.create(name="Idempotency Recovery", workspace_path=self.test_dir)
        task = mgr.create_task(title="Data Migration")
        mgr.start_task(task.id)
        mgr.create_checkpoint(
            task_id=task.id,
            state_snapshot={"stage": "step1"},
            completed_steps=[{"id": 1, "status": "passed"}],
            pending_steps=[{"id": 2, "status": "pending"}]
        )

        # Multiple recovery invocations should yield identical stable state
        rec1 = mgr.recover_project()
        rec2 = mgr.recover_project()
        self.assertEqual(rec1["classification"], rec2["classification"])
        self.assertEqual(mgr.project.status, ProjectStatus.ACTIVE)

    # J. Artifact Registry
    def test_j_artifact_registry(self):
        mgr = ProjectManager.create(name="Artifact Test", workspace_path=self.test_dir)
        code_file = self.test_dir / "calculator.py"
        code_file.write_text("def add(a, b): return a + b\n", encoding="utf-8")

        record = mgr.artifacts.register(
            rel_or_abs_path=code_file,
            task_id="task-001",
            project_id=mgr.project.project_id,
            artifact_type="code"
        )
        self.assertEqual(record.path, "calculator.py")
        self.assertTrue(len(record.checksum) == 64)  # Valid SHA-256
        self.assertEqual(record.status, "verified")

        fetched = mgr.artifacts.get_by_path("calculator.py")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.artifact_id, record.artifact_id)

    # K. Artifact Checksum Detection (Tamper Detection)
    def test_k_artifact_checksum(self):
        mgr = ProjectManager.create(name="Checksum Test", workspace_path=self.test_dir)
        f = self.test_dir / "secure.txt"
        f.write_text("Original content", encoding="utf-8")
        record = mgr.artifacts.register(f, "task-01", mgr.project.project_id, "document")

        # Verify clean
        valid, _, _ = mgr.artifacts.verify(record.artifact_id)
        self.assertTrue(valid)

        # Modify file externally
        f.write_text("Tampered content", encoding="utf-8")
        valid, current_cs, expected_cs = mgr.artifacts.verify(record.artifact_id)
        self.assertFalse(valid)
        self.assertNotEqual(current_cs, expected_cs)

    # L. Append-Only Event Journal
    def test_l_journal(self):
        mgr = ProjectManager.create(name="Journal Test", workspace_path=self.test_dir)
        mgr.journal.append("CUSTOM_EVENT_1", payload={"key": "val1"})
        mgr.journal.append("CUSTOM_EVENT_2", payload={"key": "val2"})

        events = mgr.journal.read_events()
        # Should contain PROJECT_CREATED + 2 custom events
        self.assertTrue(len(events) >= 3)
        event_types = [e.event_type for e in events]
        self.assertIn("PROJECT_CREATED", event_types)
        self.assertIn("CUSTOM_EVENT_1", event_types)
        self.assertIn("CUSTOM_EVENT_2", event_types)

    # M. Project Memory Isolation
    def test_m_project_memory(self):
        mgr = ProjectManager.create(name="Memory Isolation Test", workspace_path=self.test_dir)
        mgr.update_project_memory("architecture_pattern", "event-driven")
        mgr.update_project_memory("target_framework", "FastAPI")

        reloaded = ProjectManager.load(self.test_dir)
        self.assertEqual(reloaded.get_project_memory("architecture_pattern"), "event-driven")
        self.assertEqual(reloaded.get_project_memory("target_framework"), "FastAPI")

    # N. Pause Project
    def test_n_pause(self):
        mgr = ProjectManager.create(name="Pause Test", workspace_path=self.test_dir)
        mgr.pause_project("Waiting for API access")
        self.assertEqual(mgr.project.status, ProjectStatus.PAUSED)

        reloaded = ProjectManager.load(self.test_dir)
        self.assertEqual(reloaded.project.status, ProjectStatus.PAUSED)

    # O. Resume Paused Project
    def test_o_resume(self):
        mgr = ProjectManager.create(name="Resume Test", workspace_path=self.test_dir)
        mgr.pause_project()
        res = mgr.resume_project()
        self.assertEqual(res["status"], "ACTIVE")
        self.assertEqual(mgr.project.status, ProjectStatus.ACTIVE)

    # P. Cancel Project
    def test_p_cancel(self):
        mgr = ProjectManager.create(name="Cancel Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Future Task")
        mgr.cancel_project("No longer required")

        self.assertEqual(mgr.project.status, ProjectStatus.CANCELLED)
        self.assertEqual(mgr.dag.get_task(task.id).status, StepStatus.SKIPPED)

        # No tasks should be ready to execute
        self.assertEqual(len(mgr.dag.get_ready_tasks()), 0)

    # Q. Approval Persistence Across Restart
    def test_q_approval_persistence(self):
        mgr = ProjectManager.create(name="Approval Test", workspace_path=self.test_dir)
        ticket = {
            "ticket_id": "ticket-999",
            "action": "git_push_production",
            "risk_level": RiskLevel.HIGH.value,
            "required_phrase": "CONFIRM"
        }
        mgr.request_approval(ticket)
        self.assertEqual(mgr.project.status, ProjectStatus.WAITING_APPROVAL)

        # Simulate restart: reload
        reloaded = ProjectManager.load(self.test_dir)
        self.assertEqual(reloaded.project.status, ProjectStatus.WAITING_APPROVAL)
        self.assertIsNotNone(reloaded.pending_approval_ticket)
        self.assertEqual(reloaded.pending_approval_ticket["ticket_id"], "ticket-999")

        # Grant approval
        success = reloaded.grant_approval("ticket-999")
        self.assertTrue(success)
        self.assertEqual(reloaded.project.status, ProjectStatus.ACTIVE)
        self.assertIsNone(reloaded.pending_approval_ticket)

    # R. Budget Persistence Across Restart
    def test_r_budget_persistence(self):
        mgr = ProjectManager.create(
            name="Budget Test",
            workspace_path=self.test_dir,
            budget=ProjectBudget(max_steps=50, max_tool_calls=100)
        )
        mgr.project.budget.record(steps=15, tools=30, exec_time=45.2)
        mgr.save_manifest()

        reloaded = ProjectManager.load(self.test_dir)
        self.assertEqual(reloaded.project.budget.steps_taken, 15)
        self.assertEqual(reloaded.project.budget.tool_calls, 30)
        self.assertAlmostEqual(reloaded.project.budget.execution_time_seconds, 45.2, places=1)

    # S. Orphan Work Detection
    def test_s_orphan_detection(self):
        mgr = ProjectManager.create(name="Orphan Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Stale Operation")
        task.status = StepStatus.RUNNING
        # Set heartbeat 2 hours in the past
        two_hours_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=2)).isoformat()
        task.last_heartbeat = two_hours_ago
        task.updated_at = two_hours_ago
        mgr.dag.save()

        # Create a lingering .tmp file
        (mgr.zara_dir / "stale.tmp.123").write_text("orphaned data", encoding="utf-8")

        orphans = mgr.detect_orphaned_work()
        self.assertTrue(len(orphans) >= 2)
        orphan_types = [o["type"] for o in orphans]
        self.assertIn("interrupted_task", orphan_types)
        self.assertIn("stale_temp_file", orphan_types)

        # Clean temp files
        cleaned = mgr.cleanup_orphaned_work()
        self.assertEqual(cleaned, 1)

    # T. Watchdog Health Classification
    def test_t_watchdog(self):
        watchdog = TaskWatchdog(default_timeout_seconds=30.0, stall_threshold_seconds=10.0)
        task = PersistentTask(id="t1", project_id="p1", status=StepStatus.RUNNING)

        # Fresh timestamp -> HEALTHY
        task.last_heartbeat = datetime.datetime.now(datetime.timezone.utc).isoformat()
        self.assertEqual(watchdog.check_health(task), TaskHealth.HEALTHY)

        # Stalled timestamp (15 seconds ago) -> STALLED
        fifteen_secs_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=15)).isoformat()
        task.last_heartbeat = fifteen_secs_ago
        self.assertEqual(watchdog.check_health(task), TaskHealth.STALLED)

        # Timed out timestamp (45 seconds ago) -> TIMED_OUT
        forty_five_secs_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=45)).isoformat()
        task.last_heartbeat = forty_five_secs_ago
        self.assertEqual(watchdog.check_health(task), TaskHealth.TIMED_OUT)

    # U. Graceful Safe Shutdown
    def test_u_graceful_shutdown(self):
        mgr = ProjectManager.create(name="Shutdown Test", workspace_path=self.test_dir)
        mgr.project.status = ProjectStatus.ACTIVE
        mgr.shutdown(graceful=True)

        self.assertEqual(mgr.project.status, ProjectStatus.PAUSED)
        events = mgr.journal.read_events()
        event_types = [e.event_type for e in events]
        self.assertIn("SHUTDOWN_REQUESTED", event_types)
        self.assertIn("SHUTDOWN_COMPLETED", event_types)

    # V. Recovery Ambiguity (Requires Verification on Tampered State)
    def test_v_recovery_ambiguity(self):
        mgr = ProjectManager.create(name="Ambiguity Test", workspace_path=self.test_dir)
        task = mgr.create_task(title="Compile & Write")
        mgr.start_task(task.id)

        target = self.test_dir / "output.bin"
        target.write_text("initial output", encoding="utf-8")
        mgr.artifacts.register(target, task.id, mgr.project.project_id, "data")

        # Corrupt file externally
        target.write_text("corrupted output", encoding="utf-8")

        # Classify recovery
        classification, details = mgr.classify_recovery()
        self.assertEqual(classification, RecoveryClassification.REQUIRES_VERIFICATION)
        self.assertIn("checksum mismatch", details.get("reason", ""))

    # W. Resource Safety & Project Discovery
    def test_w_project_discovery_and_resource_safety(self):
        mgr1 = ProjectManager.create(name="Proj 1", workspace_path=self.test_dir / "proj1")
        mgr2 = ProjectManager.create(name="Proj 2", workspace_path=self.test_dir / "proj2")

        discovered = discover_projects(self.test_dir)
        self.assertEqual(len(discovered), 2)
        names = {p["name"] for p in discovered}
        self.assertEqual(names, {"Proj 1", "Proj 2"})


class TestPhase8IntegrationScenarios(unittest.TestCase):

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="zara_test_scenarios_")).resolve()
        self.engine = ZaraEngine(workspace_root=str(self.test_dir), enable_voice=False)

    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # Scenario 1: Long-running coding project with restart & resume
    def test_scenario_1_long_running_coding_project(self):
        mgr = ProjectManager.create(name="Math Suite", workspace_path=self.test_dir)
        self.engine.set_project_manager(mgr)

        # Task 1: Create arithmetic module
        calc_file = "calc.py"
        steps_1 = [
            PlanStep(
                id=1,
                title="Create calc.py",
                action_type=ActionType.TOOL,
                description="Write basic math operations",
                target=calc_file,
                tool="write_file",
                arguments={"path": calc_file, "content": "def multiply(a, b):\n    return a * b\n"},
                success_condition="File calc.py exists"
            )
        ]
        res1 = self.engine.run_task("Build multiply module", steps=steps_1)
        self.assertEqual(res1["status"], "COMPLETED")
        self.assertTrue((self.test_dir / calc_file).exists())

        # Check artifact registered
        art = mgr.artifacts.get_by_path(calc_file)
        self.assertIsNotNone(art)
        self.assertEqual(art.status, "verified")

        # Checkpoints exist
        ckpts = mgr.list_checkpoints()
        self.assertTrue(len(ckpts) > 0)

        # Simulate restart: reload engine with reloaded project manager
        reloaded_mgr = ProjectManager.load(self.test_dir)
        self.engine.set_project_manager(reloaded_mgr)

        # Task 2: Verify and run a test on the created file
        steps_2 = [
            PlanStep(
                id=2,
                title="Test multiply",
                action_type=ActionType.TOOL,
                description="Verify multiplication works",
                target="calc.py",
                tool="terminal_execute",
                arguments={"command": "python3 -c 'import calc; assert calc.multiply(3, 4) == 12'"},
                success_condition="Command exits with return code 0"
            )
        ]
        res2 = self.engine.run_task("Verify calculation", steps=steps_2)
        self.assertEqual(res2["status"], "COMPLETED")

    # Scenario 2: Interrupted task crash recovery
    def test_scenario_2_interrupted_task_recovery(self):
        mgr = ProjectManager.create(name="Crash Recovery Scenario", workspace_path=self.test_dir)
        t = mgr.create_task(title="Heavy Build", capability="coding")
        mgr.start_task(t.id)

        # Create checkpoint mid-task
        mgr.create_checkpoint(
            task_id=t.id,
            state_snapshot={"stage": "step1_done"},
            completed_steps=[{"id": 1, "title": "fetch deps", "status": "passed"}],
            pending_steps=[{"id": 2, "title": "compile binary", "status": "pending"}]
        )

        # Crash occurs (abrupt exit without complete)
        # Restart ZARA
        recovered_mgr = ProjectManager.load(self.test_dir)
        rec = recovered_mgr.recover_project()
        self.assertEqual(rec["classification"], RecoveryClassification.SAFE_RESUME.value)
        self.assertEqual(recovered_mgr.project.status, ProjectStatus.ACTIVE)

        # Complete the task
        recovered_mgr.complete_task(t.id, output_result={"binary": "dist/bin"})
        self.assertEqual(recovered_mgr.dag.get_task(t.id).status, StepStatus.PASSED)

    # Scenario 3: Research -> Evidence persistence -> Restart -> Coding
    def test_scenario_3_research_to_coding_pipeline(self):
        mgr = ProjectManager.create(name="Research and Code", workspace_path=self.test_dir)
        self.engine.set_project_manager(mgr)

        # Research task: collect source and notes
        research_steps = [
            PlanStep(
                id=1,
                title="Collect Source",
                action_type=ActionType.TOOL,
                description="Record documentation source",
                target="api_docs",
                tool="collect_source",
                arguments={
                    "source_id": "src_json_docs",
                    "url": "https://docs.python.org/3/library/json.html",
                    "title": "Python JSON Documentation",
                    "relevant_excerpt": "json.dumps serializes object to a JSON formatted str."
                },
                success_condition="Tool executed successfully with exit code 0"
            )
        ]
        res = self.engine.run_task("Research JSON serialization", steps=research_steps)
        self.assertEqual(res["status"], "COMPLETED")
        mgr.update_project_memory("best_practice", "Use json.dumps with indent=2")

        # Simulate process restart
        reloaded_mgr = ProjectManager.load(self.test_dir)
        self.assertEqual(reloaded_mgr.get_project_memory("best_practice"), "Use json.dumps with indent=2")

        # Resume coding with remembered context
        self.engine.set_project_manager(reloaded_mgr)
        coding_steps = [
            PlanStep(
                id=2,
                title="Write serializer",
                action_type=ActionType.TOOL,
                description="Write script using learned best practice",
                target="serializer.py",
                tool="write_file",
                arguments={"path": "serializer.py", "content": "import json\ndef dump(obj): return json.dumps(obj, indent=2)\n"},
                success_condition="File serializer.py exists"
            )
        ]
        res2 = self.engine.run_task("Implement serializer", steps=coding_steps)
        self.assertEqual(res2["status"], "COMPLETED")

    # Scenario 4: Approval persistence across process restart
    def test_scenario_4_approval_persistence_lifecycle(self):
        mgr = ProjectManager.create(name="Approval Lifecycle", workspace_path=self.test_dir)
        ticket = {
            "ticket_id": "confirm-deploy-prod",
            "action": "deploy_production",
            "risk_level": RiskLevel.CRITICAL.value,
            "required_phrase": "CONFIRM DEPLOY"
        }
        mgr.request_approval(ticket)
        self.assertEqual(mgr.project.status, ProjectStatus.WAITING_APPROVAL)

        # Process crashes or terminates
        reloaded_mgr = ProjectManager.load(self.test_dir)
        # Verify status did not silently revert to ACTIVE or bypass confirmation
        self.assertEqual(reloaded_mgr.project.status, ProjectStatus.WAITING_APPROVAL)
        self.assertEqual(reloaded_mgr.pending_approval_ticket["ticket_id"], "confirm-deploy-prod")

        # User explicitly grants approval
        reloaded_mgr.grant_approval("confirm-deploy-prod")
        self.assertEqual(reloaded_mgr.project.status, ProjectStatus.ACTIVE)

    # Scenario 5: Artifact integrity & change detection
    def test_scenario_5_artifact_integrity_verification(self):
        mgr = ProjectManager.create(name="Integrity Verification", workspace_path=self.test_dir)
        data_file = self.test_dir / "config.yaml"
        data_file.write_text("mode: strict\n", encoding="utf-8")
        art = mgr.artifacts.register(data_file, "task-01", mgr.project.project_id, "document")

        # Take snapshot
        snap1 = mgr.create_snapshot()
        self.assertIn("config.yaml", snap1.files)

        # Externally mutate file
        data_file.write_text("mode: permissive\n", encoding="utf-8")
        snap2 = mgr.create_snapshot()

        diff = snap2.diff(snap1)
        self.assertIn("config.yaml", diff["modified"])

        # Recovery should classify as REQUIRES_VERIFICATION
        t = mgr.create_task(title="Deploy Config")
        t.status = StepStatus.RUNNING
        mgr.dag.save()
        mgr.project.current_task_id = t.id
        mgr.save_manifest()

        classification, details = mgr.classify_recovery()
        self.assertEqual(classification, RecoveryClassification.REQUIRES_VERIFICATION)


if __name__ == "__main__":
    unittest.main()
