# geometry/ — MANIFEST

The authority for "what success means" in this project: the ADOS Project
Geometry and its Evaluation Rubric. `ESSAY.md` defers to this folder, not prose.

## How an agent EXECUTES this folder
- Not executed. Loaded by `scripts/project_state.py` (coordinates) and
  `scripts/lib/rubric.py` / `scripts/metrics.py` (axes, gates, declared-column
  guard). `tests/test_geometry_valid.py` validates both files against
  `schema/ados/` and checks they are referentially consistent.

## How an agent CHANGES this folder
- HIGH AUTHORITY. The GOAL, OBJECTIVES, coordinates, and gates define the
  evaluation instrument; do NOT edit without an explicit decision (NFR-Q5). A
  favourable run never edits the geometry to fit.
- If a coordinate/gate changes: bump `geometry_version`, set
  `revision.supersedes_geometry_version`, keep both files' `geometry_version`
  aligned, and update `scripts/project_state.py` / `metrics.py` + tests so every
  declared report column still maps to a real coordinate.

## Files
- `project-geometry.json` — deliveries (catalog/benchmark/decision), the named
  Project Coordinates (`COORD-B-*`, `COORD-C-COVERAGE`, `COORD-D-VERDICT`) with
  measures / does_not_measure / 0-100 anchors, and the vectors.
- `evaluation-rubric.json` — weighted axes + the mandatory gates (`GATE-PRIVACY`,
  `GATE-COVERAGE`, `GATE-SCHEMA`) and the aggregation/unknown/confidence policies.
