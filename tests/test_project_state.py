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

    def _coverage_coord(self, state):
        cat = next(v for v in state["vector_states"]
                   if v["vector_ref"] == "VEC-CATALOG")
        return next(cv for cv in cat["coordinate_values"]
                    if cv["coordinate_ref"] == "COORD-C-COVERAGE")

    def test_coverage_measured_validates_and_carries_natives(self):
        natives = [{"metric": "seen", "value": 100, "unit": "conversations"},
                   {"metric": "skipped", "value": 5, "unit": "conversations"}]
        state = ps.build_state(self.geom, "codex", _QROW, _PROW, sweep="s",
                               evidence=["t.jsonl"], coverage=95.0,
                               coverage_natives=natives)
        jsonschema.Draft202012Validator(_schema()).validate(state)
        cov = self._coverage_coord(state)
        self.assertEqual(cov["attainment_0_100"], 95.0)
        self.assertEqual(cov["measurement_status"], "measured")
        self.assertEqual(cov["native_observations"][0]["metric"], "seen")

    def test_coverage_unknown_stays_null(self):
        cov = self._coverage_coord(self.state)
        self.assertIsNone(cov["attainment_0_100"])
        self.assertEqual(cov["measurement_status"], "unknown")

    def _verdict_gates(self, state):
        dec = next(v for v in state["vector_states"]
                   if v["vector_ref"] == "VEC-DECISION")
        cv = dec["coordinate_values"][0]
        return {n["metric"]: n["value"] for n in cv["native_observations"]}

    def test_verdict_carries_gate_evidence(self):
        # schema_valid 93 -> GATE-SCHEMA cap_50; skipped 5 -> GATE-COVERAGE fail.
        natives = [{"metric": "skipped", "value": 5, "unit": "conversations"}]
        state = ps.build_state(self.geom, "codex", _QROW, _PROW, sweep="s",
                               evidence=["t.jsonl"], coverage=95.0,
                               coverage_natives=natives)
        jsonschema.Draft202012Validator(_schema()).validate(state)
        gates = self._verdict_gates(state)
        self.assertEqual(gates["GATE-COVERAGE"], "fail")
        self.assertEqual(gates["GATE-SCHEMA"], "cap_50")

    def test_shard_loss_fails_coverage_gate(self):
        # A lost shard (parsed < total) is a visible coverage miss even when no
        # individual conversation was skipped (F1: the silent-drop blind spot).
        natives = [{"metric": "skipped", "value": 0, "unit": "conversations"},
                   {"metric": "shards_total", "value": 3, "unit": "shards"},
                   {"metric": "shards_parsed", "value": 2, "unit": "shards"}]
        state = ps.build_state(self.geom, "codex", _QROW, _PROW, sweep="s",
                               evidence=["t.jsonl"], coverage=66.7,
                               coverage_natives=natives)
        jsonschema.Draft202012Validator(_schema()).validate(state)
        gates = self._verdict_gates(state)
        self.assertEqual(gates["GATE-COVERAGE"], "fail")

    def test_all_shards_parsed_passes_coverage_gate(self):
        natives = [{"metric": "skipped", "value": 0, "unit": "conversations"},
                   {"metric": "shards_total", "value": 3, "unit": "shards"},
                   {"metric": "shards_parsed", "value": 3, "unit": "shards"}]
        gates = self._verdict_gates(ps.build_state(
            self.geom, "codex", dict(_QROW, schema_valid_pct=100.0), _PROW,
            sweep="s", evidence=["t.jsonl"], coverage=100.0,
            coverage_natives=natives))
        self.assertEqual(gates["GATE-COVERAGE"], "pass")

    def test_gates_pass_and_unknown(self):
        clean = dict(_QROW, schema_valid_pct=100.0)
        natives = [{"metric": "skipped", "value": 0, "unit": "conversations"}]
        gates = self._verdict_gates(ps.build_state(
            self.geom, "codex", clean, _PROW, sweep="s", evidence=["t.jsonl"],
            coverage=100.0, coverage_natives=natives))
        self.assertEqual(gates["GATE-COVERAGE"], "pass")
        self.assertEqual(gates["GATE-SCHEMA"], "pass")
        # No coverage data and no schema_valid -> both unknown.
        bare = dict(_QROW)
        bare.pop("schema_valid_pct")
        gates2 = self._verdict_gates(ps.build_state(
            self.geom, "codex", bare, _PROW, sweep="s", evidence=["t.jsonl"]))
        self.assertEqual(gates2["GATE-COVERAGE"], "unknown")
        self.assertEqual(gates2["GATE-SCHEMA"], "unknown")


class PrivacyGateTest(unittest.TestCase):
    """GATE-PRIVACY (NFR-P3): local providers pass (offline); cloud providers
    pass only with recorded scrub evidence, fail on an unscrubbed cloud call,
    and stay unknown without evidence."""

    def setUp(self):
        self.geom = ps.load_geometry()

    def _gate(self, model, privacy):
        state = ps.build_state(self.geom, model, _QROW, _PROW, sweep="s",
                               evidence=["t.jsonl"], privacy=privacy)
        jsonschema.Draft202012Validator(_schema()).validate(state)
        dec = next(v for v in state["vector_states"]
                   if v["vector_ref"] == "VEC-DECISION")
        natives = dec["coordinate_values"][0]["native_observations"]
        gates = {n["metric"]: n["value"] for n in natives}
        return gates, natives

    def test_local_provider_passes_without_evidence(self):
        gates, _ = self._gate("ollama:gemma4:31b", None)
        self.assertEqual(gates["GATE-PRIVACY"], "pass")

    def test_cloud_with_scrub_evidence_passes(self):
        privacy = {"cloud_provider": True, "scrub_cloud": True, "scrub_hits": 7}
        gates, natives = self._gate("codex", privacy)
        self.assertEqual(gates["GATE-PRIVACY"], "pass")
        # The scrub count is carried as supporting evidence.
        hits = next(n for n in natives if n["metric"] == "scrub_hits")
        self.assertEqual(hits["value"], 7)

    def test_cloud_without_scrub_fails(self):
        privacy = {"cloud_provider": True, "scrub_cloud": False, "scrub_hits": 0}
        gates, _ = self._gate("openai:gpt-5-mini", privacy)
        self.assertEqual(gates["GATE-PRIVACY"], "fail")

    def test_cloud_without_evidence_is_unknown(self):
        gates, _ = self._gate("anthropic:claude", None)
        self.assertEqual(gates["GATE-PRIVACY"], "unknown")

    def test_privacy_gate_helper_directly(self):
        self.assertEqual(ps._privacy_gate("ollama:x", None)[0], "pass")
        self.assertEqual(ps._privacy_gate("", None)[0], "unknown")
        self.assertEqual(
            ps._privacy_gate("codex", {"scrub_cloud": True, "scrub_hits": 0})[0],
            "pass")


class CoverageFromStoreTest(unittest.TestCase):
    def test_counts_to_attainment(self):
        import tempfile
        import zip_ledger
        store = tempfile.mkdtemp()
        zip_ledger.save(store, {"zips": {
            "h1": {"basename": "a.zip", "seen": 60, "skipped": 3, "written": 57},
            "h2": {"basename": "b.zip", "seen": 40, "skipped": 0, "written": 40},
        }})
        att, natives = ps.coverage_from_store(store)
        self.assertEqual(att, 97.0)  # (100-3)/100
        by = {n["metric"]: n["value"] for n in natives}
        self.assertEqual((by["seen"], by["skipped"], by["written"]), (100, 3, 97))

    def test_no_ledger_is_unknown(self):
        import tempfile
        att, natives = ps.coverage_from_store(tempfile.mkdtemp())
        self.assertIsNone(att)
        self.assertEqual(natives, [])

    def test_shard_loss_scales_attainment_and_records_natives(self):
        import tempfile
        import zip_ledger
        store = tempfile.mkdtemp()
        # No conversations skipped, but 1 of 3 shards yielded nothing: the
        # conversation-level 100% must be scaled down by the parse ratio.
        zip_ledger.save(store, {"zips": {
            "h1": {"basename": "a.zip", "seen": 60, "skipped": 0, "written": 60,
                   "shards_total": 3, "shards_parsed": 2},
        }})
        att, natives = ps.coverage_from_store(store)
        by = {n["metric"]: n["value"] for n in natives}
        self.assertEqual((by["shards_total"], by["shards_parsed"]), (3, 2))
        # 100.0 * 2/3 -> 66.7
        self.assertEqual(att, 66.7)

    def test_all_shards_parsed_keeps_full_attainment(self):
        import tempfile
        import zip_ledger
        store = tempfile.mkdtemp()
        zip_ledger.save(store, {"zips": {
            "h1": {"basename": "a.zip", "seen": 50, "skipped": 0, "written": 50,
                   "shards_total": 2, "shards_parsed": 2},
        }})
        att, _ = ps.coverage_from_store(store)
        self.assertEqual(att, 100.0)


if __name__ == "__main__":
    unittest.main()
