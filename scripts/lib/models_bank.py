"""
models_bank.py — the model bank.

A single place that maps a MODEL NAME to its PROVIDER and the options that
provider needs. This lets `gpt summarize --model <name>` run without also passing
--provider / --num-ctx / --host: the provider and required options are populated
from here. It also powers the catalog printed by `gpt summarize` with no args.

Sources, merged in order (later wins on a (provider, name) collision):
  1. config/models.json          — committed bank (curated)
  2. config/models.local.json    — personal additions (gitignored, optional)
  3. live Ollama discovery       — any installed generation model on the host
"""
from __future__ import annotations

import json
import os
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT, "config")

# Display + resolution preference order across providers.
PROVIDER_ORDER = {
    "codex": 0, "claude": 1, "cursor": 2, "ollama": 3, "openai": 4, "anthropic": 5,
}
TIER_LABEL = {
    "plan": "plan/quota", "local": "local $0", "api": "API $",
}


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _static_entries() -> list[dict]:
    """Bank entries from config/models.json + config/models.local.json."""
    out: dict[tuple[str, str], dict] = {}
    for fn in ("models.json", "models.local.json"):
        data = _read_json(os.path.join(CONFIG_DIR, fn))
        for m in (data.get("models") or []):
            name = (m.get("name") or "").strip()
            provider = (m.get("provider") or "").strip()
            if not name or not provider:
                continue
            out[(provider, name)] = dict(m, name=name, provider=provider)
    return list(out.values())


def _discovered_ollama(host: str | None) -> list[dict]:
    """Installed Ollama generation models on the live host (best effort)."""
    try:
        import ollama_probe  # noqa: E402  (scripts/lib on sys.path)
    except Exception:
        return []
    try:
        if not ollama_probe.host_available(host):
            return []
        models = ollama_probe.discover_models(host)
    except Exception:
        return []
    out: list[dict] = []
    for m in models:
        name = m.get("name")
        if not name or (m.get("role") or "generation") == "embedding":
            continue
        size = m.get("size_gb")
        note = f"{size:.1f} GB" if isinstance(size, (int, float)) else ""
        out.append({
            "name": name, "provider": "ollama", "tier": "local",
            "free": True, "note": note, "_discovered": True,
        })
    return out


def load_bank(cfg: dict | None = None, include_ollama: bool = True,
              host: str | None = None) -> list[dict]:
    """Return the merged model bank (static config + live Ollama models)."""
    cfg = cfg or {}
    if host is None:
        host = (cfg.get("ollama") or {}).get("host")
    entries = _static_entries()
    have = {(e["provider"], e["name"]) for e in entries}
    if include_ollama:
        for e in _discovered_ollama(host):
            if (e["provider"], e["name"]) not in have:
                entries.append(e)
                have.add((e["provider"], e["name"]))
    entries.sort(key=lambda e: (PROVIDER_ORDER.get(e["provider"], 99),
                                e["name"].lower()))
    return entries


def resolve(name: str, cfg: dict | None = None,
            host: str | None = None) -> dict | None:
    """Resolve a model NAME to {provider, model, num_ctx?, host?, ...}.

    Returns None when the name is not in the bank and is not an installed
    Ollama model. On an ambiguous name (same name under several providers) the
    one earliest in PROVIDER_ORDER wins.
    """
    if not name:
        return None
    cfg = cfg or {}
    matches = [e for e in load_bank(cfg=cfg, host=host) if e["name"] == name]
    if not matches:
        return None
    best = min(matches, key=lambda e: PROVIDER_ORDER.get(e["provider"], 99))
    resolved: dict[str, Any] = {
        "provider": best["provider"],
        "model": best["name"],
        "ambiguous": [m["provider"] for m in matches] if len(matches) > 1 else None,
    }
    if best.get("num_ctx") is not None:
        resolved["num_ctx"] = int(best["num_ctx"])
    if best.get("host"):
        resolved["host"] = best["host"]
    return resolved


def format_bank(cfg: dict | None = None, host: str | None = None) -> str:
    """Pretty, copy-pasteable catalog grouped by provider."""
    entries = load_bank(cfg=cfg, host=host)
    lines: list[str] = []
    lines.append("Model bank — run any of these by NAME (provider auto-filled):")
    lines.append("  Usage:  gpt summarize --model <name> [--limit N] [--run-label NAME]")
    lines.append("")
    last_provider = None
    for e in entries:
        prov = e["provider"]
        if prov != last_provider:
            tier = TIER_LABEL.get(e.get("tier", ""), e.get("tier", ""))
            lines.append(f"  [{prov}]  ({tier})" if tier else f"  [{prov}]")
            last_provider = prov
        # `free` and `installed` are surfaced on the RIGHT, inside the trailing
        # `#` comment, so the runnable command on the left stays copy-pasteable.
        tags = [t for t in ("free" if e.get("free") else "",
                            "installed" if e.get("_discovered") else "") if t]
        note = e.get("note") or ""
        comment = " · ".join(p for p in (", ".join(tags), note) if p)
        cmd = f"    gpt summarize --model {e['name']}"
        if comment:
            cmd = f"{cmd:<54} # {comment}".rstrip()
        lines.append(cmd)
    lines.append("")
    lines.append("  free = covered by your plan/quota or local $0; others are token/usage billed.")
    lines.append("  Edit the bank in config/models.json (or config/models.local.json).")
    return "\n".join(lines)
