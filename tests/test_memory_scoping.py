"""
Tests for ZARA Phase 14: Memory Scoping, Project Isolation & User Directives.
Tests GLOBAL, USER, PROJECT, TASK, and SESSION scopes, strict boundary isolation,
privacy levels, explicit user directives ("remember that..."), and negative directives ("off the record", "forget").
"""
import unittest
import tempfile
import shutil
from pathlib import Path

from modules.memory import (
    MemoryStore,
    MemoryItem,
    MemoryType,
    MemoryScope,
    MemorySource,
    PrivacyLevel,
)
from modules.memory_extractor import MemoryExtractor


class TestMemoryScoping(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.workspace = Path(self.temp_dir)
        self.memory_file = self.workspace / "zara_log.md"
        self.db_path = self.workspace / "vectors.db"
        self.store = MemoryStore(memory_path=self.memory_file, db_path=self.db_path)
        self.extractor = MemoryExtractor()

    def tearDown(self):
        self.store.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_global_scope_accessible_everywhere(self):
        """Verify GLOBAL memories are retrieved regardless of project_id."""
        item = MemoryItem(
            type=MemoryType.FACT,
            content="Standard HTTP port for development is 8000",
            scope=MemoryScope.GLOBAL
        )
        self.store.store_memory(item)

        # Retrieve without project
        res_no_proj = self.store.retrieve(query="HTTP port 8000")
        self.assertEqual(len(res_no_proj), 1)

        # Retrieve within project-1
        res_p1 = self.store.retrieve(query="HTTP port 8000", project_id="proj-1")
        self.assertEqual(len(res_p1), 1)

        # Retrieve within project-2
        res_p2 = self.store.retrieve(query="HTTP port 8000", project_id="proj-2")
        self.assertEqual(len(res_p2), 1)

    def test_02_user_scope_accessible_across_projects(self):
        """Verify USER preferences are accessible across multiple projects."""
        item = MemoryItem(
            type=MemoryType.PREFERENCE,
            content="User prefers tabs over spaces for indentation",
            scope=MemoryScope.USER
        )
        self.store.store_memory(item)

        res_p1 = self.store.retrieve(query="indentation tabs", project_id="proj-app1")
        self.assertEqual(len(res_p1), 1)
        res_p2 = self.store.retrieve(query="indentation tabs", project_id="proj-app2")
        self.assertEqual(len(res_p2), 1)

    def test_03_project_boundary_strict_isolation(self):
        """Verify memories scoped to Project A are NEVER visible to Project B."""
        item_a = MemoryItem(
            type=MemoryType.PROJECT_CONTEXT,
            content="Project Alpha secret architectural formula is XYZ-99",
            scope=MemoryScope.PROJECT,
            project_id="proj-alpha"
        )
        self.store.store_memory(item_a)

        # Query from Project Alpha finds it
        res_alpha = self.store.retrieve(query="architectural formula", project_id="proj-alpha")
        self.assertEqual(len(res_alpha), 1)
        self.assertEqual(res_alpha[0].project_id, "proj-alpha")

        # Query from Project Beta gets NOTHING
        res_beta = self.store.retrieve(query="architectural formula", project_id="proj-beta")
        self.assertEqual(len(res_beta), 0)

        # Query without project gets NOTHING (cannot leak project memories into global context)
        res_global = self.store.retrieve(query="architectural formula", project_id=None)
        self.assertEqual(len(res_global), 0)

    def test_04_task_scope_isolation(self):
        """Verify TASK scoped memories require matching project and task."""
        item = MemoryItem(
            type=MemoryType.TASK_CONTEXT,
            content="Temporary intermediate calculation result for task-01",
            scope=MemoryScope.TASK,
            project_id="proj-gamma",
            task_id="task-01"
        )
        self.store.store_memory(item)

        # Matching task and project
        res_exact = self.store.retrieve(
            query="intermediate calculation",
            project_id="proj-gamma",
            task_id="task-01"
        )
        self.assertEqual(len(res_exact), 1)

        # Different task in same project
        res_diff_task = self.store.retrieve(
            query="intermediate calculation",
            project_id="proj-gamma",
            task_id="task-02"
        )
        self.assertEqual(len(res_diff_task), 0)

    def test_05_session_scope_isolation(self):
        """Verify SESSION scoped memories are isolated to the specific session."""
        item = MemoryItem(
            type=MemoryType.FACT,
            content="Active terminal PID during current session is 9982",
            scope=MemoryScope.SESSION,
            session_id="sess-101"
        )
        self.store.store_memory(item)

        res_sess1 = self.store.retrieve(query="terminal PID", session_id="sess-101")
        self.assertEqual(len(res_sess1), 1)

        res_sess2 = self.store.retrieve(query="terminal PID", session_id="sess-202")
        self.assertEqual(len(res_sess2), 0)

    def test_06_privacy_levels_handling(self):
        """Verify NORMAL, PRIVATE, SENSITIVE, and SECRET privacy levels."""
        p_norm = MemoryItem(type=MemoryType.FACT, content="Public release notes v1.0", privacy_level=PrivacyLevel.NORMAL)
        p_priv = MemoryItem(type=MemoryType.FACT, content="Internal developer notes", privacy_level=PrivacyLevel.PRIVATE)
        p_sens = MemoryItem(type=MemoryType.FACT, content="Sensitive customer stats", privacy_level=PrivacyLevel.SENSITIVE)
        p_secr = MemoryItem(type=MemoryType.FACT, content="Ultra secret key data", privacy_level=PrivacyLevel.SECRET)

        self.assertIsNotNone(self.store.store_memory(p_norm))
        self.assertIsNotNone(self.store.store_memory(p_priv))
        self.assertIsNotNone(self.store.store_memory(p_sens))

        with self.assertRaises(ValueError):
            self.store.store_memory(p_secr)

    def test_07_extractor_explicit_remember_preference(self):
        """Verify MemoryExtractor parses 'Remember that I prefer...' into PREFERENCE."""
        user_msg = "Please remember that I prefer pytest over unittest for Python"
        candidates, directive = self.extractor.extract_from_user_input(user_msg, project_id=None)

        self.assertIsNone(directive)
        self.assertEqual(len(candidates), 1)
        item = candidates[0]
        self.assertEqual(item.type, MemoryType.PREFERENCE)
        self.assertEqual(item.scope, MemoryScope.USER)
        self.assertIn("pytest over unittest", item.content)
        self.assertGreaterEqual(item.confidence, 0.95)

    def test_08_extractor_explicit_remember_instruction_rule(self):
        """Verify MemoryExtractor parses 'Always use...' into INSTRUCTION."""
        user_msg = "Always use python3 -m pytest -v when testing"
        candidates, directive = self.extractor.extract_from_user_input(user_msg, project_id="proj-build")

        self.assertIsNone(directive)
        self.assertEqual(len(candidates), 1)
        item = candidates[0]
        self.assertEqual(item.type, MemoryType.INSTRUCTION)
        self.assertEqual(item.scope, MemoryScope.PROJECT)
        self.assertIn("rule", item.tags)

    def test_09_extractor_negative_directive_do_not_store(self):
        """Verify 'don't remember this' or 'off the record' produces do_not_store action."""
        phrases = [
            "Don't remember this instruction",
            "This conversation is off the record",
            "Do not store my temporary password",
            "Private mode please"
        ]
        for p in phrases:
            candidates, directive = self.extractor.extract_from_user_input(p)
            self.assertEqual(len(candidates), 0)
            self.assertIsNotNone(directive)
            self.assertEqual(directive.get("action"), "do_not_store")

    def test_10_extractor_forget_directive(self):
        """Verify 'forget about...' extracts target memory to remove."""
        user_msg = "Forget about my preference for light theme"
        candidates, directive = self.extractor.extract_from_user_input(user_msg)

        self.assertEqual(len(candidates), 0)
        self.assertIsNotNone(directive)
        self.assertEqual(directive.get("action"), "forget")
        self.assertIn("light theme", directive.get("target"))

    def test_11_extractor_rejects_credential_inputs(self):
        """Verify MemoryExtractor rejects input containing API keys."""
        raw_msg = "Remember that my secret API key is api_key = 'sk-proj-9988228833992211'"
        candidates, directive = self.extractor.extract_from_user_input(raw_msg)
        self.assertEqual(len(candidates), 0)
        self.assertIsNotNone(directive)
        self.assertEqual(directive.get("action"), "rejected_secret")

    def test_12_extractor_from_task_failure(self):
        """Verify task failure produces ERROR_PATTERN memory."""
        res = {
            "status": "failed",
            "error": "ConnectionRefusedError: [Errno 61] Connection refused on port 8080"
        }
        items = self.extractor.extract_from_task_result(
            task_id="task-12",
            goal="Connect to mock server",
            result=res,
            project_id="proj-web"
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].type, MemoryType.ERROR_PATTERN)
        self.assertIn("ConnectionRefusedError", items[0].content)

    def test_13_extractor_from_task_success_with_artifacts(self):
        """Verify task success produces SUCCESS_PATTERN and PROJECT_CONTEXT for artifacts."""
        res = {
            "status": "completed",
            "summary": "Rendered 3D scene successfully",
            "artifacts": ["render.png", "scene.blend"]
        }
        items = self.extractor.extract_from_task_result(
            task_id="task-render",
            goal="Render 3D scene",
            result=res,
            project_id="proj-blender"
        )
        self.assertGreaterEqual(len(items), 2)
        types = [it.type for it in items]
        self.assertIn(MemoryType.SUCCESS_PATTERN, types)
        self.assertIn(MemoryType.PROJECT_CONTEXT, types)

    def test_14_extractor_from_user_feedback(self):
        """Verify feedback extraction marks importance higher on negative ratings."""
        pos_items = self.extractor.extract_from_feedback("Great explanation of the architecture", rating=1.0)
        self.assertEqual(len(pos_items), 1)
        self.assertEqual(pos_items[0].type, MemoryType.USER_FEEDBACK)
        self.assertAlmostEqual(pos_items[0].importance, 0.85)

        neg_items = self.extractor.extract_from_feedback("Do not use deprecated library next time", rating=0.2)
        self.assertEqual(len(neg_items), 1)
        self.assertGreater(neg_items[0].importance, pos_items[0].importance)

    def test_15_project_cleanup_does_not_affect_global(self):
        """Verify deleting project memories does not harm global or user memories."""
        self.store.store_memory(MemoryItem(type=MemoryType.FACT, content="Global fact", scope=MemoryScope.GLOBAL))
        self.store.store_memory(MemoryItem(type=MemoryType.FACT, content="Project fact", scope=MemoryScope.PROJECT, project_id="proj-del"))

        proj_items = self.store.list_memories(project_id="proj-del")
        for p in proj_items:
            self.store.delete_memory(p.memory_id, soft=False)

        self.assertEqual(len(self.store.list_memories(project_id="proj-del")), 0)
        global_items = self.store.list_memories(scope=MemoryScope.GLOBAL)
        self.assertEqual(len(global_items), 1)


if __name__ == "__main__":
    unittest.main()
