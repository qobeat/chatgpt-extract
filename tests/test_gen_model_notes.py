"""FR-D2: model verdict notes are generated from the corrected metric, not
hand-written, and stay in sync (idempotent regeneration)."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")


def _load():
    spec = importlib.util.spec_from_file_location(
        "gen_model_notes", os.path.join(SCRIPTS, "gen_model_notes.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


g = _load()

QROW = {"model": "ollama:qwen3:8b", "completion_pct": 80,
        "depth_on_success_pct": 92, "schema_valid_pct": 70,
        "completed": 8, "n_items": 10}
PROW = {"model": "ollama:qwen3:8b", "sec_per_item": 9.8,
        "usd_per_1k_items": 0.0, "wh_per_item": None}


class FormatNoteTest(unittest.TestCase):
    def test_note_is_separated_not_blended(self):
        note = g.format_note(QROW, PROW)
        # Separated columns present; no single blended "quality%".
        self.assertIn("compl 8/10", note)
        self.assertIn("depth* 92%", note)
        self.assertIn("json 70%", note)
        self.assertIn("9.8 s/item", note)

    def test_accuracy_included_when_present(self):
        q = dict(QROW, accuracy_pct=83)
        self.assertIn("acc 83%", g.format_note(q, None))

    def test_no_data_returns_none(self):
        self.assertIsNone(g.format_note(None, None))


class RegenerateTest(unittest.TestCase):
    def setUp(self):
        self.models = {"models": [
            {"name": "qwen3:8b", "provider": "ollama",
             "note": "OLD hand-written 74% depth, 8/10"},
            {"name": "codex", "provider": "codex", "note": "keep me"},
            {"name": "qwen2.5-coder:3b-cpu", "provider": "ollama",
             "skip": True, "note": "skip note"},
        ]}

    def test_regenerate_replaces_only_models_with_data(self):
        new, changed = g.regenerate(self.models, [QROW], [PROW])
        notes = {e["name"]: e["note"] for e in new["models"]}
        self.assertEqual(changed, ["qwen3:8b"])
        self.assertNotIn("hand-written", notes["qwen3:8b"])
        self.assertEqual(notes["codex"], "keep me")          # no data → kept
        self.assertEqual(notes["qwen2.5-coder:3b-cpu"], "skip note")  # skipped

    def test_regeneration_is_idempotent(self):
        new1, changed1 = g.regenerate(self.models, [QROW], [PROW])
        new2, changed2 = g.regenerate(new1, [QROW], [PROW])
        self.assertTrue(changed1)
        self.assertEqual(changed2, [])  # second pass changes nothing

    def test_note_matches_format_note_output(self):
        new, _ = g.regenerate(self.models, [QROW], [PROW])
        entry = next(e for e in new["models"] if e["name"] == "qwen3:8b")
        self.assertEqual(entry["note"], g.format_note(QROW, PROW))


class ScopedPathsTest(unittest.TestCase):
    """FR-D2: notes must be reproducible from one defined sweep, not whatever
    runs happen to litter $DATA_ROOT."""

    def test_runs_glob_selects_only_matching_run_labels(self):
        with tempfile.TemporaryDirectory() as d:
            runs = os.path.join(d, "runs")
            for label in ("cmp-oct2-qwen3-8b", "cmp-oct2-codex",
                          "cmp-old-10item", "ollama-legacy"):
                rd = os.path.join(runs, label)
                os.makedirs(rd)
                open(os.path.join(rd, "reconstructed_projects.json"), "w").close()
                open(os.path.join(rd, "summarize_trace.jsonl"), "w").close()
            orig = g.paths.data_root
            g.paths.data_root = lambda: d
            try:
                outs, traces = g._scoped_paths("cmp-oct2-*")
            finally:
                g.paths.data_root = orig
        self.assertEqual(len(outs), 2)
        self.assertEqual(len(traces), 2)
        self.assertTrue(all("cmp-oct2-" in p for p in outs))
        self.assertFalse(any("cmp-old-10item" in p for p in outs))
        self.assertFalse(any("ollama-legacy" in p for p in outs))


if __name__ == "__main__":
    unittest.main()
