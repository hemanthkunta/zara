"""
ZARA Terminal and Test Runner Tools.
"""
from pathlib import Path
import subprocess
import time
import os
from typing import Dict, Any, Optional
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel, BASE_DIR, COMMAND_TIMEOUT_SECONDS
from modules.execution import ExecutionEngine

class TerminalExecutionTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR, use_docker: bool = False):
        super().__init__(
            name="terminal_execute",
            description="Execute a shell command within the workspace with safety controls.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                    "timeout_seconds": {"type": "integer"}
                },
                "required": ["command"]
            },
            risk_level=RiskLevel.MEDIUM,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS
        )
        self.engine = ExecutionEngine(str(workspace_root), use_docker=use_docker)

    def run(self, command: str, timeout_seconds: Optional[int] = None) -> ToolResult:
        timeout = timeout_seconds or self.timeout_seconds
        result = self.engine.execute(command, timeout=timeout)
        if result.success:
            return ToolResult(
                success=True,
                data={"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code}
            )
        else:
            return ToolResult(
                success=False,
                data={"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.exit_code},
                error=result.stderr or f"Command failed with exit code {result.exit_code}"
            )

class TestRunnerTool(BaseTool):
    def __init__(self, workspace_root: Path = BASE_DIR):
        super().__init__(
            name="run_tests",
            description="Run test suite using unittest or pytest and collect pass/fail evidence.",
            parameters_schema={
                "type": "object",
                "properties": {
                    "test_path": {"type": "string"},
                    "framework": {"type": "string"}
                },
                "required": []
            },
            risk_level=RiskLevel.LOW
        )
        self.workspace_root = workspace_root

    def run(self, test_path: str = "tests", framework: str = "auto") -> ToolResult:
        start = time.time()
        # Prefer python3 -m unittest discover for zero external dependencies
        if test_path.endswith(".py"):
            cmd = f"python3 -m unittest {test_path} -v"
        else:
            cmd = f"python3 -m unittest discover -s {test_path} -v"
        try:
            env = dict(os.environ)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.run(
                cmd,
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=60,
                env=env
            )
            duration = time.time() - start
            passed = (proc.returncode == 0)
            output = proc.stderr if proc.stderr else proc.stdout

            return ToolResult(
                success=passed,
                data={
                    "passed": passed,
                    "exit_code": proc.returncode,
                    "output": output,
                    "duration": duration
                },
                error=None if passed else f"Test failures detected:\n{output[:1500]}"
            )
        except Exception as e:
            return ToolResult(success=False, data=None, error=str(e))
