"""
ZARA Debugging Module: Deep error diagnosis, traceback parsing, hypothesis formation, and targeted patching.
"""
import re
from typing import Dict, Any, Optional, List
from core.state import Diagnosis

class DebuggingModule:
    @staticmethod
    def parse_traceback(error_output: str) -> Dict[str, Any]:
        """Extract failing file, line number, exception type, and message from traceback."""
        clean_err = error_output.strip()
        lines = clean_err.splitlines()

        exception_type = "UnknownError"
        exception_message = ""
        failing_file = None
        failing_line = None

        # Look for Exception at bottom
        for line in reversed(lines):
            line_s = line.strip()
            if ":" in line_s and any(line_s.startswith(exc) for exc in [
                "AssertionError", "TypeError", "ValueError", "KeyError", "IndexError",
                "AttributeError", "NameError", "SyntaxError", "ImportError", "ModuleNotFoundError",
                "FileNotFoundError", "ZeroDivisionError", "RuntimeError"
            ]):
                parts = line_s.split(":", 1)
                exception_type = parts[0].strip()
                exception_message = parts[1].strip()
                break

        # Look for File "...", line ...
        file_matches = re.findall(r'File "([^"]+)", line (\d+)', clean_err)
        if file_matches:
            # Take the last frame (closest to error)
            failing_file, line_str = file_matches[-1]
            try:
                failing_line = int(line_str)
            except ValueError:
                failing_line = None

        return {
            "exception_type": exception_type,
            "exception_message": exception_message,
            "failing_file": failing_file,
            "failing_line": failing_line
        }

    @staticmethod
    def diagnose_failure(
        step_title: str,
        expected_condition: str,
        error_output: str,
        attempt: int,
        llm_router: Optional[Any] = None
    ) -> Diagnosis:
        """Analyze failure and synthesize a concrete hypothesis and targeted fix."""
        parsed = DebuggingModule.parse_traceback(error_output)
        clean_err = error_output.strip()

        hypothesis = f"Encountered {parsed['exception_type']}: {parsed['exception_message']}"
        proposed_fix: Dict[str, Any] = {}

        if parsed["exception_type"] == "ModuleNotFoundError":
            missing_mod = re.findall(r"No module named ['\"]([^'\"]+)['\"]", clean_err)
            mod = missing_mod[0] if missing_mod else "unknown"
            hypothesis = f"Missing dependency: Python module '{mod}' is not installed."
            proposed_fix = {"action": "install_dependency", "package": mod}

        elif parsed["exception_type"] == "SyntaxError":
            hypothesis = f"Syntax error in {parsed['failing_file'] or 'file'} at line {parsed['failing_line'] or 'unknown'}."
            proposed_fix = {"action": "fix_syntax", "file": parsed["failing_file"], "line": parsed["failing_line"]}

        elif parsed["exception_type"] == "AssertionError":
            hypothesis = (
                f"Test assertion failed at {parsed['failing_file']}:{parsed['failing_line']}. "
                f"Code returned unexpected value deviating from specification."
            )
            proposed_fix = {"action": "fix_implementation_logic", "file": parsed["failing_file"]}

        elif "FileNotFoundError" in clean_err:
            hypothesis = f"Required file was not found during execution."
            proposed_fix = {"action": "create_missing_file"}

        # If LLM router is provided and we are diagnosing, ask LLM for deep analysis
        if llm_router and parsed["failing_file"]:
            try:
                prompt = (
                    f"Diagnose this failure:\n"
                    f"Step: {step_title}\n"
                    f"Expected: {expected_condition}\n"
                    f"Error Trace:\n{error_output[:800]}\n"
                    f"Return JSON with hypothesis and proposed fix."
                )
                llm_diag = llm_router.generate_structured(prompt)
                if isinstance(llm_diag, dict) and "hypothesis" in llm_diag:
                    hypothesis = llm_diag["hypothesis"]
                    if "proposed_fix" in llm_diag:
                        proposed_fix = llm_diag["proposed_fix"]
            except Exception:
                pass

        return Diagnosis(
            attempt=attempt,
            failure_reason=clean_err[:500],
            hypothesis=hypothesis,
            proposed_fix=proposed_fix
        )
