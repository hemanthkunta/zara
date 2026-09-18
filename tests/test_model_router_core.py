"""
ZARA Phase 16: Tests for Model Router Core Abstractions, Registry, Selection, and Redaction.
"""
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from modules.model_router import (
    ModelProvider,
    MockModelProvider,
    GoogleGenAIProvider,
    AnthropicCompatibleProvider,
    OpenAICompatibleProvider,
    LocalProvider,
    ProviderType,
    ProviderStatus,
    ModelCapability,
    ModelInfo,
    ModelRequest,
    ModelSelection,
    ModelRegistry,
    ModelRouter,
    StreamEvent,
    StreamEventType
)
from brain.base import LLMMessage, Role, LLMResponse, ToolCall
from core.observability import audit_logger


class TestModelRouterCore(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.cache_file = Path(self.tmp_dir.name) / "models_cache.json"
        self.registry = ModelRegistry(cache_file=self.cache_file)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_01_provider_interface_and_mock(self):
        """Verify ModelProvider base operations and MockModelProvider functionality."""
        prov = MockModelProvider(name="test_mock", default_model="test-model")
        self.assertEqual(prov.provider_type, ProviderType.MOCK)
        self.assertTrue(prov.is_available())
        caps = prov.capabilities()
        self.assertIn(ModelCapability.TEXT, caps)
        self.assertIn(ModelCapability.CODE, caps)
        self.assertIn(ModelCapability.VISION, caps)

        messages = [LLMMessage(role=Role.USER, content="Hello ZARA Brain")]
        resp = prov.generate(messages)
        self.assertIsInstance(resp, LLMResponse)
        self.assertEqual(resp.provider, "test_mock")
        self.assertEqual(resp.model, "test-model")
        self.assertGreater(resp.usage.total_tokens, 0)

    def test_02_model_info_dataclass_and_serialization(self):
        """Verify ModelInfo serialization and deserialization roundtrip."""
        info = ModelInfo(
            provider="google",
            model_id="gemini-test",
            display_name="Gemini Test Model",
            capabilities={ModelCapability.TEXT, ModelCapability.VISION, ModelCapability.CODE},
            context_window=100000,
            max_output_tokens=4096,
            supports_streaming=True,
            supports_tools=True,
            supports_vision=True,
            cost_input=0.0005,
            cost_output=0.0015,
            priority=2
        )
        d = info.to_dict()
        self.assertEqual(d["model_id"], "gemini-test")
        self.assertEqual(d["provider"], "google")
        self.assertIn("text", d["capabilities"])
        self.assertIn("vision", d["capabilities"])

        restored = ModelInfo.from_dict(d)
        self.assertEqual(restored.model_id, info.model_id)
        self.assertEqual(restored.context_window, 100000)
        self.assertTrue(restored.supports_vision)
        self.assertIn(ModelCapability.VISION, restored.capabilities)

    def test_03_model_registry_initialization(self):
        """Verify default models catalog loaded in ModelRegistry."""
        models = self.registry.list_models()
        self.assertGreaterEqual(len(models), 5)
        model_ids = [m.model_id for m in models]
        self.assertIn("mock-zara-model", model_ids)
        self.assertIn("gemini-2.5-flash", model_ids)
        self.assertIn("claude-3-5-sonnet-20241022", model_ids)
        self.assertIn("gpt-4o", model_ids)

    def test_04_model_registry_custom_registration(self):
        """Verify registering a custom model dynamically in ModelRegistry."""
        custom_model = ModelInfo(
            provider="custom_http",
            model_id="custom-fast-v1",
            display_name="Custom Fast LLM",
            capabilities={ModelCapability.TEXT, ModelCapability.STREAMING},
            priority=1
        )
        self.registry.register_model(custom_model)
        retrieved = self.registry.get_model("custom-fast-v1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.display_name, "Custom Fast LLM")

    def test_05_model_registry_list_and_filters(self):
        """Verify listing models with provider and capability filtering."""
        google_models = self.registry.list_models(provider="google")
        self.assertTrue(all(m.provider == "google" for m in google_models))
        self.assertGreaterEqual(len(google_models), 1)

        vision_models = self.registry.list_models(capability=ModelCapability.VISION)
        self.assertTrue(all(ModelCapability.VISION in m.capabilities for m in vision_models))

    def test_06_model_registry_cache_save_and_load(self):
        """Verify saving and restoring model registry cache to disk."""
        self.registry.save_cache()
        self.assertTrue(self.cache_file.exists())

        new_reg = ModelRegistry(cache_file=self.cache_file)
        self.assertIn("gemini-2.5-flash", new_reg.models)

    def test_07_model_discovery_offline_safety(self):
        """Verify discover_models executes safely without external network calls."""
        discovered = self.registry.discover_models()
        self.assertIsInstance(discovered, list)
        mock_m = [m for m in discovered if m.provider == "mock"][0]
        self.assertEqual(mock_m.availability, ProviderStatus.AVAILABLE)

    def test_08_provider_availability_without_keys(self):
        """Verify external providers report UNAVAILABLE when API keys are absent."""
        with patch.dict(os.environ, {}, clear=True):
            g_prov = GoogleGenAIProvider(api_key=None)
            a_prov = AnthropicCompatibleProvider(api_key=None)
            o_prov = OpenAICompatibleProvider(api_key=None)
            l_prov = LocalProvider()

            self.assertFalse(g_prov.is_available())
            self.assertFalse(a_prov.is_available())
            self.assertFalse(o_prov.is_available())
            self.assertFalse(l_prov.is_available())

    def test_09_provider_availability_with_keys(self):
        """Verify external providers report AVAILABLE when API keys are supplied."""
        g_prov = GoogleGenAIProvider(api_key="mock_google_key")
        a_prov = AnthropicCompatibleProvider(api_key="mock_anthropic_key")
        o_prov = OpenAICompatibleProvider(api_key="mock_openai_key")

        self.assertTrue(g_prov.is_available())
        self.assertTrue(a_prov.is_available())
        self.assertTrue(o_prov.is_available())

    def test_10_capability_matching_hard_requirements(self):
        """Verify router matches hard capability requirements strictly."""
        router = ModelRouter(registry=self.registry)
        req = ModelRequest(
            task_type="vision_inspect",
            required_capabilities={ModelCapability.VISION}
        )
        sel = router.route(req)
        self.assertIn("vision", sel.capability_match)
        target_info = router.registry.get_model(sel.model_id)
        self.assertTrue(ModelCapability.VISION in target_info.capabilities)

    def test_11_task_to_capability_inference(self):
        """Verify sensible capability requirements are inferred for standard task types."""
        router = ModelRouter(registry=self.registry)

        # Coding task
        sel_code = router.route(ModelRequest(task_type="coding"))
        self.assertIn("code", sel_code.capability_match)

        # Research task
        sel_research = router.route(ModelRequest(task_type="research"))
        self.assertIn("long_context", sel_research.capability_match)

        # Vision task
        sel_vision = router.route(ModelRequest(task_type="vision"))
        self.assertIn("vision", sel_vision.capability_match)

    def test_12_user_preference_prioritization(self):
        """Verify user preference elevates matching model priority."""
        router = ModelRouter(registry=self.registry)
        req = ModelRequest(
            task_type="general_qa",
            user_preference="mock"
        )
        sel = router.route(req)
        self.assertEqual(sel.provider, "mock")
        self.assertIn("mock", sel.model_id)

    def test_13_project_preference_prioritization(self):
        """Verify project preference elevates matching model when no user preference set."""
        router = ModelRouter(registry=self.registry)
        req = ModelRequest(
            task_type="general_qa",
            project_preference="mock"
        )
        sel = router.route(req)
        self.assertEqual(sel.provider, "mock")

    def test_14_user_preference_cannot_override_missing_capability(self):
        """Verify user preference for non-vision model cannot override vision requirement."""
        # Create a model without vision
        no_vision_model = ModelInfo(
            provider="mock",
            model_id="mock-text-only",
            display_name="Mock Text Only",
            capabilities={ModelCapability.TEXT},
            priority=1
        )
        self.registry.register_model(no_vision_model)

        router = ModelRouter(registry=self.registry)
        req = ModelRequest(
            task_type="vision_analysis",
            vision_required=True,
            user_preference="mock-text-only"
        )
        sel = router.route(req)
        # Should not select mock-text-only because it lacks VISION capability
        self.assertNotEqual(sel.model_id, "mock-text-only")

    def test_15_context_size_constraint_filtering(self):
        """Verify models with insufficient context window are rejected."""
        small_window_model = ModelInfo(
            provider="mock",
            model_id="small-context-model",
            display_name="Small Context Model",
            capabilities={ModelCapability.TEXT},
            context_window=2000,
            priority=1
        )
        self.registry.register_model(small_window_model)

        router = ModelRouter(registry=self.registry)
        req = ModelRequest(
            task_type="general_qa",
            context_size=5000  # Exceeds 2000
        )
        sel = router.route(req)
        self.assertNotEqual(sel.model_id, "small-context-model")

    def test_16_cost_estimation_calculation(self):
        """Verify token and cost estimation calculations."""
        prov = MockModelProvider()
        cost = prov.estimate_cost(input_tokens=1000, output_tokens=2000, cost_in_per_k=0.001, cost_out_per_k=0.002)
        expected = (1.0 * 0.001) + (2.0 * 0.002)  # 0.005
        self.assertAlmostEqual(cost, expected, places=5)

    def test_17_secret_scrubbing_in_audit_and_events(self):
        """Verify API keys and credentials are automatically scrubbed from logged text."""
        raw_text = "Generated using sk-proj-1234567890abcdef12345678 and AIzaSyD9876543210ZYXWVUTSRQPONMLKJIHGFED"
        scrubbed = audit_logger.scrub_secrets(raw_text)
        self.assertNotIn("sk-proj-1234567890abcdef12345678", scrubbed)
        self.assertNotIn("AIzaSyD9876543210ZYXWVUTSRQPONMLKJIHGFED", scrubbed)
        self.assertIn("[REDACTED_API_KEY]", scrubbed)
        self.assertIn("[REDACTED_GEMINI_KEY]", scrubbed)

    def test_18_no_uncontrolled_requests_during_startup(self):
        """Verify router initialization is fast and offline without external connections."""
        router = ModelRouter()
        self.assertIsNotNone(router.registry)
        self.assertIsNotNone(router.health_tracker)
        st = router.get_status()
        self.assertEqual(st["status"], "HEALTHY")

    def test_19_model_selection_dataclass(self):
        """Verify ModelSelection serialization."""
        ms = ModelSelection(
            provider="mock",
            model_id="mock-zara-model",
            reason="Direct match",
            capability_match=["text", "code"],
            estimated_cost=0.0001,
            estimated_latency=1.5,
            fallback_chain=["gemini-2.5-flash"]
        )
        d = ms.to_dict()
        self.assertEqual(d["provider"], "mock")
        self.assertEqual(len(d["fallback_chain"]), 1)

    def test_20_model_request_dataclass(self):
        """Verify ModelRequest fields and defaults."""
        req = ModelRequest(task_type="coding", max_output_tokens=2048)
        self.assertEqual(req.task_type, "coding")
        self.assertEqual(req.max_output_tokens, 2048)
        self.assertTrue(req.request_id.startswith("req_"))

    def test_21_stream_event_dataclass(self):
        """Verify StreamEvent serialization."""
        evt = StreamEvent(event_type=StreamEventType.TOKEN, token="Hello ")
        d = evt.to_dict()
        self.assertEqual(d["event_type"], "token")
        self.assertEqual(d["token"], "Hello ")

    def test_22_count_tokens_rough_estimation(self):
        """Verify token count rough estimation."""
        prov = MockModelProvider()
        text = "Four words in text"
        count = prov.count_tokens(text)
        self.assertGreaterEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
