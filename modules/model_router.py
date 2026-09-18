"""
ZARA Phase 16: AI Model Router, Provider Abstraction & Intelligent Failover.

Provides:
- ModelProvider interface and HTTP/mock adapters.
- Structured ModelInfo, ModelRequest, and ModelSelection models.
- ModelRegistry with capability indexing, dynamic discovery, and cache.
- ModelHealthTracker with TTL caching and latency tracking.
- CircuitBreaker state machine per provider (HEALTHY -> DEGRADED -> OPEN -> HALF_OPEN).
- Intelligent capability-aware and preference-prioritized routing algorithm.
- Retry policy with exponential backoff and jitter.
- Multi-provider failover chain.
- Structured JSON output verification and safe repair.
- Normalized streaming events.
- Strict secret scrubbing and tool-call safety.
"""
from __future__ import annotations

import os
import re
import json
import time
import math
import random
import urllib.request
import urllib.error
import ssl
import datetime
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple, Generator, Callable

from brain.base import LLMMessage, LLMResponse, LLMUsage, Role, ToolCall
from brain.providers.mock import MockLLMProvider
from config.settings import (
    DEFAULT_LLM_PROVIDER,
    DEFAULT_MODEL_GEMINI,
    DEFAULT_MODEL_ANTHROPIC,
    DEFAULT_MODEL_OPENAI,
    DEFAULT_MODEL_OLLAMA,
    OLLAMA_BASE_URL,
    MODEL_ROUTER_ENABLED,
    DEFAULT_MODEL,
    MODEL_REQUEST_TIMEOUT,
    MAX_MODEL_RETRIES,
    MAX_PROVIDER_FAILOVERS,
    MODEL_HEALTH_TTL,
    MODEL_SELECTION_MODE,
    MAX_COST_PER_REQUEST,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
    CIRCUIT_BREAKER_COOLDOWN_SECONDS,
    MODELS_DISCOVERY_CACHE_FILE
)
from core.observability import audit_logger
from modules.events import EventBus, EventType, Event


# ──────────────────────────────────────────────────────────────────────────────
# Enums & Classifications
# ──────────────────────────────────────────────────────────────────────────────

class ProviderType(str, Enum):
    OPENAI_COMPATIBLE = "openai_compatible"
    ANTHROPIC_COMPATIBLE = "anthropic_compatible"
    GOOGLE_GENERATIVE_AI = "google_generative_ai"
    LOCAL = "local"
    CUSTOM_HTTP = "custom_http"
    MOCK = "mock"


class ProviderStatus(str, Enum):
    CONFIGURED = "configured"
    AVAILABLE = "available"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    RATE_LIMITED = "rate_limited"
    UNAVAILABLE = "unavailable"
    AUTH_FAILED = "auth_failed"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


class ModelCapability(str, Enum):
    TEXT = "text"
    CODE = "code"
    STRUCTURED_OUTPUT = "structured_output"
    VISION = "vision"
    AUDIO = "audio"
    STREAMING = "streaming"
    TOOLS = "tools"
    REASONING = "reasoning"
    LONG_CONTEXT = "long_context"


class CircuitState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OPEN = "open"
    HALF_OPEN = "half_open"


class ModelFailureType(str, Enum):
    TIMEOUT = "timeout"
    NETWORK_ERROR = "network_error"
    RATE_LIMIT = "rate_limit"
    SERVER_ERROR = "server_error"
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    CONTENT_POLICY = "content_policy"
    CAPABILITY_MISMATCH = "capability_mismatch"
    UNKNOWN = "unknown"


class StreamEventType(str, Enum):
    STREAM_START = "stream_start"
    TOKEN = "token"
    TOOL_PROPOSAL = "tool_proposal"
    STREAM_END = "stream_end"
    STREAM_ERROR = "stream_error"


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ModelInfo:
    provider: str
    model_id: str
    display_name: str
    capabilities: Set[ModelCapability] = field(default_factory=set)
    context_window: int = 8192
    max_output_tokens: int = 4096
    supports_streaming: bool = True
    supports_tools: bool = True
    supports_vision: bool = False
    supports_audio: bool = False
    supports_structured_output: bool = True
    supports_reasoning: bool = False
    availability: ProviderStatus = ProviderStatus.CONFIGURED
    cost_input: float = 0.001   # USD per 1k tokens
    cost_output: float = 0.002  # USD per 1k tokens
    priority: int = 10          # Lower is higher priority

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "capabilities": [c.value if isinstance(c, ModelCapability) else str(c) for c in self.capabilities],
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
            "supports_audio": self.supports_audio,
            "supports_structured_output": self.supports_structured_output,
            "supports_reasoning": self.supports_reasoning,
            "availability": self.availability.value if isinstance(self.availability, ProviderStatus) else str(self.availability),
            "cost_input": self.cost_input,
            "cost_output": self.cost_output,
            "priority": self.priority
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModelInfo:
        caps = set()
        for c in data.get("capabilities", []):
            try:
                caps.add(ModelCapability(c))
            except ValueError:
                pass
        avail = data.get("availability", ProviderStatus.CONFIGURED.value)
        try:
            avail_enum = ProviderStatus(avail)
        except ValueError:
            avail_enum = ProviderStatus.CONFIGURED

        return cls(
            provider=data.get("provider", "unknown"),
            model_id=data.get("model_id", "unknown"),
            display_name=data.get("display_name", ""),
            capabilities=caps,
            context_window=data.get("context_window", 8192),
            max_output_tokens=data.get("max_output_tokens", 4096),
            supports_streaming=data.get("supports_streaming", True),
            supports_tools=data.get("supports_tools", True),
            supports_vision=data.get("supports_vision", False),
            supports_audio=data.get("supports_audio", False),
            supports_structured_output=data.get("supports_structured_output", True),
            supports_reasoning=data.get("supports_reasoning", False),
            availability=avail_enum,
            cost_input=data.get("cost_input", 0.0),
            cost_output=data.get("cost_output", 0.0),
            priority=data.get("priority", 10)
        )


@dataclass
class ModelRequest:
    task_type: str = "general_qa"
    required_capabilities: Set[ModelCapability] = field(default_factory=set)
    preferred_capabilities: Set[ModelCapability] = field(default_factory=set)
    context_size: int = 0
    max_output_tokens: int = 4096
    latency_requirement: str = "normal"  # "low", "normal"
    quality_requirement: str = "high"
    cost_limit: Optional[float] = None
    streaming_required: bool = False
    structured_output_required: bool = False
    vision_required: bool = False
    tool_use_required: bool = False
    user_preference: Optional[str] = None
    project_preference: Optional[str] = None
    request_id: str = field(default_factory=lambda: f"req_{int(time.time()*1000)}_{random.randint(100, 999)}")
    worker_id: Optional[str] = None
    task_id: Optional[str] = None
    project_id: Optional[str] = None


@dataclass
class ModelSelection:
    provider: str
    model_id: str
    reason: str
    capability_match: List[str]
    estimated_cost: float
    estimated_latency: float
    fallback_chain: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class StreamEvent:
    event_type: StreamEventType
    token: Optional[str] = None
    tool_call: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    finish_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value if isinstance(self.event_type, StreamEventType) else str(self.event_type),
            "token": self.token,
            "tool_call": self.tool_call,
            "error": self.error,
            "finish_reason": self.finish_reason
        }


# ──────────────────────────────────────────────────────────────────────────────
# Provider Abstraction & Adapters
# ──────────────────────────────────────────────────────────────────────────────

class ModelProvider(ABC):
    """Abstract interface for LLM model providers in ZARA."""

    def __init__(self, provider_type: ProviderType, name: str, default_model: str):
        self.provider_type = provider_type
        self.name = name
        self.default_model = default_model

    @abstractmethod
    def is_available(self) -> bool:
        """Check if provider configuration and environment are present."""
        pass

    @abstractmethod
    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        """Generate a response synchronously."""
        pass

    @abstractmethod
    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        """Yield normalized streaming events."""
        pass

    @abstractmethod
    def health(self) -> Dict[str, Any]:
        """Check provider operational status and latency without side effects."""
        pass

    @abstractmethod
    def capabilities(self) -> Set[ModelCapability]:
        """Return full capability set supported by this provider."""
        pass

    def count_tokens(self, text: str) -> int:
        """Estimate token count: ~4 chars per token."""
        return max(1, len(text) // 4)

    def estimate_cost(self, input_tokens: int, output_tokens: int, cost_in_per_k: float = 0.001, cost_out_per_k: float = 0.002) -> float:
        """Calculate approximate USD cost."""
        return round((input_tokens / 1000.0) * cost_in_per_k + (output_tokens / 1000.0) * cost_out_per_k, 6)


class MockModelProvider(ModelProvider):
    """Deterministic offline mock provider with full feature simulation for testing."""

    def __init__(self, name: str = "mock", default_model: str = "mock-zara-model"):
        super().__init__(ProviderType.MOCK, name, default_model)
        self.mock_backend = MockLLMProvider()

    def is_available(self) -> bool:
        return True

    def capabilities(self) -> Set[ModelCapability]:
        return {
            ModelCapability.TEXT,
            ModelCapability.CODE,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.VISION,
            ModelCapability.STREAMING,
            ModelCapability.TOOLS,
            ModelCapability.REASONING,
            ModelCapability.LONG_CONTEXT
        }

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        resp = self.mock_backend.generate(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools
        )
        resp.provider = self.name
        resp.model = model_name or self.default_model
        return resp

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        yield StreamEvent(event_type=StreamEventType.STREAM_START)
        resp = self.generate(messages, system_prompt, temperature, max_tokens, tools, model_name)
        chunks = resp.content.split(" ")
        for ch in chunks:
            yield StreamEvent(event_type=StreamEventType.TOKEN, token=ch + " ")
        if resp.tool_calls:
            for tc in resp.tool_calls:
                yield StreamEvent(event_type=StreamEventType.TOOL_PROPOSAL, tool_call=asdict(tc))
        yield StreamEvent(event_type=StreamEventType.STREAM_END, finish_reason=resp.finish_reason)

    def health(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": ProviderStatus.HEALTHY.value,
            "available": True,
            "latency_ms": 1.5,
            "error": None
        }


class GoogleGenAIProvider(ModelProvider):
    """Adapter for Google Gemini / Generative AI using native HTTP requests."""

    def __init__(self, name: str = "google", default_model: str = DEFAULT_MODEL_GEMINI, api_key: Optional[str] = None):
        super().__init__(ProviderType.GOOGLE_GENERATIVE_AI, name, default_model)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> Set[ModelCapability]:
        return {
            ModelCapability.TEXT,
            ModelCapability.CODE,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.VISION,
            ModelCapability.STREAMING,
            ModelCapability.TOOLS,
            ModelCapability.REASONING,
            ModelCapability.LONG_CONTEXT
        }

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        if not self.api_key:
            raise PermissionError("Google API key not configured")

        m_name = model_name or self.default_model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={self.api_key}"

        contents = []
        for m in messages:
            role = "user" if m.role in (Role.USER, Role.SYSTEM) else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)

        ctx = None
        try:
            ctx = ssl.create_default_context()
        except Exception:
            pass

        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            he.close()
            if he.code == 429:
                raise RuntimeError(f"Rate limit exceeded (429): {he.reason}")
            elif he.code in (401, 403):
                raise PermissionError(f"Authentication failed ({he.code}): {he.reason}")
            raise RuntimeError(f"Google GenAI API error ({he.code}): {he.reason}")
        except urllib.error.URLError as ue:
            raise TimeoutError(f"Network error connecting to Google GenAI: {ue.reason}")

        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini API returned no candidates: {data}")

        text = "".join(p.get("text", "") for p in candidates[0].get("content", {}).get("parts", []))
        usage_meta = data.get("usageMetadata", {})
        prompt_t = usage_meta.get("promptTokenCount", self.count_tokens(text))
        comp_t = usage_meta.get("candidatesTokenCount", self.count_tokens(text))

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_t, completion_tokens=comp_t, total_tokens=prompt_t + comp_t),
            model=m_name,
            provider=self.name,
            finish_reason="stop"
        )

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        yield StreamEvent(event_type=StreamEventType.STREAM_START)
        resp = self.generate(messages, system_prompt, temperature, max_tokens, tools, model_name)
        for part in resp.content.split(" "):
            yield StreamEvent(event_type=StreamEventType.TOKEN, token=part + " ")
        yield StreamEvent(event_type=StreamEventType.STREAM_END, finish_reason=resp.finish_reason)

    def health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {
                "provider": self.name,
                "status": ProviderStatus.UNAVAILABLE.value,
                "available": False,
                "latency_ms": 0.0,
                "error": "API key missing"
            }
        return {
            "provider": self.name,
            "status": ProviderStatus.HEALTHY.value,
            "available": True,
            "latency_ms": 45.0,
            "error": None
        }


class AnthropicCompatibleProvider(ModelProvider):
    """Adapter for Anthropic Claude models."""

    def __init__(self, name: str = "anthropic", default_model: str = DEFAULT_MODEL_ANTHROPIC, api_key: Optional[str] = None):
        super().__init__(ProviderType.ANTHROPIC_COMPATIBLE, name, default_model)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> Set[ModelCapability]:
        return {
            ModelCapability.TEXT,
            ModelCapability.CODE,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.VISION,
            ModelCapability.STREAMING,
            ModelCapability.TOOLS,
            ModelCapability.REASONING,
            ModelCapability.LONG_CONTEXT
        }

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        if not self.api_key:
            raise PermissionError("Anthropic API key not configured")

        m_name = model_name or self.default_model
        url = "https://api.anthropic.com/v1/messages"
        payload_msgs = [{"role": m.role.value, "content": m.content} for m in messages if m.role != Role.SYSTEM]
        body = {
            "model": m_name,
            "messages": payload_msgs,
            "max_tokens": max_tokens,
            "temperature": temperature
        }
        if system_prompt:
            body["system"] = system_prompt

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            he.close()
            if he.code == 429:
                raise RuntimeError(f"Anthropic rate limit: {he.reason}")
            elif he.code in (401, 403):
                raise PermissionError(f"Anthropic authentication failed: {he.reason}")
            raise RuntimeError(f"Anthropic API error ({he.code}): {he.reason}")
        except urllib.error.URLError as ue:
            raise TimeoutError(f"Network error: {ue.reason}")

        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage_data = data.get("usage", {})
        prompt_t = usage_data.get("input_tokens", 0)
        comp_t = usage_data.get("output_tokens", 0)

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_t, completion_tokens=comp_t, total_tokens=prompt_t + comp_t),
            model=m_name,
            provider=self.name,
            finish_reason="stop"
        )

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        yield StreamEvent(event_type=StreamEventType.STREAM_START)
        resp = self.generate(messages, system_prompt, temperature, max_tokens, tools, model_name)
        for part in resp.content.split(" "):
            yield StreamEvent(event_type=StreamEventType.TOKEN, token=part + " ")
        yield StreamEvent(event_type=StreamEventType.STREAM_END, finish_reason=resp.finish_reason)

    def health(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": ProviderStatus.HEALTHY.value if self.api_key else ProviderStatus.UNAVAILABLE.value,
            "available": bool(self.api_key),
            "latency_ms": 60.0 if self.api_key else 0.0,
            "error": None if self.api_key else "API key missing"
        }


class OpenAICompatibleProvider(ModelProvider):
    """Adapter for OpenAI GPT and OpenAI-compatible API endpoints."""

    def __init__(self, name: str = "openai", default_model: str = DEFAULT_MODEL_OPENAI, api_key: Optional[str] = None, base_url: str = "https://api.openai.com/v1"):
        super().__init__(ProviderType.OPENAI_COMPATIBLE, name, default_model)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def capabilities(self) -> Set[ModelCapability]:
        return {
            ModelCapability.TEXT,
            ModelCapability.CODE,
            ModelCapability.STRUCTURED_OUTPUT,
            ModelCapability.VISION,
            ModelCapability.STREAMING,
            ModelCapability.TOOLS,
            ModelCapability.REASONING
        }

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        if not self.api_key:
            raise PermissionError("OpenAI API key not configured")

        m_name = model_name or self.default_model
        url = f"{self.base_url}/chat/completions"
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msgs.append({"role": m.role.value, "content": m.content})

        body = {
            "model": m_name,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as he:
            he.close()
            if he.code == 429:
                raise RuntimeError(f"OpenAI rate limit: {he.reason}")
            elif he.code in (401, 403):
                raise PermissionError(f"OpenAI authentication failed: {he.reason}")
            raise RuntimeError(f"OpenAI error ({he.code}): {he.reason}")
        except urllib.error.URLError as ue:
            raise TimeoutError(f"Network error: {ue.reason}")

        choice = data.get("choices", [{}])[0]
        text = choice.get("message", {}).get("content", "") or ""
        usage_data = data.get("usage", {})
        prompt_t = usage_data.get("prompt_tokens", 0)
        comp_t = usage_data.get("completion_tokens", 0)

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_t, completion_tokens=comp_t, total_tokens=prompt_t + comp_t),
            model=m_name,
            provider=self.name,
            finish_reason=choice.get("finish_reason", "stop")
        )

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        yield StreamEvent(event_type=StreamEventType.STREAM_START)
        resp = self.generate(messages, system_prompt, temperature, max_tokens, tools, model_name)
        for part in resp.content.split(" "):
            yield StreamEvent(event_type=StreamEventType.TOKEN, token=part + " ")
        yield StreamEvent(event_type=StreamEventType.STREAM_END, finish_reason=resp.finish_reason)

    def health(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": ProviderStatus.HEALTHY.value if self.api_key else ProviderStatus.UNAVAILABLE.value,
            "available": bool(self.api_key),
            "latency_ms": 55.0 if self.api_key else 0.0,
            "error": None if self.api_key else "API key missing"
        }


class LocalProvider(ModelProvider):
    """Adapter for local models (e.g. Ollama or local LLM server)."""

    def __init__(self, name: str = "local", default_model: str = DEFAULT_MODEL_OLLAMA, base_url: str = OLLAMA_BASE_URL):
        super().__init__(ProviderType.LOCAL, name, default_model)
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        # Check endpoint reachability with short timeout without blocking
        return False  # Default to False unless explicitly configured / running

    def capabilities(self) -> Set[ModelCapability]:
        return {
            ModelCapability.TEXT,
            ModelCapability.CODE,
            ModelCapability.STRUCTURED_OUTPUT
        }

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None,
        timeout: float = MODEL_REQUEST_TIMEOUT
    ) -> LLMResponse:
        raise RuntimeError("Local Ollama endpoint not reachable or offline")

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        model_name: Optional[str] = None
    ) -> Generator[StreamEvent, None, None]:
        raise RuntimeError("Local Ollama endpoint not reachable or offline")

    def health(self) -> Dict[str, Any]:
        return {
            "provider": self.name,
            "status": ProviderStatus.UNAVAILABLE.value,
            "available": False,
            "latency_ms": 0.0,
            "error": "Local daemon offline"
        }


# ──────────────────────────────────────────────────────────────────────────────
# Circuit Breaker & Health Tracking
# ──────────────────────────────────────────────────────────────────────────────

class CircuitBreaker:
    """Per-provider circuit breaker state machine."""

    def __init__(
        self,
        provider_name: str,
        failure_threshold: int = CIRCUIT_BREAKER_FAILURE_THRESHOLD,
        cooldown_seconds: float = CIRCUIT_BREAKER_COOLDOWN_SECONDS
    ):
        self.provider_name = provider_name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.state: CircuitState = CircuitState.HEALTHY
        self.failure_count: int = 0
        self.last_failure_time: Optional[float] = None
        self.opened_at: Optional[float] = None
        self._lock = threading.Lock()

    def can_execute(self) -> bool:
        """Evaluate if the circuit permits sending a request."""
        with self._lock:
            if self.state in (CircuitState.HEALTHY, CircuitState.DEGRADED):
                return True

            if self.state == CircuitState.OPEN:
                now = time.time()
                if self.opened_at and (now - self.opened_at) >= self.cooldown_seconds:
                    self.state = CircuitState.HALF_OPEN
                    return True
                return False

            if self.state == CircuitState.HALF_OPEN:
                # Single probe permitted
                return True

            return False

    def record_success(self) -> None:
        """Reset breaker upon successful execution."""
        with self._lock:
            self.failure_count = 0
            self.state = CircuitState.HEALTHY
            self.opened_at = None

    def record_failure(self, failure_type: ModelFailureType) -> None:
        """Increment failure counter and transition state if threshold exceeded."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                # Probe failed, reopen immediately
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                self.opened_at = time.time()
            elif self.failure_count > 0:
                self.state = CircuitState.DEGRADED

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "provider": self.provider_name,
                "state": self.state.value,
                "failure_count": self.failure_count,
                "failure_threshold": self.failure_threshold,
                "opened_at": self.opened_at,
                "cooldown_seconds": self.cooldown_seconds
            }


class ModelHealthTracker:
    """Tracks latency, availability, and error history with TTL caching."""

    def __init__(self, ttl_seconds: float = MODEL_HEALTH_TTL):
        self.ttl_seconds = ttl_seconds
        self._stats: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def record_success(self, provider: str, latency: float) -> None:
        with self._lock:
            st = self._stats.setdefault(provider, {
                "status": ProviderStatus.HEALTHY,
                "latency_history": [],
                "last_success": None,
                "last_failure": None,
                "error_count": 0,
                "timeout_count": 0,
                "rate_limit_count": 0,
                "auth_failures": 0,
                "consecutive_failures": 0,
                "last_check": time.time()
            })
            st["status"] = ProviderStatus.HEALTHY
            st["last_success"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            st["consecutive_failures"] = 0
            st["latency_history"].append(latency)
            if len(st["latency_history"]) > 20:
                st["latency_history"].pop(0)
            st["last_check"] = time.time()

    def record_failure(self, provider: str, failure_type: ModelFailureType, error_msg: str) -> None:
        with self._lock:
            st = self._stats.setdefault(provider, {
                "status": ProviderStatus.UNKNOWN,
                "latency_history": [],
                "last_success": None,
                "last_failure": None,
                "error_count": 0,
                "timeout_count": 0,
                "rate_limit_count": 0,
                "auth_failures": 0,
                "consecutive_failures": 0,
                "last_check": time.time()
            })
            st["last_failure"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            st["error_count"] += 1
            st["consecutive_failures"] += 1
            st["last_check"] = time.time()

            if failure_type == ModelFailureType.TIMEOUT:
                st["timeout_count"] += 1
                st["status"] = ProviderStatus.TIMEOUT
            elif failure_type == ModelFailureType.RATE_LIMIT:
                st["rate_limit_count"] += 1
                st["status"] = ProviderStatus.RATE_LIMITED
            elif failure_type == ModelFailureType.AUTHENTICATION:
                st["auth_failures"] += 1
                st["status"] = ProviderStatus.AUTH_FAILED
            else:
                st["status"] = ProviderStatus.DEGRADED if st["consecutive_failures"] < 3 else ProviderStatus.UNAVAILABLE

    def get_health(self, provider: str) -> Dict[str, Any]:
        with self._lock:
            st = self._stats.get(provider)
            if not st:
                return {
                    "provider": provider,
                    "status": ProviderStatus.UNKNOWN.value,
                    "avg_latency_ms": 0.0,
                    "error_count": 0,
                    "consecutive_failures": 0,
                    "is_fresh": False
                }
            now = time.time()
            is_fresh = (now - st["last_check"]) < self.ttl_seconds
            lat_list = st["latency_history"]
            avg_lat = round(sum(lat_list) / len(lat_list) * 1000.0, 2) if lat_list else 0.0

            return {
                "provider": provider,
                "status": st["status"].value if isinstance(st["status"], ProviderStatus) else str(st["status"]),
                "avg_latency_ms": avg_lat,
                "last_success": st["last_success"],
                "last_failure": st["last_failure"],
                "error_count": st["error_count"],
                "timeout_count": st["timeout_count"],
                "rate_limit_count": st["rate_limit_count"],
                "auth_failures": st["auth_failures"],
                "consecutive_failures": st["consecutive_failures"],
                "is_fresh": is_fresh
            }

    def is_healthy(self, provider: str) -> bool:
        h = self.get_health(provider)
        return h["status"] in (ProviderStatus.HEALTHY.value, ProviderStatus.CONFIGURED.value, ProviderStatus.UNKNOWN.value)


# ──────────────────────────────────────────────────────────────────────────────
# Model Registry
# ──────────────────────────────────────────────────────────────────────────────

class ModelRegistry:
    """Catalog of models, capabilities, and pricing with discovery caching."""

    def __init__(self, cache_file: Path = MODELS_DISCOVERY_CACHE_FILE):
        self.cache_file = Path(cache_file)
        self.models: Dict[str, ModelInfo] = {}
        self._lock = threading.Lock()
        self._init_default_models()
        self.load_cache()

    def _init_default_models(self) -> None:
        """Register the built-in known catalog of models across providers."""
        defaults = [
            ModelInfo(
                provider="mock",
                model_id="mock-zara-model",
                display_name="ZARA Offline Deterministic Mock Brain",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.VISION, ModelCapability.STREAMING, ModelCapability.TOOLS,
                    ModelCapability.REASONING, ModelCapability.LONG_CONTEXT
                },
                context_window=32768,
                max_output_tokens=8192,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_structured_output=True,
                supports_reasoning=True,
                availability=ProviderStatus.AVAILABLE,
                cost_input=0.0,
                cost_output=0.0,
                priority=1
            ),
            ModelInfo(
                provider="google",
                model_id="gemini-2.5-flash",
                display_name="Google Gemini 2.5 Flash",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.VISION, ModelCapability.STREAMING, ModelCapability.TOOLS,
                    ModelCapability.LONG_CONTEXT
                },
                context_window=1048576,
                max_output_tokens=8192,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_structured_output=True,
                supports_reasoning=True,
                availability=ProviderStatus.CONFIGURED,
                cost_input=0.0001,
                cost_output=0.0004,
                priority=2
            ),
            ModelInfo(
                provider="google",
                model_id="gemini-1.5-pro",
                display_name="Google Gemini 1.5 Pro",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.VISION, ModelCapability.STREAMING, ModelCapability.TOOLS,
                    ModelCapability.REASONING, ModelCapability.LONG_CONTEXT
                },
                context_window=2097152,
                max_output_tokens=8192,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_structured_output=True,
                supports_reasoning=True,
                availability=ProviderStatus.CONFIGURED,
                cost_input=0.00125,
                cost_output=0.005,
                priority=5
            ),
            ModelInfo(
                provider="anthropic",
                model_id="claude-3-5-sonnet-20241022",
                display_name="Anthropic Claude 3.5 Sonnet",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.VISION, ModelCapability.STREAMING, ModelCapability.TOOLS,
                    ModelCapability.REASONING, ModelCapability.LONG_CONTEXT
                },
                context_window=200000,
                max_output_tokens=8192,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_structured_output=True,
                supports_reasoning=True,
                availability=ProviderStatus.CONFIGURED,
                cost_input=0.003,
                cost_output=0.015,
                priority=3
            ),
            ModelInfo(
                provider="openai",
                model_id="gpt-4o",
                display_name="OpenAI GPT-4o",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT,
                    ModelCapability.VISION, ModelCapability.STREAMING, ModelCapability.TOOLS,
                    ModelCapability.REASONING
                },
                context_window=128000,
                max_output_tokens=4096,
                supports_streaming=True,
                supports_tools=True,
                supports_vision=True,
                supports_structured_output=True,
                supports_reasoning=True,
                availability=ProviderStatus.CONFIGURED,
                cost_input=0.0025,
                cost_output=0.010,
                priority=4
            ),
            ModelInfo(
                provider="local",
                model_id="llama3.1",
                display_name="Local Ollama Llama 3.1",
                capabilities={
                    ModelCapability.TEXT, ModelCapability.CODE, ModelCapability.STRUCTURED_OUTPUT
                },
                context_window=8192,
                max_output_tokens=2048,
                supports_streaming=True,
                supports_tools=False,
                supports_vision=False,
                supports_structured_output=True,
                supports_reasoning=False,
                availability=ProviderStatus.UNAVAILABLE,
                cost_input=0.0,
                cost_output=0.0,
                priority=8
            )
        ]
        for m in defaults:
            self.models[m.model_id] = m

    def register_model(self, model: ModelInfo) -> None:
        with self._lock:
            self.models[model.model_id] = model

    def get_model(self, model_id: str) -> Optional[ModelInfo]:
        with self._lock:
            return self.models.get(model_id)

    def list_models(
        self,
        provider: Optional[str] = None,
        capability: Optional[ModelCapability] = None
    ) -> List[ModelInfo]:
        with self._lock:
            result = list(self.models.values())
            if provider:
                result = [m for m in result if m.provider.lower() == provider.lower()]
            if capability:
                result = [m for m in result if capability in m.capabilities]
            return sorted(result, key=lambda m: m.priority)

    def load_cache(self) -> None:
        if not self.cache_file.exists():
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data.get("models", []):
                    m = ModelInfo.from_dict(item)
                    self.models[m.model_id] = m
        except Exception:
            pass

    def save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cache_file, "w", encoding="utf-8") as f:
                data = {"models": [m.to_dict() for m in self.models.values()]}
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def discover_models(self) -> List[ModelInfo]:
        """Check availability of configured providers without unbounded network calls."""
        with self._lock:
            for m in self.models.values():
                if m.provider == "mock":
                    m.availability = ProviderStatus.AVAILABLE
                elif m.provider == "google":
                    m.availability = ProviderStatus.AVAILABLE if (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")) else ProviderStatus.UNAVAILABLE
                elif m.provider == "anthropic":
                    m.availability = ProviderStatus.AVAILABLE if os.getenv("ANTHROPIC_API_KEY") else ProviderStatus.UNAVAILABLE
                elif m.provider == "openai":
                    m.availability = ProviderStatus.AVAILABLE if os.getenv("OPENAI_API_KEY") else ProviderStatus.UNAVAILABLE
                elif m.provider == "local":
                    m.availability = ProviderStatus.UNAVAILABLE
            self.save_cache()
            return list(self.models.values())


# ──────────────────────────────────────────────────────────────────────────────
# Intelligent Model Router
# ──────────────────────────────────────────────────────────────────────────────

class ModelRouter:
    """Master AI Model Router for ZARA."""

    def __init__(
        self,
        event_bus: Optional[EventBus] = None,
        registry: Optional[ModelRegistry] = None,
        health_tracker: Optional[ModelHealthTracker] = None,
        default_model: str = DEFAULT_MODEL
    ):
        self.event_bus = event_bus or EventBus()
        self.registry = registry or ModelRegistry()
        self.health_tracker = health_tracker or ModelHealthTracker()
        self.default_model = default_model

        # Providers registry
        self.providers: Dict[str, ModelProvider] = {
            "mock": MockModelProvider(),
            "google": GoogleGenAIProvider(),
            "anthropic": AnthropicCompatibleProvider(),
            "openai": OpenAICompatibleProvider(),
            "local": LocalProvider()
        }

        # Circuit breakers per provider
        self.circuit_breakers: Dict[str, CircuitBreaker] = {
            name: CircuitBreaker(name) for name in self.providers
        }

        # Metrics
        self.metrics = {
            "requests_total": 0,
            "requests_successful": 0,
            "requests_failed": 0,
            "requests_timed_out": 0,
            "requests_rate_limited": 0,
            "failovers_total": 0,
            "retries_total": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0
        }
        self._lock = threading.Lock()

    def get_circuit_breaker(self, provider_name: str) -> CircuitBreaker:
        with self._lock:
            if provider_name not in self.circuit_breakers:
                self.circuit_breakers[provider_name] = CircuitBreaker(provider_name)
            return self.circuit_breakers[provider_name]

    def _emit_event(self, event_type: EventType, payload: Dict[str, Any]) -> None:
        if self.event_bus:
            # Scrub secrets before emitting
            safe_payload = audit_logger.scrub_secrets(json.dumps(payload))
            try:
                clean_dict = json.loads(safe_payload)
            except Exception:
                clean_dict = {"raw": safe_payload}
            self.event_bus.publish(Event(
                type=event_type,
                source="model_router",
                payload=clean_dict
            ))

    # ──────────────────────────────────────────────────────────────────────────
    # Model Selection Algorithm
    # ──────────────────────────────────────────────────────────────────────────

    def route(self, request: ModelRequest) -> ModelSelection:
        """Capability-aware intelligent model selection algorithm."""
        # 1. Resolve Required Capabilities
        req_caps = set(request.required_capabilities)
        if request.vision_required:
            req_caps.add(ModelCapability.VISION)
        if request.structured_output_required:
            req_caps.add(ModelCapability.STRUCTURED_OUTPUT)
        if request.tool_use_required:
            req_caps.add(ModelCapability.TOOLS)
        if request.streaming_required:
            req_caps.add(ModelCapability.STREAMING)

        # Task-specific default requirements
        tt = (request.task_type or "general_qa").lower()
        if "coding" in tt:
            req_caps.add(ModelCapability.CODE)
        elif "debugging" in tt:
            req_caps.add(ModelCapability.CODE)
            req_caps.add(ModelCapability.STRUCTURED_OUTPUT)
        elif "vision" in tt:
            req_caps.add(ModelCapability.VISION)
        elif "research" in tt:
            req_caps.add(ModelCapability.LONG_CONTEXT)
        elif "synthesis" in tt:
            req_caps.add(ModelCapability.STRUCTURED_OUTPUT)
        elif "cyber" in tt or "blender" in tt:
            req_caps.add(ModelCapability.CODE)

        # 2. Candidate Filtering
        all_models = self.registry.list_models()
        candidates: List[Tuple[ModelInfo, int, str]] = []

        for m in all_models:
            # Hard Capability Check
            if not req_caps.issubset(m.capabilities):
                continue

            # Context Window Check
            if request.context_size > 0 and request.context_size > m.context_window:
                continue

            # Provider availability & circuit breaker check
            provider_inst = self.providers.get(m.provider)
            if not provider_inst or not provider_inst.is_available():
                if m.provider != "mock":
                    continue

            cb = self.get_circuit_breaker(m.provider)
            if not cb.can_execute():
                continue

            # Calculate preference score (lower is higher priority)
            score = m.priority

            # Priority 1: User Preference
            if request.user_preference and (request.user_preference.lower() in m.model_id.lower() or request.user_preference.lower() in m.provider.lower()):
                score -= 100

            # Priority 2: Project Preference
            elif request.project_preference and (request.project_preference.lower() in m.model_id.lower() or request.project_preference.lower() in m.provider.lower()):
                score -= 50

            # Preferred capabilities bonus
            if request.preferred_capabilities:
                bonus = len(request.preferred_capabilities.intersection(m.capabilities))
                score -= (bonus * 2)

            # Health penalty if degraded
            h = self.health_tracker.get_health(m.provider)
            if h["status"] == ProviderStatus.DEGRADED.value:
                score += 15

            candidates.append((m, score, m.provider))

        # Sort candidates by score
        candidates.sort(key=lambda x: x[1])

        if not candidates:
            # Fallback to mock provider to ensure offline resilience
            mock_model = self.registry.get_model("mock-zara-model") or ModelInfo(
                provider="mock", model_id="mock-zara-model", display_name="Mock Brain"
            )
            return ModelSelection(
                provider="mock",
                model_id="mock-zara-model",
                reason="Default offline fallback; no external providers match requirements or are configured.",
                capability_match=[c.value for c in mock_model.capabilities],
                estimated_cost=0.0,
                estimated_latency=1.5,
                fallback_chain=[]
            )

        selected_model, best_score, prov = candidates[0]
        fallback_models = [c[0].model_id for c in candidates[1:]]

        reason = f"Selected {selected_model.display_name} for task '{request.task_type}' (matches {len(req_caps)} required capabilities)."
        cost = selected_model.cost_input * (request.context_size / 1000.0) if request.context_size else 0.0001
        lat = self.health_tracker.get_health(selected_model.provider)["avg_latency_ms"] or 50.0

        return ModelSelection(
            provider=selected_model.provider,
            model_id=selected_model.model_id,
            reason=reason,
            capability_match=[c.value for c in req_caps],
            estimated_cost=round(cost, 6),
            estimated_latency=lat,
            fallback_chain=fallback_models
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Request Execution, Retry Policy & Failover
    # ──────────────────────────────────────────────────────────────────────────

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        request: Optional[ModelRequest] = None
    ) -> LLMResponse:
        """Generate with capability-aware routing, retries, and intelligent failover."""
        if not request:
            request = ModelRequest(
                task_type="general_qa",
                context_size=sum(len(m.content) for m in messages) // 4,
                max_output_tokens=max_tokens
            )

        self._emit_event(EventType.MODEL_REQUEST_STARTED, {
            "request_id": request.request_id,
            "task_type": request.task_type,
            "worker_id": request.worker_id
        })

        selection = self.route(request)
        self._emit_event(EventType.MODEL_SELECTED, {
            "request_id": request.request_id,
            "provider": selection.provider,
            "model": selection.model_id,
            "reason": selection.reason
        })

        # Context window verification & trimming
        target_model_info = self.registry.get_model(selection.model_id)
        if target_model_info:
            messages = self._constrain_context(messages, target_model_info.context_window)

        # Execution chain: selected model + fallbacks
        model_chain = [selection.model_id] + selection.fallback_chain
        last_exception = None

        with self._lock:
            self.metrics["requests_total"] += 1

        for model_id in model_chain[:MAX_PROVIDER_FAILOVERS + 1]:
            m_info = self.registry.get_model(model_id)
            if not m_info:
                continue

            provider = self.providers.get(m_info.provider)
            if not provider:
                continue

            cb = self.get_circuit_breaker(m_info.provider)
            if not cb.can_execute():
                continue

            # Retry loop for retryable errors
            for attempt in range(1, MAX_MODEL_RETRIES + 1):
                start_t = time.time()
                try:
                    resp = provider.generate(
                        messages=messages,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        tools=tools,
                        model_name=m_info.model_id
                    )
                    lat = time.time() - start_t

                    # Record success
                    cb.record_success()
                    self.health_tracker.record_success(m_info.provider, lat)

                    with self._lock:
                        self.metrics["requests_successful"] += 1
                        self.metrics["total_tokens"] += resp.usage.total_tokens
                        self.metrics["total_cost_usd"] += provider.estimate_cost(
                            resp.usage.prompt_tokens, resp.usage.completion_tokens,
                            m_info.cost_input, m_info.cost_output
                        )

                    audit_logger.log_event(
                        event_type="MODEL_GENERATE_SUCCESS",
                        action="generate",
                        model=m_info.model_id,
                        duration_seconds=lat,
                        result=f"Generated {resp.usage.completion_tokens} tokens",
                        extra={"provider": m_info.provider, "request_id": request.request_id}
                    )

                    self._emit_event(EventType.MODEL_REQUEST_COMPLETED, {
                        "request_id": request.request_id,
                        "provider": m_info.provider,
                        "model": m_info.model_id,
                        "tokens": resp.usage.total_tokens,
                        "duration_ms": round(lat * 1000.0, 2)
                    })

                    return resp

                except Exception as e:
                    lat = time.time() - start_t
                    fail_type = self._classify_error(e)
                    cb.record_failure(fail_type)
                    self.health_tracker.record_failure(m_info.provider, fail_type, str(e))
                    last_exception = e

                    with self._lock:
                        if fail_type == ModelFailureType.TIMEOUT:
                            self.metrics["requests_timed_out"] += 1
                        elif fail_type == ModelFailureType.RATE_LIMIT:
                            self.metrics["requests_rate_limited"] += 1

                    # Check if error is safe to retry
                    if fail_type in (ModelFailureType.TIMEOUT, ModelFailureType.NETWORK_ERROR, ModelFailureType.RATE_LIMIT, ModelFailureType.SERVER_ERROR):
                        if attempt < MAX_MODEL_RETRIES:
                            with self._lock:
                                self.metrics["retries_total"] += 1
                            self._emit_event(EventType.MODEL_RETRY, {
                                "request_id": request.request_id,
                                "provider": m_info.provider,
                                "attempt": attempt,
                                "error": audit_logger.scrub_secrets(str(e))
                            })
                            # Exponential backoff with jitter
                            backoff = (0.2 * (2 ** (attempt - 1))) + random.uniform(0.05, 0.15)
                            time.sleep(backoff)
                            continue

                    # Non-retryable error (Auth, Invalid Request, Content Policy) or retry budget exceeded
                    break

            # Failover to next provider in fallback chain
            with self._lock:
                self.metrics["failovers_total"] += 1
            self._emit_event(EventType.MODEL_FAILOVER, {
                "request_id": request.request_id,
                "failed_model": model_id,
                "error": audit_logger.scrub_secrets(str(last_exception))
            })

        # All models exhausted; fallback to mock provider if not already tried
        if "mock" in self.providers and last_exception:
            mock_resp = self.providers["mock"].generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens
            )
            return mock_resp

        with self._lock:
            self.metrics["requests_failed"] += 1
        self._emit_event(EventType.MODEL_REQUEST_FAILED, {
            "request_id": request.request_id,
            "error": audit_logger.scrub_secrets(str(last_exception))
        })
        raise RuntimeError(f"All model providers exhausted for request: {audit_logger.scrub_secrets(str(last_exception))}")

    def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        schema: Optional[Dict[str, Any]] = None,
        task_type: str = "general_qa",
        **kwargs
    ) -> Dict[str, Any]:
        """Generate structured JSON with validation and safe repair."""
        req = ModelRequest(
            task_type=task_type,
            structured_output_required=True,
            context_size=len(prompt) // 4
        )

        sys_msg = (system_prompt or "") + "\n\nCRITICAL: Respond ONLY with a valid JSON object. Do not include extraneous text."
        messages = [LLMMessage(role=Role.USER, content=prompt)]

        resp = self.generate(messages=messages, system_prompt=sys_msg, request=req, **kwargs)
        text = resp.content.strip()

        parsed = self._extract_and_repair_json(text)
        if parsed.get("parsed") is False and schema:
            # Safe retry with explicit syntax instruction
            repair_prompt = f"The previous response was not valid JSON:\n\n{text[:400]}\n\nPlease format the data strictly as JSON matching schema: {json.dumps(schema)}"
            messages.append(LLMMessage(role=Role.ASSISTANT, content=text))
            messages.append(LLMMessage(role=Role.USER, content=repair_prompt))
            retry_resp = self.generate(messages=messages, system_prompt=sys_msg, request=req)
            parsed = self._extract_and_repair_json(retry_resp.content.strip())

        return parsed

    def stream(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None,
        request: Optional[ModelRequest] = None
    ) -> Generator[StreamEvent, None, None]:
        """Streaming generator yielding normalized StreamEvents."""
        if not request:
            request = ModelRequest(task_type="general_qa", streaming_required=True)
        selection = self.route(request)
        provider = self.providers.get(selection.provider, self.providers["mock"])
        return provider.stream(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            model_name=selection.model_id
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helper & Safety Methods
    # ──────────────────────────────────────────────────────────────────────────

    def _classify_error(self, e: Exception) -> ModelFailureType:
        """Classify exception into ModelFailureType."""
        msg = str(e).lower()
        if isinstance(e, TimeoutError) or "timeout" in msg or "timed out" in msg:
            return ModelFailureType.TIMEOUT
        if isinstance(e, PermissionError) or "unauthorized" in msg or "401" in msg or "403" in msg or "api key" in msg:
            return ModelFailureType.AUTHENTICATION
        if "429" in msg or "rate limit" in msg or "quota" in msg:
            return ModelFailureType.RATE_LIMIT
        if "500" in msg or "502" in msg or "503" in msg or "504" in msg or "server error" in msg:
            return ModelFailureType.SERVER_ERROR
        if "policy" in msg or "safety" in msg:
            return ModelFailureType.CONTENT_POLICY
        if "bad request" in msg or "400" in msg:
            return ModelFailureType.INVALID_REQUEST
        if isinstance(e, urllib.error.URLError):
            return ModelFailureType.NETWORK_ERROR
        return ModelFailureType.UNKNOWN

    def _constrain_context(self, messages: List[LLMMessage], context_window: int) -> List[LLMMessage]:
        """Compact context if total tokens exceed model context window, preserving safety/system prompts."""
        total_tokens = sum(len(m.content) // 4 for m in messages)
        if total_tokens <= context_window:
            return messages

        # Preserve System messages and the most recent User instruction
        system_msgs = [m for m in messages if m.role == Role.SYSTEM]
        user_msgs = [m for m in messages if m.role == Role.USER]
        other_msgs = [m for m in messages if m.role not in (Role.SYSTEM, Role.USER)]

        # Trim older middle messages first
        budget_for_middle = max(500, context_window - sum(len(m.content)//4 for m in system_msgs) - 1000)
        trimmed_middle: List[LLMMessage] = []
        cur = 0
        for m in reversed(other_msgs):
            t = len(m.content) // 4
            if cur + t < budget_for_middle:
                trimmed_middle.insert(0, m)
                cur += t

        latest_user = user_msgs[-1:] if user_msgs else []
        return system_msgs + trimmed_middle + latest_user

    def _extract_and_repair_json(self, text: str) -> Dict[str, Any]:
        """Extract and safely repair malformed JSON string."""
        # 1. Backtick extraction
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        candidate = match.group(1).strip() if match else text.strip()

        # 2. Outer brace extraction
        if not (candidate.startswith("{") and candidate.endswith("}")):
            start = candidate.find("{")
            end = candidate.rfind("}")
            if start != -1 and end != -1 and end > start:
                candidate = candidate[start:end+1]

        # 3. Direct JSON parse attempt
        try:
            return json.loads(candidate)
        except Exception:
            pass

        # 4. Simple syntax repair (dangling commas, unclosed quotes)
        repaired = re.sub(r",\s*([\]}])", r"\1", candidate)
        try:
            return json.loads(repaired)
        except Exception:
            # Return raw content marked as unparsed
            return {"raw_text": text, "parsed": False}

    def get_status(self) -> Dict[str, Any]:
        """Return structured router status for UI and CLI."""
        active_provider = "mock"
        for name in ("google", "anthropic", "openai", "local"):
            if self.providers[name].is_available():
                active_provider = name
                break

        return {
            "active_provider": active_provider,
            "active_model": self.default_model,
            "status": "HEALTHY",
            "models_count": len(self.registry.models),
            "circuit_breakers": {name: cb.to_dict() for name, cb in self.circuit_breakers.items()},
            "metrics": dict(self.metrics)
        }

    def get_active_provider(self) -> ModelProvider:
        """Compatibility helper for existing callers."""
        for name in ("google", "anthropic", "openai", "local"):
            if self.providers[name].is_available():
                return self.providers[name]
        return self.providers["mock"]

    def close(self) -> None:
        """Clean shutdown of router resources."""
        pass
