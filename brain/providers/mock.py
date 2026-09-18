"""
ZARA Mock LLM Provider: Deterministic rule-based LLM provider for offline testing and zero-key workflows.
"""
import json
import re
from typing import List, Dict, Any, Optional
from brain.base import LLMProvider, LLMMessage, LLMResponse, LLMUsage, Role, ToolCall

class MockLLMProvider(LLMProvider):
    def __init__(self, model_name: str = "zara-mock-v1"):
        super().__init__(model_name)

    def is_available(self) -> bool:
        return True

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        user_text = ""
        for m in reversed(messages):
            if m.role == Role.USER:
                user_text = m.content
                break

        # Check for planning requests
        if "break this task down into" in user_text.lower() or "break into" in user_text.lower():
            response_content = self._generate_mock_plan(user_text)
        elif "diagnose" in user_text.lower() or "failure" in user_text.lower():
            response_content = self._generate_mock_diagnosis(user_text)
        elif "fibonacci" in user_text.lower():
            response_content = self._generate_fibonacci_solution()
        else:
            response_content = (
                f"ZARA Reasoning Engine: Processed request '{user_text[:80]}'. "
                f"Ready to proceed with verifiable execution steps."
            )

        tokens = self.count_tokens(user_text) + self.count_tokens(response_content)
        usage = LLMUsage(
            prompt_tokens=self.count_tokens(user_text),
            completion_tokens=self.count_tokens(response_content),
            total_tokens=tokens,
            cost_usd=0.0
        )

        return LLMResponse(
            content=response_content,
            usage=usage,
            model=self.model_name,
            provider="mock"
        )

    def _generate_mock_plan(self, prompt: str) -> str:
        # Provide structured plan steps in JSON format
        return json.dumps({
            "steps": [
                {
                    "title": "Inspect workspace environment",
                    "action_type": "execute",
                    "target": "pwd",
                    "payload": {"command": "pwd"},
                    "success_condition": "Current directory displayed with exit code 0"
                },
                {
                    "title": "Implement core logic",
                    "action_type": "code",
                    "target": "solution.py",
                    "payload": {"file_path": "solution.py", "content": "# Core implementation\n"},
                    "success_condition": "File written and AST syntax valid"
                }
            ]
        }, indent=2)

    def _generate_mock_diagnosis(self, prompt: str) -> str:
        return json.dumps({
            "hypothesis": "Test failed because function behavior did not match specification.",
            "root_cause": "Assertion failure in test case.",
            "proposed_fix": {"action": "patch_logic", "target": "fix"}
        }, indent=2)

    def _generate_fibonacci_solution(self) -> str:
        return json.dumps({
            "code": "def fibonacci(n: int) -> int:\n    if n <= 0:\n        return 0\n    elif n == 1:\n        return 1\n    a, b = 0, 1\n    for _ in range(2, n + 1):\n        a, b = b, a + b\n    return b\n",
            "test": "import unittest\nfrom fibonacci import fibonacci\n\nclass TestFib(unittest.TestCase):\n    def test_fib(self):\n        self.assertEqual(fibonacci(0), 0)\n        self.assertEqual(fibonacci(1), 1)\n        self.assertEqual(fibonacci(7), 13)\n\nif __name__ == '__main__':\n    unittest.main()\n"
        }, indent=2)
