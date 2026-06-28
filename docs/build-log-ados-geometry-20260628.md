# Build log — ADOS Geometry release (2026-06-28)

Local build on the Dell 5820 / RTX 3090 / WSL2 box. Implements the 16-file Claude
dev pack. Tests: **253 passed, 18 subtests** (was 223) — green at every step.

## Tasks

1. **Clean kill (NFR-R2).** `providers/base.py::_post_json` gained
   `retry_on_timeout` / `max_attempts`; `ollama_provider` passes
   `retry_on_timeout=False, max_attempts=1`, so a CPU-spilled local item fails
   once instead of retrying the 300 s socket timeout ~4×. Test:
   `tests/test_clean_kill.py` (single attempt on `TimeoutError` and on a
   `URLError`-wrapped socket timeout; cloud path still retries).
2. **`gemma4:31b num_ctx=16384`** pinned in `config/models.json` (+ note).
   `models_bank.resolve("gemma4:31b")["num_ctx"] == 16384`
   (`tests/test_schema_validation.py`).
3. **ADOS Project Geometry adopted.** 5 schemas → `schema/ados/`; seed →
   `geometry/project-geometry.json` (`COORD-B-COMPLETION` anchors enriched to a
   fuller, genuinely-distinct ladder 0/30/50/70/90/100; formula coordinates kept
   on principled custom anchors per the anchor-critic rule). `ESSAY.md` replaced
   with the ADOS normative document; `ados-vocabulary/ADOS-MAPPING.md` added.
   Validation + referential integrity: `tests/test_geometry_valid.py`.
4. **Project State + Rubric.** `geometry/evaluation-rubric.json` (5 axes Σ=100;
   GATE-PRIVACY/GATE-COVERAGE *fail*, GATE-SCHEMA *cap_50*). Pure scorer
   `scripts/lib/rubric.py` (gates applied after aggregation). `gpt state`
   (`scripts/project_state.py`) emits a schema-valid, append-only Project State.
   Tests: `tests/test_rubric_gates.py`, `tests/test_project_state.py`.
5. **Canonical verdicts (FR-D2).** Regenerated from one named sweep:
   `gpt gen-model-benchmarks --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex
   --date 2026-06-26`. All 16 model verdicts reproduce **byte-for-byte**; only
   `generated_at` changed — proving the verdict reruns clean from committed
   commands. jun2026 is deliberately not folded in (no workload conflation).
6. **Geometry-aware metrics.** `scripts/metrics.py` binds every rendered column
   to a declared Project Coordinate (`COLUMN_COORDINATES` +
   `assert_columns_declared`); an undeclared column is refused.
   `tests/test_metrics_geometry.py`.

## Lifecycle (ADOS 0.8.20)

Governed roadmap moved to `TODO.md`; `PLANNED-WORKS.md` demoted to an informal
note; `CHANGELOG.md` release entry added.

## Constraints honored

GOAL + 3 OBJECTIVES unchanged. No off-machine calls. Raw chat data stayed in
`$DATA_ROOT` (gitignored). Each change confined to its target (NFR-Q5).
