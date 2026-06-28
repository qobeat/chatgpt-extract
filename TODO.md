# TODO — chatgpt-extract roadmap (governed lifecycle surface)

This is the project's governed roadmap surface, per ADOS 0.8.20 (which renamed
`PLANNED-WORKS.md` → `TODO.md` and forbids `PLANNED-WORKS.md` in a strict
package). `PLANNED-WORKS.md` is retained only as an informal planning note and is
**not** a governed surface — fold any roadmap change here.

Success is defined by the Project Geometry, not by this list:
`geometry/project-geometry.json` (authority) + `geometry/evaluation-rubric.json`.
The GOAL and the three OBJECTIVES (**O1 Catalog**, **O2 Benchmark**, **O3
Decision**) are unchanged and must not be edited without an explicit request.

## Shipped

Completed work is recorded in the durable surfaces, not as a growing list here:

- **`CHANGELOG.md`** — named, dated releases: **Semantics** (gpt ask/index +
  cross-sweep unify), **ADOS Geometry**, **Benchmark Validity & Model Bank**,
  **2.0.0**.
- **`REQUIREMENTS.md`** — every satisfied requirement is tagged `[IMPLEMENTED]`
  with its verification; see §4 "Implemented in the current release".
- **`README.md`** — the command table + "Ask your chats" runbook; **`ESSAY.md`**
  states the durable thesis (`AUTHORITY_REF: project-geometry.json`).

## Next

> New feature ideas land here first (not implemented until scheduled).

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
- [ ] **Cross-sweep accuracy (FR-D3 follow-up).** Thread `--reference` through
  `gpt state --all` so the cross-sweep report can populate `COORD-B-ACCURACY`
  per workload (today the batch path leaves accuracy `unknown` → `—` because no
  etalon is passed).
- [ ] **Semantic ask enhancements (FR-Q follow-ups).** `gpt ask --json` for
  scripting; auto-refresh the index after `gpt run` (or warn when the index is
  stale vs the catalog); chunk-level citations with line offsets so `[n]` links
  to an exact transcript span; optional cross-encoder re-rank of the top-K for
  higher precision; let `gpt ask` fall back to keyword search when no index
  exists instead of erroring.

## Out of scope (non-goals)

A hosted service or web UI; a database backend; a synthetic-benchmark suite;
storing raw personal data in any git repo; any change to the GOAL or the three
OBJECTIVES. Raising any of these requires an explicit decision, not a roadmap
edit.
