"""
models_bank.py — the model bank.

A single place that maps a MODEL NAME to its PROVIDER and the options that
provider needs. This lets `gpt summarize --model <name>` run without also passing
--provider / --num-ctx / --host: the provider and required options are populated
from here. It also powers the catalog printed by `gpt summarize` with no args.

Sources, merged in order (later wins on a (provider, name) collision):
  1. config/models.json          — committed bank (curated, hand-edited)
  2. config/models.local.json    — personal additions (gitignored, optional)
  3. live Ollama discovery       — any installed generation model on the host

Two machine-owned sidecars are JOINED onto each entry at load time (never edited
by hand here):
  - config/plans.json                       — subscription plan registry; resolved
                                              via billing.plan_id into entry["billing_plan"].
  - config/generated/model_benchmarks.json  — typed benchmark verdicts; matched by
                                              'provider:name' into entry["benchmark"].
"""
from __future__ import annotations

import json
import os
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(ROOT, "config")
PLANS_PATH = os.path.join(CONFIG_DIR, "plans.json")
BENCHMARKS_PATH = os.path.join(CONFIG_DIR, "generated", "model_benchmarks.json")

# Display + resolution preference order across providers.
PROVIDER_ORDER = {
    "codex": 0, "claude": 1, "cursor": 2, "ollama": 3, "openai": 4, "anthropic": 5,
}


def _read_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _load_plans() -> dict[str, dict]:
    """Plan registry keyed by id (config/plans.json)."""
    data = _read_json(PLANS_PATH)
    return {p["id"]: p for p in (data.get("plans") or []) if p.get("id")}


def _load_benchmarks() -> dict[str, dict]:
    """Typed benchmark rows keyed by 'provider:name' (generated sidecar)."""
    data = _read_json(BENCHMARKS_PATH)
    return dict(data.get("models") or {})


def _entry_key(entry: dict) -> str:
    """The 'provider:name' join key used by the benchmarks sidecar and the bank."""
    return f"{entry.get('provider', '')}:{entry.get('name', '')}"


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
            "name": name, "provider": "ollama", "billing": {"kind": "local"},
            "note": note, "_discovered": True,
        })
    return out


def _attach_sidecars(entries: list[dict], plans: dict[str, dict],
                     bench: dict[str, dict]) -> None:
    """Join the plan registry and generated benchmarks onto each entry in place."""
    for e in entries:
        b = bench.get(_entry_key(e))
        if b is not None:
            e["benchmark"] = b
        billing = e.get("billing") or {}
        plan_id = billing.get("plan_id")
        if plan_id and plan_id in plans:
            e["billing_plan"] = plans[plan_id]


def load_bank(cfg: dict | None = None, include_ollama: bool = True,
              host: str | None = None) -> list[dict]:
    """Return the merged model bank (static config + live Ollama models), with the
    plan registry and generated benchmarks joined onto each entry."""
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
    _attach_sidecars(entries, _load_plans(), _load_benchmarks())
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


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------
def billing_label(entry: dict) -> str:
    """Short, honest cost label for the bank listing, derived from the structured
    `billing` object (+ the joined plan record)."""
    billing = entry.get("billing") or {}
    kind = billing.get("kind")
    if kind == "local":
        return "local $0"
    if kind == "token":
        return "token (pay-per-use)"
    if kind == "subscription":
        plan = entry.get("billing_plan") or {}
        label = plan.get("label") or billing.get("plan_id") or "plan"
        price = plan.get("price_per_period")
        period = {"month": "mo", "year": "yr"}.get(plan.get("billing_period", ""), "")
        priced = f" ${price:g}/{period}" if isinstance(price, (int, float)) and period else ""
        metered = " · metered" if billing.get("metered") else ""
        return f"{label}{priced}{metered}"
    return ""


def benchmark_summary(entry: dict) -> str:
    """One-line typed-benchmark verdict from entry['benchmark'] (separated axes,
    never blended). Empty when the model has no benchmark row."""
    b = entry.get("benchmark")
    if not b:
        return ""
    parts: list[str] = []
    comp, n = b.get("completed"), b.get("n_items")
    if comp is not None and n is not None:
        parts.append(f"compl {comp:g}/{n:g}")
    for key, fmt in (("depth_on_success_pct", "depth* {:.0f}%"),
                     ("schema_valid_pct", "json {:.0f}%"),
                     ("iq", "IQ {:.0f}"),
                     ("accuracy_pct", "acc {:.0f}%")):
        v = b.get(key)
        if isinstance(v, (int, float)):
            parts.append(fmt.format(v))
    s = b.get("sec_per_item")
    if isinstance(s, (int, float)):
        parts.append(f"{s:.1f} s/item")
    wh = b.get("wh_per_item")
    if isinstance(wh, (int, float)):
        parts.append(f"{wh:.3f} Wh/item")
    usd = b.get("usd_per_1k_items")
    if isinstance(usd, (int, float)) and usd > 0:
        parts.append(f"${usd:.2f}/1k")
    return " · ".join(parts)


def format_bank(cfg: dict | None = None, host: str | None = None) -> str:
    """Pretty, copy-pasteable catalog grouped by provider, with billing + typed
    benchmark verdicts surfaced in the trailing comment."""
    entries = load_bank(cfg=cfg, host=host)
    lines: list[str] = []
    lines.append("Model bank — run any of these by NAME (provider auto-filled):")
    lines.append("  Usage:  gpt summarize --model <name> [--limit N] [--run-label NAME]")
    lines.append("")
    last_provider = None
    for e in entries:
        prov = e["provider"]
        if prov != last_provider:
            lines.append(f"  [{prov}]")
            last_provider = prov
        # Skipped models (e.g. too slow / too big for this machine) are shown so
        # the verdict is visible, but NOT as a copy-pasteable run line.
        if e.get("skip"):
            reason = e.get("skip_reason") or e.get("note") or "skipped"
            lines.append(f"    (skip) {e['name']:<28} # SKIP: {reason}")
            continue
        # Billing + installed tag + human note + benchmark verdict go on the RIGHT,
        # inside the trailing `#` comment, so the runnable command stays paste-able.
        tags = [t for t in (billing_label(e),
                             "installed" if e.get("_discovered") else "") if t]
        comment_bits = [", ".join(tags), e.get("note") or "", benchmark_summary(e)]
        comment = " · ".join(p for p in comment_bits if p)
        cmd = f"    gpt summarize --model {e['name']}"
        if comment:
            cmd = f"{cmd:<54} # {comment}".rstrip()
        lines.append(cmd)
    lines.append("")
    lines.append("  Billing: local $0 = Ollama on your GPU (electricity); subscription = "
                 "covered by a plan (see config/plans.json); token = pay-per-token "
                 "(config/pricing.json).")
    lines.append("  (skip) = present on this host but not recommended to run (see SKIP reason).")
    lines.append("  Edit the bank in config/models.json (or config/models.local.json); "
                 "benchmark verdicts are generated into config/generated/model_benchmarks.json.")
    return "\n".join(lines)
