# PLAN — Phase 1: Benchmark validity & the keep-vs-return re-decision

**Read first (only these):** `PLANNED-WORKS.md` (Phase 1), `REQUIREMENTS.md`
(FR-B2..B6, FR-D1, FR-D2, NFR-P3), `AI_MODEL_TESTS.md` (§3.4–3.5 metric, §8/§9),
`skills/model-benchmark/SKILL.md`, `skills/publish-redaction/SKILL.md`,
`README.md` (Privacy model, Goal/Objectives O2+O3).

## GOAL of this phase
Make the benchmark defensible and produce a final, evidence-grounded answer to
"is the RTX 3090 worth \$1,400 for this workload?" — replacing the verdict that
currently rests on a metric blending depth with reliability and omitting
correctness.

## Scope guard (NFR-Q5)
Touch only `scripts/metrics.py`, `scripts/compare_models.py`, the provider
modules under `scripts/lib/providers/`, `config/models.json`, the benchmark
sections of `AI_MODEL_TESTS.md`, and their tests. Do **not** change extraction,
clustering, or the ontology.

## Actions and success conditions (priority order)

1. **Split reliability from quality in `metrics.py` (FR-B2, FR-B5).**
   - Compute `quality%` (depth) over **completed items only**; report
     `completion = LLM_OK/attempted` as its own column; keep failed items visible
     but excluded from the depth mean.
   - *Success:* the master table has separate `completion` and `depth-on-success`
     columns; recomputing the published example reproduces qwen3:8b ≈ 92.5%
     depth-on-success at 8/10 completion; the doc/code contradiction ("over
     completed items") is gone.

2. **Add structured-output enforcement + retry (FR-B4).**
   - In `ollama_provider` set `format=json` (or attach a GBNF grammar); on a parse
     miss, retry once, then record an honest failure. Apply the equivalent to
     cloud providers where supported.
   - *Success:* on the same sample, the big models' completion rises materially
     vs the pre-change baseline; a regression test asserts a deliberately
     prose-wrapped response is parsed or cleanly retried, not coerced to empty.

3. **Add a correctness check (FR-B3).**
   - Extend `gpt compare` to adjudicate each item against a **reference** (use
     `codex`/a cloud model as the key, or a hand-checked set): does the
     classification + key fields match the source bundle? Emit an `accuracy%`
     column distinct from depth.
   - *Success:* `gpt compare` outputs per-model `accuracy%`; the report shows a
     case where high depth ≠ high accuracy, demonstrating the two are separate.

4. **Cloud pre-send scrubber as a gate before re-running cloud models (NFR-P3).**
   - Per `skills/publish-redaction`, scrub each bundle before any
     `cursor`/`codex`/`claude`/`openai` call. Local Ollama is exempt.
   - *Success:* a unit test proves a bundle containing a fixture email/home-path is
     scrubbed before the provider call; no cloud re-run happens without it.

5. **Measure cost/power, then re-run and re-decide (FR-B6, FR-D1, FR-D2).**
   - Replace the `chars/4` estimate with token-exact cloud cost and measured
     local watt-hours × rate. Re-run the suite on the corrected harness.
   - Regenerate `config/models.json` `note` verdicts from the corrected metric and
     rewrite the `AI_MODEL_TESTS.md` verdict + §8/§9 from the new numbers.
   - *Success:* the keep-vs-return verdict in `AI_MODEL_TESTS.md` cites completion
     + depth-on-success + accuracy + `s/item` + measured cost, side by side, and
     is reproducible from committed commands (FR-D1).

## Acceptance criteria
`gpt metrics` reports completion / depth-on-success / schema-valid / accuracy as
separate columns (FR-B2/B3); the Ollama provider enforces structured output with
retry (FR-B4); a cloud pre-send scrubber exists and gates cloud calls (NFR-P3);
`config/models.json` verdicts are regenerated (FR-D2); `pytest -q` is green
(NFR-Q1).

## Out of scope
Catalog content-type coverage (Phase 2), publish-boundary hardening (Phase 3),
CLI ergonomics (Phase 4).
