"""
ZARA Tool System: Abstract Base Tool, ToolResult, and Parameter Schemas.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, Tuple
from config.settings import RiskLevel

@dataclass
class ToolResult:
    success: bool
    data: Any
    error: Optional[str] = None
    duration_seconds: float = 0.0

class BaseTool(ABC):
    def __init__(
        self,
        name: str,
        description: str,
        parameters_schema: Dict[str, Any],
        risk_level: RiskLevel = RiskLevel.LOW,
        timeout_seconds: int = 30
    ):
        self.name = name
        self.description = description
        self.parameters_schema = parameters_schema
        self.risk_level = risk_level
        self.timeout_seconds = timeout_seconds

    def validate_inputs(self, kwargs: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate required arguments according to parameters_schema."""
        required = self.parameters_schema.get("required", [])
        properties = self.parameters_schema.get("properties", {})

        for field in required:
            if field not in kwargs:
                return False, f"Missing required parameter '{field}' for tool '{self.name}'"

        for field, value in kwargs.items():
            if field in properties:
                expected_type = properties[field].get("type")
                if expected_type == "string" and not isinstance(value, str):
                    return False, f"Parameter '{field}' must be a string, got {type(value).__name__}"
                elif expected_type == "integer" and not isinstance(value, int):
                    return False, f"Parameter '{field}' must be an integer, got {type(value).__name__}"
                elif expected_type == "boolean" and not isinstance(value, bool):
                    return False, f"Parameter '{field}' must be a boolean, got {type(value).__name__}"

        return True, None

    @abstractmethod
    def run(self, **kwargs) -> ToolResult:
        """Core tool logic."""
        pass
