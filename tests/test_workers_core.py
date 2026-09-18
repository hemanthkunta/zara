"""
Tests for ZARA Phase 15: Worker Core Models, Specialist Types & Budgets.
Verifies Worker dataclass, states, capabilities, budgets, serialization,
WorkerResult, and Orchestrator state persistence.
"""
import unittest
import tempfile
import shutil
from pathlib import Path

from modules.workers import (
    Worker,
    WorkerType,
    WorkerStatus,
    WorkerFailureType,
    WorkerBudget,
    WorkerResult,
    map_task_to_worker_type,
    get_worker_capabilities,
    WorkstreamOrchestrator,
)
from modules.workspace import PersistentTask
from modules.resource_locking import ResourceManager


class TestWorkersCore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workers_dir = Path(self.temp_dir) / "workers"
        self.rm = ResourceManager()
        self.orchestrator = WorkstreamOrchestrator(
            engine=None,
            resource_manager=self.rm,
            workers_dir=self.workers_dir
        )

    def tearDown(self):
        self.orchestrator.close()
        self.rm.clear()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_worker_instantiation_defaults(self):
        """Verify Worker dataclass initializes with correct defaults."""
        worker = Worker(worker_id="wkr-01", task_id="task-01")
        self.assertEqual(worker.worker_id, "wkr-01")
        self.assertEqual(worker.task_id, "task-01")
        self.assertEqual(worker.worker_type, WorkerType.GENERAL)
        self.assertEqual(worker.status, WorkerStatus.CREATED)
        self.assertEqual(worker.confidence, 1.0)
        self.assertIsNotNone(worker.created_at)
        self.assertIsNone(worker.started_at)
        self.assertIsNone(worker.completed_at)

    def test_02_worker_budget_tracking_and_limits(self):
        """Verify WorkerBudget detects runtime, tool calls, and retries limits."""
        budget = WorkerBudget(max_runtime=10.0, max_tool_calls=5, max_retries=1)
        exceeded, reason = budget.is_exceeded()
        self.assertFalse(exceeded)

        # Runtime exceeded
        budget.current_runtime = 15.0
        exceeded, reason = budget.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("Runtime limit exceeded", reason)

        # Tool calls exceeded
        budget.current_runtime = 5.0
        budget.current_tool_calls = 6
        exceeded, reason = budget.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("Tool calls limit exceeded", reason)

        # Retries exceeded
        budget.current_tool_calls = 2
        budget.current_retries = 2
        exceeded, reason = budget.is_exceeded()
        self.assertTrue(exceeded)
        self.assertIn("Retries limit exceeded", reason)

    def test_03_worker_serialization_roundtrip(self):
        """Verify Worker to_dict and from_dict preserve all properties."""
        worker = Worker(
            worker_id="wkr-ser-01",
            task_id="task-ser-01",
            worker_type=WorkerType.CODING,
            project_id="proj-test",
            status=WorkerStatus.RUNNING,
            capabilities=["coding", "filesystem"],
            input={"code": "print('hello')"},
            output={"result": "success"},
            error=None,
            confidence=0.95,
            budget=WorkerBudget(max_runtime=60.0, current_runtime=12.5),
            parent_task_id="task-parent-01",
            required_resources=[{"type": "filesystem", "target": "main.py"}]
        )
        data = worker.to_dict()
        restored = Worker.from_dict(data)

        self.assertEqual(restored.worker_id, worker.worker_id)
        self.assertEqual(restored.worker_type, WorkerType.CODING)
        self.assertEqual(restored.status, WorkerStatus.RUNNING)
        self.assertEqual(restored.capabilities, ["coding", "filesystem"])
        self.assertEqual(restored.budget.current_runtime, 12.5)
        self.assertEqual(restored.required_resources[0]["target"], "main.py")

    def test_04_worker_budget_serialization(self):
        """Verify WorkerBudget serialization roundtrip."""
        budget = WorkerBudget(max_runtime=50.0, max_tool_calls=10, current_tool_calls=3)
        data = budget.to_dict()
        restored = WorkerBudget.from_dict(data)
        self.assertEqual(restored.max_runtime, 50.0)
        self.assertEqual(restored.current_tool_calls, 3)

    def test_05_worker_result_creation_and_serialization(self):
        """Verify WorkerResult dataclass and serialization."""
        res = WorkerResult(
            worker_id="wkr-res-01",
            task_id="task-res-01",
            status=WorkerStatus.COMPLETED,
            summary="Unit tests passed",
            artifacts=["test_out.txt"],
            evidence=[{"exit_code": 0}],
            confidence=0.98,
            verification={"method": "pytest", "passed": True}
        )
        data = res.to_dict()
        restored = WorkerResult.from_dict(data)
        self.assertEqual(restored.worker_id, "wkr-res-01")
        self.assertEqual(restored.status, WorkerStatus.COMPLETED)
        self.assertEqual(restored.artifacts, ["test_out.txt"])
        self.assertTrue(restored.verification["passed"])

    def test_06_map_task_to_worker_type_inference(self):
        """Verify map_task_to_worker_type accurately identifies specialist roles."""
        t_cyber = PersistentTask(id="1", project_id="p", title="Audit cybersecurity port scan", capability="cyber_lab")
        t_blender = PersistentTask(id="2", project_id="p", title="Render 3D object in Blender", capability="blender")
        t_research = PersistentTask(id="3", project_id="p", title="Search latest LLM papers", capability="research")
        t_code = PersistentTask(id="4", project_id="p", title="Implement FastAPI routes", capability="coding")
        t_test = PersistentTask(id="5", project_id="p", title="Run test suite with pytest", capability="testing")
        t_debug = PersistentTask(id="6", project_id="p", title="Fix syntax error traceback", capability="debugging")
        t_vision = PersistentTask(id="7", project_id="p", title="Capture screenshot and verify GUI", capability="vision")
        t_browser = PersistentTask(id="8", project_id="p", title="Browse documentation page", capability="browser")
        t_fs = PersistentTask(id="9", project_id="p", title="List files in directory", capability="filesystem")
        t_verify = PersistentTask(id="10", project_id="p", title="Perform formal verification", capability="verification")
        t_gen = PersistentTask(id="11", project_id="p", title="Do miscellaneous chore", capability="general")

        self.assertEqual(map_task_to_worker_type(t_cyber), WorkerType.CYBER_LAB)
        self.assertEqual(map_task_to_worker_type(t_blender), WorkerType.BLENDER)
        self.assertEqual(map_task_to_worker_type(t_research), WorkerType.RESEARCH)
        self.assertEqual(map_task_to_worker_type(t_code), WorkerType.CODING)
        self.assertEqual(map_task_to_worker_type(t_test), WorkerType.TESTING)
        self.assertEqual(map_task_to_worker_type(t_debug), WorkerType.DEBUGGING)
        self.assertEqual(map_task_to_worker_type(t_vision), WorkerType.VISION)
        self.assertEqual(map_task_to_worker_type(t_browser), WorkerType.BROWSER)
        self.assertEqual(map_task_to_worker_type(t_fs), WorkerType.FILESYSTEM)
        self.assertEqual(map_task_to_worker_type(t_verify), WorkerType.VERIFICATION)
        self.assertEqual(map_task_to_worker_type(t_gen), WorkerType.GENERAL)

    def test_07_worker_capabilities_mapping(self):
        """Verify get_worker_capabilities maps all 11 worker types to valid capabilities."""
        all_types = list(WorkerType)
        self.assertEqual(len(all_types), 11)
        for wt in all_types:
            caps = get_worker_capabilities(wt)
            self.assertIsInstance(caps, list)
            self.assertGreater(len(caps), 0)

    def test_08_orchestrator_create_worker(self):
        """Verify WorkstreamOrchestrator.create_worker registers worker and infers resources."""
        task = PersistentTask(
            id="task-create-01",
            project_id="proj-create-01",
            title="Compile binary",
            capability="coding",
            artifacts=["bin/app"]
        )
        worker = self.orchestrator.create_worker(task, project_id="proj-create-01")
        self.assertEqual(worker.task_id, "task-create-01")
        self.assertEqual(worker.worker_type, WorkerType.CODING)
        self.assertIn(worker.worker_id, self.orchestrator.workers)
        # Check inferred resource for artifact
        self.assertEqual(len(worker.required_resources), 1)
        self.assertEqual(worker.required_resources[0]["target"], "bin/app")

    def test_09_orchestrator_save_and_load_worker_state(self):
        """Verify save_worker_state and load_worker_state persist state to disk."""
        worker = Worker(
            worker_id="wkr-disk-01",
            task_id="task-disk-01",
            worker_type=WorkerType.RESEARCH,
            status=WorkerStatus.COMPLETED,
            output={"result": "Done"}
        )
        self.orchestrator.save_worker_state(worker)
        # Verify file exists on disk
        target_file = self.workers_dir / "wkr-disk-01.json"
        self.assertTrue(target_file.exists())

        loaded = self.orchestrator.load_worker_state("wkr-disk-01")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.worker_id, "wkr-disk-01")
        self.assertEqual(loaded.worker_type, WorkerType.RESEARCH)
        self.assertEqual(loaded.status, WorkerStatus.COMPLETED)

    def test_10_orchestrator_pause_and_resume_worker(self):
        """Verify pause_worker and resume_worker change worker states properly."""
        worker = Worker(worker_id="wkr-pause-01", task_id="t-1", status=WorkerStatus.RUNNING)
        self.orchestrator.workers[worker.worker_id] = worker

        # Pause
        ok = self.orchestrator.pause_worker("wkr-pause-01")
        self.assertTrue(ok)
        self.assertEqual(worker.status, WorkerStatus.WAITING)
        self.assertIn("wkr-pause-01", self.orchestrator._paused_workers)

        # Resume
        ok_resume = self.orchestrator.resume_worker("wkr-pause-01")
        self.assertTrue(ok_resume)
        self.assertEqual(worker.status, WorkerStatus.RUNNING)
        self.assertNotIn("wkr-pause-01", self.orchestrator._paused_workers)

    def test_11_orchestrator_cancel_worker(self):
        """Verify cancel_worker halts worker and transitions status to CANCELLED."""
        worker = Worker(worker_id="wkr-cancel-01", task_id="t-1", status=WorkerStatus.RUNNING)
        self.orchestrator.workers[worker.worker_id] = worker

        ok = self.orchestrator.cancel_worker("wkr-cancel-01")
        self.assertTrue(ok)
        self.assertEqual(worker.status, WorkerStatus.CANCELLED)
        self.assertIn("wkr-cancel-01", self.orchestrator._cancelled_workers)

    def test_12_orchestrator_cancel_all(self):
        """Verify cancel_all cancels every registered worker."""
        w1 = Worker(worker_id="wkr-all-1", task_id="t-1", status=WorkerStatus.RUNNING)
        w2 = Worker(worker_id="wkr-all-2", task_id="t-2", status=WorkerStatus.QUEUED)
        self.orchestrator.workers[w1.worker_id] = w1
        self.orchestrator.workers[w2.worker_id] = w2

        cancelled_count = self.orchestrator.cancel_all()
        self.assertEqual(cancelled_count, 2)
        self.assertEqual(w1.status, WorkerStatus.CANCELLED)
        self.assertEqual(w2.status, WorkerStatus.CANCELLED)

    def test_13_orchestrator_list_workers_filters(self):
        """Verify list_workers supports project_id and status filters."""
        w1 = Worker(worker_id="w1", task_id="t1", project_id="p-1", status=WorkerStatus.RUNNING)
        w2 = Worker(worker_id="w2", task_id="t2", project_id="p-1", status=WorkerStatus.COMPLETED)
        w3 = Worker(worker_id="w3", task_id="t3", project_id="p-2", status=WorkerStatus.RUNNING)
        self.orchestrator.workers = {"w1": w1, "w2": w2, "w3": w3}

        # Filter by project
        p1_workers = self.orchestrator.list_workers(project_id="p-1")
        self.assertEqual(len(p1_workers), 2)

        # Filter by status
        running_workers = self.orchestrator.list_workers(status=WorkerStatus.RUNNING)
        self.assertEqual(len(running_workers), 2)

        # Both filters
        p1_completed = self.orchestrator.list_workers(project_id="p-1", status=WorkerStatus.COMPLETED)
        self.assertEqual(len(p1_completed), 1)
        self.assertEqual(p1_completed[0].worker_id, "w2")

    def test_14_orchestrator_metrics(self):
        """Verify get_metrics calculates counts, runtimes, and success rate accurately."""
        w1 = Worker(worker_id="w1", task_id="t1", status=WorkerStatus.COMPLETED)
        w1.budget.current_runtime = 10.0
        w2 = Worker(worker_id="w2", task_id="t2", status=WorkerStatus.FAILED)
        w2.budget.current_runtime = 20.0
        w3 = Worker(worker_id="w3", task_id="t3", status=WorkerStatus.RUNNING)
        self.orchestrator.workers = {"w1": w1, "w2": w2, "w3": w3}

        metrics = self.orchestrator.get_metrics()
        self.assertEqual(metrics["total_workers"], 3)
        self.assertEqual(metrics["active_workers"], 1)
        self.assertEqual(metrics["completed_workers"], 1)
        self.assertEqual(metrics["failed_workers"], 1)
        self.assertEqual(metrics["average_runtime_seconds"], 15.0)
        self.assertEqual(metrics["success_rate"], 0.5)

    def test_15_empty_metrics(self):
        """Verify metrics on fresh orchestrator return zeros gracefully."""
        metrics = self.orchestrator.get_metrics()
        self.assertEqual(metrics["total_workers"], 0)
        self.assertEqual(metrics["active_workers"], 0)
        self.assertEqual(metrics["success_rate"], 1.0)
        self.assertEqual(metrics["average_runtime_seconds"], 0.0)

    def test_16_nonexistent_worker_lookup(self):
        """Verify querying nonexistent worker returns None without raising."""
        w = self.orchestrator.get_worker("does-not-exist")
        self.assertIsNone(w)

    def test_17_invalid_pause_resume_handling(self):
        """Verify pausing or resuming nonexistent worker returns False."""
        self.assertFalse(self.orchestrator.pause_worker("ghost-worker"))
        self.assertFalse(self.orchestrator.resume_worker("ghost-worker"))
        self.assertFalse(self.orchestrator.cancel_worker("ghost-worker"))

    def test_18_worker_failure_types_defined(self):
        """Verify all WorkerFailureType enums are present."""
        expected = [
            "transient", "dependency_failure", "resource_conflict",
            "tool_failure", "code_failure", "safety_block",
            "authorization_failure", "budget_exceeded", "unknown"
        ]
        actual = [f.value for f in WorkerFailureType]
        for exp in expected:
            self.assertIn(exp, actual)


if __name__ == "__main__":
    unittest.main()
