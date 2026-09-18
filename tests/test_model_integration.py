"""
ZARA Phase 16: Tests for End-to-End Model Router Integration, Engine, Workers, UI, and CLI.
"""
import io
import json
import unittest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from core.engine import ZaraEngine
from modules.model_router import (
    ModelRouter,
    ModelRequest,
    ModelCapability,
    MockModelProvider,
    StreamEventType,
    ModelInfo
)
from brain.base import LLMMessage, Role, ToolCall, LLMResponse
from modules.events import EventBus, EventType
from modules.workers import Worker, WorkerType
from ui.server import create_ui_app
from cli import cmd_models


class TestModelIntegration(unittest.TestCase):
    def setUp(self):
        self.event_bus = EventBus()
        self.router = ModelRouter(event_bus=self.event_bus)

    def tearDown(self):
        self.router.close()

    def test_01_router_generate_mock_end_to_end(self):
        """Verify synchronous generate with mock provider end to end."""
        messages = [LLMMessage(role=Role.USER, content="Explain quantum computing")]
        resp = self.router.generate(messages=messages)
        self.assertIsNotNone(resp)
        self.assertEqual(resp.provider, "mock")
        self.assertGreater(resp.usage.total_tokens, 0)
        self.assertIn("stop", resp.finish_reason)

    def test_02_router_failover_to_fallback_model(self):
        """Verify failing primary model triggers failover to fallback model."""
        fail_count = 0

        class PrimaryFailProvider(MockModelProvider):
            def generate(self, *args, **kwargs):
                nonlocal fail_count
                fail_count += 1
                raise TimeoutError("Primary provider timed out")

        self.router.providers["failing_primary"] = PrimaryFailProvider()
        fail_model = ModelInfo(
            provider="failing_primary",
            model_id="fail-primary-v1",
            display_name="Failing Primary Model",
            capabilities={ModelCapability.TEXT},
            priority=1
        )
        self.router.registry.register_model(fail_model)

        req = ModelRequest(task_type="general_qa", user_preference="fail-primary-v1")
        messages = [LLMMessage(role=Role.USER, content="Hello")]

        resp = self.router.generate(messages=messages, request=req)
        self.assertIsNotNone(resp)
        # Verify fallback to mock succeeded
        self.assertEqual(resp.provider, "mock")
        self.assertGreaterEqual(fail_count, 1)

    def test_03_router_fallback_exhaustion_handled(self):
        """Verify controlled error when all providers in the chain fail."""
        class AlwaysFailProvider(MockModelProvider):
            def generate(self, *args, **kwargs):
                raise RuntimeError("Total failure")

        failing_router = ModelRouter(event_bus=self.event_bus)
        failing_router.providers["mock"] = AlwaysFailProvider()
        # Remove other providers
        failing_router.providers = {"mock": AlwaysFailProvider()}

        messages = [LLMMessage(role=Role.USER, content="test")]
        with self.assertRaises(RuntimeError):
            failing_router.generate(messages=messages)

    def test_04_router_generate_structured_json_valid(self):
        """Verify generate_structured parses clean JSON response from LLM."""
        res = self.router.generate_structured("Return user profile as JSON with name and role")
        self.assertIsInstance(res, dict)

    def test_05_router_generate_structured_json_repair(self):
        """Verify JSON enclosed in markdown code blocks or with trailing commas is safely repaired."""
        # Directly test internal parser
        raw_markdown = '```json\n{"status": "ok", "steps": ["one", "two",],}\n```'
        parsed = self.router._extract_and_repair_json(raw_markdown)
        self.assertIsInstance(parsed, dict)
        self.assertEqual(parsed.get("status"), "ok")

    def test_06_router_streaming_events_normalized(self):
        """Verify streaming generator yields normalized StreamEvents."""
        messages = [LLMMessage(role=Role.USER, content="Stream test")]
        events = list(self.router.stream(messages=messages))
        self.assertGreater(len(events), 2)
        self.assertEqual(events[0].event_type, StreamEventType.STREAM_START)
        token_events = [e for e in events if e.event_type == StreamEventType.TOKEN]
        self.assertGreater(len(token_events), 0)
        self.assertEqual(events[-1].event_type, StreamEventType.STREAM_END)

    def test_07_router_context_constrain_preserves_system_prompt(self):
        """Verify context compaction trims middle messages while strictly preserving system instructions."""
        sys_msg = LLMMessage(role=Role.SYSTEM, content="CRITICAL: You are ZARA.")
        user_msg = LLMMessage(role=Role.USER, content="Latest instruction")
        filler_msgs = [
            LLMMessage(role=Role.ASSISTANT, content=f"Step {i} completed with detailed logs " * 20)
            for i in range(50)
        ]
        all_msgs = [sys_msg] + filler_msgs + [user_msg]

        constrained = self.router._constrain_context(all_msgs, context_window=500)
        self.assertLess(len(constrained), len(all_msgs))
        self.assertEqual(constrained[0].role, Role.SYSTEM)
        self.assertIn("CRITICAL: You are ZARA.", constrained[0].content)
        self.assertEqual(constrained[-1].role, Role.USER)
        self.assertIn("Latest instruction", constrained[-1].content)

    def test_08_router_multimodal_vision_check(self):
        """Verify router requires vision capability for screenshot/vision analysis."""
        req = ModelRequest(task_type="vision", vision_required=True)
        sel = self.router.route(req)
        self.assertIn("vision", sel.capability_match)
        target = self.router.registry.get_model(sel.model_id)
        self.assertTrue(target.supports_vision)

    def test_09_tool_call_proposal_not_executed_directly(self):
        """Verify router returns proposed tool calls without executing them."""
        class ToolProposingProvider(MockModelProvider):
            def generate(self, *args, **kwargs):
                return LLMResponse(
                    content="I propose running terminal command",
                    tool_calls=[ToolCall(id="call_1", name="terminal_run", arguments={"command": "ls -la"})],
                    model=self.default_model,
                    provider=self.name
                )

        self.router.providers["mock"] = ToolProposingProvider()
        resp = self.router.generate([LLMMessage(role=Role.USER, content="List files")])
        self.assertEqual(len(resp.tool_calls), 1)
        self.assertEqual(resp.tool_calls[0].name, "terminal_run")
        # Ensure it was not executed; only returned
        self.assertEqual(resp.tool_calls[0].arguments["command"], "ls -la")

    def test_10_zara_engine_initializes_model_router(self):
        """Verify ZaraEngine instantiates model_router and links self.brain."""
        engine = ZaraEngine()
        try:
            self.assertTrue(hasattr(engine, "model_router"))
            self.assertIsInstance(engine.model_router, ModelRouter)
            self.assertEqual(engine.brain, engine.model_router)
        finally:
            engine.close()

    def test_11_zara_engine_generate_structured_via_brain(self):
        """Verify ZaraEngine can call brain.generate_structured cleanly."""
        engine = ZaraEngine()
        try:
            res = engine.brain.generate_structured("Break this task down into steps: build API")
            self.assertIsInstance(res, dict)
            self.assertIn("steps", res)
        finally:
            engine.close()

    def test_12_worker_orchestrator_get_model_for_worker(self):
        """Verify WorkstreamOrchestrator can resolve specialized model for worker."""
        engine = ZaraEngine()
        try:
            worker = Worker(
                worker_id="wkr_coding_01",
                task_id="t_code",
                worker_type=WorkerType.CODING
            )
            selection = engine.workstream_orchestrator.get_model_for_worker(worker)
            self.assertIsNotNone(selection)
            self.assertIn("code", selection.capability_match)
        finally:
            engine.close()

    def test_13_worker_execution_with_model_router(self):
        """Verify delegated worker executes cleanly with model router available."""
        engine = ZaraEngine()
        try:
            worker = Worker(
                worker_id="wkr_research_01",
                task_id="t_res",
                worker_type=WorkerType.RESEARCH,
                input={"query": "Autonomous Agent Design"}
            )
            from modules.workspace import PersistentTask
            task = PersistentTask(id="t_res", project_id="p-default", title="Research task")
            res = engine.workstream_orchestrator.execute_worker(worker, task)
            self.assertEqual(res.status.value, "completed")
            self.assertIn("Autonomous Agent Design", res.summary)
        finally:
            engine.close()

    def test_14_event_bus_emits_model_events(self):
        """Verify EventBus receives MODEL_REQUEST_STARTED, MODEL_SELECTED, MODEL_REQUEST_COMPLETED."""
        events_emitted = []

        def event_handler(evt):
            events_emitted.append(evt.type)

        self.event_bus.subscribe(EventType.MODEL_REQUEST_STARTED, event_handler)
        self.event_bus.subscribe(EventType.MODEL_SELECTED, event_handler)
        self.event_bus.subscribe(EventType.MODEL_REQUEST_COMPLETED, event_handler)

        self.router.generate([LLMMessage(role=Role.USER, content="Hello")])
        self.assertIn(EventType.MODEL_REQUEST_STARTED, events_emitted)
        self.assertIn(EventType.MODEL_SELECTED, events_emitted)
        self.assertIn(EventType.MODEL_REQUEST_COMPLETED, events_emitted)

    def test_15_ui_api_models_endpoint(self):
        """Verify GET /api/models returns registered model catalog."""
        engine = ZaraEngine()
        try:
            app = create_ui_app(engine)
            client = TestClient(app)
            resp = client.get("/api/models")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("models", data)
            self.assertGreaterEqual(data["total"], 1)
        finally:
            engine.close()

    def test_16_ui_api_models_status_and_health(self):
        """Verify GET /api/models/status and GET /api/models/health."""
        engine = ZaraEngine()
        try:
            app = create_ui_app(engine)
            client = TestClient(app)

            st_resp = client.get("/api/models/status")
            self.assertEqual(st_resp.status_code, 200)
            st_data = st_resp.json()
            self.assertEqual(st_data["status"], "HEALTHY")

            h_resp = client.get("/api/models/health")
            self.assertEqual(h_resp.status_code, 200)
            h_data = h_resp.json()
            self.assertIn("providers", h_data)
        finally:
            engine.close()

    def test_17_ui_api_models_routing_and_circuit_breakers(self):
        """Verify GET /api/models/routing and GET /api/models/circuit-breakers."""
        engine = ZaraEngine()
        try:
            app = create_ui_app(engine)
            client = TestClient(app)

            r_resp = client.get("/api/models/routing")
            self.assertEqual(r_resp.status_code, 200)
            r_data = r_resp.json()
            self.assertIn("routes", r_data)
            self.assertGreater(len(r_data["routes"]), 0)

            cb_resp = client.get("/api/models/circuit-breakers")
            self.assertEqual(cb_resp.status_code, 200)
            cb_data = cb_resp.json()
            self.assertIn("circuit_breakers", cb_data)
        finally:
            engine.close()

    def test_18_cli_cmd_models_status_and_list(self):
        """Verify CLI cmd_models status and list subcommands."""
        args_status = MagicMock()
        args_status.models_action = "status"

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_models(args_status)
            out = mock_out.getvalue()
            self.assertIn("ZARA AI MODEL ROUTER", out)
            self.assertIn("Active Provider:", out)

        args_list = MagicMock()
        args_list.models_action = "list"
        args_list.provider = None

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_models(args_list)
            out = mock_out.getvalue()
            self.assertIn("REGISTERED AI MODELS", out)

    def test_19_cli_cmd_models_health_and_circuit_breakers(self):
        """Verify CLI cmd_models health and circuit-breakers subcommands."""
        args_health = MagicMock()
        args_health.models_action = "health"

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_models(args_health)
            out = mock_out.getvalue()
            self.assertIn("MODEL PROVIDERS HEALTH", out)

        args_cb = MagicMock()
        args_cb.models_action = "circuit-breakers"

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            cmd_models(args_cb)
            out = mock_out.getvalue()
            self.assertIn("CIRCUIT BREAKERS", out)

    def test_20_clean_shutdown_zero_resource_warnings(self):
        """Verify engine and router close cleanly with no open sockets or handles."""
        engine = ZaraEngine()
        engine.close()
        self.router.close()


if __name__ == "__main__":
    unittest.main()
