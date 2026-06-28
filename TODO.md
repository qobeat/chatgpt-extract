# TODO — chatgpt-extract roadmap (governed lifecycle surface)

This is the project's governed roadmap surface, per ADOS 0.8.20 (which renamed
`PLANNED-WORKS.md` → `TODO.md` and forbids `PLANNED-WORKS.md` in a strict
package). `PLANNED-WORKS.md` is retained only as an informal planning note and is
**not** a governed surface — fold any roadmap change here.

Success is defined by the Project Geometry, not by this list:
`geometry/project-geometry.json` (authority) + `geometry/evaluation-rubric.json`.
The GOAL and the three OBJECTIVES (**O1 Catalog**, **O2 Benchmark**, **O3
Decision**) are unchanged and must not be edited without an explicit request.

## Done

- [x] **Phase 1 — Benchmark validity & the keep-vs-return re-decision.** Separated
  completion / depth-on-success / accuracy / schema-validity / load-separated
  speed / measured Wh/item; correctness adjudicated vs a `codex` reference;
  cloud pre-send scrubber (`--scrub-cloud`); verdict in `AI_MODEL_TESTS.md`.
- [x] **ADOS Project Geometry release.** The benchmark is now expressed as a
  governed, schema-valid Geometry (8 coordinates, 3 deliveries) + Evaluation
  Rubric (5 axes Σ=100, 3 mandatory gates). `gpt metrics` is geometry-aware
  (columns bound to declared coordinates); `gpt state` emits an append-only
  Project State; clean-kill (NFR-R2) and `gemma4:31b num_ctx=16384` gaps closed;
  the `cmp-oct2-*` verdicts regenerate reproducibly against the codex reference.

## Next

- [ ] **Phase 2 — Catalog completeness & fidelity (O1).** Largely landed
  (`tether_quote`/`tether_browsing_display`/`execution_output`/reasoning,
  per-message `model_slug`, attachments, coverage tests). Lift
  `COORD-C-COVERAGE` from `unknown` to a measured observation in `gpt state` by
  reading the extract log counts (added/skipped/errors).
- [ ] **Phase 3 — Publish / redaction hardening + observability (NFR-P).**
  Redaction as an active transform; broaden patterns; wire the catalog repo's
  run-stats. Audit `COORD-D-VERDICT` and emit GATE-PRIVACY / GATE-COVERAGE
  evidence into Project State so the rubric score is gate-aware end to end.
- [ ] **Phase 4 — CLI / UX polish & packaging.** Consistent verbs, `--json`
  everywhere, vendored-lib pinning (`VENDORED_FROM`), install ergonomics.

## Out of scope (non-goals)

A hosted service or web UI; a database backend; a synthetic-benchmark suite;
storing raw personal data in any git repo; any change to the GOAL or the three
OBJECTIVES. Raising any of these requires an explicit decision, not a roadmap
edit.
