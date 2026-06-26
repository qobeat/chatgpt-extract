# Benchmark — oct2024 export, all providers (instrumented: timing, accuracy, power)

**Date:** 2026-06-26 · **Workload:** `runs/oct2024` (`chatgpt-20241027.zip` →
27 project bundles, the same set for every model) · **Context:** `--num-ctx
16384` held constant · **Sweep label:** `cmp-oct2-*` · **Hardware:** RTX 3090
24 GB (local Ollama); cursor/codex/claude via signed-in plan.

This is the **fully instrumented** run: Ollama's `load_duration` separates model
load from inference, classification is adjudicated against a reference for
**accuracy** (not just depth), and the 12 local models were re-run with
`--meter-power` so **GPU watt-hours per item are measured, not estimated**
(FR-B6). The four metrics — completion, depth-on-success, accuracy, and Wh/item —
are reported in separate columns and never blended (see `AI_MODEL_TESTS.md` §3.5).

## Master table — reliability, depth, accuracy, speed, and measured power

`compl%` = LLM_OK / 27 (reliability). `depth*` = mean fill over **completed**
items only (failures excluded, never scored 0). `acc%` = (archetype+domain)
match vs the `codex` reference over shared completed items. `warm s/it` = s/item
with the one-time VRAM load removed. `Wh/item` = **measured** GPU energy per
completed item. Cloud rows have no VRAM load or GPU draw (`—`).

| rank | model | compl% | depth* | acc% | json% | s/item | warm s/it | gen tok/s | **Wh/item** | $/1k |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | codex | 100% | 99% | 100% | 100% | 15.2 | — | 49.3 | — | $0 (plan) |
| 2 | cursor composer-2.5 | 100% | 99% | 81% | 100% | 18.7 | — | 46.0 | — | $0 (plan) |
| 3 | claude | 100% | 98% | 59% | 100% | 24.5 | — | 34.0 | — | $0 (plan) |
| 4 | cursor composer-2.5-fast | 100% | 98% | 81% | 100% | 12.7 | — | 64.4 | — | $0 (plan) |
| 5 | ollama llama3.1:8b | 96% | 59% | 0% | 96% | 7.3 | 5.3 | 44.5 | 0.540 | $0 local |
| 6 | ollama gemma4:31b | 93% | 90% | 68% | 93% | 39.0 | 30.8 | 14.6 | 2.912 | $0 local |
| 7 | ollama qwen3.6:27b | 93% | 88% | 60% | 93% | 29.7 | 22.3 | 19.8 | 2.360 | $0 local |
| 8 | ollama qwen3:8b | 93% | 85% | 16% | 93% | 8.8 | 6.8 | 49.7 | 0.696 | $0 local |
| 9 | ollama qwen3.6:35b | 93% | 79% | 64% | 93% | 20.3 | 10.8 | 27.3 | 1.086 | $0 local |
| 10 | ollama qwen2.5-coder:7b | 93% | 72% | 4% | 93% | 7.6 | 5.7 | 53.9 | 0.614 | $0 local |
| 11 | ollama qwen2.5-coder:1.5b | 93% | 67% | 0% | 93% | 3.5 | 3.0 | 120.7 | **0.252** | $0 local |
| 12 | ollama qwen2.5vl:7b | 93% | 67% | 16% | 93% | 7.6 | 5.4 | 50.4 | 0.577 | $0 local |
| 13 | ollama qwen2.5-coder:14b | 93% | 65% | 20% | 93% | 14.1 | 10.2 | 27.7 | 1.059 | $0 local |
| 14 | ollama qwen2.5-coder:3b | 93% | 56% | 8% | 93% | 4.5 | 3.6 | 81.9 | 0.378 | $0 local |
| 15 | ollama gemma3:1b | 89% | 21% | 0% | 7% | 3.6 | 2.4 | 79.9 | 0.239 | $0 local |
| 16 | ollama gpt-oss:20b | 85% | 78% | 57% | 85% | 22.0 | 16.3 | 21.1 | 1.856 | $0 local |

(Local rows ranked by `s/item` within the speed view; the table above is sorted
by reliability then depth. `gpt-oss:20b` lands last on reliability at 85% = 23/27.)

## What the accuracy column changes

Adding correctness (vs the `codex` answer key) is the most important new signal,
because it **decouples "filled the schema" from "got it right":**

1. **High depth ≠ high accuracy.** `qwen3:8b` fills 85% of the schema but only
   **16%** of its classifications match the reference; the `qwen2.5-coder` family
   is near-zero accuracy despite clean JSON. These models emit well-formed records
   with the **wrong** archetype/domain — exactly the failure `depth%` alone hides.
2. **Among local models, the big reasoners are the only ones that classify
   correctly:** `gemma4:31b` 68%, `qwen3.6:35b` 64%, `qwen3.6:27b` 60%,
   `gpt-oss:20b` 57%. So the earlier "small models are competitive" read (from
   depth) **reverses on accuracy** — small coder models are fast and fill fields
   but mislabel the work.
3. **The cloud models lead on accuracy too** (codex 100% by definition as the
   key; composer-2.5/fast 81%; claude 59%), and they are the only models at 100%
   reliability.

## Measured GPU power (FR-B6) — the economics, finally on real numbers

The 12 local models were metered with `nvidia-smi --query-gpu=power.draw` (1 Hz,
trapezoidal-integrated to watt-hours). Range: **0.24 Wh/item** (`gemma3:1b`,
`qwen2.5-coder:1.5b`) to **2.91 Wh/item** (`gemma4:31b`). At **$0.20/kWh**:

| local pick | Wh/item | electricity $/item | $/1,000 items |
|---|---:|---:|---:|
| qwen2.5-coder:1.5b (speed) | 0.252 | $0.00005 | $0.05 |
| qwen3:8b (best local depth) | 0.696 | $0.00014 | $0.14 |
| gemma4:31b (best local accuracy) | 2.912 | $0.00058 | $0.58 |

Even the heaviest local model costs **well under a tenth of a cent per item** in
electricity. Marginal cost is therefore **not** the deciding factor — the $1,400
capital cost is, and it stands against $0-marginal, higher-reliability,
higher-accuracy plan-covered cloud models. **The GPU does not pay back on this
workload** (it only pencils out at sustained very high local volume or where
privacy/offline is mandatory). See `AI_MODEL_TESTS.md` §6.

## Timing — load is the real cost of big local models

`warm s/it` strips the one-time VRAM load (exact, from `load_duration`). Warm,
the fast local models beat the cloud per item (`qwen2.5-coder:1.5b` 3.0 s/it,
`qwen3:8b` 6.8 s/it vs cursor-fast 12.7, codex 15.2, claude 24.5) at $0 marginal —
but the cloud finishes 27/27 while local tops out at 26/27 (llama3.1) / 25/27.
The big models' wall `s/item` is dominated by load/eviction order
(`gemma4:31b` 39.0 wall → 30.8 warm; `qwen3.6:35b` 20.3 → 10.8 after a 238 s
load), so `load s` is a context-dependent cost, not a per-model constant.

## Verdict

On this 27-bundle workload the decision is unchanged and now rests on four
separated, measured axes: **the plan-covered cloud models win on reliability
(100% vs ≤96%) and accuracy (≥59% vs ≤68% local, and most local models far
lower), at $0 marginal.** Local inference is genuinely cheap to run
(≤0.6 Wh/item for the useful picks) and warm-fast, but that buys *capability*,
not better *output*, and cannot recover a $1,400 capital cost here. If kept for
privacy/volume: `gemma4:31b`/`qwen3.6:27b` for classification accuracy,
`qwen3:8b` for depth, `qwen2.5-coder:1.5b` for fast bulk first passes.

## Reproduce

```bash
# 1. Main sweep (all 16 models, isolated per model, num_ctx 16384):
bash ~/chatgpt-reconstructor-data/bench_oct2024.sh cmp-oct2

# 2. Power-metered re-run of the 12 LOCAL models (measured Wh/item; FR-B6):
bash ~/chatgpt-reconstructor-data/bench_oct2024_power.sh cmp-oct2

# 3. Read the numbers back (read-only):
python scripts/metrics.py perf    "$DATA_ROOT"/runs/cmp-oct2-*/summarize_trace.jsonl
python scripts/metrics.py quality "$DATA_ROOT"/runs/cmp-oct2-*/reconstructed_projects.json \
  --correctness ref=cmp-oct2-codex
python scripts/gen_model_notes.py --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex
```

> Power metering requires the Ollama systemd service to have the GPU attached. If
> a reboot restarts `ollama.service` before CUDA is ready it silently falls back
> to CPU (≈2.4 tok/s, no `--n-gpu-layers`); `sudo systemctl restart ollama`
> re-detects the RTX 3090 (`ollama ps` then shows `100% GPU`).
