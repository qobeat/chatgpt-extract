# Timing — load vs. inference (oct2024 sweep, post-hoc)

**Date:** 2026-06-25 · **Workload:** `runs/oct2024` (the `chatgpt-20241027.zip`
export → 27 project bundles) · **Context:** `--num-ctx 16384` held constant ·
**Hardware:** RTX 3090 24 GB (local Ollama); cursor/codex/claude via signed-in plan.

## Why this document exists

The standard `s/item` metric (`gpt metrics perf`) averages wall-seconds over
completed items, which **silently includes the one-time cost of loading the model
into VRAM**. That load is paid only on the first call of a run (`keep_alive` keeps
the model warm afterwards), so it is a fixed cost smeared across the run — and it
penalises large local models far out of proportion to their actual inference
speed. This report separates the two so latency is read honestly.

These numbers are **post-hoc estimates** recovered from each run's
`summarize_trace.jsonl`: this sweep predates the `load_duration` instrumentation,
so the load is estimated as `secs(first completed item) − median(secs of the
rest)`. Runs made after the provider patch report **exact** load from Ollama's
`load_duration` (see `docs/`/`AI_MODEL_TESTS.md` for the instrumented re-run).

## Results — sorted by warm (load-excluded) speed

| model | items | fails | s/item (incl. load) | warm s/item | load s (est) |
|---|---:|---:|---:|---:|---:|
| ollama:gemma3:1b | 25 | 2 | 3.5 | 2.5 | ~7.6 |
| ollama:qwen2.5-coder:1.5b | 25 | 2 | 3.1 | 3.0 | ~0.2 |
| ollama:qwen2.5-coder:3b | 25 | 2 | 4.3 | 3.5 | ~18.6 |
| ollama:qwen2.5vl:7b | 25 | 2 | 7.0 | 4.7 | ~47.5 |
| ollama:llama3.1:8b | 26 | 1 | 6.6 | 5.1 | ~32.8 |
| ollama:qwen2.5-coder:7b | 25 | 2 | 7.1 | 5.5 | ~34.4 |
| ollama:qwen3:8b | 25 | 2 | 8.5 | 6.1 | ~45.7 |
| ollama:qwen2.5-coder:14b | 25 | 2 | 13.3 | 10.1 | ~58.9 |
| **ollama:qwen3.6:35b** | 25 | 2 | **26.5** | **10.7** | **~379.2** |
| cursor:composer-2.5-fast | 27 | 0 | 12.5 | 12.2 | ~3.3 |
| ollama:gpt-oss:20b | 22 | 5 | 20.0 | 14.8 | ~93.7 |
| cursor:composer-2.5 | 27 | 0 | 17.8 | 16.5 | ~1.1 |
| claude | 27 | 0 | 23.8 | 19.1 | ~31.6 |
| ollama:qwen3.6:27b | 25 | 2 | 29.0 | 21.4 | ~133.5 |
| ollama:gemma4:31b | 25 | 2 | 37.5 | 28.1 | ~152.7 |

*`codex` is omitted: it completed 0 items (harness bug — ran outside a trusted
git dir without `--skip-git-repo-check`; the circuit breaker tripped after 3
immediate failures). Fixed in the codex provider; see the instrumented re-run.*

## Key findings

1. **Load dominates the apparent cost of big local models.** `qwen3.6:35b` reads
   as 26.5 s/item but is **10.7 s/item warm** — ~60% faster than its headline,
   and actually faster than both cursor models once loaded. Its ~379 s load is an
   outlier: the 23 GB model sits at the VRAM edge (24.0/24.6 GB) and the previous
   17 GB model must be evicted first, so the cold load is pathologically slow.
2. **The ranking changes when load is removed.** By raw `s/item`, `gemma4:31b`
   (37.5) and `qwen3.6:27b` (29.0) look slowest; warm, they are 28.1 and 21.4,
   and `qwen3.6:35b` leaps from near-bottom to mid-pack. Small coder models are
   fast either way.
3. **Cloud models have no VRAM load**, so warm ≈ wall for them. Their small "load"
   estimate (~1–3 s for cursor) is just first-call/network overhead. **Claude's
   ~31.6 s estimate is not a load** — it is first-call latency the estimator can't
   distinguish from load; treat cloud "load s" as first-call overhead, not VRAM
   load.

## Caveats

- **Estimate, not measurement.** `load = secs(first) − median(rest)` assumes the
  first item is the only cold one and that warm items are i.i.d. It is noisy at
  n≈25 and meaningless for cloud (no VRAM load). Exact figures require the
  `load_duration` capture (now implemented) and a fresh run.
- **Sequencing effect.** Each Ollama model's load includes evicting the previous
  model, so load depends on run order and VRAM pressure — not a pure per-model
  constant.
- **`items` < 27** for Ollama runs reflects parse failures (non-JSON), counted in
  `fails`; those are a reliability signal, separate from timing.
- Reproduce: `python scripts/timing_report.py --glob "$DATA_ROOT/runs/cmp-oct-*"`.
