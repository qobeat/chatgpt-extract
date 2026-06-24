"""Local Ollama provider — $0 marginal cost (refactor of the original call_ollama)."""
from __future__ import annotations

import os
import sys

from .base import Provider, ProviderError, Usage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ollama_probe  # noqa: E402


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str, host: str | None = None, num_ctx: int = 32768,
                 keep_alive: str = "24h", timeout: int = 300, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.host = ollama_probe.normalize_host(host)
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive

    def preflight(self) -> tuple[bool, str]:
        return ollama_probe.preflight(self.model, self.host, num_ctx=self.num_ctx)

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "think": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.1, "num_ctx": self.num_ctx, "num_predict": 1500},
        }
        if json_mode:
            payload["format"] = "json"
        data = self._post_json(
            self.host.rstrip("/") + "/api/chat",
            payload,
            {"Content-Type": "application/json"},
        )
        text = (data.get("message") or {}).get("content", "")
        if not text:
            raise ProviderError("ollama: empty response")
        usage = Usage(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
        )
        return text, usage
