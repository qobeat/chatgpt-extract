"""Unit tests for cost estimation, ledger, and circuit breakers."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import cost as cost_lib  # noqa: E402


class CostTest(unittest.TestCase):
    def setUp(self):
        self.pricing = cost_lib.load_pricing()

    def test_ollama_is_free(self):
        usd = cost_lib.usd_for(self.pricing, "ollama", "gpt-oss:20b", 1_000_000, 1_000_000)
        self.assertEqual(usd, 0.0)

    def test_openai_estimate_nonzero(self):
        est = cost_lib.estimate_run(self.pricing, "openai", "gpt-5-mini",
                                    [40000, 40000])
        self.assertGreater(est["est_usd"], 0)
        self.assertEqual(est["n_items"], 2)

    def test_unknown_model_falls_back_to_star(self):
        # Should not raise; uses '*' default for the provider.
        usd = cost_lib.usd_for(self.pricing, "openai", "totally-made-up", 1000, 1000)
        self.assertGreaterEqual(usd, 0.0)

    def test_ledger_accumulates(self):
        ledger = cost_lib.CostLedger(pricing=self.pricing)
        ledger.record("openai", "gpt-5-mini", "a", 10000, 1000)
        ledger.record("openai", "gpt-5-mini", "b", 10000, 1000)
        self.assertEqual(len(ledger.entries), 2)
        self.assertGreater(ledger.total_usd, 0)

    def test_breaker_consecutive_failures(self):
        b = cost_lib.CircuitBreaker(max_consecutive_failures=3)
        b.record_failure(); b.record_failure()
        self.assertFalse(b.tripped)
        b.record_failure()
        self.assertTrue(b.tripped)

    def test_breaker_success_resets(self):
        b = cost_lib.CircuitBreaker(max_consecutive_failures=2)
        b.record_failure()
        b.record_success()
        b.record_failure()
        self.assertFalse(b.tripped)

    def test_breaker_spend_cap(self):
        b = cost_lib.CircuitBreaker(max_usd=1.0)
        self.assertFalse(b.check_spend(0.5))
        self.assertTrue(b.check_spend(1.5))

    def test_breaker_would_exceed(self):
        b = cost_lib.CircuitBreaker(max_usd=1.0)
        self.assertFalse(b.would_exceed(0.5, 0.4))
        self.assertTrue(b.would_exceed(0.9, 0.2))


class ShadowBudgetTest(unittest.TestCase):
    """Token-equivalent budget for plan-metered providers (--budget-usd)."""
    def setUp(self):
        self.pricing = cost_lib.load_pricing()

    def test_subscription_real_usd_is_zero_but_shadow_nonzero(self):
        est = cost_lib.estimate_run(self.pricing, "codex", "*",
                                    [40000] * 27)
        self.assertEqual(est["est_usd"], 0.0)          # $0 marginal on the plan
        self.assertGreater(est["shadow_usd"], 0.0)     # token-equivalent > 0
        self.assertTrue(est["subscription"])

    def test_shadow_for_codex_uses_reference_rate(self):
        # 1M input + 1M output at gpt-5 reference (1.25 + 10.00) = $11.25.
        usd = cost_lib.shadow_usd_for(self.pricing, "codex", "*",
                                      1_000_000, 1_000_000)
        self.assertAlmostEqual(usd, 11.25, places=2)

    def test_shadow_falls_back_to_real_when_unset(self):
        # openai has no shadow_* rate -> shadow == real estimate.
        real = cost_lib.usd_for(self.pricing, "openai", "gpt-5-mini", 1000, 1000)
        shadow = cost_lib.shadow_usd_for(self.pricing, "openai", "gpt-5-mini",
                                         1000, 1000)
        self.assertEqual(real, shadow)

    def test_ollama_shadow_is_free(self):
        self.assertEqual(
            cost_lib.shadow_usd_for(self.pricing, "ollama", "x", 10**6, 10**6),
            0.0)


if __name__ == "__main__":
    unittest.main()
