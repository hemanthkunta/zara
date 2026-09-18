"""
Tests for ZARA Phase 15: Parallel Workstream Orchestration & System-Wide Integration.
Verifies concurrent DAG execution, dependency barriers, cyber scope isolation,
concurrency limits, failure classification, EventBus notifications, UI REST endpoints, and CLI.
"""
import unittest
import tempfile
import shutil
import argparse
from pathlib import Path
from unittest.mock import patch

from core.engine import ZaraEngine
from core.state import StepStatus
from modules.workspace import PersistentTask, PersistentDAG
from modules.resource_locking import ResourceManager, ResourceType, AccessMode
from modules.workers import (
    Worker,
    WorkerType,
    WorkerStatus,
    WorkerResult,
    WorkstreamOrchestrator,
)
from modules.events import EventBus, EventType
from ui.server import create_ui_app
from fastapi.testclient import TestClient
from cli import cmd_workers


class TestParallelOrchestration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.engine = ZaraEngine(workspace_root=self.workspace)
        self.rm = self.engine.resource_manager
        self.orchestrator = self.engine.workstream_orchestrator

    def tearDown(self):
        self.engine.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_execute_parallel_independent_tasks(self):
        """Verify two independent tasks execute concurrently and both succeed."""
        t1 = PersistentTask(id="task-indep-1", project_id="p-1", title="Research topic A", capability="research")
        t2 = PersistentTask(id="task-indep-2", project_id="p-1", title="Implement module B", capability="coding")

        results = self.orchestrator.execute_parallel_batch([t1, t2], project_id="p-1")
        self.assertEqual(len(results), 2)
        self.assertEqual(results["task-indep-1"].status, WorkerStatus.COMPLETED)
        self.assertEqual(results["task-indep-2"].status, WorkerStatus.COMPLETED)

    def test_02_dependency_barrier_blocks_child_task(self):
        """Verify child task is BLOCKED until all dependencies complete."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="proj-barrier")

        t_parent = PersistentTask(id="t-parent", project_id="proj-barrier", title="Compile core", status=StepStatus.PENDING)
        t_child = PersistentTask(id="t-child", project_id="proj-barrier", title="Deploy app", dependencies=["t-parent"], status=StepStatus.PENDING)
        dag.add_task(t_parent)
        dag.add_task(t_child)

        ready = dag.get_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].id, "t-parent")

        # Directly testing runnability check for child before parent passes
        w_child = self.orchestrator.create_worker(t_child, project_id="proj-barrier")
        runnable, reason = self.orchestrator.evaluate_task_runnability(t_child, dag, w_child)
        self.assertFalse(runnable)
        self.assertIn("not completed", reason)

    def test_03_dependency_unblocked_after_parent_passes(self):
        """Verify child task becomes runnable once parent task is updated to PASSED."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="proj-unblock")

        t_parent = PersistentTask(id="t-parent", project_id="proj-unblock", title="Build backend", status=StepStatus.PENDING)
        t_child = PersistentTask(id="t-child", project_id="proj-unblock", title="Run integration tests", dependencies=["t-parent"], status=StepStatus.PENDING)
        dag.add_task(t_parent)
        dag.add_task(t_child)

        # Mark parent passed
        dag.update_task_status("t-parent", StepStatus.PASSED)
        ready = dag.get_ready_tasks()
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].id, "t-child")

        w_child = self.orchestrator.create_worker(t_child, project_id="proj-unblock")
        runnable, reason = self.orchestrator.evaluate_task_runnability(t_child, dag, w_child)
        self.assertTrue(runnable)
        self.assertIsNone(reason)

    def test_04_concurrency_limit_enforced(self):
        """Verify parallel batch respects max_parallel_workers limit."""
        custom_orch = WorkstreamOrchestrator(
            engine=self.engine,
            resource_manager=self.rm,
            max_parallel_workers=2
        )
        tasks = [
            PersistentTask(id=f"t-{i}", project_id="p-lim", title=f"Worker chore {i}", capability="general")
            for i in range(4)
        ]
        results = custom_orch.execute_parallel_batch(tasks, project_id="p-lim")
        self.assertEqual(len(results), 4)
        self.assertTrue(all(r.status == WorkerStatus.COMPLETED for r in results.values()))
        custom_orch.close()

    def test_05_cyber_security_scope_validation_per_worker(self):
        """Verify each cyber worker validates target against CyberLabScope individually."""
        t_auth = PersistentTask(
            id="t-cyber-auth",
            project_id="p-cyber",
            title="Scan localhost",
            capability="cyber_lab",
            input_payload={"target": "127.0.0.1"}
        )
        w_auth = self.orchestrator.create_worker(t_auth, project_id="p-cyber")
        res_auth = self.orchestrator.execute_worker(w_auth, t_auth)
        self.assertEqual(res_auth.status, WorkerStatus.COMPLETED)
        self.assertIn("Cyber security scan completed", res_auth.summary)

    def test_06_cyber_security_unauthorized_target_rejected(self):
        """Verify cyber worker targeting unauthorized host is rejected with failure."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="p-cyber-bad")

        t_unauth = PersistentTask(
            id="t-cyber-unauth",
            project_id="p-cyber-bad",
            title="Scan malicious host",
            capability="cyber_lab",
            input_payload={"target": "unauthorized-external-domain.com"}
        )
        dag.add_task(t_unauth)
        w_unauth = self.orchestrator.create_worker(t_unauth, project_id="p-cyber-bad")

        runnable, reason = self.orchestrator.evaluate_task_runnability(t_unauth, dag, w_unauth)
        self.assertFalse(runnable)
        self.assertIn("Security scope violation", reason)

    def test_07_resource_lock_conflict_prevents_runnability(self):
        """Verify worker is blocked when another worker holds an exclusive lock on its resource."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="p-lock")

        # Worker 1 acquires exclusive lock on common.py
        self.rm.acquire(ResourceType.FILESYSTEM, "common.py", worker_id="wkr-first", mode=AccessMode.EXCLUSIVE)

        t2 = PersistentTask(
            id="t-conflict",
            project_id="p-lock",
            title="Write to common.py",
            artifacts=["common.py"]
        )
        dag.add_task(t2)
        w2 = self.orchestrator.create_worker(t2, project_id="p-lock")

        runnable, reason = self.orchestrator.evaluate_task_runnability(t2, dag, w2)
        self.assertFalse(runnable)
        self.assertIn("Resource conflict", reason)

    def test_08_event_bus_notifications_on_worker_lifecycle(self):
        """Verify events emitted on worker created, started, completed, and resource released."""
        received_events = []
        def handler(event):
            received_events.append(event.type)

        self.engine.event_bus.subscribe(EventType.WORKER_CREATED, handler)
        self.engine.event_bus.subscribe(EventType.WORKER_STARTED, handler)
        self.engine.event_bus.subscribe(EventType.WORKER_COMPLETED, handler)
        self.engine.event_bus.subscribe(EventType.WORKER_RESOURCE_RELEASED, handler)

        t = PersistentTask(id="t-ev", project_id="p-ev", title="Chore with events", capability="general")
        w = self.orchestrator.create_worker(t, project_id="p-ev")
        self.orchestrator.execute_worker(w, t)

        self.assertIn(EventType.WORKER_CREATED, received_events)
        self.assertIn(EventType.WORKER_STARTED, received_events)
        self.assertIn(EventType.WORKER_COMPLETED, received_events)
        self.assertIn(EventType.WORKER_RESOURCE_RELEASED, received_events)

    def test_09_full_dag_execution_to_completion(self):
        """Verify run_dag_to_completion executes sequential and parallel branches cleanly."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="p-full")

        # A -> B, A -> C, (B, C) -> D
        ta = PersistentTask(id="A", project_id="p-full", title="Analyze specs", capability="general")
        tb = PersistentTask(id="B", project_id="p-full", title="Build backend", capability="coding", dependencies=["A"])
        tc = PersistentTask(id="C", project_id="p-full", title="Build frontend", capability="coding", dependencies=["A"])
        td = PersistentTask(id="D", project_id="p-full", title="Verify integration", capability="verification", dependencies=["B", "C"])

        dag.add_task(ta)
        dag.add_task(tb)
        dag.add_task(tc)
        dag.add_task(td)

        summary = self.orchestrator.run_dag_to_completion(dag, project_id="p-full")
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertEqual(summary["tasks_passed"], 4)
        self.assertEqual(summary["tasks_total"], 4)

    def test_10_partial_failure_halts_dependent_branch(self):
        """Verify failure in one branch halts downstream child but independent tasks finish."""
        tasks_file = self.workspace / "tasks.json"
        dag = PersistentDAG(tasks_file=tasks_file, project_id="p-part")

        # T1 succeeds, T2 fails, T3 depends on T2
        t1 = PersistentTask(id="t1", project_id="p-part", title="Independent chore", capability="general")
        t2 = PersistentTask(
            id="t2",
            project_id="p-part",
            title="Unauthorized cyber scan",
            capability="cyber_lab",
            input_payload={"target": "unauthorized-domain.com"}
        )
        t3 = PersistentTask(id="t3", project_id="p-part", title="Downstream task", dependencies=["t2"])

        dag.add_task(t1)
        dag.add_task(t2)
        dag.add_task(t3)

        summary = self.orchestrator.run_dag_to_completion(dag, project_id="p-part")
        self.assertEqual(summary["status"], "PARTIALLY_COMPLETED")
        self.assertEqual(dag.get_task("t1").status, StepStatus.PASSED)
        self.assertEqual(dag.get_task("t2").status, StepStatus.FAILED)
        self.assertEqual(dag.get_task("t3").status, StepStatus.PENDING)

    def test_11_engine_execute_plan_parallel_method(self):
        """Verify ZaraEngine.execute_plan_parallel wraps workstream execution properly."""
        t1 = PersistentTask(id="t-p1", project_id="p-wrap", title="Task 1", capability="research")
        t2 = PersistentTask(id="t-p2", project_id="p-wrap", title="Task 2", capability="coding")

        res = self.engine.execute_plan_parallel([t1, t2], project_id="p-wrap")
        self.assertEqual(res["status"], "COMPLETED")
        self.assertEqual(res["tasks_passed"], 2)

    def test_12_ui_api_get_workers_endpoint(self):
        """Verify GET /api/workers returns registered workers and metrics."""
        t = PersistentTask(id="t-ui-1", project_id="p-ui", title="UI test task")
        self.orchestrator.create_worker(t, project_id="p-ui")

        app = create_ui_app(self.engine)
        client = TestClient(app)

        res = client.get("/api/workers")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(len(data.get("workers", [])), 1)
        self.assertIn("metrics", data)

    def test_13_ui_api_get_worker_locks_endpoint(self):
        """Verify GET /api/workers/locks returns active resource locks."""
        self.rm.acquire(ResourceType.FILESYSTEM, "test_ui_file.py", worker_id="wkr-ui-locks")
        app = create_ui_app(self.engine)
        client = TestClient(app)

        res = client.get("/api/workers/locks")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data.get("count", 0), 1)

    def test_14_ui_api_get_workers_graph_endpoint(self):
        """Verify GET /api/workers/graph returns task DAG edges and workers."""
        app = create_ui_app(self.engine)
        client = TestClient(app)

        res = client.get("/api/workers/graph")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("tasks", data)
        self.assertIn("workers", data)
        self.assertIn("edges", data)

    def test_15_ui_api_get_single_worker_and_404(self):
        """Verify GET /api/workers/{id} returns details and 404 for missing worker."""
        t = PersistentTask(id="t-single", project_id="p-single", title="Single task")
        w = self.orchestrator.create_worker(t, project_id="p-single")

        app = create_ui_app(self.engine)
        client = TestClient(app)

        res = client.get(f"/api/workers/{w.worker_id}")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["worker"]["worker_id"], w.worker_id)

        res_missing = client.get("/api/workers/missing-worker-id")
        self.assertEqual(res_missing.status_code, 404)

    def test_16_ui_api_pause_resume_cancel_endpoints(self):
        """Verify POST /api/workers/{id}/pause, resume, and cancel."""
        t = PersistentTask(id="t-ctl", project_id="p-ctl", title="Control task")
        w = self.orchestrator.create_worker(t, project_id="p-ctl")
        w.status = WorkerStatus.RUNNING

        app = create_ui_app(self.engine)
        client = TestClient(app)

        # Pause
        p_res = client.post(f"/api/workers/{w.worker_id}/pause")
        self.assertEqual(p_res.status_code, 200)
        self.assertEqual(p_res.json()["status"], "PAUSED")

        # Resume
        r_res = client.post(f"/api/workers/{w.worker_id}/resume")
        self.assertEqual(r_res.status_code, 200)
        self.assertEqual(r_res.json()["status"], "RESUMED")

        # Cancel
        c_res = client.post(f"/api/workers/{w.worker_id}/cancel")
        self.assertEqual(c_res.status_code, 200)
        self.assertEqual(c_res.json()["status"], "CANCELLED")

    def test_17_cli_cmd_workers_status(self):
        """Verify CLI cmd_workers with status action executes cleanly."""
        args = argparse.Namespace(workers_action="status")
        with patch("cli.ZaraEngine", return_value=self.engine):
            cmd_workers(args)

    def test_18_cli_cmd_workers_list_and_locks(self):
        """Verify CLI cmd_workers with list and locks actions."""
        t = PersistentTask(id="t-cli", project_id="p-cli", title="CLI task")
        self.orchestrator.create_worker(t, project_id="p-cli")
        self.rm.acquire(ResourceType.FILESYSTEM, "cli_locked.py", worker_id="wkr-cli")

        args_list = argparse.Namespace(workers_action="list", project=None, status=None)
        args_locks = argparse.Namespace(workers_action="locks")

        with patch("cli.ZaraEngine", return_value=self.engine):
            cmd_workers(args_list)
            cmd_workers(args_locks)

    def test_19_cli_cmd_workers_inspect_and_cancel(self):
        """Verify CLI cmd_workers inspect and cancel subcommands."""
        t = PersistentTask(id="t-cli-ctl", project_id="p-cli", title="Inspect chore")
        w = self.orchestrator.create_worker(t, project_id="p-cli")

        args_inspect = argparse.Namespace(workers_action="inspect", worker_id=w.worker_id)
        args_cancel = argparse.Namespace(workers_action="cancel", worker_id=w.worker_id)

        with patch("cli.ZaraEngine", return_value=self.engine):
            cmd_workers(args_inspect)
            cmd_workers(args_cancel)

    def test_20_clean_shutdown_and_no_resource_warnings(self):
        """Verify orchestrator and resource manager close without open resources."""
        self.orchestrator.close()
        self.assertEqual(len(self.rm.get_locks()), 0)


if __name__ == "__main__":
    unittest.main()
