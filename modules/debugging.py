"""
ZARA Debugging Module: Deep error diagnosis, traceback parsing, hypothesis formation, and targeted patching.
"""
import re
import json
from typing import Dict, Any, Optional, List
from core.state import Diagnosis
from core.prompts import DIAGNOSE_PROMPT_TEMPLATE

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
        step_title: str = "",
        expected_condition: str = "",
        error_output: str = "",
        attempt: int = 1,
        llm_router: Optional[Any] = None,
        step: Optional[Any] = None,
        task: Optional[str] = None,
        previous_attempts: Optional[List[Any]] = None,
        context: Optional[Any] = None
    ) -> Diagnosis:
        """Analyze failure and synthesize a concrete hypothesis, root cause category, and targeted fix."""
        parsed = DebuggingModule.parse_traceback(error_output)
        clean_err = error_output.strip()

        if step is not None:
            step_title = getattr(step, "title", step_title)
            expected_condition = getattr(step, "success_condition", expected_condition)
            tool_name = getattr(step, "tool", None) or (
                step.action_type.value if hasattr(step.action_type, "value") else str(step.action_type)
            )
            arguments = getattr(step, "arguments", {}) or getattr(step, "payload", {})
            step_id = getattr(step, "id", 1)
        else:
            tool_name = "unknown"
            arguments = {}
            step_id = 1

        category = "code_logic"
        failure_type = "code_logic"
        hypothesis = f"Encountered {parsed['exception_type']}: {parsed['exception_message']}"
        root_cause = hypothesis
        affected_file = parsed.get("failing_file")
        affected_line = parsed.get("failing_line")
        explanation = hypothesis
        recommended_action = "Inspect source code and apply targeted fix"
        confidence = 0.9
        proposed_fix: Dict[str, Any] = {}
        corrected_arguments: Optional[Dict[str, Any]] = None
        corrected_tool: Optional[str] = None

        # Heuristic diagnosis
        if "command not found" in clean_err or "/bin/sh:" in clean_err:
            category = "command"
            failure_type = "command_failure"
            hypothesis = f"Shell command error: {clean_err.splitlines()[0]}"
            root_cause = hypothesis
            recommended_action = "Fix command string or executable path"
            proposed_fix = {"action": "fix_command"}
        elif "Missing required parameter" in clean_err or "Invalid parameter" in clean_err or "validation failed" in clean_err.lower():
            category = "tool_arguments"
            failure_type = "tool_validation"
            hypothesis = f"Tool argument validation failed: {clean_err}"
            root_cause = hypothesis
            recommended_action = "Supply valid arguments matching tool parameter schema"
            proposed_fix = {"action": "fix_tool_arguments"}
        elif parsed["exception_type"] in ("ModuleNotFoundError", "ImportError"):
            category = "dependency"
            failure_type = "import_error"
            missing_mod = re.findall(r"No module named ['\"]([^'\"]+)['\"]", clean_err)
            mod = missing_mod[0] if missing_mod else "unknown"
            hypothesis = f"Missing python package or module '{mod}'. Needs installation or import fix."
            root_cause = f"Cannot import '{mod}'"
            recommended_action = f"Install missing package '{mod}' or fix import path"
            proposed_fix = {"action": "install_dependency", "package": mod, "module": mod, "file": affected_file}
        elif parsed["exception_type"] == "SyntaxError":
            category = "syntax_error"
            failure_type = "syntax_error"
            hypothesis = f"Syntax error in {affected_file or 'file'} at line {affected_line or 'unknown'}: {parsed['exception_message']}."
            root_cause = f"SyntaxError: {parsed['exception_message']}"
            recommended_action = f"Fix syntax in {affected_file} at line {affected_line}"
            proposed_fix = {"action": "fix_syntax", "file": affected_file, "line": affected_line}
        elif parsed["exception_type"] == "AssertionError":
            category = "code_logic"
            failure_type = "assertion_failure"
            hypothesis = (
                f"Test assertion failed at {affected_file}:{affected_line}. "
                f"Code returned unexpected value deviating from specification ({parsed['exception_message'] or 'assertion failure'})."
            )
            root_cause = f"Assertion failed: {parsed['exception_message'] or 'value mismatch'}"
            recommended_action = f"Modify implementation logic in {affected_file} to produce expected output"
            proposed_fix = {"action": "fix_implementation_logic", "file": affected_file}
        elif parsed["exception_type"] in ("ZeroDivisionError", "TypeError", "ValueError", "KeyError", "IndexError", "AttributeError", "RuntimeError"):
            category = "code_logic"
            failure_type = "runtime_error"
            hypothesis = f"Runtime exception {parsed['exception_type']} in {affected_file}:{affected_line}: {parsed['exception_message']}"
            root_cause = f"{parsed['exception_type']}: {parsed['exception_message']}"
            recommended_action = f"Add validation or guard against {parsed['exception_type']} in {affected_file}"
            proposed_fix = {"action": "fix_runtime_error", "file": affected_file, "exception": parsed["exception_type"]}
        elif "FileNotFoundError" in clean_err or "does not exist" in clean_err:
            category = "dependency"
            failure_type = "file_not_found"
            file_target = affected_file or (arguments.get("path") if isinstance(arguments, dict) else None)
            hypothesis = f"Required file was not found during execution: {file_target or 'unknown'}"
            root_cause = f"Missing file {file_target}"
            recommended_action = f"Create missing file {file_target}"
            proposed_fix = {"action": "create_missing_file", "file": file_target}
        elif "Verification failed" in clean_err:
            category = "verification"
            failure_type = "verification_failure"
            hypothesis = clean_err
            root_cause = "Actual output did not meet stated verification condition"
            recommended_action = "Align actual output with verification condition"
            proposed_fix = {"action": "align_output_or_condition"}

        # LLM-guided deep diagnosis if available
        if llm_router:
            try:
                prompt = DIAGNOSE_PROMPT_TEMPLATE.format(
                    step_id=step_id,
                    step_title=step_title,
                    tool_name=tool_name,
                    arguments=json.dumps(arguments) if isinstance(arguments, dict) else str(arguments),
                    success_condition=expected_condition,
                    error_output=clean_err[:1000],
                    attempt=attempt,
                    max_attempts=5,
                    previous_attempts=json.dumps(previous_attempts) if previous_attempts else "None"
                )
                llm_diag = llm_router.generate_structured(prompt)
                if isinstance(llm_diag, dict):
                    if "root_cause_category" in llm_diag:
                        category = str(llm_diag["root_cause_category"])
                    if "failure_type" in llm_diag:
                        failure_type = str(llm_diag["failure_type"])
                    if "root_cause" in llm_diag:
                        root_cause = str(llm_diag["root_cause"])
                    if "hypothesis" in llm_diag:
                        hypothesis = str(llm_diag["hypothesis"])
                    if "explanation" in llm_diag:
                        explanation = str(llm_diag["explanation"])
                    if "affected_file" in llm_diag and llm_diag["affected_file"]:
                        affected_file = str(llm_diag["affected_file"])
                    if "affected_line" in llm_diag and llm_diag["affected_line"]:
                        try:
                            affected_line = int(llm_diag["affected_line"])
                        except (ValueError, TypeError):
                            pass
                    if "recommended_action" in llm_diag:
                        recommended_action = str(llm_diag["recommended_action"])
                    if "confidence" in llm_diag:
                        try:
                            confidence = float(llm_diag["confidence"])
                        except (ValueError, TypeError):
                            pass
                    if "corrected_tool" in llm_diag and llm_diag["corrected_tool"]:
                        corrected_tool = str(llm_diag["corrected_tool"])
                    if "corrected_arguments" in llm_diag and isinstance(llm_diag["corrected_arguments"], dict):
                        corrected_arguments = llm_diag["corrected_arguments"]
                    if "proposed_fix" in llm_diag and isinstance(llm_diag["proposed_fix"], dict):
                        proposed_fix = llm_diag["proposed_fix"]
            except Exception:
                pass

        return Diagnosis(
            attempt=attempt,
            failure_reason=clean_err[:500],
            hypothesis=hypothesis,
            proposed_fix=proposed_fix,
            root_cause_category=category,
            corrected_arguments=corrected_arguments,
            corrected_tool=corrected_tool,
            failure_type=failure_type,
            root_cause=root_cause,
            affected_file=affected_file,
            affected_line=affected_line,
            explanation=explanation,
            recommended_action=recommended_action,
            confidence=confidence
        )
