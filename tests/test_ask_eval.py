"""Phase 0: the ask-eval grader is pure and offline-testable, and the committed
ask_battery.jsonl is well-formed. No Ollama, no index, no network — so CI stays
green while `gpt ask-eval` provides the live, answer-level scorecard."""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "ask_battery.jsonl")
VALID_TYPES = {"refuse", "contains_all", "contains_any", "version_equals"}


def _load():
    spec = importlib.util.spec_from_file_location(
        "ask_eval", os.path.join(SCRIPTS, "ask_eval.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ae = _load()


class RefusalTest(unittest.TestCase):
    def test_detects_refusals(self):
        for a in ["The excerpts do not contain that; I couldn't find it.",
                  "I could not find any mention of that in the indexed chats.",
                  "The provided excerpts do not mention quantum teleportation."]:
            self.assertTrue(ae.is_refusal(a), a)

    def test_normal_answer_is_not_a_refusal(self):
        self.assertFalse(ae.is_refusal(
            "The latest stable ados-profile version is v1.23 [1]."))


class VersionTest(unittest.TestCase):
    def test_extracts_in_order(self):
        self.assertEqual(
            ae.extract_versions("ados-profile-v1.4 then 1.23 and 2.0"),
            ["1.4", "1.23", "2.0"])

    def test_no_versions(self):
        self.assertEqual(ae.extract_versions("no numbers here"), [])


class GradeTest(unittest.TestCase):
    def test_refuse(self):
        self.assertTrue(ae.grade_answer("couldn't find it", {"type": "refuse"})[0])
        self.assertFalse(ae.grade_answer("It is pepperoni.",
                                         {"type": "refuse"})[0])

    def test_contains_all(self):
        g = {"type": "contains_all", "needles": ["research", "market"]}
        self.assertTrue(ae.grade_answer("research and MARKET families", g)[0])
        self.assertFalse(ae.grade_answer("research only", g)[0])

    def test_contains_any(self):
        g = {"type": "contains_any", "needles": ["drift", "not approve"]}
        self.assertTrue(ae.grade_answer("high-risk DRIFT blocked it", g)[0])
        self.assertFalse(ae.grade_answer("totally unrelated", g)[0])

    def test_version_equals_first_token(self):
        g = {"type": "version_equals", "expected": "1.23"}
        self.assertTrue(ae.grade_answer("The latest stable is v1.23.", g)[0])
        # Leads with the wrong version -> fail (reproduces the live Q7 miss).
        self.assertFalse(ae.grade_answer("The latest stable is v1.4.", g)[0])

    def test_version_equals_refusal_fails_positive(self):
        g = {"type": "version_equals", "expected": "2.0"}
        self.assertFalse(ae.grade_answer("I couldn't find that.", g)[0])


class FixtureTest(unittest.TestCase):
    def test_battery_is_well_formed(self):
        rows = ae.load_battery(FIXTURE)
        self.assertEqual(len(rows), 12)
        ids = set()
        for r in rows:
            self.assertIn("id", r)
            self.assertIn("question", r)
            ids.add(r["id"])
            g = r.get("grade") or {}
            self.assertIn(g.get("type"), VALID_TYPES, r["id"])
            if g["type"] in ("contains_all", "contains_any"):
                self.assertTrue(g.get("needles"), r["id"])
            if g["type"] == "version_equals":
                self.assertTrue(g.get("expected"), r["id"])
        self.assertEqual(len(ids), 12, "battery ids must be unique")

    def test_known_answers_reproduce_expected_grades(self):
        """Lock the grader to the live 2026-06-29 run: 10/12 pass (8 correct
        answers + 2 correct refusals; Q7/Q8 version-superlatives fail)."""
        by_id = {r["id"]: (r.get("grade") or {}) for r in ae.load_battery(FIXTURE)}
        canned = {
            "readme_rule": ("version numbers belong only in CHANGELOG.md", True),
            "geometry": ("the goal-attractor geometry with meaning axes", True),
            "compliance_check": ("verifies package identity, metadata, geometry", True),
            "axis_families": ("research, specification, competition, science, market", True),
            "attempt_124": ("there were attempts to move to 1.24 (PASS)", True),
            "pillars": ("the ADOS pillars evolved into pure doctrine", True),
            "latest_stable": ("the latest stable version is v1.4", False),
            "newest_overall": ("the newest overall is v1.4, stable", False),
            "neg_pizza": ("the excerpts do not contain that; couldn't find it", True),
            "neg_quantum": ("the spec does not mention quantum teleportation", True),
            "v2_not_stable": ("not approved as a clean successor; high-risk drift", True),
            "adr_0005": ("a proposed ADR clarifying the term canonical", True),
        }
        passes = 0
        for qid, (answer, expect) in canned.items():
            ok, reason = ae.grade_answer(answer, by_id[qid])
            self.assertEqual(ok, expect, f"{qid}: {reason}")
            passes += int(ok)
        self.assertEqual(passes, 10)


if __name__ == "__main__":
    unittest.main()
