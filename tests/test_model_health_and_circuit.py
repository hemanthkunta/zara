"""
ZARA Phase 16: Tests for Model Health Tracking, Circuit Breakers, Retry Policy, and Error Classification.
"""
import time
import unittest
from unittest.mock import patch, MagicMock

from modules.model_router import (
    ModelHealthTracker,
    CircuitBreaker,
    CircuitState,
    ProviderStatus,
    ModelFailureType,
    ModelRouter,
    ModelRequest,
    MockModelProvider
)


class TestModelHealthAndCircuit(unittest.TestCase):
    def setUp(self):
        self.tracker = ModelHealthTracker(ttl_seconds=10.0)
        self.breaker = CircuitBreaker(provider_name="test_prov", failure_threshold=3, cooldown_seconds=0.2)

    def test_01_health_tracker_initial_state(self):
        """Verify initial status of unregistered provider returns unknown gracefully."""
        h = self.tracker.get_health("unknown_provider")
        self.assertEqual(h["status"], ProviderStatus.UNKNOWN.value)
        self.assertEqual(h["error_count"], 0)
        self.assertFalse(h["is_fresh"])

    def test_02_health_tracker_record_success(self):
        """Verify recording successful requests updates status and rolling latency."""
        self.tracker.record_success("google", 0.05)
        self.tracker.record_success("google", 0.07)
        h = self.tracker.get_health("google")
        self.assertEqual(h["status"], ProviderStatus.HEALTHY.value)
        self.assertGreater(h["avg_latency_ms"], 0)
        self.assertIsNotNone(h["last_success"])
        self.assertTrue(h["is_fresh"])

    def test_03_health_tracker_record_failure(self):
        """Verify recording failure increments error and consecutive failure counts."""
        self.tracker.record_failure("google", ModelFailureType.SERVER_ERROR, "500 Internal Error")
        h = self.tracker.get_health("google")
        self.assertEqual(h["error_count"], 1)
        self.assertEqual(h["consecutive_failures"], 1)
        self.assertEqual(h["status"], ProviderStatus.DEGRADED.value)

    def test_04_health_tracker_ttl_freshness(self):
        """Verify health tracker evaluates TTL expiration accurately."""
        short_tracker = ModelHealthTracker(ttl_seconds=0.05)
        short_tracker.record_success("anthropic", 0.04)
        self.assertTrue(short_tracker.get_health("anthropic")["is_fresh"])
        time.sleep(0.06)
        self.assertFalse(short_tracker.get_health("anthropic")["is_fresh"])

    def test_05_health_tracker_rate_limit_tracking(self):
        """Verify RATE_LIMIT failure sets status to RATE_LIMITED."""
        self.tracker.record_failure("openai", ModelFailureType.RATE_LIMIT, "429 Too Many Requests")
        h = self.tracker.get_health("openai")
        self.assertEqual(h["status"], ProviderStatus.RATE_LIMITED.value)
        self.assertEqual(h["rate_limit_count"], 1)

    def test_06_health_tracker_auth_failure_tracking(self):
        """Verify AUTHENTICATION failure sets status to AUTH_FAILED."""
        self.tracker.record_failure("anthropic", ModelFailureType.AUTHENTICATION, "401 Invalid Key")
        h = self.tracker.get_health("anthropic")
        self.assertEqual(h["status"], ProviderStatus.AUTH_FAILED.value)
        self.assertEqual(h["auth_failures"], 1)

    def test_07_circuit_breaker_initial_state(self):
        """Verify initial breaker state is HEALTHY and can_execute is True."""
        self.assertEqual(self.breaker.state, CircuitState.HEALTHY)
        self.assertTrue(self.breaker.can_execute())
        self.assertEqual(self.breaker.failure_count, 0)

    def test_08_circuit_breaker_degraded_state(self):
        """Verify single failure transitions breaker to DEGRADED state."""
        self.breaker.record_failure(ModelFailureType.SERVER_ERROR)
        self.assertEqual(self.breaker.state, CircuitState.DEGRADED)
        self.assertEqual(self.breaker.failure_count, 1)
        self.assertTrue(self.breaker.can_execute())

    def test_09_circuit_breaker_open_state(self):
        """Verify consecutive failures reaching threshold transitions breaker to OPEN."""
        self.breaker.record_failure(ModelFailureType.SERVER_ERROR)
        self.breaker.record_failure(ModelFailureType.SERVER_ERROR)
        self.breaker.record_failure(ModelFailureType.SERVER_ERROR)
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertEqual(self.breaker.failure_count, 3)

    def test_10_circuit_breaker_blocks_execution_when_open(self):
        """Verify can_execute returns False when breaker is OPEN and cooldown has not elapsed."""
        for _ in range(3):
            self.breaker.record_failure(ModelFailureType.TIMEOUT)
        self.assertEqual(self.breaker.state, CircuitState.OPEN)
        self.assertFalse(self.breaker.can_execute())

    def test_11_circuit_breaker_cooldown_to_half_open(self):
        """Verify cooldown expiration transitions OPEN breaker to HALF_OPEN on next check."""
        for _ in range(3):
            self.breaker.record_failure(ModelFailureType.TIMEOUT)
        self.assertFalse(self.breaker.can_execute())
        time.sleep(0.25)  # Wait for cooldown
        self.assertTrue(self.breaker.can_execute())
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

    def test_12_circuit_breaker_half_open_success_recovers(self):
        """Verify successful probe in HALF_OPEN state resets breaker to HEALTHY."""
        for _ in range(3):
            self.breaker.record_failure(ModelFailureType.TIMEOUT)
        time.sleep(0.25)
        self.breaker.can_execute()  # Transitions to HALF_OPEN
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        self.breaker.record_success()
        self.assertEqual(self.breaker.state, CircuitState.HEALTHY)
        self.assertEqual(self.breaker.failure_count, 0)

    def test_13_circuit_breaker_half_open_failure_reopens(self):
        """Verify failure during probe in HALF_OPEN immediately re-opens circuit."""
        for _ in range(3):
            self.breaker.record_failure(ModelFailureType.TIMEOUT)
        time.sleep(0.25)
        self.breaker.can_execute()  # Transitions to HALF_OPEN
        self.assertEqual(self.breaker.state, CircuitState.HALF_OPEN)

        self.breaker.record_failure(ModelFailureType.TIMEOUT)
        self.assertEqual(self.breaker.state, CircuitState.OPEN)

    def test_14_error_classification_timeout(self):
        """Verify router classifies timeout errors accurately."""
        router = ModelRouter()
        self.assertEqual(router._classify_error(TimeoutError("Request timed out")), ModelFailureType.TIMEOUT)
        self.assertEqual(router._classify_error(RuntimeError("Connection timed out after 30s")), ModelFailureType.TIMEOUT)

    def test_15_error_classification_auth(self):
        """Verify router classifies auth failures accurately."""
        router = ModelRouter()
        self.assertEqual(router._classify_error(PermissionError("Unauthorized API key")), ModelFailureType.AUTHENTICATION)
        self.assertEqual(router._classify_error(RuntimeError("401 Unauthorized")), ModelFailureType.AUTHENTICATION)

    def test_16_error_classification_rate_limit(self):
        """Verify router classifies rate limit errors accurately."""
        router = ModelRouter()
        self.assertEqual(router._classify_error(RuntimeError("Rate limit exceeded 429")), ModelFailureType.RATE_LIMIT)

    def test_17_error_classification_server_error(self):
        """Verify router classifies server errors accurately."""
        router = ModelRouter()
        self.assertEqual(router._classify_error(RuntimeError("500 Server Error")), ModelFailureType.SERVER_ERROR)
        self.assertEqual(router._classify_error(RuntimeError("503 Service Unavailable")), ModelFailureType.SERVER_ERROR)

    def test_18_retry_policy_retries_transient_error(self):
        """Verify router retries on transient errors."""
        router = ModelRouter()
        call_count = 0

        class FlakyProvider(MockModelProvider):
            def generate(self, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 2:
                    raise TimeoutError("Simulated transient timeout")
                return super().generate(*args, **kwargs)

        router.providers["flaky"] = FlakyProvider()
        flaky_model = router.registry.get_model("mock-zara-model")
        flaky_model.provider = "flaky"

        req = ModelRequest(task_type="general_qa", user_preference="flaky")
        from brain.base import LLMMessage, Role
        resp = router.generate(messages=[LLMMessage(role=Role.USER, content="ping")], request=req)
        self.assertIsNotNone(resp)
        self.assertEqual(call_count, 2)

    def test_19_retry_policy_does_not_retry_auth_failure(self):
        """Verify router does not retry fatal authentication errors."""
        router = ModelRouter()
        call_count = 0

        class AuthFailProvider(MockModelProvider):
            def generate(self, *args, **kwargs):
                nonlocal call_count
                call_count += 1
                raise PermissionError("401 Invalid API key")

        router.providers["auth_bad"] = AuthFailProvider()
        bad_model = router.registry.get_model("mock-zara-model")
        bad_model.provider = "auth_bad"

        req = ModelRequest(task_type="general_qa", user_preference="auth_bad")
        from brain.base import LLMMessage, Role
        # Should failover or complete via mock without repeatedly retrying the auth failure
        router.generate(messages=[LLMMessage(role=Role.USER, content="test")], request=req)
        # Verify it didn't retry 3 times on the same auth failure
        self.assertEqual(call_count, 1)

    def test_20_circuit_breaker_serialization(self):
        """Verify CircuitBreaker to_dict serialization."""
        self.breaker.record_failure(ModelFailureType.TIMEOUT)
        d = self.breaker.to_dict()
        self.assertEqual(d["provider"], "test_prov")
        self.assertEqual(d["state"], CircuitState.DEGRADED.value)
        self.assertEqual(d["failure_count"], 1)


if __name__ == "__main__":
    unittest.main()
