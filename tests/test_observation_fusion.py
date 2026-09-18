"""
Unit Tests for ZARA Phase 12: Observation Fusion & Conflict Resolution.
Tests same-entity fusion, conflict detection, source priority hierarchy,
confidence resolution, provenance preservation, and safe query APIs.
"""
import unittest
import time
from pathlib import Path

from modules.world_model import (
    WorldModel,
    WorldState,
    Observation,
    Entity,
    Relationship,
    ObservationConflict,
    Modality,
    EntityType,
    SourcePriority
)


class TestObservationFusion(unittest.TestCase):
    def setUp(self):
        self.wm = WorldModel(workspace_root=".")

    # 1. Same-entity fusion
    def test_01_same_entity_fusion(self):
        # First observation: Screen shows VS Code
        obs1 = Observation(
            modality=Modality.SCREEN,
            source="screen_vision",
            payload={"application": "VS Code", "window_title": "app.py"},
            confidence=0.8
        )
        self.wm.observe(obs1)
        ent = self.wm.get_entity("app:vs code")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.name, "VS Code")
        self.assertEqual(ent.state, "ACTIVE")
        self.assertEqual(len(ent.provenance), 1)

        # Second observation: macOS API reports VS Code active
        obs2 = Observation(
            modality=Modality.SCREEN,
            source="macos_api",
            payload={"application": "VS Code", "window_title": "app.py", "screen_dimensions": {"width": 1920, "height": 1080}},
            confidence=1.0
        )
        self.wm.observe(obs2)
        # Should fuse into the same entity, not create a duplicate
        self.assertEqual(len([e for e in self.wm.entities.values() if e.name == "VS Code"]), 1)
        ent = self.wm.get_entity("app:vs code")
        self.assertEqual(len(ent.provenance), 2)
        self.assertIn("screen_dimensions", ent.attributes)

    # 2. Conflicting observations detection
    def test_02_conflicting_observations_detection(self):
        # Observation 1: Vision thinks VS Code is open
        obs1 = Observation(
            modality=Modality.SCREEN,
            source="screen_vision",
            payload={"application": "VS Code", "is_active": True},
            confidence=0.7
        )
        self.wm.observe(obs1)

        # Observation 2: Direct macOS API says VS Code is in background
        obs2 = Observation(
            modality=Modality.SCREEN,
            source="direct_system_api",
            payload={"application": "VS Code", "is_active": False},
            confidence=0.99
        )
        self.wm.observe(obs2)

        # A conflict should be recorded
        self.assertTrue(len(self.wm.conflicts) > 0)
        c = self.wm.conflicts[-1]
        self.assertEqual(c.entity_id, "app:vs code")
        self.assertEqual(c.conflict_type, "state_mismatch")

    # 3. Source priority resolution
    def test_03_source_priority_resolution(self):
        # Vision says ACTIVE (Priority 60)
        obs_vision = Observation(
            modality=Modality.SCREEN,
            source="screen_vision",
            payload={"application": "Blender", "is_active": True},
            confidence=0.65
        )
        self.wm.observe(obs_vision)
        ent = self.wm.get_entity("app:blender")
        self.assertEqual(ent.state, "ACTIVE")

        # Direct macOS API says BACKGROUND (Priority 100) -> Overrides Vision
        obs_api = Observation(
            modality=Modality.SCREEN,
            source="direct_system_api",
            payload={"application": "Blender", "is_active": False},
            confidence=0.98
        )
        self.wm.observe(obs_api)
        ent = self.wm.get_entity("app:blender")
        self.assertEqual(ent.state, "BACKGROUND")

        # User statement says ACTIVE (Priority 40) -> Cannot override Direct API!
        obs_user = Observation(
            modality=Modality.VOICE,
            source="user_statement",
            payload={"transcript": "Blender is active"},
            confidence=0.5
        )
        # Manually invoke upsert with lower priority
        self.wm._upsert_entity(
            entity_id="app:blender",
            entity_type=EntityType.APPLICATION,
            name="Blender",
            state="ACTIVE",
            attributes={},
            obs=obs_user
        )
        ent = self.wm.get_entity("app:blender")
        # Remains BACKGROUND because Direct API has higher priority than User Statement
        self.assertEqual(ent.state, "BACKGROUND")

    # 4. Confidence resolution
    def test_04_confidence_resolution(self):
        obs1 = Observation(
            modality=Modality.TERMINAL,
            source="tool_terminal",
            payload={"command": "npm test", "status": "RUNNING"},
            confidence=0.85
        )
        self.wm.observe(obs1)
        proc_ent = [e for e in self.wm.entities.values() if e.type == EntityType.TERMINAL_PROCESS][0]
        self.assertEqual(proc_ent.confidence, 0.85)

    # 5. Provenance preservation across fused facts
    def test_05_provenance_preservation(self):
        obs_a = Observation(
            modality=Modality.FILESYSTEM,
            source="tool_write",
            payload={"path": "/repo/server.py", "state": "MODIFIED"}
        )
        obs_b = Observation(
            modality=Modality.FILESYSTEM,
            source="git_status_tool",
            payload={"path": "/repo/server.py", "state": "MODIFIED"}
        )
        self.wm.observe(obs_a)
        self.wm.observe(obs_b)
        ent = self.wm.get_entity(f"file:{Path('/repo/server.py').resolve()}")
        self.assertIn(obs_a.observation_id, ent.provenance)
        self.assertIn(obs_b.observation_id, ent.provenance)

    # 6. Entity relationships & queries
    def test_06_entity_relationships_and_queries(self):
        # Project contains Task, Task uses Process, Process modifies File
        self.wm.add_relationship("proj:alpha", "CONTAINS", "task:build", confidence=1.0)
        self.wm.add_relationship("task:build", "USES", "proc:npm", confidence=0.9)
        self.wm.add_relationship("proc:npm", "PRODUCES", "file:dist/bundle.js", confidence=1.0)

        self.assertEqual(len(self.wm.relationships), 3)
        rel0 = self.wm.relationships[0]
        self.assertEqual(rel0.source_id, "proj:alpha")
        self.assertEqual(rel0.predicate, "CONTAINS")
        self.assertEqual(rel0.target_id, "task:build")

    # 7. Project entity filtering
    def test_07_project_entity_filtering(self):
        # Project 1
        obs_p1 = Observation(
            modality=Modality.PROJECT,
            source="manifest",
            payload={"project_id": "proj-auth", "name": "Auth Service"},
            project_id="proj-auth"
        )
        obs_f1 = Observation(
            modality=Modality.FILESYSTEM,
            source="tool",
            payload={"path": "/src/jwt.py"},
            project_id="proj-auth"
        )
        # Project 2
        obs_p2 = Observation(
            modality=Modality.PROJECT,
            source="manifest",
            payload={"project_id": "proj-billing", "name": "Billing Service"},
            project_id="proj-billing"
        )

        self.wm.observe(obs_p1)
        self.wm.observe(obs_f1)
        self.wm.observe(obs_p2)

        auth_entities = self.wm.get_project_entities("proj-auth")
        auth_ids = [e.entity_id for e in auth_entities]
        self.assertIn("proj:proj-auth", auth_ids)
        self.assertIn(f"file:{Path('/src/jwt.py').resolve()}", auth_ids)
        self.assertNotIn("proj:proj-billing", auth_ids)

    # 8. Safe query APIs
    def test_08_safe_query_apis(self):
        self.wm.update_world(
            active_app="Xcode",
            active_window="ContentView.swift",
            active_project="proj-ios",
            active_task="task-ui-fix",
            confidence=0.92
        )
        self.assertEqual(self.wm.get_active_app(), "Xcode")
        self.assertEqual(self.wm.get_active_window(), "ContentView.swift")
        self.assertEqual(self.wm.get_active_project(), "proj-ios")
        self.assertEqual(self.wm.get_active_task(), "task-ui-fix")

    # 9. Authorization isolation: World Model observation NEVER grants authorization
    def test_09_authorization_isolation(self):
        # Even if an observation claims a host is authorized or seen in terminal:
        obs = Observation(
            modality=Modality.CYBER,
            source="terminal_stdout",
            payload={"target": "10.0.0.1", "authorized": True},  # Untrusted external observation
            trusted=False
        )
        self.wm.observe(obs)
        ent = self.wm.get_entity("cyber:10.0.0.1")
        self.assertIsNotNone(ent)
        # Notice: entity state is UNAUTHORIZED because trusted=False
        self.assertEqual(ent.state, "UNAUTHORIZED")
        self.assertFalse(ent.attributes.get("trusted_authorization"))

        # And check_authorization query defaults to False (fail-closed)
        self.assertFalse(self.wm.check_authorization("10.0.0.1"))

    # 10. Source priority mapping values
    def test_10_source_priority_mapping(self):
        self.assertEqual(WorldModel.get_source_priority_value("direct_system_api"), SourcePriority.DIRECT_SYSTEM_API.value)
        self.assertEqual(WorldModel.get_source_priority_value("tool_result"), SourcePriority.RECENT_STRUCTURED_TOOL.value)
        self.assertEqual(WorldModel.get_source_priority_value("screen_vision"), SourcePriority.RECENT_SCREEN_VISION.value)
        self.assertEqual(WorldModel.get_source_priority_value("user_voice"), SourcePriority.RECENT_USER_STATEMENT.value)
        self.assertEqual(WorldModel.get_source_priority_value("memory_lesson"), SourcePriority.MEMORY.value)
        self.assertEqual(WorldModel.get_source_priority_value("unknown_src"), SourcePriority.UNKNOWN.value)

    # 11. Multi-observation event tracking
    def test_11_multi_observation_event_tracking(self):
        for i in range(5):
            self.wm.observe(Observation(
                modality=Modality.EVENT,
                source="event_bus",
                payload={"type": f"event_{i}"}
            ))
        changes = self.wm.get_recent_changes()
        self.assertEqual(len(changes), 5)
        self.assertEqual(changes[-1]["type"], "event_4")

    # 12. Browser page entity creation
    def test_12_browser_page_entity_creation(self):
        obs = Observation(
            modality=Modality.BROWSER,
            source="tool_browser",
            payload={
                "url": "https://docs.python.org/3/library/ast.html",
                "title": "ast — Abstract Syntax Trees",
                "domain": "docs.python.org"
            },
            project_id="proj-py"
        )
        self.wm.observe(obs)
        ent = self.wm.get_entity("browser:https://docs.python.org/3/library/ast.html")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.type, EntityType.BROWSER_PAGE)
        self.assertEqual(ent.name, "ast — Abstract Syntax Trees")
        self.assertEqual(self.wm.current_state.browser_state["domain"], "docs.python.org")

    # 13. Terminal process completion fusion
    def test_13_terminal_process_completion_fusion(self):
        obs = Observation(
            modality=Modality.TERMINAL,
            source="tool_terminal",
            payload={
                "process_id": "proc-99",
                "command": "python3 -m unittest",
                "status": "COMPLETED",
                "exit_code": 0
            }
        )
        self.wm.observe(obs)
        ent = self.wm.get_entity("proc:proc-99")
        self.assertEqual(ent.state, "COMPLETED")
        self.assertEqual(ent.attributes["exit_code"], 0)

    # 14. Blender scene state fusion
    def test_14_blender_scene_state_fusion(self):
        obs = Observation(
            modality=Modality.BLENDER,
            source="blender_inspect_tool",
            payload={
                "scene_name": "MainScene",
                "objects": ["Cube", "Camera", "Light"],
                "render_status": "READY"
            },
            project_id="proj-3d"
        )
        self.wm.observe(obs)
        ent = self.wm.get_entity("blender:MainScene")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.type, EntityType.BLENDER_SCENE)
        self.assertEqual(len(ent.attributes["objects"]), 3)
        self.assertEqual(self.wm.current_state.blender_state["scene"], "MainScene")

    # 15. World model diff with multiple modality shifts
    def test_15_world_model_diff_multiple_shifts(self):
        prev = WorldState(
            active_app="Chrome",
            active_window="Research",
            project_state={"active_project": "proj-1"},
            blender_state={"render_status": "IDLE"}
        )
        curr = WorldState(
            active_app="Blender",
            active_window="3D Viewport",
            project_state={"active_project": "proj-2"},
            blender_state={"render_status": "RENDERING"}
        )
        diff = self.wm.diff(prev, curr)
        self.assertTrue(diff["has_changes"])
        self.assertEqual(diff["changes_count"], 4)
        self.assertIn("active_app", diff["changes"])
        self.assertIn("active_window", diff["changes"])
        self.assertIn("active_project", diff["changes"])
        self.assertIn("blender", diff["changes"])


if __name__ == "__main__":
    unittest.main()
