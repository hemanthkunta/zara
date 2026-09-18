"""
Unit tests for ZARA LLM Brain Provider Architecture.
"""
import unittest
from brain.base import LLMMessage, Role
from brain.providers.mock import MockLLMProvider
from brain.router import LLMRouter

class TestLLMBrain(unittest.TestCase):
    def test_mock_provider_generation(self):
        provider = MockLLMProvider()
        self.assertTrue(provider.is_available())

        messages = [LLMMessage(role=Role.USER, content="Hello ZARA")]
        resp = provider.generate(messages)
        self.assertIn("ZARA Reasoning Engine", resp.content)
        self.assertEqual(resp.provider, "mock")
        self.assertGreater(resp.usage.total_tokens, 0)

    def test_mock_provider_structured_plan(self):
        provider = MockLLMProvider()
        messages = [LLMMessage(role=Role.USER, content="Break this task down into steps: build API")]
        resp = provider.generate(messages)
        self.assertIn("steps", resp.content)
        self.assertIn("Inspect workspace environment", resp.content)

    def test_llm_router_structured_json(self):
        router = LLMRouter(preferred_provider="mock")
        res = router.generate_structured("Break this task down into verifiable steps")
        self.assertIsInstance(res, dict)
        self.assertIn("steps", res)
        self.assertGreaterEqual(len(res["steps"]), 1)

    def test_llm_router_fallback(self):
        # Force fallback by specifying non-existent key or offline provider
        router = LLMRouter(preferred_provider="mock")
        active = router.get_active_provider()
        self.assertIsNotNone(active)

if __name__ == "__main__":
    unittest.main()
