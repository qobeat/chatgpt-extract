"""Provider interface + shared HTTP with retry/backoff for 429/5xx."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


class ProviderError(Exception):
    """Raised on unrecoverable provider failure (after retries/backoff)."""


class RetryableError(ProviderError):
    """Raised on 429/5xx so the breaker/backoff layer can react."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    # Optional server-reported timings (milliseconds). Populated by providers
    # that expose them (e.g. Ollama's *_duration fields); 0.0 when unknown so
    # the load/warm split degrades gracefully for providers without VRAM load.
    load_ms: float = 0.0
    prompt_eval_ms: float = 0.0
    eval_ms: float = 0.0
    total_ms: float = 0.0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


class Provider:
    """Base class. Implementations return (text, Usage)."""

    name = "base"

    def __init__(self, model: str, timeout: int = 300, max_retries: int = 4,
                 **_: object):
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        raise NotImplementedError

    def preflight(self) -> tuple[bool, str]:
        """Cheap readiness check. Default: assume OK."""
        return True, "ok"

    # --- shared HTTP helper with exponential backoff + jitter ---------------
    def _post_json(self, url: str, payload: dict, headers: dict,
                   ) -> dict:
        data = json.dumps(payload).encode("utf-8")
        last_err = "unknown"
        for attempt in range(1, self.max_retries + 1):
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST")
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    body = resp.read().decode("utf-8", errors="replace")
                    return json.loads(body) if body else {}
            except urllib.error.HTTPError as e:
                code = e.code
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = str(e)
                last_err = f"HTTP {code}: {err_body[:300]}"
                if code == 429 or 500 <= code < 600:
                    self._backoff(attempt)
                    continue
                raise ProviderError(last_err) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)
                self._backoff(attempt)
                continue
        raise RetryableError(f"{self.name}: exhausted {self.max_retries} retries "
                             f"({last_err})")

    def _backoff(self, attempt: int) -> None:
        delay = min(30.0, (2 ** (attempt - 1))) + random.uniform(0, 0.5)
        time.sleep(delay)
