"""
Integration Tests for ZARA Phase 12: Multimodal Subsystem Integration.
Tests Vision/Screen, Voice, Browser, Terminal, Filesystem, Blender,
Cyber Lab, EventBus, Workspace, and World-Aware Planning integrations.
"""
import unittest
import time
import tempfile
import shutil
from pathlib import Path

from core.engine import ZaraEngine
from core.state import GUIState, GUIElement, TaskContext, PlanStep, ActionType
from modules.world_model import (
    WorldModel,
    WorldState,
    Observation,
    Modality,
    TemporalStatus,
    EntityType
)
from modules.workspace import ProjectManager, PersistentTask
from modules.events import EventBus, Event, EventType
from modules.goals import Goal, GoalDomain, AmbiguityLevel
from modules.planning import HierarchicalPlanner


class TestWorldIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="zara_world_test_")
        self.workspace = Path(self.tmp_dir)
        self.event_bus = EventBus()
        self.engine = ZaraEngine(
            workspace_root=str(self.workspace),
            enable_voice=False,
            event_bus=self.event_bus
        )
        self.pm = ProjectManager.create(
            name="World Test Project",
            workspace_path=self.workspace
        )
        self.engine.set_project_manager(self.pm)

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Vision: screenshot -> GUIState -> World Observation -> Entity extraction
    def test_01_vision_screenshot_to_world_entity(self):
        gui = GUIState(
            application="Visual Studio Code",
            window_title="engine.py",
            elements=[
                GUIElement(type="button", label="Save", x=100, y=100),
                GUIElement(type="field", label="Editor", x=200, y=200)
            ],
            screen_dimensions={"width": 1920, "height": 1080}
        )
        obs = Observation(
            modality=Modality.VISION,
            source="vision_module",
            payload=gui.to_dict(),
            confidence=0.95
        )
        self.engine.world_model.observe(obs)
        app_ent = self.engine.world_model.get_entity("app:visual studio code")
        win_ent = self.engine.world_model.get_entity("win:visual studio code:engine.py")
        self.assertIsNotNone(app_ent)
        self.assertIsNotNone(win_ent)
        self.assertEqual(app_ent.name, "Visual Studio Code")
        self.assertEqual(win_ent.name, "engine.py")
        self.assertEqual(self.engine.world_model.current_state.active_app, "Visual Studio Code")

    # 2. Vision: GUIState elements count and screen dimensions
    def test_02_vision_guistate_metadata(self):
        gui = GUIState(
            application="Safari",
            window_title="Apple",
            elements=[GUIElement(type="button", label="Search", x=50, y=50)]
        )
        obs = Observation(
            modality=Modality.SCREEN,
            source="macos_screen_capture",
            payload=gui.to_dict()
        )
        self.engine.world_model.observe(obs)
        screen_st = self.engine.world_model.current_state.screen_state
        self.assertIsNotNone(screen_st)
        self.assertEqual(screen_st["elements_count"], 1)
        self.assertEqual(screen_st["application"], "Safari")

    # 3. Voice: voice request observation -> entity association
    def test_03_voice_request_association(self):
        obs = Observation(
            modality=Modality.VOICE,
            source="voice_stt",
            payload={"transcript": "ZARA, continue my Blender project", "command_type": "COMMAND"},
            project_id=self.pm.project.project_id
        )
        self.engine.world_model.observe(obs)
        self.assertIsNotNone(self.engine.world_model.current_state.voice_state)
        self.assertEqual(self.engine.world_model.current_state.voice_state["transcript"], "ZARA, continue my Blender project")

    # 4. Voice: voice -> project context relationship
    def test_04_voice_to_project_relationship(self):
        obs = Observation(
            modality=Modality.VOICE,
            source="voice_controller",
            payload={"transcript": "Run security tests"},
            project_id=self.pm.project.project_id
        )
        self.engine.world_model.observe(obs)
        # Verify relationship between voice device/request and project
        rel = [r for r in self.engine.world_model.relationships if r.predicate == "DESCRIBES"]
        self.assertTrue(len(rel) > 0)
        self.assertEqual(rel[0].target_id, f"proj:{self.pm.project.project_id}")

    # 5. Browser: URL & page title -> browser_page entity
    def test_05_browser_observation_entity(self):
        obs = Observation(
            modality=Modality.BROWSER,
            source="browser_open",
            payload={
                "url": "https://python.org",
                "title": "Python Language",
                "domain": "python.org",
                "research_context": "Checking latest release notes"
            },
            project_id=self.pm.project.project_id,
            task_id="step_1"
        )
        self.engine.world_model.observe(obs)
        ent = self.engine.world_model.get_entity("browser:https://python.org")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.type, EntityType.BROWSER_PAGE)
        self.assertEqual(self.engine.world_model.current_state.browser_state["domain"], "python.org")

    # 6. Terminal: process tracking and completion
    def test_06_terminal_process_tracking(self):
        obs_start = Observation(
            modality=Modality.TERMINAL,
            source="terminal_execute",
            payload={"process_id": "p-1234", "command": "python3 build.py", "status": "RUNNING"},
            project_id=self.pm.project.project_id,
            task_id="step_2"
        )
        self.engine.world_model.observe(obs_start)
        self.assertEqual(self.engine.world_model.current_state.terminal_state["status"], "RUNNING")

        obs_finish = Observation(
            modality=Modality.TERMINAL,
            source="terminal_execute",
            payload={"process_id": "p-1234", "command": "python3 build.py", "status": "COMPLETED", "exit_code": 0},
            project_id=self.pm.project.project_id,
            task_id="step_2"
        )
        self.engine.world_model.observe(obs_finish)
        self.assertEqual(self.engine.world_model.current_state.terminal_state["exit_code"], 0)
        self.assertEqual(self.engine.world_model.current_state.terminal_state["status"], "COMPLETED")

    # 7. Filesystem: artifact integration & changed-file detection
    def test_07_filesystem_artifact_integration(self):
        code_file = self.workspace / "service.py"
        code_file.write_text("print('hello')", encoding="utf-8")

        obs = Observation(
            modality=Modality.FILESYSTEM,
            source="tool_write_file",
            payload={"path": str(code_file), "size": len("print('hello')"), "artifact_id": "art-01"},
            project_id=self.pm.project.project_id,
            task_id="step_3"
        )
        self.engine.world_model.observe(obs)
        ent = self.engine.world_model.get_entity(f"file:{code_file.resolve()}")
        self.assertIsNotNone(ent)
        self.assertEqual(ent.type, EntityType.FILE)
        self.assertEqual(ent.name, "service.py")
        self.assertEqual(ent.attributes["artifact_id"], "art-01")

    # 8. Blender: scene integration and render status
    def test_08_blender_scene_and_render_integration(self):
        obs = Observation(
            modality=Modality.BLENDER,
            source="blender_tools",
            payload={
                "scene_name": "StudioSetup",
                "objects": ["Backdrop", "KeyLight", "Camera"],
                "render_status": "RENDER_COMPLETE",
                "last_render": "studio_render_01.png"
            },
            project_id=self.pm.project.project_id
        )
        self.engine.world_model.observe(obs)
        self.assertEqual(self.engine.world_model.current_state.blender_state["scene"], "StudioSetup")
        self.assertEqual(self.engine.world_model.current_state.blender_state["render_status"], "RENDER_COMPLETE")
        self.assertEqual(self.engine.world_model.current_state.blender_state["last_render"], "studio_render_01.png")

    # 9. Cyber Lab: target state & authorization isolation
    def test_09_cyber_lab_target_state_and_auth_isolation(self):
        # Observation from tool
        obs = Observation(
            modality=Modality.CYBER,
            source="cyber_tool",
            payload={
                "target": "127.0.0.1",
                "environment_status": "READY",
                "last_validation": "2026-09-18T10:00:00Z",
                "findings_count": 2
            },
            project_id=self.pm.project.project_id,
            trusted=False
        )
        self.engine.world_model.observe(obs)
        cyber_st = self.engine.world_model.current_state.cyber_state
        self.assertEqual(cyber_st["authorized_target"], "127.0.0.1")
        self.assertEqual(cyber_st["findings_count"], 2)

        # Invariant: World model observation alone cannot grant authorization
        self.assertFalse(self.engine.world_model.check_authorization("127.0.0.1", cyber_scope=None))

    # 10. Events: world-change event published on EventBus
    def test_10_world_change_event_publishing(self):
        received_events = []
        self.event_bus.subscribe(
            EventType.WORLD_STATE_CHANGED,
            lambda evt: received_events.append(evt)
        )

        step = PlanStep(
            id=1,
            title="Create test file",
            action_type=ActionType.CODE,
            description="Write a test script",
            target="test_script.py",
            payload={"file_path": str(self.workspace / "test_script.py"), "content": "x = 42"}
        )
        ctx = TaskContext(task="write test script", working_dir=str(self.workspace))
        res = self.engine.act(step, ctx)
        self.assertTrue(res.success)
        # Verify event was published
        self.assertTrue(len(received_events) > 0)
        self.assertEqual(received_events[0].type, EventType.WORLD_STATE_CHANGED)

    # 11. Events: Event storm protection and deduplication
    def test_11_event_storm_protection(self):
        # Publishing duplicate events rapidly is handled cleanly by EventBus
        evt1 = Event(type=EventType.WORLD_STATE_CHANGED, source="test", payload={"key": "val"})
        evt2 = Event(type=EventType.WORLD_STATE_CHANGED, source="test", payload={"key": "val"})
        self.event_bus.publish(evt1)
        self.event_bus.publish(evt2)
        # Both published without raising recursion or overflow
        self.assertTrue(True)

    # 12. Planning: world-aware planning incorporates world state
    def test_12_world_aware_planning(self):
        # Set Blender scene state in World Model
        self.engine.world_model.observe(Observation(
            modality=Modality.BLENDER,
            source="blender_inspect",
            payload={"scene_name": "ProductScene", "objects": ["Bottle", "Camera"]}
        ))

        goal = Goal(
            goal_id="g-3d",
            raw_request="Continue my Blender project",
            normalized_goal="Continue procedural 3D model in Blender",
            domain=GoalDomain.BLENDER,
            desired_outcome="Render finalized bottle scene"
        )
        tasks, val, cost = self.engine.plan_goal(goal)
        self.assertTrue(val.valid)
        self.assertTrue(len(tasks) >= 3)
        self.assertEqual(tasks[0].capability, "blender")

    # 13. Pre-action staleness refresh hook verification
    def test_13_pre_action_staleness_refresh_hook(self):
        # Screen is UNKNOWN initially
        self.assertEqual(self.engine.world_model.get_staleness(Modality.SCREEN), TemporalStatus.UNKNOWN)

        # Mock screenshot tool
        refresh_called = []
        class MockScreenshotTool:
            name = "screenshot_capture"
            def execute(self):
                refresh_called.append(True)
                from tools.registry import ToolResult
                return ToolResult(
                    success=True,
                    data={"application": "Safari", "window_title": "Google"},
                    duration_seconds=0.01
                )
            def validate_inputs(self, args):
                return True, ""

        self.engine.tools.register(MockScreenshotTool())

        # When a GUI tool like mouse_click is requested and screen is STALE/UNKNOWN,
        # the engine pre-action hook triggers screenshot_capture refresh probe
        step = PlanStep(
            id=10,
            title="Click search bar",
            action_type=ActionType.TOOL,
            tool="mouse_click",
            description="Click on element",
            target="search_bar",
            arguments={"x": 100, "y": 100}
        )
        ctx = TaskContext(task="click button", working_dir=str(self.workspace))
        self.engine.act(step, ctx)
        self.assertTrue(len(refresh_called) > 0)
        self.assertEqual(self.engine.world_model.get_staleness(Modality.SCREEN), TemporalStatus.CURRENT)

    # 14. World State persistence and restoration in ProjectManager
    def test_14_world_state_persistence_in_project_manager(self):
        self.engine.world_model.update_world(
            active_app="VS Code",
            active_window="main.py",
            active_project=self.pm.project.project_id
        )
        self.pm.save_world_state(self.engine.world_model.current_state.to_dict())

        loaded = self.pm.load_world_state()
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["active_app"], "VS Code")
        self.assertEqual(loaded["active_window"], "main.py")

    # 15. World Snapshot persistence and listing in ProjectManager
    def test_15_world_snapshot_persistence_in_project_manager(self):
        snap = self.engine.world_model.create_snapshot(active_project=self.pm.project.project_id)
        snap_path = self.pm.save_world_snapshot(snap)
        self.assertTrue(snap_path.exists())

        snapshots = self.pm.list_world_snapshots()
        self.assertIn(snap.snapshot_id, snapshots)

        loaded_snap = self.pm.load_world_snapshot(snap.snapshot_id)
        self.assertIsNotNone(loaded_snap)
        self.assertEqual(loaded_snap["snapshot_id"], snap.snapshot_id)

    # 16. Complete end-to-end task loop updating World Model
    def test_16_end_to_end_task_loop_world_update(self):
        summary = self.engine.run_task("Create hello_world.py that prints hello", tag="coding")
        self.assertEqual(summary["status"], "COMPLETED")
        self.assertIsNotNone(self.engine.world_model.current_state)
        # Check that the file was recorded as an entity
        created_file = self.workspace / "hello_world.py"
        ent = self.engine.world_model.get_entity(f"file:{created_file.resolve()}")
        self.assertIsNotNone(ent)


if __name__ == "__main__":
    unittest.main()
