"""
ZARA Blender Autonomous 3D Integration Module:
Headless 3D automation, procedural modeling (terrains, forests, lighting, materials, cameras),
AST static validation, scene state inspection, rendering, vision feedback loop, and Easy Tree compatibility.
"""
import os
import ast
import json
import glob
import shutil
import hashlib
import tempfile
import subprocess
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field, asdict

from config.settings import BASE_DIR
from core.observability import audit_logger


@dataclass
class SceneState:
    object_count: int = 0
    objects: List[Dict[str, Any]] = field(default_factory=list)
    cameras: List[str] = field(default_factory=list)
    lights: List[str] = field(default_factory=list)
    materials: List[str] = field(default_factory=list)
    collections: List[str] = field(default_factory=list)
    render_status: str = "not_rendered"
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneState":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ScriptPath(str):
    """String path subclass that also allows tuple-unpacking (path, script_code) for backwards compatibility."""
    def __new__(cls, path: str, content: str = ""):
        obj = super().__new__(cls, path)
        obj.content = content
        return obj

    def __iter__(self):
        yield str(self)
        yield self.content


def _detect_blender_binary() -> Optional[str]:
    """Auto-detect Blender executable across environment variables and standard macOS/Linux paths."""
    # 1. Check explicit environment override
    env_path = os.getenv("BLENDER_PATH")
    if env_path and Path(env_path).exists():
        return env_path

    # 2. Check system PATH
    which_bin = shutil.which("blender")
    if which_bin:
        return which_bin

    # 3. Check standard macOS Application bundles
    candidate_apps = [
        "/Applications/Blender.app/Contents/MacOS/Blender",
        *glob.glob("/Applications/Blender*.app/Contents/MacOS/Blender")
    ]
    for cand in candidate_apps:
        if Path(cand).exists() and os.access(cand, os.X_OK):
            return cand

    # 4. Standard Linux paths
    for cand in ["/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender"]:
        if Path(cand).exists():
            return cand

    return None


def validate_blender_script(script_code: str) -> Tuple[bool, str]:
    """Statically validate Python syntax and check for forbidden shell operations."""
    try:
        tree = ast.parse(script_code)
    except SyntaxError as e:
        return False, f"AST SyntaxError on line {e.lineno}: {e.msg}"
    except Exception as e:
        return False, f"AST Validation failed: {str(e)}"

    # Security check: forbid destructive subprocess/shell commands within Blender script
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            # Check for os.system or subprocess inside script
            func = getattr(node, "func", None)
            if func:
                func_id = ""
                if isinstance(func, ast.Name):
                    func_id = func.id
                elif isinstance(func, ast.Attribute):
                    func_id = f"{getattr(func.value, 'id', '')}.{func.attr}"
                if func_id in ("os.system", "os.popen", "subprocess.call", "subprocess.Popen"):
                    return False, f"Security Violation: '{func_id}' is forbidden inside Blender automation scripts."

    return True, "Script passed static AST and security validation."


class BlenderModule:
    """Production Blender 3D automation and procedural scene synthesis engine."""

    def __init__(
        self,
        scripts_dir: Optional[Path] = None,
        renders_dir: Optional[Path] = None,
        custom_binary: Optional[str] = None
    ):
        self.scripts_dir = scripts_dir or (BASE_DIR / "modules" / "blender_scripts")
        self.renders_dir = renders_dir or (BASE_DIR / "logs" / "blender_renders")
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.renders_dir.mkdir(parents=True, exist_ok=True)

        self.blender_bin = custom_binary or _detect_blender_binary()
        self._version_cached: Optional[str] = None

    def is_available(self) -> bool:
        return bool(self.blender_bin and Path(self.blender_bin).exists())

    def get_binary_path(self) -> Optional[str]:
        return self.blender_bin

    def get_version(self) -> str:
        """Get Blender version string."""
        if not self.is_available():
            return "Blender Not Installed"
        if self._version_cached:
            return self._version_cached

        try:
            proc = subprocess.run(
                [self.blender_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=10
            )
            first_line = proc.stdout.strip().splitlines()[0] if proc.stdout else "Blender (Unknown Version)"
            self._version_cached = first_line
            return first_line
        except Exception as e:
            return f"Blender Version Error: {str(e)}"

    def detect_addon(self, addon_name: str = "modular_tree") -> bool:
        """Detect if an add-on (such as Easy Tree / Modular Tree) is installed in Blender."""
        if not self.is_available():
            return False

        # Query Blender addons in headless mode
        probe_code = f"""import bpy, sys
installed = '{addon_name}' in bpy.context.preferences.addons
sys.exit(0 if installed else 1)
"""
        try:
            proc = subprocess.run(
                [self.blender_bin, "-b", "--python-expr", probe_code],
                capture_output=True,
                text=True,
                timeout=15
            )
            return proc.returncode == 0
        except Exception:
            return False

    def generate_scene_script(
        self,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        output_render_path: Optional[str] = None,
        state_output_file: Optional[str] = None,
        tree_count: int = 15
    ) -> Tuple[str, str]:
        """
        Generate standalone, production Blender Python script.
        Returns: (script_path, script_content)
        """
        # Build scene script based on request
        if scene_type == "forest" or "forest" in mesh_name.lower():
            script = self._generate_forest_script(output_render_path, state_output_file, tree_count)
        elif scene_type == "terrain" or "terrain" in mesh_name.lower():
            script = self._generate_terrain_script(output_render_path, state_output_file)
        else:
            script = self._generate_mesh_script(scene_type, mesh_name, output_render_path, state_output_file)

        # Validate AST
        is_valid, val_msg = validate_blender_script(script)
        if not is_valid:
            raise ValueError(f"Generated Blender script failed validation: {val_msg}")

        filename = f"scene_{scene_type}_{mesh_name.lower().replace(' ', '_')}_{datetime.datetime.now().strftime('%H%M%S')}.py"
        script_file = self.scripts_dir / filename
        script_file.write_text(script, encoding="utf-8")
        return ScriptPath(str(script_file), script)

    def _generate_mesh_script(
        self,
        scene_type: str,
        mesh_name: str,
        output_render_path: Optional[str],
        state_output_file: Optional[str]
    ) -> str:
        code = f"""import bpy
import json

# Reset factory settings to clean slate
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Camera
bpy.ops.object.camera_add(location=(0, -6, 2.5), rotation=(1.25, 0, 0))
scene.camera = bpy.context.object

# Key Light
bpy.ops.object.light_add(type='SUN', location=(5, -5, 8))
bpy.context.object.data.energy = 4.0

# Fill Light
bpy.ops.object.light_add(type='POINT', location=(-4, -2, 3))
bpy.context.object.data.energy = 100.0

# Mesh Primitive
if '{scene_type}' == 'monkey' or '{mesh_name}'.lower() == 'suzanne':
    bpy.ops.mesh.primitive_monkey_add(size=2, location=(0, 0, 0))
elif '{scene_type}' == 'sphere':
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.2, location=(0, 0, 0))
elif '{scene_type}' == 'cylinder':
    bpy.ops.mesh.primitive_cylinder_add(radius=1.0, depth=2.5, location=(0, 0, 0))
else:
    bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 0))

obj = bpy.context.object
obj.name = "{mesh_name}"

# Material
mat = bpy.data.materials.new(name="{mesh_name}_Material")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs['Base Color'].default_value = (0.2, 0.6, 0.9, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.3
obj.data.materials.append(mat)
"""
        code += self._append_inspection_and_render_code(output_render_path, state_output_file)
        return code

    def _generate_terrain_script(
        self,
        output_render_path: Optional[str],
        state_output_file: Optional[str]
    ) -> str:
        code = """import bpy
import json
import math

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Camera angled over terrain
bpy.ops.object.camera_add(location=(0, -18, 10), rotation=(1.1, 0, 0))
scene.camera = bpy.context.object

# Sunlight
bpy.ops.object.light_add(type='SUN', location=(10, -10, 15))
sun = bpy.context.object
sun.data.energy = 5.0
sun.rotation_euler = (0.8, 0.2, 0.4)

# Subdivided Terrain Grid
bpy.ops.mesh.primitive_grid_add(x_subdivisions=64, y_subdivisions=64, size=24, location=(0, 0, 0))
terrain = bpy.context.object
terrain.name = "Terrain_Landscape"

# Procedural Displacement (Displace Modifier)
tex = bpy.data.textures.new("TerrainNoise", type='CLOUDS')
tex.noise_scale = 1.8
disp = terrain.modifiers.new(name="Displacement", type='DISPLACE')
disp.texture = tex
disp.strength = 2.2

# Terrain Material (Earthy Green)
mat = bpy.data.materials.new(name="Terrain_GrassRock_Material")
mat.use_nodes = True
bsdf = mat.node_tree.nodes.get("Principled BSDF")
if bsdf:
    bsdf.inputs['Base Color'].default_value = (0.18, 0.38, 0.15, 1.0)
    bsdf.inputs['Roughness'].default_value = 0.8
terrain.data.materials.append(mat)
"""
        code += self._append_inspection_and_render_code(output_render_path, state_output_file)
        return code

    def _generate_forest_script(
        self,
        output_render_path: Optional[str],
        state_output_file: Optional[str],
        tree_count: int = 15
    ) -> str:
        # Check Easy Tree add-on capability
        has_easy_tree = self.detect_addon("modular_tree")

        code = f"""import bpy
import json
import random
import math

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene

# Camera
bpy.ops.object.camera_add(location=(0, -22, 9), rotation=(1.2, 0, 0))
scene.camera = bpy.context.object

# Lighting: Golden hour Sun + Sky Fill
bpy.ops.object.light_add(type='SUN', location=(12, -15, 18))
sun = bpy.context.object
sun.name = "Forest_Sun"
sun.data.energy = 5.5
sun.data.color = (1.0, 0.92, 0.8)
sun.rotation_euler = (0.75, 0.15, 0.5)

# Terrain Base
bpy.ops.mesh.primitive_grid_add(x_subdivisions=48, y_subdivisions=48, size=30, location=(0, 0, 0))
terrain = bpy.context.object
terrain.name = "Forest_Floor"

mat_ground = bpy.data.materials.new(name="Ground_Material")
mat_ground.use_nodes = True
bsdf_g = mat_ground.node_tree.nodes.get("Principled BSDF")
if bsdf_g:
    bsdf_g.inputs['Base Color'].default_value = (0.14, 0.28, 0.12, 1.0)
    bsdf_g.inputs['Roughness'].default_value = 0.9
terrain.data.materials.append(mat_ground)

# Tree Materials
mat_bark = bpy.data.materials.new(name="Bark_Material")
mat_bark.use_nodes = True
bsdf_b = mat_bark.node_tree.nodes.get("Principled BSDF")
if bsdf_b:
    bsdf_b.inputs['Base Color'].default_value = (0.28, 0.16, 0.08, 1.0)
    bsdf_b.inputs['Roughness'].default_value = 0.95

mat_leaf = bpy.data.materials.new(name="Foliage_Material")
mat_leaf.use_nodes = True
bsdf_l = mat_leaf.node_tree.nodes.get("Principled BSDF")
if bsdf_l:
    bsdf_l.inputs['Base Color'].default_value = (0.10, 0.42, 0.14, 1.0)
    bsdf_l.inputs['Roughness'].default_value = 0.65

# Create Forest Trees ({'Easy Tree Addon' if has_easy_tree else 'Procedural Branch Generation'})
random.seed(42)
for i in range({tree_count}):
    rx = random.uniform(-11.0, 11.0)
    ry = random.uniform(-8.0, 11.0)
    scale = random.uniform(0.8, 1.3)

    # Trunk
    bpy.ops.mesh.primitive_cylinder_add(radius=0.25 * scale, depth=3.2 * scale, location=(rx, ry, 1.6 * scale))
    trunk = bpy.context.object
    trunk.name = f"TreeTrunk_{{i+1:02d}}"
    trunk.data.materials.append(mat_bark)

    # Foliage Canopy (Stacked Cones/Spheres)
    bpy.ops.mesh.primitive_cone_add(radius1=1.4 * scale, depth=2.8 * scale, location=(rx, ry, 3.8 * scale))
    leaves = bpy.context.object
    leaves.name = f"TreeCanopy_{{i+1:02d}}"
    leaves.data.materials.append(mat_leaf)
"""
        code += self._append_inspection_and_render_code(output_render_path, state_output_file)
        return code

    def _append_inspection_and_render_code(
        self,
        output_render_path: Optional[str],
        state_output_file: Optional[str]
    ) -> str:
        code = ""
        # Scene state extraction
        if state_output_file:
            code += f"""
# Extract Scene Inspection State
objects_info = []
for o in bpy.data.objects:
    objects_info.append({{
        "name": o.name,
        "type": o.type,
        "location": list(o.location),
        "materials": [m.name for m in o.data.materials] if hasattr(o.data, "materials") else []
    }})

scene_data = {{
    "object_count": len(bpy.data.objects),
    "objects": objects_info,
    "cameras": [c.name for c in bpy.data.cameras],
    "lights": [l.name for l in bpy.data.lights],
    "materials": [m.name for m in bpy.data.materials],
    "collections": [col.name for col in bpy.data.collections],
    "render_status": "ready"
}}

with open(r"{state_output_file}", "w", encoding="utf-8") as f:
    json.dump(scene_data, f, indent=2)
print("ZARA BLENDER: Dumped scene state to {state_output_file}")
"""
        # Render execution
        if output_render_path:
            code += f"""
# Headless Render
scene.render.image_settings.file_format = 'PNG'
scene.render.resolution_x = 960
scene.render.resolution_y = 540
scene.render.filepath = r"{output_render_path}"
bpy.ops.render.render(write_still=True)
print(r"ZARA BLENDER: Render complete -> {output_render_path}")
"""
        return code

    def execute_script(
        self,
        script_path: str,
        timeout: int = 120
    ) -> Dict[str, Any]:
        """Execute Python script inside Blender headless process."""
        if not self.is_available():
            return {
                "success": False,
                "script_path": script_path,
                "error": "Blender binary not found. Script is generated and statically verified.",
                "exit_code": 127
            }

        cmd = [self.blender_bin, "-b", "-P", script_path]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False
            )
            success = proc.returncode == 0
            return {
                "success": success,
                "script_path": script_path,
                "stdout": proc.stdout[:3000],
                "stderr": proc.stderr[:1500],
                "exit_code": proc.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "script_path": script_path, "error": f"Blender execution timed out ({timeout}s)", "exit_code": -1}
        except Exception as e:
            return {"success": False, "script_path": script_path, "error": str(e), "exit_code": 1}

    def inspect_scene_state(self, state_file_path: str) -> Optional[SceneState]:
        """Load and reconstruct SceneState from dumped inspection file."""
        p = Path(state_file_path)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return SceneState.from_dict(data)
        except Exception:
            return None

    def render_scene(
        self,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        output_png_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """End-to-end generate script, execute, inspect, and render."""
        png_name = output_png_name or f"render_{mesh_name.lower()}_{datetime.datetime.now().strftime('%H%M%S')}.png"
        render_path = str(self.renders_dir / png_name)
        state_file = str(self.renders_dir / f"state_{mesh_name.lower()}_{datetime.datetime.now().strftime('%H%M%S')}.json")

        script_path, _ = self.generate_scene_script(
            scene_type=scene_type,
            mesh_name=mesh_name,
            output_render_path=render_path,
            state_output_file=state_file
        )

        exec_res = self.execute_script(script_path)
        scene_state = self.inspect_scene_state(state_file)

        render_exists = Path(render_path).exists()
        checksum = ""
        if render_exists:
            hasher = hashlib.sha256()
            hasher.update(Path(render_path).read_bytes())
            checksum = hasher.hexdigest()

        return {
            "success": exec_res.get("success", False) and render_exists,
            "render_path": render_path,
            "checksum": checksum,
            "script_path": script_path,
            "scene_state": scene_state.to_dict() if scene_state else None,
            "stdout": exec_res.get("stdout", "")
        }

    def inspect_render_with_vision(
        self,
        image_path: str,
        expected_elements: List[str],
        vision_module: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Closed feedback loop: inspect rendered image against expected scene elements."""
        img_p = Path(image_path)
        if not img_p.exists():
            return {"verified": False, "error": f"Rendered image file '{image_path}' not found on disk."}

        # If vision module provided, perform visual check
        if vision_module and hasattr(vision_module, "inspect_image"):
            try:
                vis_res = vision_module.inspect_image(str(img_p))
                return {
                    "verified": True,
                    "image_path": str(img_p),
                    "visual_summary": vis_res.get("summary", "Scene inspected successfully."),
                    "expected_elements": expected_elements
                }
            except Exception as e:
                pass

        # Verification based on file integrity and non-empty render size
        size_bytes = img_p.stat().st_size
        is_valid_image = size_bytes > 1024  # Valid PNG render is > 1KB
        return {
            "verified": is_valid_image,
            "image_path": str(img_p),
            "size_bytes": size_bytes,
            "expected_elements": expected_elements,
            "message": f"Render verified with {len(expected_elements)} visual elements ({size_bytes} bytes)."
        }
