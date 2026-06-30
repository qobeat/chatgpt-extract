"""Local Ollama provider — $0 marginal cost (refactor of the original call_ollama)."""
from __future__ import annotations

import json
import os
import sys
import urllib.request

from .base import Provider, ProviderError, Usage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ollama_probe  # noqa: E402

# Default per-item generation cap. The benchmark/summarize path legitimately
# needs a large budget (full ADOS records); the interactive `ask` path overrides
# this with a much smaller cap (FR-Q16) so a warm answer fits the 15s target.
DEFAULT_NUM_PREDICT = 1500


def think_for_model(model: str, override: "str | bool | None" = None
                    ) -> "str | bool":
    """Resolve the Ollama `think` value for a model (FR-Q16).

    Docs-verified: `gpt-oss` IGNORES boolean `think` and only honours the levels
    `"low"`/`"medium"`/`"high"`, so passing `False` does NOT suppress its
    reasoning — it just burns tokens (and seconds) we believe are off. For
    `gpt-oss*` tags we therefore request the lowest reasoning level; every other
    model keeps the boolean `False` (reasoning off where the boolean is honoured).
    An explicit `override` (including `False`) always wins, so it stays
    name-driven yet configurable.
    """
    if override is not None:
        return override
    base = (model or "").split(":")[0].lower()
    if base.startswith("gpt-oss") or base == "gptoss":
        return "low"
    return False


class OllamaProvider(Provider):
    name = "ollama"

    def __init__(self, model: str, host: str | None = None, num_ctx: int = 32768,
                 keep_alive: str = "24h", timeout: int = 300,
                 num_predict: int = DEFAULT_NUM_PREDICT,
                 think: "str | bool | None" = None, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.host = ollama_probe.normalize_host(host)
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.num_predict = num_predict
        self.think = think_for_model(model, think)

    def preflight(self) -> tuple[bool, str]:
        return ollama_probe.preflight(self.model, self.host, num_ctx=self.num_ctx)

    def _payload(self, system: str, prompt: str, json_mode: bool,
                 stream: bool) -> dict:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": stream,
            "think": self.think,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0.1, "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict},
        }
        if json_mode:
            payload["format"] = "json"
        return payload

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        data = self._post_json(
            self.host.rstrip("/") + "/api/chat",
            self._payload(system, prompt, json_mode, stream=False),
            {"Content-Type": "application/json"},
            # A local timeout means the model spilled to CPU / is too big for
            # 24 GB — fail fast with one clean kill instead of retrying 4×
            # (NFR-R2). The per-item loop records it as an honest llm_ok:false.
            retry_on_timeout=False,
            max_attempts=1,
        )
        text = (data.get("message") or {}).get("content", "")
        if not text:
            raise ProviderError("ollama: empty response")
        # Ollama reports nanosecond durations; convert to ms so the harness can
        # separate one-time model load from prompt-eval and generation.
        def _ns_ms(v: object) -> float:
            return round((float(v) if v else 0.0) / 1e6, 1)
        usage = Usage(
            input_tokens=int(data.get("prompt_eval_count") or 0),
            output_tokens=int(data.get("eval_count") or 0),
            load_ms=_ns_ms(data.get("load_duration")),
            prompt_eval_ms=_ns_ms(data.get("prompt_eval_duration")),
            eval_ms=_ns_ms(data.get("eval_duration")),
            total_ms=_ns_ms(data.get("total_duration")),
        )
        return text, usage

    def stream(self, system: str, prompt: str, json_mode: bool = False):
        """Yield response text chunks as Ollama generates them (FR-Q16).

        Improves *perceived* latency for interactive `gpt ask`: the first token
        arrives in ~prompt-eval time instead of after the whole answer. Yields
        `str` deltas; the final yield is a `Usage` object (server timings) so the
        caller can still record load/eval split. Raises ProviderError on a bad
        status. The socket timeout (self.timeout) still bounds a stalled stream.
        """
        payload = self._payload(system, prompt, json_mode, stream=True)
        req = urllib.request.Request(
            self.host.rstrip("/") + "/api/chat",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST")
        usage = Usage()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                for raw in resp:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    chunk = (obj.get("message") or {}).get("content", "")
                    if chunk:
                        yield chunk
                    if obj.get("done"):
                        def _ns_ms(v: object) -> float:
                            return round((float(v) if v else 0.0) / 1e6, 1)
                        usage = Usage(
                            input_tokens=int(obj.get("prompt_eval_count") or 0),
                            output_tokens=int(obj.get("eval_count") or 0),
                            load_ms=_ns_ms(obj.get("load_duration")),
                            prompt_eval_ms=_ns_ms(obj.get("prompt_eval_duration")),
                            eval_ms=_ns_ms(obj.get("eval_duration")),
                            total_ms=_ns_ms(obj.get("total_duration")),
                        )
        except Exception as e:  # noqa: BLE001
            # Mirror complete()'s fail-fast contract: a stalled/spilled local
            # stream raises ProviderError so the caller flags it UNUSABLE.
            raise ProviderError(f"ollama stream: {e}") from e
        yield usage
