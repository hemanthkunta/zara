"""
ZARA LLM Router: Provider orchestration, automatic fallback, and structured generation.
"""
import os
import json
import time
import re
from typing import List, Dict, Any, Optional
from brain.base import LLMProvider, LLMMessage, LLMResponse, Role
from brain.providers.mock import MockLLMProvider
from brain.providers.gemini import GeminiProvider
from brain.providers.adapters import AnthropicProvider, OpenAIProvider, OllamaProvider
from core.observability import audit_logger
from config.settings import DEFAULT_LLM_PROVIDER

class LLMRouter:
    def __init__(self, preferred_provider: str = DEFAULT_LLM_PROVIDER):
        self.preferred_provider = preferred_provider
        self.providers: Dict[str, LLMProvider] = {
            "gemini": GeminiProvider(),
            "anthropic": AnthropicProvider(),
            "openai": OpenAIProvider(),
            "ollama": OllamaProvider(),
            "mock": MockLLMProvider()
        }

    def get_active_provider(self) -> LLMProvider:
        """Select the best available LLM provider based on config and available keys."""
        if self.preferred_provider != "auto" and self.preferred_provider in self.providers:
            provider = self.providers[self.preferred_provider]
            if provider.is_available():
                return provider

        # Fallback priority chain
        for name in ("gemini", "anthropic", "openai", "ollama"):
            if self.providers[name].is_available():
                return self.providers[name]

        # Default fallback to offline mock provider
        return self.providers["mock"]

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        """Generate with automatic failover and audit logging."""
        active = self.get_active_provider()
        start = time.time()

        try:
            response = active.generate(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools
            )
            duration = time.time() - start
            audit_logger.log_event(
                event_type="LLM_GENERATE",
                action="generate",
                model=response.model,
                duration_seconds=duration,
                result=f"Generated {response.usage.completion_tokens} tokens"
            )
            return response
        except Exception as e:
            duration = time.time() - start
            audit_logger.log_event(
                event_type="LLM_ERROR",
                action="generate",
                model=active.model_name,
                duration_seconds=duration,
                error=str(e)
            )
            # Failover to mock provider if real provider failed
            if active != self.providers["mock"]:
                mock_resp = self.providers["mock"].generate(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )
                return mock_resp
            raise

    def generate_structured(
        self,
        prompt: str,
        system_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """Convenience method to generate and parse structured JSON from LLM."""
        messages = [
            LLMMessage(role=Role.USER, content=prompt + "\n\nCRITICAL: Reply ONLY with a valid JSON object. Do not include markdown code block backticks if possible.")
        ]
        resp = self.generate(messages, system_prompt=system_prompt)
        text = resp.content.strip()

        # Extract JSON if enclosed in markdown backticks
        json_match = re.search(r"```(?:json)?\s*(\{.*\}|\[.*\])\s*```", text, re.DOTALL)
        if json_match:
            text = json_match.group(1).strip()
        elif text.startswith("{") and text.endswith("}"):
            text = text
        else:
            # Try to find first { and last }
            start_idx = text.find("{")
            end_idx = text.rfind("}")
            if start_idx != -1 and end_idx != -1:
                text = text[start_idx:end_idx+1]

        try:
            return json.loads(text)
        except Exception:
            return {"raw_text": resp.content, "parsed": False}
