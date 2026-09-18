"""
ZARA Verification Module: Multi-adapter verification engine and verifiable evidence collector.
"""
import hashlib
import time
import subprocess
import datetime
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List

@dataclass
class VerificationEvidence:
    verified: bool
    adapter_name: str
    command: Optional[str]
    exit_code: int
    duration_seconds: float
    output_hash: str
    details: str
    timestamp: str = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())

class VerificationEngine:
    def __init__(self, workspace_root: Path):
        self.workspace_root = Path(workspace_root).resolve()

    def verify_command(self, command: str, timeout: int = 60) -> VerificationEvidence:
        """Run a shell check and record cryptographic evidence of outcome."""
        start = time.time()
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=self.workspace_root,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            duration = time.time() - start
            output = (proc.stdout or "") + (proc.stderr or "")
            out_hash = hashlib.sha256(output.encode("utf-8")).hexdigest()
            passed = (proc.returncode == 0)

            return VerificationEvidence(
                verified=passed,
                adapter_name="command_exit_code",
                command=command,
                exit_code=proc.returncode,
                duration_seconds=duration,
                output_hash=out_hash,
                details=output[:1000] if not passed else "Command verified successfully with exit code 0."
            )
        except Exception as e:
            duration = time.time() - start
            return VerificationEvidence(
                verified=False,
                adapter_name="command_exit_code",
                command=command,
                exit_code=-1,
                duration_seconds=duration,
                output_hash="error",
                details=f"Verification execution failed: {str(e)}"
            )

    def verify_python_syntax(self, relative_path: str) -> VerificationEvidence:
        """Verify Python file compiles without syntax errors."""
        start = time.time()
        target = (self.workspace_root / relative_path).resolve()
        if not target.exists():
            return VerificationEvidence(
                verified=False,
                adapter_name="python_syntax",
                command=None,
                exit_code=1,
                duration_seconds=0.0,
                output_hash="",
                details=f"Target file {relative_path} does not exist"
            )

        try:
            import ast
            ast.parse(target.read_text(encoding="utf-8"))
            duration = time.time() - start
            return VerificationEvidence(
                verified=True,
                adapter_name="python_syntax",
                command=None,
                exit_code=0,
                duration_seconds=duration,
                output_hash=hashlib.sha256(target.read_bytes()).hexdigest(),
                details=f"File {relative_path} AST parsed cleanly."
            )
        except SyntaxError as e:
            duration = time.time() - start
            return VerificationEvidence(
                verified=False,
                adapter_name="python_syntax",
                command=None,
                exit_code=1,
                duration_seconds=duration,
                output_hash="",
                details=f"SyntaxError in {relative_path}:{e.lineno} - {e.msg}"
            )
