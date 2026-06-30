"""Provider interface + shared HTTP with retry/backoff for 429/5xx."""
from __future__ import annotations

import json
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


def _is_timeout(exc: BaseException) -> bool:
    """True when an exception (or the reason wrapped by a URLError) is a socket
    timeout. socket.timeout is a TimeoutError subclass since Python 3.10."""
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError)


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
                   retry_on_timeout: bool = True,
                   max_attempts: int | None = None,
                   ) -> dict:
        """POST JSON with bounded retry/backoff on 429/5xx and transport errors.

        retry_on_timeout=False makes a socket/connection TIMEOUT terminal: the
        local Ollama path uses this so a CPU-spilled/too-big item fails once
        (NFR-R2) instead of burning ~4×timeout before giving up. max_attempts
        bounds the total tries (defaults to self.max_retries)."""
        attempts = self.max_retries if max_attempts is None else max(1, max_attempts)
        data = json.dumps(payload).encode("utf-8")
        last_err = "unknown"
        for attempt in range(1, attempts + 1):
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
                    if attempt < attempts:  # don't sleep before a terminal fail
                        self._backoff(attempt)
                    continue
                raise ProviderError(last_err) from e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last_err = str(e)
                # A local timeout means the model spilled/too big — fail fast on
                # the path that asks for it, rather than retrying 4× (NFR-R2).
                # Under a tight budget (max_retries=1) this also makes the HTTP
                # openai/anthropic SLA path abort at the socket timeout instead
                # of burning a backoff sleep before the terminal failure.
                if not retry_on_timeout and _is_timeout(e):
                    raise ProviderError(
                        f"{self.name}: timed out after {self.timeout}s "
                        f"(no retry; likely VRAM spill)") from e
                if attempt < attempts:  # don't sleep before a terminal fail
                    self._backoff(attempt)
                continue
        raise RetryableError(f"{self.name}: exhausted {attempts} attempt(s) "
                             f"({last_err})")

    def _backoff(self, attempt: int) -> None:
        delay = min(30.0, (2 ** (attempt - 1))) + random.uniform(0, 0.5)
        time.sleep(delay)
