"""A Project State emitted from a sweep must validate against the ADOS schema and
carry the per-provider observation against the named coordinates. Tested with
synthetic metric rows so it runs offline (no $DATA_ROOT, no sweep needed).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest

import jsonschema

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ps = _load_module("project_state", "scripts/project_state.py")

_QROW = {
    "model": "ollama:gemma4:31b", "completion_pct": 93.0,
    "depth_on_success_pct": 90.0, "schema_valid_pct": 93.0,
    "accuracy_pct": 68.0, "completed": 25, "n_items": 27,
}
_PROW = {"model": "ollama:gemma4:31b", "sec_per_item": 39.0, "wh_per_item": 2.9121}


def _schema() -> dict:
    with open(os.path.join(ROOT, "schema", "ados", "project-state.schema.json"),
              encoding="utf-8") as f:
        return json.load(f)


class ProjectStateTest(unittest.TestCase):
    def setUp(self):
        self.geom = ps.load_geometry()
        self.state = ps.build_state(
            self.geom, "ollama:gemma4:31b", _QROW, _PROW,
            sweep="cmp-oct2", evidence=["summarize_trace.jsonl", "cmp-oct2-codex"],
            observed_at="2026-06-28T05:00:00+00:00")

    def test_state_validates_against_schema(self):
        jsonschema.Draft202012Validator(_schema()).validate(self.state)

    def test_state_id_matches_pattern(self):
        # Colons in the model label must be coerced out of the id where needed;
        # the schema pattern forbids whitespace and leading punctuation.
        jsonschema.Draft202012Validator(_schema()).validate(self.state)
        self.assertTrue(self.state["state_id"].startswith("STATE-"))

    def test_benchmark_coordinates_carry_attainment(self):
        bench = next(v for v in self.state["vector_states"]
                     if v["vector_ref"] == "VEC-BENCHMARK")
        by_ref = {cv["coordinate_ref"]: cv for cv in bench["coordinate_values"]}
        self.assertEqual(by_ref["COORD-B-COMPLETION"]["attainment_0_100"], 93.0)
        self.assertEqual(by_ref["COORD-B-ACCURACY"]["attainment_0_100"], 68.0)
        self.assertEqual(by_ref["COORD-B-COMPLETION"]["measurement_status"],
                         "measured")
        # Energy is diagnostic: recorded as a native observation, attainment null.
        energy = by_ref["COORD-B-ENERGY"]
        self.assertIsNone(energy["attainment_0_100"])
        self.assertEqual(energy["native_observations"][0]["metric"], "wh_per_item")

    def test_evidence_refs_are_pattern_safe(self):
        validator = jsonschema.Draft202012Validator(_schema())
        validator.validate(self.state)  # would raise if any ref broke the pattern

    def test_unknown_accuracy_when_no_reference(self):
        qrow = dict(_QROW)
        qrow.pop("accuracy_pct")
        state = ps.build_state(self.geom, "codex", qrow, _PROW,
                               sweep="s", evidence=["t.jsonl"])
        jsonschema.Draft202012Validator(_schema()).validate(state)
        bench = next(v for v in state["vector_states"]
                     if v["vector_ref"] == "VEC-BENCHMARK")
        acc = next(cv for cv in bench["coordinate_values"]
                   if cv["coordinate_ref"] == "COORD-B-ACCURACY")
        self.assertIsNone(acc["attainment_0_100"])
        self.assertEqual(acc["measurement_status"], "unknown")


if __name__ == "__main__":
    unittest.main()
