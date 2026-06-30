"""
Benchmark feature — ranking, leaderboard, and the latency-usable verdict
(README feature 3).

`test_metrics_quality.py` and `test_gen_model_benchmarks.py` cover quality
aggregation and schema validity. This adds the user-facing rendering/ranking
surface plus the NEW interactive latency verdict from `gpt ask-eval` that feeds
the governed model decision.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import arena  # noqa: E402
import ask_eval  # noqa: E402
import metrics  # noqa: E402


class MetricsRankingTest(unittest.TestCase):
    def test_sort_quality_presentation_order(self):
        rows = [
            {"model": "b", "completion_pct": 90, "depth_on_success_pct": 80,
             "schema_valid_pct": 70},
            {"model": "a", "completion_pct": 90, "depth_on_success_pct": 95,
             "schema_valid_pct": 60},
            {"model": "c", "completion_pct": 100, "depth_on_success_pct": 10,
             "schema_valid_pct": 10},
        ]
        metrics._sort_quality(rows)
        # reliability first (c), then depth-on-success breaks the 90/90 tie (a>b)
        self.assertEqual([r["model"] for r in rows], ["c", "a", "b"])

    def test_render_perf_ranks_by_speed(self):
        rows = [
            {"model": "fast", "sec_per_item": 2.0, "gen_tok_s": 50.0,
             "throughput_tok_s": 80.0, "completed": 10, "attempted": 10},
            {"model": "slow", "sec_per_item": 9.0, "gen_tok_s": 10.0,
             "throughput_tok_s": 20.0, "completed": 10, "attempted": 10},
        ]
        out = metrics.render_perf(rows)
        self.assertIn("PERFORMANCE", out)
        # rank 1 line should mention the fast model before the slow one
        self.assertLess(out.index("fast"), out.index("slow"))

    def test_render_perf_empty(self):
        self.assertIn("No LLM_OK", metrics.render_perf([]))


class ArenaLeaderboardTest(unittest.TestCase):
    def test_filter_exact_and_substring(self):
        rows = [{"model": "qwen3:8b"}, {"model": "gpt-oss:20b"},
                {"model": "claude:sonnet"}]
        self.assertEqual(arena._filter(rows, []), rows)  # no filter = all
        self.assertEqual([r["model"] for r in arena._filter(rows, ["qwen3:8b"])],
                         ["qwen3:8b"])
        self.assertEqual([r["model"] for r in arena._filter(rows, ["gpt"])],
                         ["gpt-oss:20b"])


class LatencyVerdictTest(unittest.TestCase):
    def _results(self, slowest_ms, unusable):
        return [
            {"id": "q1", "elapsed_ms": 5.0, "unusable": False, "passed": True,
             "gold_hit": True, "grade_type": "contains_any", "reason": "ok"},
            {"id": "q2", "elapsed_ms": slowest_ms, "unusable": unusable,
             "passed": not unusable, "gold_hit": True,
             "grade_type": "contains_all", "reason": "ok"},
        ]

    def test_usable_verdict(self):
        ls = ask_eval.latency_summary(self._results(8000.0, False), budget=15)
        self.assertTrue(ls["usable"])
        self.assertEqual(ls["n_unusable"], 0)
        self.assertEqual(ls["slowest_ms"], 8000.0)
        self.assertEqual(ls["slowest_id"], "q2")
        out = ask_eval.render(self._results(8000.0, False), budget=15)
        self.assertIn("USABLE", out)
        self.assertNotIn("UNUSABLE", out)

    def test_unusable_verdict(self):
        ls = ask_eval.latency_summary(self._results(16000.0, True), budget=15)
        self.assertFalse(ls["usable"])
        self.assertEqual(ls["n_unusable"], 1)
        out = ask_eval.render(self._results(16000.0, True), budget=15)
        self.assertIn("UNUSABLE", out)


if __name__ == "__main__":
    unittest.main()
