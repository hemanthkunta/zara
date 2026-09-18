"""
ZARA Git Module: Controlled Git operations and Pull Request preparation with safety gates.
"""
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
from config.settings import BASE_DIR, RiskLevel

class GitModule:
    def __init__(self, repo_dir: Path = BASE_DIR):
        self.repo_dir = Path(repo_dir).resolve()

    def _run_git(self, args: list) -> Dict[str, Any]:
        try:
            proc = subprocess.run(
                ["git"] + args,
                cwd=self.repo_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            return {
                "success": (proc.returncode == 0),
                "exit_code": proc.returncode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip()
            }
        except Exception as e:
            return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(e)}

    def status(self) -> Dict[str, Any]:
        return self._run_git(["status", "--short"])

    def diff(self, cached: bool = False) -> Dict[str, Any]:
        args = ["diff", "--cached"] if cached else ["diff"]
        return self._run_git(args)

    def log(self, max_count: int = 5) -> Dict[str, Any]:
        return self._run_git(["log", f"-n{max_count}", "--oneline"])

    def create_branch(self, branch_name: str) -> Dict[str, Any]:
        safe_name = "".join(c for c in branch_name if c.isalnum() or c in ("-", "_", "/"))
        return self._run_git(["checkout", "-b", safe_name])

    def commit(self, message: str) -> Dict[str, Any]:
        # Stage all tracked modified files and commit
        self._run_git(["add", "-A"])
        return self._run_git(["commit", "-m", message])

    def prepare_pr_bundle(self, title: str, description: str, base_branch: str = "main") -> Dict[str, Any]:
        """Synthesize branch diff and commit log into a structured PR bundle."""
        diff_res = self.diff()
        log_res = self.log(max_count=5)
        return {
            "title": title,
            "description": description,
            "base_branch": base_branch,
            "recent_commits": log_res.get("stdout", ""),
            "diff_summary": diff_res.get("stdout", "")[:2000],
            "requires_human_push_approval": True
        }
