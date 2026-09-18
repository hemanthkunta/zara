"""
Tests for ZARA Phase 9: Autonomous Blender 3D Subsystem.
Headless binary detection, AST static validation, procedural scene synthesis
(meshes, terrain, realistic forests), scene state inspection, headless rendering,
vision feedback inspection loop, and tool integrations.
"""
import unittest
import tempfile
from pathlib import Path
from typing import Dict, Any

from modules.blender import (
    BlenderModule,
    SceneState,
    validate_blender_script,
    _detect_blender_binary
)
from tools.blender_tools import (
    BlenderScriptTool,
    BlenderExecuteTool,
    BlenderInspectTool,
    BlenderRenderTool
)
from modules.workspace import ProjectManager, ProjectType
from core.engine import ZaraEngine


class TestBlenderCoreAndValidation(unittest.TestCase):
    """Verify binary detection, version probing, and AST security validation."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scripts_dir = Path(self.tmp_dir.name) / "scripts"
        self.renders_dir = Path(self.tmp_dir.name) / "renders"
        self.blender = BlenderModule(
            scripts_dir=self.scripts_dir,
            renders_dir=self.renders_dir
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_01_detect_blender_binary(self):
        bin_path = _detect_blender_binary()
        # Blender is installed at /Applications/Blender.app/Contents/MacOS/Blender on this machine
        self.assertIsNotNone(bin_path)
        self.assertTrue(Path(bin_path).exists())

    def test_02_blender_is_available(self):
        self.assertTrue(self.blender.is_available())
        path = self.blender.get_binary_path()
        self.assertIn("Blender", path)

    def test_03_blender_version_probe(self):
        ver = self.blender.get_version()
        self.assertIn("Blender", ver)

    def test_04_ast_validation_valid_script(self):
        code = """import bpy
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))
"""
        is_valid, msg = validate_blender_script(code)
        self.assertTrue(is_valid)
        self.assertIn("passed", msg)

    def test_05_ast_validation_syntax_error(self):
        bad_code = "import bpy\ndef broken_func(:\n    pass"
        is_valid, msg = validate_blender_script(bad_code)
        self.assertFalse(is_valid)
        self.assertIn("SyntaxError", msg)

    def test_06_ast_validation_forbids_os_system(self):
        malicious_code = """import bpy, os
os.system("rm -rf /tmp/test")
"""
        is_valid, msg = validate_blender_script(malicious_code)
        self.assertFalse(is_valid)
        self.assertIn("Security Violation", msg)

    def test_07_ast_validation_forbids_subprocess(self):
        malicious_code = """import bpy, subprocess
subprocess.call(["whoami"])
"""
        is_valid, msg = validate_blender_script(malicious_code)
        self.assertFalse(is_valid)
        self.assertIn("Security Violation", msg)

    def test_08_addon_detection_fallback(self):
        # Non-existent addon should return False safely without raising
        has_addon = self.blender.detect_addon("non_existent_fake_addon_12345")
        self.assertFalse(has_addon)


class TestBlenderProceduralGeneration(unittest.TestCase):
    """Verify procedural generation of Suzanne meshes, undulating terrain, and forest canopy."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scripts_dir = Path(self.tmp_dir.name) / "scripts"
        self.renders_dir = Path(self.tmp_dir.name) / "renders"
        self.blender = BlenderModule(
            scripts_dir=self.scripts_dir,
            renders_dir=self.renders_dir
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_09_generate_suzanne_mesh_script(self):
        script_path, content = self.blender.generate_scene_script(
            scene_type="monkey",
            mesh_name="Suzanne"
        )
        self.assertTrue(Path(script_path).exists())
        self.assertIn("primitive_monkey_add", content)
        self.assertIn("Principled BSDF", content)

    def test_10_generate_sphere_mesh_script(self):
        script_path, content = self.blender.generate_scene_script(
            scene_type="sphere",
            mesh_name="CrystalOrb"
        )
        self.assertTrue(Path(script_path).exists())
        self.assertIn("primitive_uv_sphere_add", content)
        self.assertIn("CrystalOrb", content)

    def test_11_generate_procedural_terrain_script(self):
        script_path, content = self.blender.generate_scene_script(
            scene_type="terrain",
            mesh_name="HighlandRidge"
        )
        self.assertTrue(Path(script_path).exists())
        self.assertIn("primitive_grid_add", content)
        self.assertIn("Terrain_Landscape", content)
        self.assertIn("Roughness", content)

    def test_12_generate_procedural_forest_script(self):
        script_path, content = self.blender.generate_scene_script(
            scene_type="forest",
            mesh_name="OakForest",
            tree_count=12
        )
        self.assertTrue(Path(script_path).exists())
        self.assertIn("Forest_Floor", content)
        self.assertIn("TreeTrunk", content)
        self.assertIn("TreeCanopy", content)


class TestBlenderExecutionAndRendering(unittest.TestCase):
    """Verify headless execution, inspection state dumping, rendering, and vision feedback loop."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.scripts_dir = Path(self.tmp_dir.name) / "scripts"
        self.renders_dir = Path(self.tmp_dir.name) / "renders"
        self.blender = BlenderModule(
            scripts_dir=self.scripts_dir,
            renders_dir=self.renders_dir
        )

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_13_headless_execute_clean_script(self):
        test_py = self.scripts_dir / "test_exec.py"
        test_py.write_text("import bpy\nprint('ZARA BLENDER LIVE EXECUTION SUCCESS')\n", encoding="utf-8")
        res = self.blender.execute_script(str(test_py), timeout=30)
        self.assertTrue(res.get("success"))
        self.assertIn("ZARA BLENDER LIVE EXECUTION SUCCESS", res.get("stdout", ""))

    def test_14_scene_state_dataclass_serialization(self):
        state = SceneState(
            object_count=4,
            objects=[{"name": "Suzanne", "type": "MESH"}],
            cameras=["Camera"],
            lights=["SunLight"],
            materials=["Suzanne_Material"],
            collections=["Collection"],
            render_status="ready"
        )
        d = state.to_dict()
        self.assertEqual(d["object_count"], 4)
        self.assertEqual(len(d["objects"]), 1)

        restored = SceneState.from_dict(d)
        self.assertEqual(restored.object_count, 4)
        self.assertEqual(restored.cameras, ["Camera"])

    def test_15_end_to_end_render_mesh(self):
        """Execute real headless Blender render for Suzanne monkey primitive."""
        res = self.blender.render_scene(
            scene_type="monkey",
            mesh_name="SuzanneTest",
            output_png_name="suzanne_test.png"
        )
        self.assertTrue(res.get("success"))
        self.assertTrue(Path(res["render_path"]).exists())
        self.assertTrue(len(res.get("checksum", "")) == 64)  # SHA-256 hex string

        # Validate dumped scene state
        scene_state = res.get("scene_state")
        self.assertIsNotNone(scene_state)
        self.assertGreaterEqual(scene_state.get("object_count", 0), 3)  # Camera, Light, Mesh

    def test_16_end_to_end_render_forest(self):
        """Execute real headless Blender render for procedural forest scene."""
        res = self.blender.render_scene(
            scene_type="forest",
            mesh_name="MiniGrove",
            output_png_name="forest_grove.png"
        )
        self.assertTrue(res.get("success"))
        img_p = Path(res["render_path"])
        self.assertTrue(img_p.exists())
        self.assertGreater(img_p.stat().st_size, 2048)  # Valid PNG render > 2KB

        scene_state = res.get("scene_state")
        self.assertIsNotNone(scene_state)
        self.assertGreaterEqual(len(scene_state.get("materials", [])), 2)

    def test_17_vision_feedback_inspection_loop(self):
        # Render scene first
        res = self.blender.render_scene(
            scene_type="cylinder",
            mesh_name="Pillar",
            output_png_name="pillar.png"
        )
        self.assertTrue(res.get("success"))

        # Inspect render via vision module loop
        vis_res = self.blender.inspect_render_with_vision(
            image_path=res["render_path"],
            expected_elements=["Pillar", "Lighting", "Shadow"]
        )
        self.assertTrue(vis_res.get("verified"))
        self.assertEqual(len(vis_res.get("expected_elements", [])), 3)
        self.assertGreater(vis_res.get("size_bytes", 0), 1024)


class TestBlenderWorkspaceAndTools(unittest.TestCase):
    """Verify tool wrappers, project templates, and engine registration."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.tmp_dir.name)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_18_create_blender_scene_project_dag(self):
        mgr = ProjectManager.create_blender_scene_project(
            name="Suzanne Hero Shot",
            workspace_path=self.workspace_path,
            scene_type="monkey",
            mesh_name="Suzanne"
        )
        self.assertEqual(mgr.project.project_type, ProjectType.BLENDER_SCENE)
        tasks = mgr.dag.list_tasks()
        self.assertEqual(len(tasks), 6)
        task_ids = [t.id for t in tasks]
        self.assertIn("task_blender_binary_check", task_ids)
        self.assertIn("task_generate_scene_script", task_ids)
        self.assertIn("task_ast_security_validation", task_ids)
        self.assertIn("task_headless_render", task_ids)
        self.assertIn("task_scene_inspection", task_ids)
        self.assertIn("task_vision_verification", task_ids)

    def test_19_create_blender_environment_project_dag(self):
        mgr = ProjectManager.create_blender_environment_project(
            name="Whispering Pines Forest",
            workspace_path=self.workspace_path,
            tree_count=25
        )
        self.assertEqual(mgr.project.project_type, ProjectType.BLENDER_ENVIRONMENT)
        tasks = mgr.dag.list_tasks()
        self.assertEqual(len(tasks), 6)
        task_ids = [t.id for t in tasks]
        self.assertIn("task_env_addon_check", task_ids)
        self.assertIn("task_env_generate_script", task_ids)
        self.assertIn("task_env_ast_validation", task_ids)
        self.assertIn("task_env_headless_render", task_ids)
        self.assertIn("task_env_scene_inspection", task_ids)
        self.assertIn("task_env_vision_verification", task_ids)

    def test_20_blender_tools_registered_in_engine(self):
        engine = ZaraEngine(workspace_root=str(self.workspace_path), enable_voice=False)
        tool_names = engine.tools.list_tool_names()
        self.assertIn("blender_generate_script", tool_names)
        self.assertIn("blender_execute_script", tool_names)
        self.assertIn("blender_inspect_scene", tool_names)
        self.assertIn("blender_render_scene", tool_names)

    def test_21_blender_script_tool_run(self):
        tool = BlenderScriptTool()
        res = tool.run(scene_type="sphere", mesh_name="Orb")
        self.assertTrue(res.success)
        self.assertIn("script_path", res.data)
        self.assertTrue(Path(res.data["script_path"]).exists())

    def test_22_blender_render_tool_run(self):
        tool = BlenderRenderTool()
        res = tool.run(scene_type="basic_mesh", mesh_name="TestCube", output_png_name="cube_tool.png")
        self.assertTrue(res.success)
        self.assertIn("render_path", res.data)
        self.assertTrue(Path(res.data["render_path"]).exists())


if __name__ == "__main__":
    unittest.main()
