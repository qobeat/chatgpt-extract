"""Eval-facet invariants (docs/REDESIGN-PROPOSAL.md §4): difficulty arithmetic,
tier mapping, and the rule that SUBJECTIVE items never enter the IQ number. These
are cross-field semantics JSON Schema cannot express, so they live in tests."""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, rel))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cl = _load("classify", "classify.py")
m = _load("metrics", "metrics.py")

TIER_RANGES = {t["id"]: t["score_range"]
               for t in json.load(open(os.path.join(ROOT, "ontology",
                                                     "difficulty.json")))["difficulty_tiers"]}


class DifficultyArithmeticTest(unittest.TestCase):
    def _facets(self, **kw):
        base = dict(has_code=False, has_image=False, n_data=0, n_versions=0, n_conv=1)
        base.update(kw)
        return cl._facet_priors("software_app", "software_engineering", **base)

    def test_score_is_sum_of_four_subaxes_and_tier_matches_range(self):
        for kw in (dict(), dict(has_code=True, n_conv=5, n_versions=3),
                   dict(n_versions=1, n_conv=2)):
            f = self._facets(**kw)["difficulty"]
            self.assertEqual(
                f["score"],
                f["steps"] + f["specialisation"] + f["ambiguity"] + f["context_load"])
            lo, hi = TIER_RANGES[f["tier"]]
            self.assertTrue(lo <= f["score"] <= hi, f)

    def test_creative_media_is_subjective(self):
        f = cl._facet_priors("media_generation", "arts_creative",
                             has_code=False, has_image=True, n_data=0,
                             n_versions=0, n_conv=1)
        self.assertEqual(f["verifiability_class"], "subjective")
        self.assertEqual(f["modality"], "image")


def _item(slug, arch, dom, *, verifiability, tier, cognitive):
    return {
        "slug": slug, "llm_ok": True, "classification_source": "llm",
        "schema_valid": True, "goal": "g",
        "objectives": [{"text": "a"}], "requirements": ["r"], "archetype_fields": {"k": "v"},
        "primary_archetype": {"id": arch}, "primary_domain_pair": {"domain": dom},
        "verifiability_class": verifiability,
        "difficulty": {"tier": tier},
        "cognitive_type": cognitive,
    }


class IqExclusionTest(unittest.TestCase):
    def test_subjective_excluded_and_difficulty_weighted(self):
        ref = {
            "obj1": ("software_app", "software_engineering"),
            "subj1": ("media_generation", "arts_creative"),
            "hard1": ("research_analysis", "general_knowledge"),
        }
        items = [
            # objective T1 correct (weight 1)
            _item("obj1", "software_app", "software_engineering",
                  verifiability="objective", tier="T1", cognitive="reason_analyze"),
            # subjective WRONG — must NOT drag IQ down (excluded entirely)
            _item("subj1", "content_writing", "arts_creative",
                  verifiability="subjective", tier="T2", cognitive="generate_create"),
            # objective T4 wrong (weight 4)
            _item("hard1", "media_generation", "arts_creative",
                  verifiability="objective", tier="T4", cognitive="reason_analyze"),
        ]
        iq, by_skill, by_diff = m._iq_and_breakdowns(items, ref)
        # IQ = (1*1 + 4*0) / (1 + 4) = 20.0; subjective item not in denominator.
        self.assertEqual(iq, 20.0)
        self.assertIn("T1", by_diff)
        self.assertIn("T4", by_diff)
        self.assertNotIn("T2", by_diff)  # subjective tier excluded

    def test_no_facets_returns_none(self):
        ref = {"a": ("software_app", "software_engineering")}
        plain = [{"slug": "a", "llm_ok": True, "classification_source": "llm",
                  "goal": "g", "objectives": [{"text": "x"}], "requirements": [],
                  "archetype_fields": {"k": "v"},
                  "primary_archetype": {"id": "software_app"},
                  "primary_domain_pair": {"domain": "software_engineering"}}]
        self.assertIsNone(m._iq_and_breakdowns(plain, ref))


if __name__ == "__main__":
    unittest.main()
