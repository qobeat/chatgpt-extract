"""
ask_route.py — capability router for `gpt ask` (REQ-6 / REQ-7).

`gpt ask` is designed around an interactive latency target (REQ-5): an answer
should come back fast on the *most capable available* engine. This module makes
that routing decision deterministic and testable, separate from the I/O that
gathers the inputs (GPU residency, cloud-engine availability).

Policy (precedence = "route, then fail"):
  1. A forced `--provider` is always honored (the cloud privacy gate still
     applies upstream).
  2. With routing enabled and the local model GPU-resident → local Ollama.
  3. With routing enabled and NO local GPU → the most capable available cloud
     engine, in `CLOUD_PREFER` order (codex > claude > cursor).
  4. Otherwise (no GPU, no cloud engine) → a hard error.

"cursor" routes to the Cursor-hosted `composer` model via the cursor provider.
"""
from __future__ import annotations

# Capability order (matches models_bank: codex > claude > cursor). Used when the
# local GPU path is unavailable; first AVAILABLE engine wins.
CLOUD_PREFER = ("codex", "claude", "cursor")

# Default model for the cursor route (Cursor-hosted composer).
CURSOR_MODEL = "composer-2.5"

CLOUD_ENGINES = frozenset(CLOUD_PREFER)


def cloud_order(prefer: list[str] | tuple[str, ...] | None) -> list[str]:
    """Engine try-order: caller's `prefer` first, then the rest of CLOUD_PREFER."""
    out: list[str] = []
    for e in list(prefer or ()) + list(CLOUD_PREFER):
        e = (e or "").lower()
        if e in CLOUD_ENGINES and e not in out:
            out.append(e)
    return out


def plan_route(*, route_enabled: bool, forced_provider: str | None,
               local_usable: bool, prefer=None) -> dict:
    """Pure routing decision (no I/O).

    Returns a dict with an `action`:
      - {"action": "forced", "provider": <name>}
      - {"action": "local"}                    # GPU Ollama
      - {"action": "local_only"}               # routing off → Ollama (gate applies)
      - {"action": "cloud", "order": [...]}     # try these engines in order
    The caller resolves cloud availability and the local GPU gate.
    """
    if forced_provider:
        return {"action": "forced", "provider": forced_provider.lower()}
    if not route_enabled:
        return {"action": "local_only"}
    if local_usable:
        return {"action": "local"}
    return {"action": "cloud", "order": cloud_order(prefer)}


def model_for_engine(engine: str, fallback: str | None = None) -> str | None:
    """Default model to use for a routed engine (composer for cursor)."""
    return CURSOR_MODEL if engine.lower() == "cursor" else fallback
