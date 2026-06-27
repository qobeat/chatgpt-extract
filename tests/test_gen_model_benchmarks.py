"""FR-B2/B3/D2: model benchmark verdicts are GENERATED (typed, machine-owned),
not hand-written, and the generator upserts (update/add, never delete) into
config/generated/model_benchmarks.json validated by its JSON Schema."""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
SCHEMA = os.path.join(ROOT, "schema", "model_benchmarks.schema.json")


def _load():
    spec = importlib.util.spec_from_file_location(
        "gen_model_benchmarks", os.path.join(SCRIPTS, "gen_model_benchmarks.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


g = _load()

QROW = {"model": "ollama:qwen3:8b", "completion_pct": 80,
        "depth_on_success_pct": 92, "schema_valid_pct": 70,
        "goal_pct": 100, "objectives_pct": 90, "requirements_pct": 80,
        "archetype_fields_pct": 60, "accuracy_pct": 83,
        "completed": 8, "n_items": 10}
PROW = {"model": "ollama:qwen3:8b", "sec_per_item": 9.8, "warm_sec_per_item": 7.1,
        "gen_tok_s": 50.0, "usd_per_1k_items": 0.0, "wh_per_item": None,
        "completed": 8, "attempted": 10, "completion_rate": 0.8}


class BenchKeyTest(unittest.TestCase):
    def test_provider_prefixed_passthrough(self):
        self.assertEqual(g.bench_key("ollama:qwen3:8b"), "ollama:qwen3:8b")
        self.assertEqual(g.bench_key("cursor:composer-2.5"), "cursor:composer-2.5")

    def test_bare_cloud_label_gets_self_provider(self):
        # 'codex' -> 'codex:codex' so it matches the schema key pattern + the bank.
        self.assertEqual(g.bench_key("codex"), "codex:codex")
        self.assertEqual(g.bench_key("claude:"), "claude:claude")


class BuildRowTest(unittest.TestCase):
    def test_typed_fields_and_none_omitted(self):
        row = g.build_row(QROW, PROW)
        self.assertEqual(row["completed"], 8)
        self.assertEqual(row["n_items"], 10)
        self.assertEqual(row["accuracy_pct"], 83.0)
        self.assertEqual(row["warm_sec_per_item"], 7.1)
        # wh_per_item is None in the perf row -> must be OMITTED, never null.
        self.assertNotIn("wh_per_item", row)
        # No blended score is ever emitted.
        self.assertNotIn("score", row)

    def test_perf_only_model_derives_reliability(self):
        row = g.build_row(None, PROW)
        self.assertEqual(row["completed"], 8)
        self.assertEqual(row["n_items"], 10)
        self.assertEqual(row["completion_pct"], 80)

    def test_no_data_returns_none(self):
        self.assertIsNone(g.build_row(None, None))


class UpsertTest(unittest.TestCase):
    def setUp(self):
        self.existing = {"models": {
            "ollama:qwen3:8b": {"n_items": 10, "completed": 7, "completion_pct": 70},
            "codex:codex": {"n_items": 10, "completed": 10, "completion_pct": 100},
        }}

    def test_updates_present_keeps_unseen_adds_new(self):
        fresh = {
            "ollama:qwen3:8b": {"n_items": 10, "completed": 8, "completion_pct": 80},
            "ollama:new-model:7b": {"n_items": 5, "completed": 5, "completion_pct": 100},
        }
        merged, changed = g.upsert(self.existing, fresh)
        # updated
        self.assertEqual(merged["ollama:qwen3:8b"]["completed"], 8)
        # kept (not in this sweep)
        self.assertEqual(merged["codex:codex"]["completed"], 10)
        # added
        self.assertIn("ollama:new-model:7b", merged)
        self.assertCountEqual(changed, ["ollama:qwen3:8b", "ollama:new-model:7b"])

    def test_idempotent(self):
        fresh = {"ollama:qwen3:8b": dict(self.existing["models"]["ollama:qwen3:8b"])}
        _merged, changed = g.upsert(self.existing, fresh)
        self.assertEqual(changed, [])


class SchemaAndInvariantTest(unittest.TestCase):
    def test_built_document_validates_and_holds_invariants(self):
        import jsonschema
        models = {"ollama:qwen3:8b": g.build_row(QROW, PROW),
                  "codex:codex": g.build_row(
                      dict(QROW, model="codex", completed=27, n_items=27,
                           completion_pct=100), None)}
        doc = g.build_document(models, "ref=cmp-oct2-codex",
                               "RTX 3090 24GB", 16384, "2026-06-26")
        with open(SCHEMA, encoding="utf-8") as f:
            jsonschema.validate(doc, json.load(f))
        # Cross-field invariant (enforced in tests, not the schema).
        for key, row in doc["models"].items():
            self.assertLessEqual(row["completed"], row["n_items"], key)

    def test_committed_file_matches_schema(self):
        import jsonschema
        path = os.path.join(ROOT, "config", "generated", "model_benchmarks.json")
        if not os.path.exists(path):
            self.skipTest("generated file not present")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        with open(SCHEMA, encoding="utf-8") as f:
            jsonschema.validate(doc, json.load(f))
        for key, row in doc["models"].items():
            self.assertLessEqual(row["completed"], row["n_items"], key)


if __name__ == "__main__":
    unittest.main()
