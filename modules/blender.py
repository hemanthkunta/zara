"""
ZARA Blender Module: Headless automation and Python script synthesis for 3D scenes.
Isolated from core reasoning engine.
"""
from pathlib import Path
import subprocess
import shutil
from typing import Dict, Any, Optional
from config.settings import BASE_DIR

class BlenderModule:
    def __init__(self, scripts_dir: Path = BASE_DIR / "modules" / "blender_scripts"):
        self.scripts_dir = scripts_dir
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.blender_bin = shutil.which("blender")

    def generate_scene_script(
        self,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        output_render_path: Optional[str] = None
    ) -> str:
        """Generate a standalone Python script runnable by Blender's embedded Python engine."""
        script = f"""import bpy

# Clear existing objects
bpy.ops.wm.read_factory_settings(use_empty=True)

# Create collection and scene
scene = bpy.context.scene

# Add camera
bpy.ops.object.camera_add(location=(0, -6, 2), rotation=(1.3, 0, 0))
scene.camera = bpy.context.object

# Add light
bpy.ops.object.light_add(type='SUN', location=(4, -4, 5))

# Create requested mesh object
if '{scene_type}' == 'monkey' or '{mesh_name}'.lower() == 'suzanne':
    bpy.ops.mesh.primitive_monkey_add(size=2, location=(0, 0, 0))
elif '{scene_type}' == 'terrain':
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=32, y_subdivisions=32, size=10, location=(0, 0, 0))
else:
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))

obj = bpy.context.object
obj.name = "{mesh_name}"

# Add basic material
mat = bpy.data.materials.new(name="{mesh_name}_Material")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs['Base Color'].default_value = (0.2, 0.6, 0.9, 1.0)
obj.data.materials.append(mat)

print(f"ZARA BLENDER: Generated scene with object {{obj.name}} at {{obj.location}}")
"""
        if output_render_path:
            script += f"""
scene.render.image_settings.file_format = 'PNG'
scene.render.filepath = "{output_render_path}"
bpy.ops.render.render(write_still=True)
print("ZARA BLENDER: Rendered scene to {output_render_path}")
"""
        script_file = self.scripts_dir / f"scene_{mesh_name.lower()}.py"
        script_file.write_text(script, encoding="utf-8")
        return str(script_file)

    def execute_script(self, script_path: str) -> Dict[str, Any]:
        """Run script in Blender headless mode if Blender binary is available."""
        if not self.blender_bin:
            return {
                "success": False,
                "script_path": script_path,
                "error": "Blender binary not found on host. Script generated and ready for Blender execution."
            }
        try:
            proc = subprocess.run(
                [self.blender_bin, "-b", "-P", script_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            return {
                "success": (proc.returncode == 0),
                "script_path": script_path,
                "stdout": proc.stdout[:2000],
                "stderr": proc.stderr[:1000]
            }
        except Exception as e:
            return {"success": False, "script_path": script_path, "error": str(e)}
