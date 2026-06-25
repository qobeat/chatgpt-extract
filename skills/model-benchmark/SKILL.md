---
name: model-benchmark
description: Use when asked to benchmark, compare, or rank AI models (local Ollama, Cursor free models, Codex, Claude) on the real ChatGPT-extraction workload, or to interpret/repair the quality and performance columns. Triggers on "benchmark all my ollama models", "why do smarter models score lower on quality", "rank models by speed/quality/cost", "is the GPU worth it". The benchmark task is always the SAME real workload: summarizing the project bundles. Output is per-model completion, depth-on-success, correctness, speed, and cost.
---

# Model Benchmark

Run every available model over the **same real workload** (the project bundles
from extraction) under controlled conditions, and report metrics that are valid —
i.e. that do not conflate distinct properties. This skill exists because the
naive quality column is misleading; follow it to avoid reproducing that mistake.

## The workload (hold it constant)
- The same N-item bundle sample, same `--num-ctx`, deterministic build once, one
  isolated `--run-label` per model. The hardest bundle (e.g. the `ados-profile`
  mega-bundle) must be in the sample so reliability is tested.

## Run
```bash
# one model
gpt summarize --model qwen3:8b --run-label cmp-qwen3-8b --num-ctx 16384
# aggregate (scope to the cmp-* runs so a stray full run does not leak in)
gpt arena            # performance + quality tables
gpt compare          # correctness adjudication vs a reference
```
Providers: `ollama_provider` (local, offline), `cursor_provider`,
`codex_provider`, `anthropic_provider` / `claude_cli_provider`, `openai_provider`.

## Report these as SEPARATE axes — never one blended rank key (FR-B2)
1. **Completion / reliability** = `LLM_OK / attempted`. This is where big local
   models are actually weak (they drop the hard bundles).
2. **Depth-on-success** = mean field-fill **over completed items only**. Compute
   it as `published_q% × N ÷ completed` if reading legacy aggregates. The current
   `metrics.py` averages over *all* written items and scores a failed item as 0 on
   every axis — which is why bigger models look worse. Exclude failures.
3. **Correctness** (FR-B3) = does the output match the source bundle? Adjudicate
   against a reference answer (use `codex`/cloud as the reference key, or a
   hand-checked set) via `gpt compare`. **Depth ≠ correctness:** three wrong
   bullets score full depth; one correct dense sentence scores low. Never let
   depth stand in for correctness.
4. **Speed** = `s/item` (wall-seconds per completed item) — the rank key for
   latency. **Not** total `tok/s`, which is inflated by input size and rewards
   fast ingestion, not fast completion.
5. **Cost** = measured, not `chars/4`. Cloud: actual token billing. Local: watt-
   hours × electricity rate (FR-B6).

## Fix the cause, not the symptom (FR-B4)
Failures come from unconstrained output (models wrap JSON in prose/markdown).
Enforce **structured output** — Ollama `format=json` or a GBNF grammar — and
**retry on parse failure**. This lifts completion toward 100% and stops failures
from injecting zeros into depth. Coercing malformed output to the empty prior
keeps the run alive but *feeds* the artifact; constrain the output instead.

## Privacy gate before any cloud run (NFR-P3)
Cloud providers receive the **raw bundle** = real personal transcripts. Run the
pre-send scrubber (see `publish-redaction` skill) before sending anything to
`cursor`/`codex`/`claude`/`openai`. Local Ollama stays offline.

## Reading the verdict
Settle keep-vs-return / local-vs-cloud on the **corrected** numbers: completion +
depth-on-success + correctness + `s/item` + measured cost, reported side by side.
Write the conclusion into `AI_MODEL_TESTS.md`; put per-model notes in
`config/models.json`. State sample size (n) and that there are no repeats.
