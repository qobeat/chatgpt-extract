"""
cost.py — pricing, pre-run cost estimation, a running spend ledger, and circuit
breakers for the multi-provider summarizer.

All dollar figures derive from config/pricing.json (editable, approximate). Local
Ollama is $0. The estimator gates paid runs; the ledger records actual usage from
provider responses; the breakers stop a run before it overspends or thrashes.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_pricing(path: str | None = None) -> dict:
    path = path or os.path.join(ROOT, "config", "pricing.json")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _model_rates(pricing: dict, provider: str, model: str) -> tuple[float, float]:
    prov = (pricing.get("providers") or {}).get(provider) or {}
    models = prov.get("models") or {}
    entry = models.get(model) or models.get("*") or {}
    return (
        float(entry.get("usd_per_1m_input", 0.0)),
        float(entry.get("usd_per_1m_output", 0.0)),
    )


def usd_for(pricing: dict, provider: str, model: str,
            input_tokens: int, output_tokens: int) -> float:
    in_rate, out_rate = _model_rates(pricing, provider, model)
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def _shadow_rates(pricing: dict, provider: str, model: str) -> tuple[float, float]:
    """Token-equivalent reference rates for plan-metered (subscription) providers.

    `codex`/`claude` are $0 marginal (covered by a plan), so the real estimator
    reports $0 and a USD budget can never bite. The shadow rate is a *what-if*
    list price (e.g. gpt-5 / claude-sonnet-4) so `--budget-usd` can still cap the
    token volume of a plan-metered run. Falls back to the real per-token rate
    when no shadow rate is configured."""
    prov = (pricing.get("providers") or {}).get(provider) or {}
    in_rate = prov.get("shadow_usd_per_1m_input")
    out_rate = prov.get("shadow_usd_per_1m_output")
    if in_rate is None and out_rate is None:
        return _model_rates(pricing, provider, model)
    real_in, real_out = _model_rates(pricing, provider, model)
    return (float(in_rate if in_rate is not None else real_in),
            float(out_rate if out_rate is not None else real_out))


def shadow_usd_for(pricing: dict, provider: str, model: str,
                   input_tokens: int, output_tokens: int) -> float:
    """USD at the token-equivalent shadow rate (see _shadow_rates)."""
    in_rate, out_rate = _shadow_rates(pricing, provider, model)
    return (input_tokens / 1_000_000.0) * in_rate + (output_tokens / 1_000_000.0) * out_rate


def estimate_run(pricing: dict, provider: str, model: str,
                 bundle_chars: list[int],
                 output_tokens_per_item: int | None = None) -> dict[str, Any]:
    """Project input/output tokens and USD for a run from per-bundle char counts."""
    cpt = int(pricing.get("chars_per_token", 4)) or 4
    out_per = (output_tokens_per_item
               if output_tokens_per_item is not None
               else int(pricing.get("default_output_tokens_per_item", 1500)))
    est_input = sum(max(0, c) // cpt for c in bundle_chars)
    est_output = out_per * len(bundle_chars)
    usd = usd_for(pricing, provider, model, est_input, est_output)
    shadow = shadow_usd_for(pricing, provider, model, est_input, est_output)
    prov = (pricing.get("providers") or {}).get(provider) or {}
    n = max(1, len(bundle_chars))
    return {
        "provider": provider,
        "model": model,
        "n_items": len(bundle_chars),
        "est_input_tokens": est_input,
        "est_output_tokens": est_output,
        "est_usd": round(usd, 4),
        "est_usd_per_item": round(usd / n, 5),
        # Token-equivalent projection used by --budget-usd for plan-metered runs.
        "shadow_usd": round(shadow, 4),
        "shadow_usd_per_item": round(shadow / n, 5),
        "usage_based_estimate": bool(prov.get("usage_based")),
        "subscription": bool(prov.get("subscription")),
    }


def format_estimate(est: dict[str, Any]) -> str:
    if est.get("subscription"):
        note = "  (covered by your plan/quota; not token-billed here)"
    elif est.get("usage_based_estimate"):
        note = "  (usage-based; upper-bound estimate)"
    else:
        note = ""
    lines = [
        f"[cost] provider={est['provider']} model={est['model']} "
        f"items={est['n_items']}",
        f"[cost] est input ~{est['est_input_tokens']:,} tok, "
        f"output ~{est['est_output_tokens']:,} tok",
        f"[cost] est total ~${est['est_usd']:.2f} "
        f"(~${est['est_usd_per_item']:.4f}/item){note}",
    ]
    # Show the token-equivalent projection when it differs from the billed $0
    # (i.e. plan-metered providers with a shadow rate), so --budget-usd is legible.
    if est.get("subscription") and est.get("shadow_usd", 0.0) > 0.0:
        lines.append(
            f"[cost] token-equivalent ~${est['shadow_usd']:.2f} "
            f"(~${est['shadow_usd_per_item']:.4f}/item) — used by --budget-usd")
    return "\n".join(lines)


@dataclass
class CostLedger:
    pricing: dict
    entries: list[dict] = field(default_factory=list)
    total_usd: float = 0.0

    def record(self, provider: str, model: str, slug: str,
               input_tokens: int, output_tokens: int) -> float:
        usd = usd_for(self.pricing, provider, model, input_tokens, output_tokens)
        self.total_usd += usd
        self.entries.append({
            "slug": slug, "provider": provider, "model": model,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "usd": round(usd, 6),
        })
        return usd


@dataclass
class CircuitBreaker:
    """
    Trips (and stays tripped) on any of:
      - max_consecutive_failures consecutive errors,
      - cumulative spend >= max_usd,
      - per-item spend >= max_usd_per_item (checked by caller via would_exceed).
    """
    max_consecutive_failures: int = 3
    max_usd: float | None = None
    max_usd_per_item: float | None = None
    consecutive_failures: int = 0
    tripped: bool = False
    reason: str | None = None

    def record_success(self) -> None:
        self.consecutive_failures = 0

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_consecutive_failures:
            self.trip(f"{self.consecutive_failures} consecutive failures")

    def trip(self, reason: str) -> None:
        self.tripped = True
        self.reason = reason

    def check_spend(self, spent_usd: float) -> bool:
        if self.max_usd is not None and spent_usd >= self.max_usd:
            self.trip(f"cumulative spend ${spent_usd:.2f} >= cap ${self.max_usd:.2f}")
        return self.tripped

    def would_exceed(self, spent_usd: float, next_item_usd: float) -> bool:
        """True if running this next call would breach the cumulative cap."""
        if self.max_usd is None:
            return False
        return (spent_usd + next_item_usd) > self.max_usd
