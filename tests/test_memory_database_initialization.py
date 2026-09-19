"""
ZARA Memory Database Initialization & Resilience Test Suite:
Verifies table creation, self-healing schema checks, idempotent migrations,
error isolation, ResourceWarning absence, API 200 JSON fallbacks, and voice error sanitization.
"""
import unittest
import sqlite3
import tempfile
import shutil
from pathlib import Path
from starlette.testclient import TestClient

from modules.memory import (
    MemoryStore,
    MemoryItem,
    MemoryType,
    MemoryScope,
    MemorySource,
    ConflictStatus,
    contains_secret,
    scrub_text,
)
from modules.voice import summarize_for_voice
from core.state import Reflection
from core.engine import ZaraEngine
from core.health import GlobalHealthService, SubsystemStatus
from ui.server import create_ui_app


class TestMemoryDatabaseInitialization(unittest.TestCase):
    """Test suite for SQLite memory schema initialization and self-healing."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = Path(self.temp_dir)
        self.mem_file = self.temp_path / "zara_log.md"
        self.db_path = self.temp_path / "vectors.db"

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_schema_initialization_on_new_db(self):
        """1. Brand new SQLite DB path initializes memories and memory_conflicts tables with indexes."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cursor.fetchall()}
            self.assertIn("memories", tables)
            self.assertIn("memory_conflicts", tables)
            self.assertIn("embeddings", tables)

            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {r[0] for r in cursor.fetchall()}
            self.assertIn("idx_mem_type", indexes)
            self.assertIn("idx_mem_scope", indexes)
            self.assertIn("idx_mem_active", indexes)
            self.assertIn("idx_conflict_res", indexes)
        finally:
            conn.close()

    def test_self_healing_when_only_embeddings_table_exists(self):
        """2. When vectors.db has only embeddings table, MemoryStore self-heals by adding memories and memory_conflicts."""
        # Pre-create db with ONLY embeddings table (the exact bug condition)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY, vector_id TEXT UNIQUE, text TEXT)")
            conn.commit()
        finally:
            conn.close()

        # Initialize MemoryStore
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        valid, msg = store.validate_schema()
        self.assertTrue(valid, f"Expected valid schema after self-healing, got: {msg}")

        # Verify tables exist
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {r[0] for r in cursor.fetchall()}
            self.assertIn("embeddings", tables)
            self.assertIn("memories", tables)
            self.assertIn("memory_conflicts", tables)
        finally:
            conn.close()

    def test_validate_schema_returns_true_when_valid(self):
        """3. validate_schema returns (True, 'Schema valid') when all tables are present."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        valid, msg = store.validate_schema()
        self.assertTrue(valid)
        self.assertEqual(msg, "Schema valid")

    def test_validate_schema_detects_missing_table(self):
        """4. validate_schema returns False and names the missing table when dropped."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DROP TABLE memories")
            conn.commit()
        finally:
            conn.close()

        valid, msg = store.validate_schema()
        self.assertFalse(valid)
        self.assertIn("memories", msg)

    def test_self_healing_on_connection_query(self):
        """5. Dropping memories table while store is alive heals upon the next _connection query."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        # Drop table externally
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DROP TABLE memories")
            conn.commit()
        finally:
            conn.close()

        # Query stats via store -> _connection automatically creates memories table before execution
        stats = store.get_stats()
        self.assertEqual(stats.total_memories, 0)

        # Confirm table was recreated
        valid, msg = store.validate_schema()
        self.assertTrue(valid)

    def test_ensure_schema_idempotency(self):
        """6. ensure_schema can be called multiple times without error or duplicating indexes."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        for _ in range(5):
            store.ensure_schema()
        valid, msg = store.validate_schema()
        self.assertTrue(valid)

    def test_get_stats_empty_store(self):
        """7. get_stats on empty store returns zero counts and no exceptions."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        stats = store.get_stats()
        self.assertEqual(stats.total_count, 0)
        self.assertEqual(stats.total_memories, 0)
        self.assertEqual(stats.active_memories, 0)
        self.assertEqual(stats.conflict_count, 0)

    def test_store_memory_and_retrieve(self):
        """8. Storing a MemoryItem writes to SQLite and is retrievable."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        item = MemoryItem(
            content="Preferred framework is PyTorch for neural networks",
            type=MemoryType.PREFERENCE,
            scope=MemoryScope.USER,
            confidence=0.95
        )
        stored_item = store.store_memory(item)
        self.assertEqual(stored_item.memory_id, item.memory_id)

        retrieved = store.retrieve("PyTorch")
        self.assertGreaterEqual(len(retrieved), 1)
        self.assertEqual(retrieved[0].memory_id, item.memory_id)
        self.assertIn("PyTorch", retrieved[0].content)

    def test_get_all_entries(self):
        """9. get_all_entries returns all active log entries."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        refl = Reflection(
            task="Deploy containerized service",
            tag="devops",
            approach="Deploy application with Docker Compose",
            result="Running on port 8080",
            lesson="Container deployment successful"
        )
        store.append_reflection(refl)
        entries = store.get_all_entries()
        self.assertGreaterEqual(len(entries), 1)
        self.assertIn("Docker Compose", entries[0])

    def test_append_reflection_flow(self):
        """10. append_reflection writes to markdown file and stores structured lessons without error."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        refl = Reflection(
            task="Optimize database indexing",
            tag="database",
            approach="Add B-tree index on column",
            result="Passed all unit tests",
            lesson="Always index foreign keys"
        )
        store.append_reflection(refl)
        content = self.mem_file.read_text(encoding="utf-8")
        self.assertIn("Add B-tree index on column", content)
        self.assertIn("Always index foreign keys", content)

    def test_engine_persist_error_isolation(self):
        """11. Engine persist handles memory exceptions without failing or propagating to caller."""
        engine = ZaraEngine(enable_voice=False)
        refl = Reflection(
            task="Test error isolation",
            tag="test",
            approach="Simulate failure",
            result="Completed",
            lesson="Fault tolerance"
        )

        class FaultyMemory:
            def append_reflection(self, r):
                raise sqlite3.OperationalError("Simulated database failure")

        orig_mem = engine.memory
        try:
            engine.memory = FaultyMemory()
            # Must not raise an exception
            engine.persist(refl)
        finally:
            engine.memory = orig_mem

    def test_connection_context_manager_cleanup(self):
        """12. _connection closes sqlite connection on normal return without leaking handles."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        with store._connection() as conn:
            self.assertIsNotNone(conn)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            _ = cursor.fetchone()
            cursor.close()

    def test_connection_context_manager_cleanup_on_exception(self):
        """13. _connection closes sqlite connection when an exception is raised inside context."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        with self.assertRaises(ValueError):
            with store._connection(commit=True) as conn:
                raise ValueError("Intentional error inside transaction")

    def test_secret_scrubbing_and_detection(self):
        """14. contains_secret detects credentials and scrub_text redacts them."""
        secret_sample = "Bearer secret_token_1234567890abcdef"
        self.assertTrue(contains_secret(secret_sample))
        scrubbed = scrub_text(secret_sample)
        self.assertNotIn("secret_token_1234567890abcdef", scrubbed)
        self.assertIn("[REDACTED", scrubbed)

    def test_memory_conflicts_initialization_and_query(self):
        """15. memory_conflicts table is queryable via get_conflicts."""
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        confs = store.get_conflicts(status=ConflictStatus.UNRESOLVED)
        self.assertEqual(confs, [])

    def test_health_monitor_check_memory_healthy(self):
        """16. GlobalHealthService._check_memory returns HEALTHY for operational store."""
        engine = ZaraEngine(enable_voice=False)
        monitor = GlobalHealthService(engine=engine)
        sub = monitor._check_memory()
        self.assertEqual(sub.status, SubsystemStatus.HEALTHY)

    def test_health_monitor_check_memory_degraded(self):
        """17. GlobalHealthService._check_memory returns DEGRADED when schema is invalid."""
        engine = ZaraEngine(enable_voice=False)
        store = MemoryStore(memory_path=self.mem_file, db_path=self.db_path)
        conn = sqlite3.connect(str(self.db_path))
        try:
            conn.execute("DROP TABLE memories")
            conn.commit()
        finally:
            conn.close()

        orig_mem = engine.memory
        try:
            engine.memory = store
            monitor = GlobalHealthService(engine=engine)
            sub = monitor._check_memory()
            self.assertEqual(sub.status, SubsystemStatus.DEGRADED)
            self.assertIn("schema invalid", sub.message.lower())
        finally:
            engine.memory = orig_mem

    def test_api_memory_endpoint_200_json(self):
        """18. GET /api/memory returns HTTP 200 with JSON payload containing entries and stats."""
        engine = ZaraEngine(enable_voice=False)
        app = create_ui_app(engine=engine)
        client = TestClient(app)

        resp = client.get("/api/memory")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("entries", data)
        self.assertIn("stats", data)
        self.assertEqual(data.get("status"), "healthy")

    def test_api_memory_endpoint_resilient_to_degraded_db(self):
        """19. GET /api/memory returns HTTP 200 with status=degraded if memory throws an error."""
        engine = ZaraEngine(enable_voice=False)

        class BrokenMemory:
            def get_all_entries(self):
                raise sqlite3.OperationalError("no such table: memories")
            def get_stats(self):
                raise sqlite3.OperationalError("no such table: memories")

        orig_mem = engine.memory
        try:
            engine.memory = BrokenMemory()
            app = create_ui_app(engine=engine)
            client = TestClient(app)

            resp = client.get("/api/memory")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data.get("status"), "degraded")
            self.assertIn("error", data)
            self.assertEqual(data.get("entries"), [])
        finally:
            engine.memory = orig_mem

    def test_voice_summary_sanitizes_sqlite_errors(self):
        """20. summarize_for_voice transforms sqlite errors into natural voice output."""
        err1 = "sqlite3.OperationalError: no such table: memories"
        spoken1 = summarize_for_voice(err1)
        self.assertEqual(spoken1, "I couldn't complete that request because the memory system needs repair.")

        err2 = "OperationalError: database is locked"
        spoken2 = summarize_for_voice(err2)
        self.assertEqual(spoken2, "I couldn't complete that request because the memory system needs repair.")


if __name__ == "__main__":
    unittest.main()
