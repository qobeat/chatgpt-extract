"""OpenAI provider — Chat Completions with JSON response format."""
from __future__ import annotations

import os

from .base import Provider, ProviderError, Usage


class OpenAIProvider(Provider):
    name = "openai"

    def __init__(self, model: str = "gpt-5-mini",
                 base_url: str | None = None, timeout: int = 300, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")

    def preflight(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "OPENAI_API_KEY is not set (add it to .env)."
        return True, "ok"

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        if not self.api_key:
            raise ProviderError("OPENAI_API_KEY is not set")
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        data = self._post_json(
            self.base_url + "/chat/completions",
            payload,
            {"Content-Type": "application/json",
             "Authorization": f"Bearer {self.api_key}"},
        )
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"openai: no choices ({str(data)[:200]})")
        text = (choices[0].get("message") or {}).get("content", "")
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("prompt_tokens") or 0),
            output_tokens=int(u.get("completion_tokens") or 0),
        )
        return text, usage
