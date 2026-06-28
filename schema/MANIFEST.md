# schema/ — MANIFEST

JSON Schemas (Draft 2020-12) that gate every structured artifact the toolkit
reads or writes. The contract layer: if it isn't schema-valid, it isn't accepted.

## How an agent EXECUTES this folder
- Not executed. Schemas are loaded by validators in the scripts and by
  `tests/test_schema_validation.py` / `test_schema_roundtrip.py` /
  `test_geometry_valid.py`. Validation is best-effort at runtime (skipped if
  `jsonschema` is absent) but MANDATORY in tests.

## How an agent CHANGES this folder
- Changing a schema is a versioned event: bump the artifact's `ontology_version`
  / `schema_version`, keep a documented migration (the `port_legacy.py` pattern),
  and update the producing/consuming code + its config in `config/`.
- Keep `additionalProperties:false` where it already is — Project State and the
  public item schema rely on strictness. Re-run `pytest -q`.

## Files
- `extracted_item_schema.json` — full internal catalog item (with provenance).
- `extracted_item_public_schema.json` — sanitized publish item (NO
  `source_conversation_ids`; enforced by `test_repo_hygiene`).
- `models_bank.schema.json` — `config/models.json` shape.
- `pricing.schema.json` — `config/pricing.json` shape.
- `plans.schema.json` — `config/plans.json` shape.
- `model_benchmarks.schema.json` — `config/generated/model_benchmarks.json` shape.
- `ontology_banks.schema.json` — the `ontology/*.json` bank shape.
- `ados/` — the ADOS governance schemas (see `ados/MANIFEST.md`).
