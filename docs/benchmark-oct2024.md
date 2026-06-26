# Benchmark — oct2024 export, all providers (instrumented, exact timing)

**Date:** 2026-06-25 · **Workload:** `runs/oct2024` (`chatgpt-20241027.zip` →
27 project bundles, the same set for every model) · **Context:** `--num-ctx
16384` held constant · **Sweep label:** `cmp-oct2-*` · **Hardware:** RTX 3090
24 GB (local Ollama); cursor/codex/claude via signed-in plan.

This run uses the **instrumented** harness: Ollama's `load_duration` is captured
per item, so model **load time is separated from inference** (no longer smeared
into `s/item`). Compare with `docs/timing-oct2024-posthoc.md`, which estimated
the same split from the earlier un-instrumented sweep.

## Performance — load vs. warm (lower is faster)

`warm s/it` = `s/item` with the one-time VRAM load removed (exact, from
`load_duration`). Cloud providers have no VRAM load, so warm = wall (shown `—`).

| rank | model | s/item | warm s/it | load s | gen s/it | gen tok/s | completed |
|---:|---|---:|---:|---:|---:|---:|---:|
| 1 | ollama qwen2.5-coder:1.5b | 3.2 | 2.7 | 12.8 | 2.09 | 126.7 | 25/27 |
| 2 | ollama gemma3:1b | 3.6 | 2.7 | 21.7 | 2.19 | 88.7 | 25/27 |
| 3 | ollama qwen2.5-coder:3b | 4.3 | 3.3 | 23.2 | 2.46 | 87.1 | 25/27 |
| 4 | ollama qwen2.5vl:7b | 7.2 | 5.2 | 48.9 | 3.74 | 53.9 | 25/27 |
| 5 | ollama qwen2.5-coder:7b | 7.1 | 5.4 | 42.6 | 3.95 | 57.0 | 25/27 |
| 6 | ollama llama3.1:8b | 7.0 | 5.5 | 39.5 | 3.42 | 45.3 | 26/27 |
| 7 | ollama qwen3:8b | 7.3 | 6.8 | 12.7 | 4.46 | 59.7 | 25/27 |
| 8 | ollama qwen2.5-coder:14b | 13.6 | 11.0 | 64.3 | 7.29 | 31.2 | 25/27 |
| 9 | ollama qwen3.6:35b | 19.0 | 11.8 | 180.3 | 8.80 | 28.8 | 25/27 |
| 10 | cursor composer-2.5-fast | 12.7 | 12.7 | — | n/a | 64.4 | 27/27 |
| 11 | codex | 15.2 | 15.2 | — | n/a | 49.3 | 27/27 |
| 12 | ollama gpt-oss:20b | 20.8 | 16.0 | 107.0 | 4.16 | 21.2 | 22/27 |
| 13 | cursor composer-2.5 | 18.7 | 18.7 | — | n/a | 46.0 | 27/27 |
| 14 | claude | 24.5 | 24.5 | — | n/a | 34.0 | 27/27 |
| 15 | ollama qwen3.6:27b | 29.9 | 24.0 | 146.9 | 17.46 | 19.6 | 25/27 |
| 16 | ollama gemma4:31b | 37.8 | 31.6 | 157.3 | 19.51 | 15.5 | 25/27 |

## Quality — reliability and depth, reported separately (never blended)

| rank | model | compl% | depth* | json% | done |
|---:|---|---:|---:|---:|---:|
| 1 | codex | 100% | 99% | 100% | 27/27 |
| 2 | cursor composer-2.5 | 100% | 99% | 100% | 27/27 |
| 3 | claude | 100% | 98% | 100% | 27/27 |
| 4 | cursor composer-2.5-fast | 100% | 98% | 100% | 27/27 |
| 5 | ollama llama3.1:8b | 96% | 58% | 96% | 26/27 |
| 6 | ollama gemma4:31b | 93% | 89% | 93% | 25/27 |
| 7 | ollama qwen3.6:27b | 93% | 88% | 93% | 25/27 |
| 8 | ollama qwen3:8b | 93% | 85% | 93% | 25/27 |
| 9 | ollama qwen3.6:35b | 93% | 79% | 93% | 25/27 |
| 10 | ollama qwen2.5-coder:14b | 93% | 72% | 93% | 25/27 |
| 11 | ollama qwen2.5-coder:7b | 93% | 69% | 93% | 25/27 |
| 12 | ollama qwen2.5vl:7b | 93% | 68% | 93% | 25/27 |
| 13 | ollama qwen2.5-coder:1.5b | 93% | 65% | 93% | 25/27 |
| 14 | ollama qwen2.5-coder:3b | 93% | 55% | 93% | 25/27 |
| 15 | ollama gemma3:1b | 93% | 28% | 4% | 25/27 |
| 16 | ollama gpt-oss:20b | 81% | 77% | 81% | 22/27 |

`compl%` = LLM_OK / all items (reliability). `depth*` = mean fill over completed
items only (failures excluded, not scored 0). `json%` = clean schema-shaped JSON
rate. See `AI_MODEL_TESTS.md` §3.5 for why these must never be blended.

## Key findings (timing)

1. **Load, not inference, is the real cost of big local models.** `qwen3.6:35b`
   ranks near the bottom by wall `s/item` (19.0) but is **11.8 s/it warm** — its
   180 s one-time load (23 GB at the VRAM edge, evicting the prior model)
   dominates. `gemma4:31b`: 37.8 → 31.6; `qwen3.6:27b`: 29.9 → 24.0; `gpt-oss:20b`:
   20.8 → 16.0.
2. **Warm, the fast local models beat the cloud on latency**, at $0 marginal:
   `qwen2.5-coder:1.5b` 2.7 s/it and `qwen3:8b` 6.8 s/it vs cursor-fast 12.7,
   codex 15.2, claude 24.5 — but the cloud models finish **27/27** while local
   tops out at 26/27 (llama3.1) / 25/27.
3. **`gen s/it` (pure generation) is even lower** than warm s/it (warm still
   includes prompt-eval/ingest): e.g. qwen3:8b 4.46 s generation vs 6.8 warm.
4. **`load s` depends on run order** (each Ollama load evicts the previous model),
   so it is a context-dependent cost, not a pure per-model constant.

## Verdict unchanged, but for a sharper reason

On reliability the cloud plan models still win (100% vs ≤96% local). But the
**local speed deficit was largely a measurement artifact**: once the one-time
load is removed, the fast local models are *faster* than the cloud per item at
$0 marginal. The honest local-vs-cloud trade on this box is **reliability +
zero-setup (cloud) vs. warm per-item speed + privacy + $0 marginal (local)** —
not "local is slow."

## Reproduce

```bash
# re-run all models on this data, instrumented, isolated per model:
bash ~/chatgpt-reconstructor-data/bench_oct2024.sh cmp-oct2
# read the numbers back:
python scripts/metrics.py perf    "$DATA_ROOT"/runs/cmp-oct2-*/summarize_trace.jsonl
python scripts/metrics.py quality "$DATA_ROOT"/runs/cmp-oct2-*/reconstructed_projects.json
python scripts/timing_report.py   --glob "$DATA_ROOT/runs/cmp-oct2-*"
```
