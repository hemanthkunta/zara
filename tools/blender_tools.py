"""
ZARA Blender Integration Tools:
Autonomous 3D modeling, procedural generation, scene state inspection,
and headless rendering tools.
"""
from typing import Dict, Any, Optional, List
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel
from modules.blender import BlenderModule, validate_blender_script


class BlenderScriptTool(BaseTool):
    """Generate a valid, production-ready Blender Python procedural modeling script."""

    def __init__(self, blender_module: Optional[BlenderModule] = None):
        super().__init__(
            name="blender_generate_script",
            description="Generate a standalone Blender Python script for meshes, terrain, or realistic forests.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "scene_type": {
                        "type": "string",
                        "enum": ["basic_mesh", "monkey", "sphere", "cylinder", "terrain", "forest"],
                        "description": "Type of 3D scene to generate."
                    },
                    "mesh_name": {
                        "type": "string",
                        "description": "Primary mesh or asset name."
                    },
                    "tree_count": {
                        "type": "integer",
                        "description": "Number of trees if scene_type is forest."
                    }
                },
                "required": ["scene_type"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=30
        )
        self.blender = blender_module or BlenderModule()

    def run(
        self,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        tree_count: int = 15,
        **kwargs
    ) -> ToolResult:
        try:
            script_path, script_code = self.blender.generate_scene_script(
                scene_type=scene_type,
                mesh_name=mesh_name,
                tree_count=tree_count
            )
            return ToolResult(
                success=True,
                data={
                    "script_path": script_path,
                    "scene_type": scene_type,
                    "mesh_name": mesh_name,
                    "script_snippet": script_code[:500] + "..." if len(script_code) > 500 else script_code
                }
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))


class BlenderExecuteTool(BaseTool):
    """Execute a Blender Python script in headless background mode."""

    def __init__(self, blender_module: Optional[BlenderModule] = None):
        super().__init__(
            name="blender_execute_script",
            description="Execute a validated Python script inside headless Blender.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "script_path": {
                        "type": "string",
                        "description": "Path to the Python script to execute inside Blender."
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Subprocess timeout in seconds."
                    }
                },
                "required": ["script_path"]
            },
            risk_level=RiskLevel.MEDIUM,
            timeout_seconds=120
        )
        self.blender = blender_module or BlenderModule()

    def run(self, script_path: str, timeout: int = 120, **kwargs) -> ToolResult:
        res = self.blender.execute_script(script_path=script_path, timeout=timeout)
        return ToolResult(
            success=res.get("success", False),
            data=res,
            error=res.get("error")
        )


class BlenderInspectTool(BaseTool):
    """Inspect the scene state and object hierarchy from a Blender scene inspection file."""

    def __init__(self, blender_module: Optional[BlenderModule] = None):
        super().__init__(
            name="blender_inspect_scene",
            description="Inspect objects, lights, cameras, and materials from a dumped scene state JSON.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "state_file_path": {
                        "type": "string",
                        "description": "Path to JSON dumped scene state."
                    }
                },
                "required": ["state_file_path"]
            },
            risk_level=RiskLevel.LOW,
            timeout_seconds=15
        )
        self.blender = blender_module or BlenderModule()

    def run(self, state_file_path: str, **kwargs) -> ToolResult:
        state = self.blender.inspect_scene_state(state_file_path)
        if not state:
            return ToolResult(
                success=False,
                data=None,
                error=f"Could not load or parse scene state from '{state_file_path}'."
            )
        return ToolResult(
            success=True,
            data=state.to_dict(),
            error=None
        )


class BlenderRenderTool(BaseTool):
    """End-to-end procedural scene creation, headless execution, and PNG rendering."""

    def __init__(self, blender_module: Optional[BlenderModule] = None):
        super().__init__(
            name="blender_render_scene",
            description="Procedurally build, execute, inspect, and render a 3D scene to PNG.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "scene_type": {
                        "type": "string",
                        "enum": ["basic_mesh", "monkey", "sphere", "cylinder", "terrain", "forest"],
                        "description": "Type of 3D scene."
                    },
                    "mesh_name": {
                        "type": "string",
                        "description": "Primary asset name."
                    },
                    "output_png_name": {
                        "type": "string",
                        "description": "Optional custom filename for output PNG render."
                    }
                },
                "required": ["scene_type"]
            },
            risk_level=RiskLevel.MEDIUM,
            timeout_seconds=180
        )
        self.blender = blender_module or BlenderModule()

    def run(
        self,
        scene_type: str = "basic_mesh",
        mesh_name: str = "Suzanne",
        output_png_name: Optional[str] = None,
        **kwargs
    ) -> ToolResult:
        res = self.blender.render_scene(
            scene_type=scene_type,
            mesh_name=mesh_name,
            output_png_name=output_png_name
        )
        return ToolResult(
            success=res.get("success", False),
            data=res,
            error=res.get("error")
        )
