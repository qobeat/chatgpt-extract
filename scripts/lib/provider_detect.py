"""Auto-detect the first available provider for the AI summary step.

Order: codex -> ollama -> claude (first whose preflight passes). Used when the
user does not pass --provider, so a default run prefers a signed-in subscription
CLI, then local Ollama, then Claude.
"""
from __future__ import annotations

from providers import get_provider  # noqa: E402  (scripts/lib on sys.path)

DEFAULT_ORDER = ("codex", "ollama", "claude")


def _kwargs_for(name: str, cfg: dict, probe_timeout: int) -> dict:
    if name == "ollama":
        oc = cfg.get("ollama") or {}
        return {
            "model": oc.get("model", "gpt-oss:20b"),
            "host": oc.get("host", "http://localhost:11434"),
            "num_ctx": int(oc.get("num_ctx", 32768)),
        }
    # cursor/codex/claude: model optional; pass a fast probe timeout where used.
    return {"model": "", "probe_timeout": probe_timeout}


def detect_provider(order: tuple[str, ...] = DEFAULT_ORDER,
                    cfg: dict | None = None,
                    probe_timeout: int = 8) -> tuple[str | None, list[str]]:
    """Return (provider_name_or_None, log_lines).

    log_lines records why each candidate was skipped, for a helpful error when
    none are available.
    """
    cfg = cfg or {}
    notes: list[str] = []
    for name in order:
        try:
            prov = get_provider(name, **_kwargs_for(name, cfg, probe_timeout))
            ok, msg = prov.preflight()
        except Exception as e:  # noqa: BLE001 - any import/runtime issue = unavailable
            notes.append(f"{name}: unavailable ({e})")
            continue
        if ok:
            notes.append(f"{name}: available")
            return name, notes
        notes.append(f"{name}: {msg.splitlines()[0] if msg else 'not ready'}")
    return None, notes
