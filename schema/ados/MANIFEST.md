# schema/ados/ — MANIFEST

The ADOS governance schemas: the strict contracts for the Project Geometry,
Evaluation Rubric, and Project State that make the measurement itself auditable.

## How an agent EXECUTES this folder
- Not executed. `scripts/project_state.py` validates emitted states against
  `project-state.schema.json`; `tests/test_geometry_valid.py` validates the
  committed `geometry/*.json` against these schemas and checks referential
  consistency (every coordinate/gate referenced actually exists).

## How an agent CHANGES this folder
- These are upstream ADOS contracts — change them ONLY by explicit decision, and
  in lockstep with `geometry/` and `scripts/project_state.py`. A new required
  field breaks every prior state; provide a migration.
- `project-state.schema.json` uses `additionalProperties:false`: extra keys are
  rejected. Carry sweep/workload identity in the filename + `evidence_refs`,
  never as ad-hoc keys. `native_observations[].value` is unconstrained (numbers
  or short strings like gate `pass`/`fail` are valid).

## Files
- `project-geometry.schema.json` — shape of `geometry/project-geometry.json`
  (deliveries, coordinates, vectors, anchors/gates).
- `evaluation-rubric.schema.json` — shape of `geometry/evaluation-rubric.json`
  (weighted axes, mandatory gates, aggregation rule).
- `project-state.schema.json` — shape of an emitted Project State observation.
- `reference-model-bank.schema.json` — reference/etalon model bank shape.
- `execution-governance-profile.schema.json` — execution governance profile.
