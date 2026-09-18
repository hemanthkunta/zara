"""
ZARA Coding Module: File manipulation, syntax verification, AST analysis, and diff generation.
"""
from pathlib import Path
import ast
import difflib
from typing import Tuple, Optional, Dict, Any, List

class CodingModule:
    def __init__(self, workspace_root: str):
        self.workspace_root = Path(workspace_root).resolve()

    def resolve_path(self, relative_path: str) -> Path:
        target = (self.workspace_root / relative_path).resolve()
        if not str(target).startswith(str(self.workspace_root)):
            raise ValueError(f"Path traversal detected: '{relative_path}' is outside workspace root.")
        return target

    def read_file(self, relative_path: str) -> str:
        target = self.resolve_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")
        return target.read_text(encoding="utf-8")

    def write_file(self, relative_path: str, content: str, validate_syntax: bool = True) -> Tuple[bool, Optional[str]]:
        """Write content to file with optional Python syntax AST parsing."""
        target = self.resolve_path(relative_path)

        if validate_syntax and target.suffix == ".py":
            try:
                ast.parse(content)
            except SyntaxError as e:
                return False, f"Python syntax error on line {e.lineno}: {e.msg}"

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return True, None

    def patch_file(self, relative_path: str, old_str: str, new_str: str) -> Tuple[bool, Optional[str]]:
        """Perform an exact targeted replacement in a file."""
        target = self.resolve_path(relative_path)
        if not target.exists():
            return False, f"File {relative_path} does not exist"

        content = target.read_text(encoding="utf-8")
        if old_str not in content:
            return False, f"Target string to replace not found in {relative_path}"

        updated_content = content.replace(old_str, new_str, 1)
        return self.write_file(relative_path, updated_content)

    def calculate_diff(self, relative_path: str, new_content: str) -> str:
        """Calculate unified diff between current file and proposed content."""
        try:
            target = self.resolve_path(relative_path)
            old_content = target.read_text(encoding="utf-8") if target.exists() else ""
        except Exception:
            old_content = ""

        diff = difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}"
        )
        return "".join(diff)

    def extract_symbols(self, relative_path: str) -> Dict[str, List[str]]:
        """Extract classes and functions defined in a Python file using AST."""
        target = self.resolve_path(relative_path)
        if not target.exists() or target.suffix != ".py":
            return {"classes": [], "functions": [], "imports": []}

        content = target.read_text(encoding="utf-8")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return {"classes": [], "functions": [], "imports": []}

        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
        imports = []
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imports.extend(alias.name for alias in n.names)
            elif isinstance(n, ast.ImportFrom):
                if n.module:
                    imports.append(n.module)

        return {"classes": classes, "functions": functions, "imports": imports}
