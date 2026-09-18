"""
ZARA Tool Registry: Central registration, schema management, permission gates, and execution logging.
"""
import time
from typing import Dict, Any, Optional, List, Callable
from tools.base import BaseTool, ToolResult
from config.settings import RiskLevel
from core.observability import audit_logger

class PermissionDeniedError(Exception):
    pass

class ToolRegistry:
    def __init__(
        self,
        max_auto_risk: RiskLevel = RiskLevel.MEDIUM,
        confirm_callback: Optional[Callable[[BaseTool, Dict[str, Any]], bool]] = None
    ):
        self._tools: Dict[str, BaseTool] = {}
        self.max_auto_risk = max_auto_risk
        self.confirm_callback = confirm_callback
        self.pending_confirmations: Dict[str, Dict[str, Any]] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        tool = self._tools.get(name)
        if not tool and name == "screenshot":
            return self._tools.get("macos_screenshot")
        if not tool and name == "macos_screenshot":
            return self._tools.get("screenshot")
        return tool

    def request_confirmation(self, tool_name: str, arguments: Dict[str, Any], description: str = "") -> str:
        """Create a pending confirmation ticket for a high-risk action."""
        import uuid
        action_id = f"act_{uuid.uuid4().hex[:8]}"
        self.pending_confirmations[action_id] = {
            "action_id": action_id,
            "tool": tool_name,
            "arguments": dict(arguments),
            "description": description or f"Execute {tool_name}",
            "confirmed": False,
            "created_at": time.time()
        }
        audit_logger.log_event(
            "CONFIRMATION_REQUESTED",
            action="request_confirmation",
            tool=tool_name,
            extra={"action_id": action_id, "description": description}
        )
        return action_id

    def confirm_action(self, action_id: str) -> bool:
        """Explicitly confirm a pending action ticket."""
        if action_id in self.pending_confirmations:
            self.pending_confirmations[action_id]["confirmed"] = True
            audit_logger.log_event(
                "CONFIRMATION_RECEIVED",
                action="confirm_action",
                extra={"action_id": action_id}
            )
            return True
        return False

    def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "risk_level": t.risk_level.value,
                "parameters": t.parameters_schema
            }
            for t in self._tools.values()
        ]

    def execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        task_id: Optional[str] = None,
        run_id: Optional[str] = None
    ) -> ToolResult:
        tool = self.get(tool_name)
        if not tool:
            err = f"Tool '{tool_name}' not found in registry."
            audit_logger.log_event("TOOL_ERROR", action="not_found", tool=tool_name, error=err)
            return ToolResult(success=False, data=None, error=err)

        # 1. Input Validation
        # Filter internal metadata fields like _action_id before schema validation
        clean_args = {k: v for k, v in arguments.items() if not k.startswith("_")}
        is_valid, val_err = tool.validate_inputs(clean_args)
        if not is_valid:
            audit_logger.log_event("TOOL_INVALID_INPUT", action="validate", tool=tool_name, error=val_err)
            return ToolResult(success=False, data=None, error=val_err)

        # 2. Permission Gate Check
        if not self._check_permission(tool, arguments):
            err = f"Permission denied for tool '{tool_name}' with risk level {tool.risk_level.value}."
            audit_logger.log_event("TOOL_PERMISSION_DENIED", action="permission_gate", tool=tool_name, error=err)
            return ToolResult(success=False, data=None, error=err)

        # 3. Execution & Audit
        start = time.time()
        try:
            result = tool.run(**clean_args)
            duration = time.time() - start
            result.duration_seconds = duration

            audit_logger.log_event(
                event_type="TOOL_EXECUTE",
                action="run",
                task_id=task_id,
                run_id=run_id,
                tool=tool_name,
                duration_seconds=duration,
                result=result.data,
                error=result.error
            )
            return result
        except Exception as e:
            duration = time.time() - start
            audit_logger.log_event(
                event_type="TOOL_EXCEPTION",
                action="run",
                task_id=task_id,
                run_id=run_id,
                tool=tool_name,
                duration_seconds=duration,
                error=str(e)
            )
            return ToolResult(success=False, data=None, error=str(e), duration_seconds=duration)

    def _check_permission(self, tool: BaseTool, arguments: Dict[str, Any]) -> bool:
        risk_order = {
            RiskLevel.LOW: 1,
            RiskLevel.MEDIUM: 2,
            RiskLevel.HIGH: 3,
            RiskLevel.CRITICAL: 4
        }
        if risk_order[tool.risk_level] <= risk_order[self.max_auto_risk]:
            return True

        # Check explicit action ticket confirmation
        action_id = arguments.get("_action_id")
        if action_id and action_id in self.pending_confirmations:
            ticket = self.pending_confirmations[action_id]
            if ticket.get("confirmed") and ticket.get("tool") == tool.name:
                return True

        if self.confirm_callback:
            return self.confirm_callback(tool, arguments)

        # Default terminal prompt fallback if no callback
        print(f"\n[ZARA CONFIRMATION REQUIRED]")
        print(f"Tool '{tool.name}' requires authorization (Risk: {tool.risk_level.value}).")
        print(f"Arguments: {arguments}")
        try:
            choice = input("Authorize action? [y/N]: ").strip().lower()
            return choice in ("y", "yes")
        except Exception:
            return False
