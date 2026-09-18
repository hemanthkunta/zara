"""
ZARA Anthropic & OpenAI & Ollama LLM Providers: HTTP adapters for Claude, GPT, and local models.
"""
import os
import json
import urllib.request
from typing import List, Dict, Any, Optional
from brain.base import LLMProvider, LLMMessage, LLMResponse, LLMUsage, Role
from config.settings import DEFAULT_MODEL_ANTHROPIC, DEFAULT_MODEL_OPENAI, DEFAULT_MODEL_OLLAMA, OLLAMA_BASE_URL

class AnthropicProvider(LLMProvider):
    def __init__(self, model_name: str = DEFAULT_MODEL_ANTHROPIC, api_key: Optional[str] = None):
        super().__init__(model_name)
        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set.")

        url = "https://api.anthropic.com/v1/messages"
        payload_messages = [{"role": m.role.value, "content": m.content} for m in messages if m.role != Role.SYSTEM]
        body = {
            "model": self.model_name,
            "messages": payload_messages,
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
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = "".join(b.get("text", "") for b in data.get("content", []))
        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("input_tokens", 0)
        comp_tokens = usage_data.get("output_tokens", 0)

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_tokens, completion_tokens=comp_tokens, total_tokens=prompt_tokens+comp_tokens),
            model=self.model_name,
            provider="anthropic"
        )

class OpenAIProvider(LLMProvider):
    def __init__(self, model_name: str = DEFAULT_MODEL_OPENAI, api_key: Optional[str] = None):
        super().__init__(model_name)
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError("OPENAI_API_KEY not set.")

        url = "https://api.openai.com/v1/chat/completions"
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msgs.append({"role": m.role.value, "content": m.content})

        body = {
            "model": self.model_name,
            "messages": msgs,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage", {})
        prompt_tokens = usage_data.get("prompt_tokens", 0)
        comp_tokens = usage_data.get("completion_tokens", 0)

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_tokens, completion_tokens=comp_tokens, total_tokens=prompt_tokens+comp_tokens),
            model=self.model_name,
            provider="openai"
        )

class OllamaProvider(LLMProvider):
    def __init__(self, model_name: str = DEFAULT_MODEL_OLLAMA, base_url: str = OLLAMA_BASE_URL):
        super().__init__(model_name)
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def generate(
        self,
        messages: List[LLMMessage],
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        tools: Optional[List[Dict[str, Any]]] = None
    ) -> LLMResponse:
        url = f"{self.base_url}/api/chat"
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        for m in messages:
            msgs.append({"role": m.role.value, "content": m.content})

        body = {
            "model": self.model_name,
            "messages": msgs,
            "stream": False,
            "options": {"temperature": temperature}
        }
        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        text = data.get("message", {}).get("content", "")
        prompt_eval = data.get("prompt_eval_count", self.count_tokens(str(messages)))
        eval_count = data.get("eval_count", self.count_tokens(text))

        return LLMResponse(
            content=text,
            usage=LLMUsage(prompt_tokens=prompt_eval, completion_tokens=eval_count, total_tokens=prompt_eval+eval_count),
            model=self.model_name,
            provider="ollama"
        )
