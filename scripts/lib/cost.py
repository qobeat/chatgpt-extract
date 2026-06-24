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
    prov = (pricing.get("providers") or {}).get(provider) or {}
    return {
        "provider": provider,
        "model": model,
        "n_items": len(bundle_chars),
        "est_input_tokens": est_input,
        "est_output_tokens": est_output,
        "est_usd": round(usd, 4),
        "est_usd_per_item": round(usd / max(1, len(bundle_chars)), 5),
        "usage_based_estimate": bool(prov.get("usage_based")),
    }


def format_estimate(est: dict[str, Any]) -> str:
    note = "  (usage-based; upper-bound estimate)" if est.get("usage_based_estimate") else ""
    return (
        f"[cost] provider={est['provider']} model={est['model']} "
        f"items={est['n_items']}\n"
        f"[cost] est input ~{est['est_input_tokens']:,} tok, "
        f"output ~{est['est_output_tokens']:,} tok\n"
        f"[cost] est total ~${est['est_usd']:.2f} "
        f"(~${est['est_usd_per_item']:.4f}/item){note}"
    )


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
