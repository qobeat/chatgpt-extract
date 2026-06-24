"""Anthropic (Claude) provider — Messages API; JSON via assistant prefill."""
from __future__ import annotations

import os

from .base import Provider, ProviderError, Usage


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-4",
                 base_url: str | None = None, timeout: int = 300,
                 max_tokens: int = 2048, api_version: str = "2023-06-01", **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL")
                         or "https://api.anthropic.com").rstrip("/")
        self.max_tokens = max_tokens
        self.api_version = api_version

    def preflight(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "ANTHROPIC_API_KEY is not set (add it to .env)."
        return True, "ok"

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        if not self.api_key:
            raise ProviderError("ANTHROPIC_API_KEY is not set")
        messages = [{"role": "user", "content": prompt}]
        # Prefill an opening brace to force a JSON object continuation.
        if json_mode:
            messages.append({"role": "assistant", "content": "{"})
        payload = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
        }
        data = self._post_json(
            self.base_url + "/v1/messages",
            payload,
            {"Content-Type": "application/json",
             "x-api-key": self.api_key,
             "anthropic-version": self.api_version},
        )
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        if json_mode:
            text = "{" + text  # restore the prefilled brace
        if not text:
            raise ProviderError(f"anthropic: empty content ({str(data)[:200]})")
        u = data.get("usage") or {}
        usage = Usage(
            input_tokens=int(u.get("input_tokens") or 0),
            output_tokens=int(u.get("output_tokens") or 0),
        )
        return text, usage
