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


if __name__ == "__main__":
    unittest.main()
