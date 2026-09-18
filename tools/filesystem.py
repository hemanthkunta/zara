"""
ZARA Filesystem Tools: Secure workspace-confined file manipulation.
"""
from pathlib import Path
import ast
from typing import Dict, Any, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel, BASE_DIR

def _safe_resolve(workspace_root: Path, relative_path: str) -> Path:
    target = (workspace_root / relative_path).resolve()
    if not str(target).startswith(str(workspace_root.resolve())):
        raise ValueError(f"Path traversal detected: '{relative_path}' points outside workspace root.")
    return target

class ReadFileTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR):
        super().__init__(
            name="read_file",
            description="Read content of a file within the workspace.",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            },
            risk_level=RiskLevel.LOW
        )
        self.workspace_root = Path(workspace_root).resolve()

    def run(self, path: str) -> ToolResult:
        try:
            target = _safe_resolve(self.workspace_root, path)
            if not target.exists():
                return ToolResult(success=False, data=None, error=f"File '{path}' does not exist.")
            content = target.read_text(encoding="utf-8")
            return ToolResult(success=True, data=content)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

class WriteFileTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR):
        super().__init__(
            name="write_file",
            description="Write content to a file with optional syntax checking.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "validate_syntax": {"type": "boolean"}
                },
                "required": ["path", "content"]
            },
            risk_level=RiskLevel.MEDIUM
        )
        self.workspace_root = Path(workspace_root).resolve()

    def run(self, path: str, content: str, validate_syntax: bool = True) -> ToolResult:
        try:
            target = _safe_resolve(self.workspace_root, path)
            if validate_syntax and target.suffix == ".py":
                try:
                    ast.parse(content)
                except SyntaxError as e:
                    return ToolResult(
                        success=False,
                        data=None,
                        error=f"Python syntax error line {e.lineno}: {e.msg}"
                    )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, data=f"Successfully wrote {len(content)} bytes to {path}")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

class PatchFileTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR):
        super().__init__(
            name="patch_file",
            description="Perform targeted string replacement in an existing file.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_str": {"type": "string"},
                    "new_str": {"type": "string"}
                },
                "required": ["path", "old_str", "new_str"]
            },
            risk_level=RiskLevel.MEDIUM
        )
        self.workspace_root = Path(workspace_root).resolve()

    def run(self, path: str, old_str: str, new_str: str) -> ToolResult:
        try:
            target = _safe_resolve(self.workspace_root, path)
            if not target.exists():
                return ToolResult(success=False, data=None, error=f"File '{path}' does not exist.")
            content = target.read_text(encoding="utf-8")
            if old_str not in content:
                return ToolResult(success=False, data=None, error=f"Target string not found in '{path}'.")
            updated = content.replace(old_str, new_str, 1)
            target.write_text(updated, encoding="utf-8")
            return ToolResult(success=True, data=f"Patched '{path}' successfully.")
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))

class ListDirTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR):
        super().__init__(
            name="list_dir",
            description="List contents of a directory in the workspace.",
            parameters_schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": []
            },
            risk_level=RiskLevel.LOW
        )
        self.workspace_root = Path(workspace_root).resolve()

    def run(self, path: str = ".") -> ToolResult:
        try:
            target = _safe_resolve(self.workspace_root, path)
            if not target.exists() or not target.is_dir():
                return ToolResult(success=False, data=None, error=f"Directory '{path}' does not exist.")
            files = [str(p.relative_to(self.workspace_root)) for p in target.iterdir()]
            return ToolResult(success=True, data=files)
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
