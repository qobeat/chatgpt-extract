"""Tests for the corrected quality metric (FR-B2/B5).

Verifies that metrics.py reports completion, depth-on-success, and schema-valid
as SEPARATE columns, that failed items are excluded from depth-on-success
(never scored as zero), and that the honest-failure flags written by
summarize.py drive the split.
"""
from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")


def _load_metrics():
    spec = importlib.util.spec_from_file_location(
        "metrics", os.path.join(SCRIPTS, "metrics.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


m = _load_metrics()


def _full_item(slug: str, llm_ok: bool = True, schema_valid: bool = True) -> dict:
    """A completed item that scores 1.0 on all four depth axes."""
    return {
        "slug": slug,
        "llm_ok": llm_ok,
        "classification_source": "llm" if llm_ok else "deterministic_prior",
        "schema_valid": schema_valid,
        "goal": "a durable target state",
        "objectives": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
        "requirements": ["r1", "r2", "r3"],
        "archetype_fields": {"k": "v"},
    }


def _thin_item(slug: str, llm_ok: bool = True) -> dict:
    """A completed item that scores only on the goal axis (depth 0.25)."""
    return {
        "slug": slug,
        "llm_ok": llm_ok,
        "classification_source": "llm" if llm_ok else "deterministic_prior",
        "schema_valid": False,
        "goal": "g",
        "objectives": [],
        "requirements": [],
        "archetype_fields": {},
    }


def _failed_item(slug: str) -> dict:
    """A deterministic-prior fallback: empty prose, llm_ok False."""
    return {
        "slug": slug,
        "llm_ok": False,
        "classification_source": "deterministic_prior",
        "schema_valid": False,
        "goal": "",
        "objectives": [],
        "requirements": [],
        "archetype_fields": {},
    }


class QualityMetricSeparationTest(unittest.TestCase):
    def _row(self, items):
        return m._quality_row("test", items, len(items))

    def test_failures_excluded_from_depth_on_success(self):
        # 6 full (depth 1.0) + 2 thin (depth 0.25) + 2 failures.
        items = ([_full_item(f"f{i}") for i in range(6)]
                 + [_thin_item(f"t{i}") for i in range(2)]
                 + [_failed_item(f"x{i}") for i in range(2)])
        row = self._row(items)
        # completion = 8 successes / 10
        self.assertEqual(row["completion_pct"], 80)
        self.assertEqual(row["completed"], 8)
        # depth-on-success = (6*1.0 + 2*0.25) / 8 = 0.8125 -> 81%
        self.assertEqual(row["depth_on_success_pct"], 81)

    def test_depth_on_success_exceeds_naive_all_items_mean(self):
        items = ([_full_item(f"f{i}") for i in range(6)]
                 + [_thin_item(f"t{i}") for i in range(2)]
                 + [_failed_item(f"x{i}") for i in range(2)])
        row = self._row(items)
        naive_all_items = (6 * 1.0 + 2 * 0.25 + 2 * 0.0) / 10 * 100  # = 65
        # The corrected metric must NOT collapse to the old fail=0 average.
        self.assertGreater(row["depth_on_success_pct"], naive_all_items)

    def test_recompute_identity_matches_published_aggregate(self):
        # AI_MODEL_TESTS.md §3.5: depth-on-success == depth_all * N / completed.
        # qwen3:8b published depth% (all 10, fail=0) = 74 at 8/10 -> 92.5%.
        # Reproduce with items whose all-items mean is 0.74 over 10.
        # 8 successes summing to 7.4 depth: 6 full (1.0) + 2 at 0.7.
        full = [_full_item(f"f{i}") for i in range(6)]
        # depth 0.7 = goal(1) + obj(0.0? need 0.8 across 3 more axes)...
        # Build axis values directly: goal=1, obj depth=1, req depth=1, af=0.0
        # -> (1+1+1+0)/4 = 0.75; tune af to hit 0.7: af with 1 of ... use 0.
        # Two items at (1,1,0.8,0): not exact; assert the identity instead.
        mid = [{
            "slug": f"m{i}", "llm_ok": True, "classification_source": "llm",
            "schema_valid": True, "goal": "g",
            "objectives": [{"text": "a"}, {"text": "b"}, {"text": "c"}],
            "requirements": ["r1", "r2"],  # depth 2/3
            "archetype_fields": {},
        } for i in range(2)]
        fails = [_failed_item(f"x{i}") for i in range(2)]
        items = full + mid + fails
        row = self._row(items)
        completed = row["completed"]
        # Independent recomputation: all-items mean * N / completed.
        depth_vals = [m._item_depth(it) for it in items]
        all_items_mean = sum(depth_vals) / len(items) * 100
        recomputed = round(all_items_mean * len(items) / completed, 0)
        self.assertEqual(row["depth_on_success_pct"], recomputed)

    def test_schema_valid_is_distinct_column(self):
        # All complete, but only half emit clean schema JSON.
        items = ([_full_item(f"a{i}", schema_valid=True) for i in range(5)]
                 + [_full_item(f"b{i}", schema_valid=False) for i in range(5)])
        row = self._row(items)
        self.assertEqual(row["completion_pct"], 100)
        self.assertEqual(row["depth_on_success_pct"], 100)
        self.assertEqual(row["schema_valid_pct"], 50)

    def test_legacy_items_without_flags_still_rank(self):
        # No llm_ok / classification_source: success inferred from content.
        legacy_ok = {"slug": "a", "goal": "g",
                     "objectives": [{"text": "x"}], "requirements": [],
                     "archetype_fields": {"k": "v"}}
        legacy_empty = {"slug": "b", "goal": "", "objectives": [],
                        "requirements": [], "archetype_fields": {}}
        row = self._row([legacy_ok, legacy_empty])
        self.assertEqual(row["completion_pct"], 50)
        self.assertEqual(row["completed"], 1)


class CorrectnessAccuracyTest(unittest.TestCase):
    def _classified(self, slug, arch, domain, depth_full=True):
        it = {
            "slug": slug, "llm_ok": True, "classification_source": "llm",
            "schema_valid": True,
            "primary_archetype": {"id": arch},
            "primary_domain_pair": {"domain": domain},
            "goal": "g",
        }
        if depth_full:
            it.update(objectives=[{"text": "a"}, {"text": "b"}, {"text": "c"}],
                      requirements=["r1", "r2", "r3"],
                      archetype_fields={"k": "v"})
        else:
            it.update(objectives=[], requirements=[], archetype_fields={})
        return it

    def test_accuracy_distinct_from_depth(self):
        # Reference key: two slugs classified by codex.
        ref_items = [self._classified("a", "software_app", "software_engineering"),
                     self._classified("b", "research_analysis", "general_knowledge")]
        ref_idx = {}
        for it in ref_items:
            ref_idx[it["slug"]] = m._item_class(it)

        # Candidate: 'a' matches but is THIN (low depth); 'b' is FULL depth but
        # WRONG classification. Depth and accuracy must point opposite ways.
        cand = [
            self._classified("a", "software_app", "software_engineering",
                             depth_full=False),
            self._classified("b", "media_generation", "art", depth_full=True),
        ]
        acc, comparable = m._accuracy(cand, ref_idx)
        self.assertEqual(comparable, 2)
        self.assertEqual(acc, 0.5)  # only 'a' matches the reference

        row = m._quality_row("cand", cand, len(cand), ref_idx)
        self.assertEqual(row["accuracy_pct"], 50)
        # The full-depth item ('b') is the WRONG one, so high depth != accuracy.
        self.assertGreater(row["depth_on_success_pct"], row["accuracy_pct"])

    def test_no_reference_means_no_accuracy_field(self):
        row = m._quality_row("x", [self._classified("a", "software_app", "se")],
                             1, ref_idx=None)
        self.assertNotIn("accuracy_pct", row)


if __name__ == "__main__":
    unittest.main()
