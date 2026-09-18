"""
ZARA Gemini LLM Provider: Direct API adapter for Google Gemini models.
"""
import os
import json
import urllib.request
from typing import List, Dict, Any, Optional
from brain.base import LLMProvider, LLMMessage, LLMResponse, LLMUsage, Role, ToolCall
from config.settings import DEFAULT_MODEL_GEMINI

class GeminiProvider(LLMProvider):
    def __init__(self, model_name: str = DEFAULT_MODEL_GEMINI, api_key: Optional[str] = None):
        super().__init__(model_name)
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

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
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY not set.")

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"

        contents = []
        for m in messages:
            role = "user" if m.role in (Role.USER, Role.SYSTEM) else "model"
            contents.append({
                "role": role,
                "parts": [{"text": m.content}]
            })

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        if system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        headers = {"Content-Type": "application/json"}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)

        import ssl
        try:
            ctx = ssl.create_default_context()
        except Exception:
            ctx = None

        try:
            resp_handle = urllib.request.urlopen(req, timeout=60, context=ctx)
        except urllib.error.HTTPError as http_err:
            http_err.close()
            raise
        except urllib.error.URLError as ssl_err:
            if "CERTIFICATE_VERIFY_FAILED" in str(ssl_err):
                u_ctx = ssl._create_unverified_context()
                try:
                    resp_handle = urllib.request.urlopen(req, timeout=60, context=u_ctx)
                except urllib.error.HTTPError as h_err:
                    h_err.close()
                    raise
            else:
                raise

        with resp_handle as resp:
            data = json.loads(resp.read().decode("utf-8"))

        candidates = data.get("candidates", [])
        if not candidates:
            raise RuntimeError(f"Gemini API returned no candidates: {data}")

        first = candidates[0]
        text = ""
        parts = first.get("content", {}).get("parts", [])
        for p in parts:
            if "text" in p:
                text += p["text"]

        usage_metadata = data.get("usageMetadata", {})
        prompt_tokens = usage_metadata.get("promptTokenCount", 0)
        completion_tokens = usage_metadata.get("candidatesTokenCount", 0)

        return LLMResponse(
            content=text,
            usage=LLMUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens
            ),
            model=self.model_name,
            provider="gemini"
        )
