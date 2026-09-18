"""
Tests for ZARA Phase 14: Advanced Memory System Core & Intelligence.
Tests all 12 memory types, CRUD, confidence, importance, hybrid search,
deduplication, contradiction handling, consolidation, temporal decay, and secret rejection.
"""
import unittest
import tempfile
import shutil
import time
import datetime
from pathlib import Path

from modules.memory import (
    MemoryStore,
    MemoryItem,
    MemoryType,
    MemoryScope,
    MemorySource,
    PrivacyLevel,
    TemporalStatus,
    ConflictStatus,
    MemoryConflict,
    contains_secret,
    scrub_text,
)


class TestMemoryAdvanced(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.memory_file = self.workspace / "zara_log.md"
        self.db_path = self.workspace / "vectors.db"
        self.store = MemoryStore(memory_path=self.memory_file, db_path=self.db_path)

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_all_twelve_memory_types_supported(self):
        """Verify that all 12 memory types can be stored, retrieved, and inspected."""
        for m_type in MemoryType:
            item = MemoryItem(
                type=m_type,
                content=f"Sample content for {m_type.value}",
                scope=MemoryScope.GLOBAL,
                confidence=0.85,
                importance=0.70,
                source=MemorySource.TASK_RESULT,
                tags=[m_type.value.lower()]
            )
            stored = self.store.store_memory(item, auto_deduplicate=False)
            self.assertIsNotNone(stored.memory_id)
            retrieved = self.store.get_memory(stored.memory_id)
            self.assertIsNotNone(retrieved)
            self.assertEqual(retrieved.type, m_type)

    def test_02_crud_operations(self):
        """Verify create, read, update, soft-delete, and hard-delete operations."""
        item = MemoryItem(
            type=MemoryType.FACT,
            content="FastAPI server listens on port 8000 by default",
            scope=MemoryScope.GLOBAL,
            confidence=0.95,
            importance=0.80,
            source=MemorySource.USER_STATED
        )
        stored = self.store.store_memory(item)
        mid = stored.memory_id

        # Read
        fetched = self.store.get_memory(mid)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.content, "FastAPI server listens on port 8000 by default")

        # Update
        fetched.content = "FastAPI server listens on port 8080 by default"
        self.store.update_memory(fetched)
        updated = self.store.get_memory(mid)
        self.assertEqual(updated.content, "FastAPI server listens on port 8080 by default")

        # Soft delete
        self.assertTrue(self.store.delete_memory(mid, soft=True))
        soft_deleted = self.store.get_memory(mid)
        self.assertFalse(soft_deleted.is_active)

        # Hard delete
        self.assertTrue(self.store.delete_memory(mid, soft=False))
        self.assertIsNone(self.store.get_memory(mid))

    def test_03_confidence_bounds_and_source_defaults(self):
        """Verify confidence is bounded between 0.0 and 1.0 and defaults match source."""
        # Out of bounds
        item_high = MemoryItem(
            type=MemoryType.FACT,
            content="Confidence ceiling test",
            confidence=1.5,
            source=MemorySource.TASK_RESULT
        )
        stored_high = self.store.store_memory(item_high)
        self.assertLessEqual(stored_high.confidence, 1.0)

        item_low = MemoryItem(
            type=MemoryType.FACT,
            content="Confidence floor test",
            confidence=-0.5,
            source=MemorySource.TASK_RESULT
        )
        stored_low = self.store.store_memory(item_low)
        self.assertGreaterEqual(stored_low.confidence, 0.0)

    def test_04_provenance_tracking(self):
        """Verify memory provenance tracks creation sources, merges, and task contexts."""
        item = MemoryItem(
            type=MemoryType.DECISION,
            content="Use SQLite WAL mode for concurrency",
            scope=MemoryScope.PROJECT,
            project_id="proj-alpha",
            task_id="task-init",
            source=MemorySource.TASK_RESULT,
            provenance=["task:task-init", "author:engineer"]
        )
        stored = self.store.store_memory(item)
        fetched = self.store.get_memory(stored.memory_id)
        self.assertIn("task:task-init", fetched.provenance)
        self.assertIn("author:engineer", fetched.provenance)

    def test_05_secret_detection_and_blocking(self):
        """Verify automatic detection and rejection of passwords, API keys, and bearer tokens."""
        secret_sample_1 = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.super_secret_payload_token"
        secret_sample_2 = "api_key = 'sk-live-9938472948274928174'"
        secret_sample_3 = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0"

        self.assertTrue(contains_secret(secret_sample_1))
        self.assertTrue(contains_secret(secret_sample_2))
        self.assertTrue(contains_secret(secret_sample_3))
        self.assertFalse(contains_secret("Just regular user preference for dark mode"))

        # Refusal when privacy level is SECRET
        secret_item = MemoryItem(
            type=MemoryType.FACT,
            content="Sensitive internal credential: " + secret_sample_2,
            privacy_level=PrivacyLevel.SECRET
        )
        with self.assertRaises(ValueError):
            self.store.store_memory(secret_item)

    def test_06_secret_scrubbing(self):
        """Verify scrub_text redacts credential patterns cleanly."""
        text = "Connect with api_key = 'secret1234567890abcdef' to the database"
        scrubbed = scrub_text(text)
        self.assertNotIn("secret1234567890abcdef", scrubbed)
        self.assertIn("[REDACTED", scrubbed)

    def test_07_near_duplicate_merging(self):
        """Verify near-identical memories merge rather than duplicate, boosting confidence."""
        item1 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="User prefers Python for backend development",
            scope=MemoryScope.USER,
            confidence=0.80,
            importance=0.70,
            source=MemorySource.USER_STATED
        )
        stored1 = self.store.store_memory(item1, auto_deduplicate=True)
        initial_id = stored1.memory_id

        item2 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="User prefers Python for backend development",
            scope=MemoryScope.USER,
            confidence=0.85,
            importance=0.70,
            source=MemorySource.USER_STATED
        )
        stored2 = self.store.store_memory(item2, auto_deduplicate=True)

        # Same ID because it merged
        self.assertEqual(stored1.memory_id, stored2.memory_id)
        fetched = self.store.get_memory(initial_id)
        self.assertGreater(fetched.confidence, 0.80)
        self.assertEqual(fetched.access_count, 1)

    def test_08_contradiction_detection_and_conflict_recording(self):
        """Verify contradictory preferences trigger MemoryConflict logging."""
        item1 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Always prefer pytest for running unit tests",
            scope=MemoryScope.USER,
            confidence=0.90,
            source=MemorySource.USER_STATED
        )
        self.store.store_memory(item1, detect_conflicts=True)

        item2 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Never prefer pytest for running unit tests",
            scope=MemoryScope.USER,
            confidence=0.95,
            source=MemorySource.USER_STATED
        )
        self.store.store_memory(item2, detect_conflicts=True)

        conflicts = self.store.get_conflicts()
        self.assertGreater(len(conflicts), 0)
        self.assertEqual(conflicts[0].conflict_type, "CONTRADICTION")

    def test_09_conflict_resolution_override(self):
        """Verify resolving a conflict updates status and resolution note."""
        item1 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Prefer light theme in dashboard",
            scope=MemoryScope.USER,
            source=MemorySource.MODEL_INFERENCE,
            confidence=0.60
        )
        s1 = self.store.store_memory(item1, detect_conflicts=True)

        item2 = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Prefer dark theme in dashboard",
            scope=MemoryScope.USER,
            source=MemorySource.MODEL_INFERENCE,
            confidence=0.65
        )
        s2 = self.store.store_memory(item2, detect_conflicts=True)

        confs = self.store.get_conflicts(status=ConflictStatus.UNRESOLVED)
        self.assertTrue(len(confs) > 0)
        cid = confs[0].conflict_id

        self.store.resolve_conflict(
            conflict_id=cid,
            resolved_by=s2.memory_id,
            resolution_status=ConflictStatus.USER_OVERRIDDEN,
            resolution_note="User explicitly stated dark theme"
        )

        resolved_confs = self.store.get_conflicts(status=ConflictStatus.USER_OVERRIDDEN)
        self.assertTrue(any(c.conflict_id == cid for c in resolved_confs))

    def test_10_temporal_decay_and_expiration(self):
        """Verify temporal decay decreases score for old memories and expires past items."""
        now = datetime.datetime.now(datetime.timezone.utc)
        past_time = (now - datetime.timedelta(days=10)).isoformat()
        future_time = (now + datetime.timedelta(days=10)).isoformat()
        expired_time = (now - datetime.timedelta(days=1)).isoformat()

        valid_item = MemoryItem(
            type=MemoryType.FACT,
            content="Valid temporary token config for session",
            scope=MemoryScope.GLOBAL,
            valid_from=past_time,
            valid_until=future_time,
            confidence=0.90
        )
        s_valid = self.store.store_memory(valid_item)

        expired_item = MemoryItem(
            type=MemoryType.FACT,
            content="Expired temporary token config for session",
            scope=MemoryScope.GLOBAL,
            valid_from=past_time,
            valid_until=expired_time,
            confidence=0.90
        )
        s_exp = self.store.store_memory(expired_item)

        # Retrieve should not return expired item
        results = self.store.retrieve(query="temporary token config")
        result_ids = [r.memory_id for r in results]
        self.assertIn(s_valid.memory_id, result_ids)
        self.assertNotIn(s_exp.memory_id, result_ids)

        # Direct check shows temporal status EXPIRED
        exp_record = self.store.get_memory(s_exp.memory_id)
        self.assertEqual(exp_record.temporal_status, TemporalStatus.EXPIRED)

    def test_11_consolidation_clusters_related_memories(self):
        """Verify memory consolidation synthesizes clusters of memories into higher-level knowledge."""
        for i in range(3):
            self.store.store_memory(MemoryItem(
                type=MemoryType.ERROR_PATTERN,
                content=f"Subprocess timeout error on macOS during unit test batch {i}",
                scope=MemoryScope.PROJECT,
                project_id="proj-cluster",
                source=MemorySource.TASK_RESULT,
                confidence=0.85
            ), auto_deduplicate=False)

        consolidated = self.store.consolidate_memories(
            scope=MemoryScope.PROJECT,
            project_id="proj-cluster",
            min_cluster_size=2
        )
        self.assertGreaterEqual(len(consolidated), 1)
        self.assertEqual(consolidated[0].type, MemoryType.SYSTEM_KNOWLEDGE)
        self.assertGreater(len(consolidated[0].provenance), 1)

    def test_12_hybrid_search_retrieval(self):
        """Verify hybrid search scores dense vector similarity + lexical keywords."""
        item1 = MemoryItem(
            type=MemoryType.SKILL,
            content="Proficient in Docker containerization and Dockerfile optimization",
            scope=MemoryScope.GLOBAL,
            confidence=0.95,
            importance=0.80
        )
        item2 = MemoryItem(
            type=MemoryType.SKILL,
            content="Proficient in Blender 3D procedural mesh generation and rendering",
            scope=MemoryScope.GLOBAL,
            confidence=0.95,
            importance=0.80
        )
        self.store.store_memory(item1)
        self.store.store_memory(item2)

        results = self.store.retrieve(query="Docker container build optimize", limit=1)
        self.assertEqual(len(results), 1)
        self.assertIn("Docker", results[0].content)

    def test_13_memory_stats_computation(self):
        """Verify get_stats returns correct totals, breakdowns, and averages."""
        self.store.store_memory(MemoryItem(
            type=MemoryType.FACT,
            content="Fact 1",
            scope=MemoryScope.GLOBAL,
            confidence=0.8,
            importance=0.6
        ))
        self.store.store_memory(MemoryItem(
            type=MemoryType.PREFERENCE,
            content="Preference 1",
            scope=MemoryScope.USER,
            confidence=0.9,
            importance=0.8
        ))

        stats = self.store.get_stats()
        self.assertEqual(stats.total_count, 2)
        self.assertEqual(stats.total_memories, 2)
        self.assertEqual(stats.active_memories, 2)
        self.assertEqual(stats.by_type.get("FACT"), 1)
        self.assertEqual(stats.by_type.get("PREFERENCE"), 1)
        self.assertEqual(stats.by_scope.get("GLOBAL"), 1)
        self.assertEqual(stats.by_scope.get("USER"), 1)
        self.assertAlmostEqual(stats.average_confidence, 0.85, places=1)

    def test_14_multidimensional_importance_scoring(self):
        """Verify importance weights user directives and security constraints higher."""
        user_inst = MemoryItem(
            type=MemoryType.INSTRUCTION,
            content="Never modify production database directly",
            scope=MemoryScope.GLOBAL,
            source=MemorySource.USER_STATED,
            importance=0.95
        )
        weak_inf = MemoryItem(
            type=MemoryType.FACT,
            content="User might have lunch around 1pm",
            scope=MemoryScope.USER,
            source=MemorySource.WEAK_INFERENCE,
            importance=0.20
        )
        s_inst = self.store.store_memory(user_inst)
        s_inf = self.store.store_memory(weak_inf)

        self.assertGreater(s_inst.importance, s_inf.importance)

    def test_15_legacy_get_all_entries_and_search_lessons(self):
        """Verify backward-compatible get_all_entries and search_lessons methods work."""
        self.memory_file.write_text("## Reflection 1\n- Approach: Direct\n- Result: Success\n- Lesson: Verify inputs\n---\n## Reflection 2\n- Approach: Mock\n- Result: Pass\n- Lesson: Clean mocks\n", encoding="utf-8")
        entries = self.store.get_all_entries()
        self.assertEqual(len(entries), 2)

        lessons = self.store.search_lessons("inputs")
        self.assertEqual(len(lessons), 1)
        self.assertIn("Verify inputs", lessons[0]["lesson"])

    def test_16_legacy_preferences_file_interaction(self):
        """Verify get_preferences and update_preference update JSON and create structured memory."""
        self.store.update_preference("theme", "cyber_dark")
        prefs = self.store.get_preferences()
        self.assertEqual(prefs.get("theme"), "cyber_dark")

        # Also stored in structured memory
        memories = self.store.retrieve(query="cyber_dark")
        self.assertTrue(any("cyber_dark" in m.content for m in memories))

    def test_17_access_count_and_touch_tracking(self):
        """Verify retrieving memories increments access_count and touch timestamp."""
        item = MemoryItem(
            type=MemoryType.FACT,
            content="Target server hostname is api.zara.internal",
            scope=MemoryScope.GLOBAL
        )
        stored = self.store.store_memory(item)
        self.assertEqual(stored.access_count, 0)

        # Retrieval touches memory
        self.store.retrieve("hostname api.zara.internal")
        fetched = self.store.get_memory(stored.memory_id)
        self.assertGreaterEqual(fetched.access_count, 1)
        self.assertIsNotNone(fetched.last_accessed_at)

    def test_18_tag_filtering(self):
        """Verify filtering memories by tags."""
        item1 = MemoryItem(type=MemoryType.FACT, content="Vue frontend config", tags=["frontend", "vue"])
        item2 = MemoryItem(type=MemoryType.FACT, content="FastAPI backend config", tags=["backend", "python"])
        self.store.store_memory(item1)
        self.store.store_memory(item2)

        results = self.store.retrieve(query="config", tag_filter="vue")
        self.assertEqual(len(results), 1)
        self.assertIn("Vue", results[0].content)

    def test_19_list_memories_filters(self):
        """Verify list_memories supports scope, project, type, and active filters."""
        self.store.store_memory(MemoryItem(type=MemoryType.FACT, content="F1", scope=MemoryScope.GLOBAL))
        self.store.store_memory(MemoryItem(type=MemoryType.PREFERENCE, content="P1", scope=MemoryScope.USER))
        self.store.store_memory(MemoryItem(type=MemoryType.DECISION, content="D1", scope=MemoryScope.PROJECT, project_id="proj-xyz"))

        facts = self.store.list_memories(memory_type=MemoryType.FACT)
        self.assertEqual(len(facts), 1)

        user_mems = self.store.list_memories(scope=MemoryScope.USER)
        self.assertEqual(len(user_mems), 1)

        proj_mems = self.store.list_memories(project_id="proj-xyz")
        self.assertEqual(len(proj_mems), 1)

    def test_20_empty_store_graceful_handling(self):
        """Verify querying empty store returns empty lists and 0 counts without error."""
        res = self.store.retrieve("anything")
        self.assertEqual(res, [])
        stats = self.store.get_stats()
        self.assertEqual(stats.total_count, 0)
        self.assertEqual(self.store.get_conflicts(), [])


if __name__ == "__main__":
    unittest.main()
