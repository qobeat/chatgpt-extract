"""The gates are the whole point: a privacy or coverage failure must NOT be
averaged away by a high score elsewhere, and a model that can't emit valid JSON
can't score above 50 on quality. These tests pin that behavior to the committed
rubric (geometry/evaluation-rubric.json).
"""
from __future__ import annotations

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import rubric  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
RUBRIC = os.path.join(ROOT, "geometry", "evaluation-rubric.json")


def _rubric() -> dict:
    with open(RUBRIC, encoding="utf-8") as f:
        return json.load(f)


# A strong provider: full attainment on every scoring coordinate.
_PERFECT = {
    "COORD-B-ACCURACY": 100.0,
    "COORD-B-COMPLETION": 100.0,
    "COORD-D-VERDICT": 100.0,
    "COORD-B-DEPTH": 100.0,
    "COORD-B-SPEED": 100.0,
}
_ALL_GATES_OK = {"GATE-PRIVACY": True, "GATE-COVERAGE": True, "GATE-SCHEMA": True}


class RubricGateTest(unittest.TestCase):
    def setUp(self):
        self.rubric = _rubric()

    def test_perfect_scores_100_when_gates_pass(self):
        res = rubric.score(self.rubric, _PERFECT, _ALL_GATES_OK)
        self.assertEqual(res["status"], "scored")
        self.assertEqual(res["score"], 100.0)
        self.assertEqual(res["failed_gates"], [])

    def test_schema_gate_caps_quality_at_50(self):
        gates = dict(_ALL_GATES_OK, **{"GATE-SCHEMA": False})
        res = rubric.score(self.rubric, _PERFECT, gates)
        self.assertIn("GATE-SCHEMA", res["failed_gates"])
        self.assertEqual(res["base_score"], 100.0)
        self.assertEqual(res["score"], 50.0)
        self.assertEqual(res["status"], "scored")

    def test_coverage_gate_fails_the_whole_score(self):
        gates = dict(_ALL_GATES_OK, **{"GATE-COVERAGE": False})
        res = rubric.score(self.rubric, _PERFECT, gates)
        self.assertIn("GATE-COVERAGE", res["failed_gates"])
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["status"], "failed")

    def test_privacy_gate_fails_the_whole_score(self):
        gates = dict(_ALL_GATES_OK, **{"GATE-PRIVACY": False})
        res = rubric.score(self.rubric, _PERFECT, gates)
        self.assertIn("GATE-PRIVACY", res["failed_gates"])
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["status"], "failed")

    def test_hard_fail_dominates_a_cap(self):
        # A coverage fail (hard 0) beats a schema cap (50) — non-compensable.
        gates = {"GATE-PRIVACY": True, "GATE-COVERAGE": False, "GATE-SCHEMA": False}
        res = rubric.score(self.rubric, _PERFECT, gates)
        self.assertEqual(res["score"], 0.0)

    def test_unknown_axis_is_excluded_and_reported(self):
        att = dict(_PERFECT)
        att["COORD-B-ACCURACY"] = None  # unknown
        res = rubric.score(self.rubric, att, _ALL_GATES_OK)
        self.assertIn("COORD-B-ACCURACY", res["excluded_axes"])
        # 100 on the remaining 70 weight -> base 70.
        self.assertEqual(res["base_score"], 70.0)


if __name__ == "__main__":
    unittest.main()
