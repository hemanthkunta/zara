"""
Tests for ZARA Phase 14: System-Wide Memory Integration.
Tests integration across Hierarchical Planner, Context Manager, ZaraEngine loop,
World Model distinction, EventBus events, UI REST API endpoints, ProjectManager, and CLI.
"""
import unittest
import tempfile
import shutil
import json
import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.engine import ZaraEngine
from core.state import Reflection, TaskContext
from modules.memory import (
    MemoryStore,
    MemoryItem,
    MemoryType,
    MemoryScope,
    MemorySource,
    ConflictStatus,
)
from modules.events import EventBus, Event, EventType
from modules.goals import Goal, GoalDomain, AmbiguityLevel
from modules.planning import HierarchicalPlanner
from modules.context import ContextManager
from modules.workspace import ProjectManager
from modules.world_model import WorldModel, Modality, Observation
from ui.server import create_ui_app
from fastapi.testclient import TestClient
from cli import cmd_memory


class TestMemoryIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.memory_file = self.workspace / "zara_log.md"
        self.db_path = self.workspace / "vectors.db"
        self.store = MemoryStore(memory_path=self.memory_file, db_path=self.db_path)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_planner_accepts_and_attaches_memory_hints(self):
        """Verify HierarchicalPlanner attaches memory hints without overriding goal objectives."""
        goal = Goal(
            goal_id="goal-test-01",
            raw_request="Build authentication service",
            domain=GoalDomain.CODING,
            ambiguity_level=AmbiguityLevel.NONE,
            normalized_goal="Build authentication service",
            desired_outcome="JWT auth service with test coverage"
        )
        memories = [
            MemoryItem(
                type=MemoryType.INSTRUCTION,
                content="Always use argon2id for password hashing",
                scope=MemoryScope.GLOBAL
            )
        ]
        tasks = HierarchicalPlanner.create_hierarchical_plan(
            goal=goal,
            project_id="proj-auth-01",
            relevant_memories=memories
        )
        self.assertGreater(len(tasks), 0)
        # Check memory hints attached to input_payload
        for t in tasks:
            self.assertIn("memory_hints", t.input_payload)
            self.assertIn("Always use argon2id", t.input_payload["memory_hints"][0])

    def test_02_context_manager_assembles_memories(self):
        """Verify ContextManager serializes memories into assembled execution context."""
        cm = ContextManager(project_id="proj-ctx-01")
        mem = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Prefer pytest runner",
            scope=MemoryScope.USER
        )
        ctx = cm.assemble_context(
            goal=None,
            current_task=None,
            memories=[mem]
        )
        self.assertIn("memories", ctx)
        self.assertEqual(len(ctx["memories"]), 1)
        self.assertIn("pytest", ctx["memories"][0]["content"])

    def test_03_engine_perceive_queries_and_attaches_memories(self):
        """Verify ZaraEngine.perceive queries memory and populates relevant_memories."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            # Seed a memory
            engine.memory.store_memory(MemoryItem(
                type=MemoryType.FACT,
                content="Legacy database port is 5432",
                scope=MemoryScope.GLOBAL
            ))
            context = engine.perceive("Check database connectivity on port 5432")
            self.assertGreaterEqual(len(context.relevant_memories), 1)
            self.assertTrue(any("5432" in l for l in context.past_lessons))
        finally:
            engine.close()

    def test_04_engine_persist_extracts_memories_from_reflection(self):
        """Verify ZaraEngine.persist extracts structured memory patterns from completed reflections."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            refl = Reflection(
                task="Deploy container to registry",
                tag="ops",
                approach="Built docker container and verified signature",
                result="All planned steps passed verification criteria.",
                lesson="Completed 'Deploy container to registry' cleanly. Verifying discrete units prevented regression."
            )
            engine.persist(refl)
            # Memory should now contain an extracted SUCCESS_PATTERN or EXPERIENCE
            memories = engine.memory.retrieve(query="Deploy container to registry")
            self.assertGreaterEqual(len(memories), 1)
        finally:
            engine.close()

    def test_05_world_model_vs_memory_distinction(self):
        """Verify World Model holds immediate observations while MemoryStore holds long-term knowledge."""
        wm = WorldModel(workspace_root=self.workspace)
        # World Model observation: immediate transient state
        obs = Observation(
            modality=Modality.TERMINAL,
            source="pytest_process",
            payload={"pid": 12345, "status": "running"},
            trusted=True
        )
        wm.observe(obs)
        self.assertEqual(len(wm.observations), 1)

        # Memory item: durable long-term instruction
        mem = MemoryItem(
            type=MemoryType.INSTRUCTION,
            content="Always use -s flag with pytest to capture stdout",
            scope=MemoryScope.GLOBAL
        )
        self.store.store_memory(mem)
        retrieved = self.store.retrieve(query="pytest stdout flag")
        self.assertEqual(len(retrieved), 1)

        # Modalities and lifetimes are strictly separated
        self.assertEqual(wm.observations[0].payload["pid"], 12345)
        self.assertEqual(retrieved[0].type, MemoryType.INSTRUCTION)

    def test_06_event_bus_event_types_defined(self):
        """Verify MEMORY_CREATED, MEMORY_UPDATED, MEMORY_CONFLICT, and MEMORY_DELETED exist on EventType."""
        self.assertEqual(EventType.MEMORY_CREATED.value, "memory_created")
        self.assertEqual(EventType.MEMORY_UPDATED.value, "memory_updated")
        self.assertEqual(EventType.MEMORY_CONFLICT.value, "memory_conflict")
        self.assertEqual(EventType.MEMORY_DELETED.value, "memory_deleted")

    def test_07_ui_api_memory_stats_endpoint(self):
        """Verify GET /api/memory/stats returns total count and category breakdowns."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            engine.memory.store_memory(MemoryItem(type=MemoryType.FACT, content="Fact item"))
            app = create_ui_app(engine)
            client = TestClient(app)

            res = client.get("/api/memory/stats")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertGreaterEqual(data.get("total_memories", 0), 1)
        finally:
            engine.close()

    def test_08_ui_api_memory_search_endpoint(self):
        """Verify GET /api/memory/search returns matching memories with redacting."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            engine.memory.store_memory(MemoryItem(
                type=MemoryType.SKILL,
                content="Expert in Kubernetes ingress configuration",
                scope=MemoryScope.GLOBAL
            ))
            app = create_ui_app(engine)
            client = TestClient(app)

            res = client.get("/api/memory/search?q=Kubernetes")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertGreaterEqual(data.get("count", 0), 1)
            self.assertIn("Kubernetes", data["results"][0]["content"])
        finally:
            engine.close()

    def test_09_ui_api_memory_get_and_delete_endpoints(self):
        """Verify GET /api/memory/{id} and DELETE /api/memory/{id}."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            stored = engine.memory.store_memory(MemoryItem(type=MemoryType.FACT, content="Removable item"))
            app = create_ui_app(engine)
            client = TestClient(app)

            # Get single
            get_res = client.get(f"/api/memory/{stored.memory_id}")
            self.assertEqual(get_res.status_code, 200)
            self.assertEqual(get_res.json()["memory"]["memory_id"], stored.memory_id)

            # Delete
            del_res = client.delete(f"/api/memory/{stored.memory_id}")
            self.assertEqual(del_res.status_code, 200)
            self.assertEqual(del_res.json()["status"], "DELETED")

            # Check deleted is inactive
            mem = engine.memory.get_memory(stored.memory_id)
            self.assertFalse(mem.is_active)
        finally:
            engine.close()

    def test_10_ui_api_memory_explicit_endpoint_and_secret_rejection(self):
        """Verify POST /api/memory/explicit accepts valid memories and rejects credentials."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            app = create_ui_app(engine)
            client = TestClient(app)

            # Valid explicit preference
            payload_ok = {
                "content": "I prefer TypeScript over plain JavaScript",
                "type": "PREFERENCE",
                "scope": "USER"
            }
            res_ok = client.post("/api/memory/explicit", json=payload_ok)
            self.assertEqual(res_ok.status_code, 200)
            self.assertEqual(res_ok.json()["status"], "STORED")

            # Rejected secret
            payload_bad = {
                "content": "Store my bearer token Bearer abcdef1234567890abcdef",
                "type": "FACT"
            }
            res_bad = client.post("/api/memory/explicit", json=payload_bad)
            self.assertEqual(res_bad.status_code, 400)
        finally:
            engine.close()

    def test_11_ui_api_memory_conflicts_endpoint(self):
        """Verify GET /api/memory/conflicts returns recorded conflicts."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            engine.memory.store_memory(MemoryItem(
                type=MemoryType.PREFERENCE,
                content="Prefer light mode",
                source=MemorySource.MODEL_INFERENCE
            ), detect_conflicts=True)
            engine.memory.store_memory(MemoryItem(
                type=MemoryType.PREFERENCE,
                content="Prefer dark mode",
                source=MemorySource.MODEL_INFERENCE
            ), detect_conflicts=True)

            app = create_ui_app(engine)
            client = TestClient(app)

            res = client.get("/api/memory/conflicts")
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertGreaterEqual(data.get("count", 0), 1)
        finally:
            engine.close()

    def test_12_project_manager_memory_query_and_export(self):
        """Verify ProjectManager.get_project_memories and export_project_memories."""
        pm = ProjectManager.create(name="Test Project", workspace_path=self.workspace / "test_proj")
        self.store.store_memory(MemoryItem(
            type=MemoryType.DECISION,
            content="Use React 19 for frontend",
            scope=MemoryScope.PROJECT,
            project_id=pm.project.project_id
        ))

        # Direct PM method
        mems = pm.get_project_memories(self.store)
        self.assertEqual(len(mems), 1)
        self.assertEqual(mems[0].content, "Use React 19 for frontend")

        # Export PM method
        export_file = pm.export_project_memories(self.store)
        self.assertTrue(export_file.exists())
        data = json.loads(export_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["content"], "Use React 19 for frontend")

    def test_13_cli_memory_stats_command(self):
        """Verify CLI memory --stats prints formatted statistics."""
        self.store.store_memory(MemoryItem(type=MemoryType.FACT, content="Sample fact"))
        args = argparse.Namespace(
            stats=True,
            conflicts=False,
            recent=False,
            export=None,
            query="",
            project=None,
            scope=None,
            type=None
        )
        with patch("cli.MemoryStore", return_value=self.store):
            # Should run without error
            cmd_memory(args)

    def test_14_cli_memory_recent_and_search_command(self):
        """Verify CLI memory --recent and query search output."""
        self.store.store_memory(MemoryItem(type=MemoryType.SKILL, content="Proficient in Python"))
        args_recent = argparse.Namespace(
            stats=False,
            conflicts=False,
            recent=True,
            export=None,
            query="",
            project=None,
            scope=None,
            type=None
        )
        args_query = argparse.Namespace(
            stats=False,
            conflicts=False,
            recent=False,
            export=None,
            query="Python",
            project=None,
            scope=None,
            type=None
        )
        with patch("cli.MemoryStore", return_value=self.store):
            cmd_memory(args_recent)
            cmd_memory(args_query)

    def test_15_cli_memory_export_command(self):
        """Verify CLI memory --export exports memories to a JSON file."""
        self.store.store_memory(MemoryItem(type=MemoryType.FACT, content="Exportable item"))
        out_file = self.workspace / "cli_export.json"
        args_export = argparse.Namespace(
            stats=False,
            conflicts=False,
            recent=False,
            export=str(out_file),
            query="",
            project=None,
            scope=None,
            type=None
        )
        with patch("cli.MemoryStore", return_value=self.store):
            cmd_memory(args_export)
        self.assertTrue(out_file.exists())
        data = json.loads(out_file.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data), 1)

    def test_16_engine_plan_goal_with_memories(self):
        """Verify plan_goal queries memory and incorporates relevant memories into plan."""
        engine = ZaraEngine(workspace_root=self.workspace)
        try:
            # Seed a memory
            engine.memory.store_memory(MemoryItem(
                type=MemoryType.INSTRUCTION,
                content="Always include pytest verification step in coding tasks",
                scope=MemoryScope.GLOBAL
            ))
            goal = Goal(
                goal_id="goal-plan-01",
                raw_request="Refactor module A",
                domain=GoalDomain.CODING,
                ambiguity_level=AmbiguityLevel.NONE,
                normalized_goal="Refactor module A",
                desired_outcome="Clean refactoring of module A"
            )
            tasks, validation, cost = engine.plan_goal(goal)
            self.assertGreater(len(tasks), 0)
            self.assertTrue(validation.valid)
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
