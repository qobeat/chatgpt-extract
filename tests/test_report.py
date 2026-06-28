"""Cross-sweep report (gpt report): workload grouping, full coverage, geometry-
declared columns, and the no-cross-workload-averaging guarantee.

Runs offline against synthetic state files written to a temp dir.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import metrics  # noqa: E402
import project_state  # noqa: E402
import report  # noqa: E402


class WorkloadMapTest(unittest.TestCase):
    def test_known_patterns(self):
        self.assertEqual(project_state.workload_for("cmp-oct2-codex"), "oct2024-cmp")
        self.assertEqual(project_state.workload_for("cmp-oct2-gemma4-31b"),
                         "oct2024-cmp")
        self.assertEqual(project_state.workload_for("perf-20260626"), "jun2026-perf")
        self.assertEqual(project_state.workload_for("perf-gemma4-20260626"),
                         "jun2026-perf")
        self.assertEqual(project_state.workload_for("ollama-legacy"), "legacy-ollama")

    def test_unknown_label_is_its_own_workload(self):
        # Never silently merged into another workload.
        self.assertEqual(project_state.workload_for("some-new-run"), "some-new-run")


def _state(completion, sec_per_item=None, wh=None):
    bench = {"vector_ref": "VEC-BENCHMARK", "coordinate_values": [
        {"coordinate_ref": "COORD-B-COMPLETION", "attainment_0_100": completion,
         "measurement_status": "measured", "native_observations": []},
        {"coordinate_ref": "COORD-B-SPEED", "attainment_0_100": None,
         "measurement_status": "measured", "native_observations": (
             [{"metric": "sec_per_item", "value": sec_per_item, "unit": "seconds"}]
             if sec_per_item is not None else [])},
        {"coordinate_ref": "COORD-B-ENERGY", "attainment_0_100": None,
         "measurement_status": "measured", "native_observations": (
             [{"metric": "wh_per_item", "value": wh, "unit": "watt_hours"}]
             if wh is not None else [])},
    ]}
    return {"geometry_id": "GEOM-chatgpt-extract", "geometry_version": 1,
            "observed_at": "2026-06-28T00:00:00+00:00",
            "vector_states": [bench]}


def _write_states(d: dict[str, dict]) -> str:
    tmp = tempfile.mkdtemp()
    for fname, state in d.items():
        with open(os.path.join(tmp, fname), "w", encoding="utf-8") as f:
            json.dump(state, f)
    return tmp


class FilenameTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(report.parse_state_filename("oct2024-cmp__codex.json"),
                         ("oct2024-cmp", "codex"))
        # model with colons survives (only the first '__' splits)
        self.assertEqual(
            report.parse_state_filename("jun2026-perf__ollama:gemma4:31b.json"),
            ("jun2026-perf", "ollama:gemma4:31b"))

    def test_parse_no_separator(self):
        self.assertEqual(report.parse_state_filename("weird.json"), ("", "weird"))


class GroupingTest(unittest.TestCase):
    def test_grouping_and_full_coverage(self):
        d = _write_states({
            "oct2024-cmp__codex.json": _state(100, 15.2),
            "oct2024-cmp__ollama:gemma4:31b.json": _state(93, 39.0, 2.912),
            "jun2026-perf__codex.json": _state(100, 25.6),
        })
        records = report.load_states(d)
        self.assertEqual(len(records), 3)
        groups = report.group_by_workload(records)
        self.assertEqual(set(groups), {"oct2024-cmp", "jun2026-perf"})
        self.assertEqual(len(groups["oct2024-cmp"]), 2)
        self.assertEqual(len(groups["jun2026-perf"]), 1)
        # every (workload, model) appears in the rendered report
        md = report.render_report(records)
        for wl in ("oct2024-cmp", "jun2026-perf"):
            self.assertIn(f"`{wl}`", md)
        for model in ("codex", "ollama:gemma4:31b"):
            self.assertIn(model, md)

    def test_native_values_rendered(self):
        d = _write_states({"oct2024-cmp__gemma.json": _state(93, 39.0, 2.912)})
        md = report.render_report(report.load_states(d))
        self.assertIn("39.0", md)    # sec_per_item
        self.assertIn("2.912", md)   # wh_per_item
        self.assertIn("93", md)      # completion attainment


class NoCrossWorkloadAveragingTest(unittest.TestCase):
    def test_same_model_in_two_workloads_kept_separate(self):
        # codex appears in BOTH workloads with different completion; the report
        # must show each value under its own workload, never a merged/averaged one.
        d = _write_states({
            "oct2024-cmp__codex.json": _state(80),
            "jun2026-perf__codex.json": _state(100),
        })
        records = report.load_states(d)
        groups = report.group_by_workload(records)
        oct = {r["model"]: r for r in groups["oct2024-cmp"]}
        jun = {r["model"]: r for r in groups["jun2026-perf"]}
        self.assertEqual(oct["codex"]["coords"]["COORD-B-COMPLETION"]["attainment"], 80)
        self.assertEqual(jun["codex"]["coords"]["COORD-B-COMPLETION"]["attainment"], 100)
        md = report.render_report(records)
        # both distinct values are present; no averaged "90" row is emitted
        self.assertIn("| codex | 80 ", md)
        self.assertIn("| codex | 100 ", md)
        self.assertNotIn("Overall", md)
        self.assertNotIn("Average", md)


class GeometryDeclaredColumnsTest(unittest.TestCase):
    def test_columns_map_to_declared_coordinates(self):
        declared = metrics.declared_coordinate_ids()
        self.assertTrue(declared, "geometry should declare coordinates")
        for _header, cid in report.column_coordinate_map().items():
            self.assertIn(cid, declared)

    def test_assert_columns_declared_passes(self):
        # Must not raise: every report column names a real coordinate.
        metrics.assert_columns_declared(report.column_coordinate_map())


if __name__ == "__main__":
    unittest.main()
