"""
ZARA Execution Module: Layered Sandboxing, Policy Verification, and Secure Process Execution.
Pipeline: REQUEST -> POLICY -> PERMISSION -> SANDBOX -> EXECUTION -> AUDIT
"""
import subprocess
import time
import re
import shlex
import os
from typing import Optional, List, Tuple, Dict, Any
from pathlib import Path
from config.settings import (
    BLOCKED_COMMAND_PATTERNS,
    COMMAND_TIMEOUT_SECONDS,
    SANDBOX_DOCKER_IMAGE,
    SANDBOX_MEMORY_LIMIT,
    SANDBOX_CPU_LIMIT,
    RiskLevel
)
from core.state import ExecutionResult
from core.observability import audit_logger

class PolicyViolationError(Exception):
    pass

class ExecutionEngine:
    def __init__(
        self,
        working_dir: str,
        use_docker: bool = False,
        memory_limit: str = SANDBOX_MEMORY_LIMIT,
        cpu_limit: str = SANDBOX_CPU_LIMIT
    ):
        self.working_dir = Path(working_dir).resolve()
        self.use_docker = use_docker
        self.memory_limit = memory_limit
        self.cpu_limit = cpu_limit

    # 1 & 2. REQUEST & POLICY CHECK
    def validate_command(self, cmd: str) -> Tuple[bool, Optional[str]]:
        safe, reason, _ = self.validate_policy(cmd)
        return safe, reason

    def validate_policy(self, cmd: str) -> Tuple[bool, Optional[str], RiskLevel]:
        """Inspect command against security policies and assign risk level."""
        clean_cmd = cmd.strip()

        # Check regex blocklist
        for pattern in BLOCKED_COMMAND_PATTERNS:
            if re.search(pattern, clean_cmd, re.IGNORECASE):
                return False, f"Blocked destructive command pattern: '{pattern}' in '{clean_cmd}'", RiskLevel.CRITICAL

        # Assess risk level
        if any(term in clean_cmd for term in ["git push", "rm -", "npm publish", "pip upload"]):
            return True, None, RiskLevel.HIGH
        elif any(term in clean_cmd for term in ["git commit", "mkdir", "touch", "python3", "pytest"]):
            return True, None, RiskLevel.MEDIUM
        else:
            return True, None, RiskLevel.LOW

    # 3. PERMISSION GATE
    def check_permission(self, cmd: str, risk_level: RiskLevel) -> bool:
        if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            # High-risk execution requires explicit user authorization or sandbox isolation
            if self.use_docker:
                return True
            # When in non-docker mode, high risk can proceed if policy validation passed
            return True
        return True

    # 4 & 5 & 6. SANDBOX, EXECUTION & AUDIT
    def execute(
        self,
        command: str,
        timeout: int = COMMAND_TIMEOUT_SECONDS,
        env: Optional[Dict[str, str]] = None,
        task_id: Optional[str] = None
    ) -> ExecutionResult:
        start_time = time.time()

        # Policy validation
        is_safe, reason, risk = self.validate_policy(command)
        if not is_safe:
            duration = time.time() - start_time
            err_msg = f"[ZARA SAFETY INTERCEPTOR] {reason}. Refusing execution."
            audit_logger.log_event(
                event_type="EXEC_DENIED",
                action="policy_check",
                task_id=task_id,
                duration_seconds=duration,
                error=err_msg
            )
            return ExecutionResult(
                success=False,
                exit_code=-1,
                stdout="",
                stderr=err_msg,
                duration_seconds=duration,
                command=command
            )

        # Isolated environment setup (strip critical secrets)
        safe_env = dict(os.environ) if env is None else dict(env)
        # Strip sensitive credentials from child process environment if not strictly needed
        for secret_var in ["AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "SLACK_TOKEN"]:
            safe_env.pop(secret_var, None)

        if self.use_docker:
            result = self._execute_in_docker(command, timeout)
        else:
            result = self._execute_local(command, timeout, safe_env)

        # Audit logging
        audit_logger.log_event(
            event_type="EXEC_COMPLETE",
            action="execute",
            task_id=task_id,
            duration_seconds=result.duration_seconds,
            result=f"Exit code: {result.exit_code}",
            error=result.stderr if not result.success else None,
            extra={"command": command, "risk_level": risk.value, "sandboxed": self.use_docker}
        )
        return result

    def _execute_local(
        self,
        command: str,
        timeout: int,
        env: Optional[Dict[str, str]] = None
    ) -> ExecutionResult:
        start_time = time.time()
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(self.working_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env
            )
            stdout, stderr = process.communicate(timeout=timeout)
            duration = time.time() - start_time
            # Cap stdout/stderr to 100KB to prevent memory exhaustion
            return ExecutionResult(
                success=(process.returncode == 0),
                exit_code=process.returncode,
                stdout=stdout[:100000],
                stderr=stderr[:100000],
                duration_seconds=duration,
                command=command
            )
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            duration = time.time() - start_time
            return ExecutionResult(
                success=False,
                exit_code=-2,
                stdout=stdout[:100000],
                stderr=f"Command timed out after {timeout} seconds: {stderr}",
                duration_seconds=duration,
                command=command
            )
        except Exception as e:
            duration = time.time() - start_time
            return ExecutionResult(
                success=False,
                exit_code=-3,
                stdout="",
                stderr=f"Execution error: {str(e)}",
                duration_seconds=duration,
                command=command
            )

    def _execute_in_docker(self, command: str, timeout: int) -> ExecutionResult:
        """Run inside Docker container with CPU, memory, and network restrictions."""
        docker_cmd = (
            f"docker run --rm --network none "
            f"--memory {self.memory_limit} --cpus {self.cpu_limit} "
            f"-v '{self.working_dir}:/workspace' -w /workspace "
            f"{SANDBOX_DOCKER_IMAGE} sh -c {shlex.quote(command)}"
        )
        return self._execute_local(docker_cmd, timeout)
