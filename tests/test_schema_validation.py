"""JSON Schema is the contract (Draft 2020-12): every committed structured data
file MUST validate against its schema. See docs/PLAN-ADDENDUM-models-json.md
"Schema catalog". Cross-field arithmetic lives in test_eval_facets.py, not here."""
from __future__ import annotations

import json
import os
import unittest

import jsonschema

ROOT = os.path.join(os.path.dirname(__file__), "..")

# (data file, schema file). Files that may be absent (generated) are guarded.
CASES = [
    ("config/models.json", "schema/models_bank.schema.json"),
    ("config/plans.json", "schema/plans.schema.json"),
    ("config/pricing.json", "schema/pricing.schema.json"),
    ("config/generated/model_benchmarks.json", "schema/model_benchmarks.schema.json"),
    ("ontology/archetypes.json", "schema/ontology_banks.schema.json"),
    ("ontology/domains.json", "schema/ontology_banks.schema.json"),
    ("ontology/cognitive_types.json", "schema/ontology_banks.schema.json"),
    ("ontology/difficulty.json", "schema/ontology_banks.schema.json"),
    ("ontology/verifiability.json", "schema/ontology_banks.schema.json"),
]

OPTIONAL = {"config/generated/model_benchmarks.json"}


def _load(rel: str) -> dict:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return json.load(f)


class SchemaValidationTest(unittest.TestCase):
    def test_data_files_validate_against_their_schema(self):
        for data_rel, schema_rel in CASES:
            with self.subTest(data=data_rel):
                if data_rel in OPTIONAL and not os.path.exists(
                        os.path.join(ROOT, data_rel)):
                    self.skipTest(f"{data_rel} not generated")
                    continue
                schema = _load(schema_rel)
                jsonschema.validate(_load(data_rel), schema)

    def test_models_billing_plan_ids_resolve(self):
        """Foreign-key check the schema can't express: every subscription's
        billing.plan_id must exist in config/plans.json."""
        plans = {p["id"] for p in _load("config/plans.json")["plans"]}
        for m in _load("config/models.json")["models"]:
            billing = m.get("billing", {})
            if billing.get("kind") == "subscription":
                self.assertIn(billing.get("plan_id"), plans, m["name"])

    def test_gemma4_31b_has_num_ctx_16384(self):
        """NFR-R2: gemma4:31b must pin num_ctx=16384 so a bare `summarize
        --model gemma4:31b` resolves to 16k (not the 32k default that risks a
        VRAM spill). The static bank entry wins over live Ollama discovery."""
        import sys
        sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
        import models_bank
        # Resolve offline: include_ollama is handled inside resolve; the static
        # entry carries num_ctx and wins on a (provider, name) collision.
        resolved = models_bank.resolve("gemma4:31b")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.get("num_ctx"), 16384)


if __name__ == "__main__":
    unittest.main()
