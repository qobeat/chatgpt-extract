# AI Model Tests — Is the RTX 3090 24 GB worth $1,400 for this workload?

**Verdict (one line):** For ADOS structured-extraction summarization, the
plan-covered cloud models finish nearly every item, classify it correctly, and
cost **$0 marginal** on a plan you already have, so the **$1,400 card is not
justified on output alone** — keep it only for privacy/offline, very high volume,
or if it is already amortised by other GPU work. With **accuracy measured**
(not just field-fill), the local gap is now primarily a **correctness** gap:
most local models emit clean schema JSON with the **wrong** archetype/domain, and
only the big reasoning models (`gemma4:31b` 74%, `qwen3.6:35b` 65%, `qwen3.6:27b`
61%) classify well — and they are the slowest, heaviest ones (§3.5, §5).

| | |
|---|---|
| **Date** | 2026-06-28 |
| **Hardware under test** | NVIDIA GeForce RTX 3090, 24 GB (≈$1,400 used) |
| **Host** | WSL2 (Ubuntu) + Ollama; Cursor / ChatGPT / Claude via signed-in plan |
| **Task** | Classify + summarize project bundles into the ADOS ontology (`gpt summarize`) |
| **Sample** | All 27 project bundles from the `oct2024` export (identical bundles for every model) |
| **Context window** | `--num-ctx 16384` (held constant) |
| **Models** | 12 local Ollama generation models (GPU) + 2 Cursor models + `codex` + `claude` — all on this `cmp-0628` sweep |
| **Metrics** | completion · depth-on-success · **accuracy vs `codex`** · schema-valid · s/item (load-separated) · **measured Wh/item** |
| **Raw data** | `$DATA_ROOT/runs/cmp-0628-*/`, `benchmark_cmp-0628.log`, `benchlogs_cmp-0628/`, `health_cmp-0628/` |

> This is the **detailed model-runs** document. For the one-page, owner-facing
> answer to all three project goals (Catalog / Ask / Benchmark) see
> [SUMMARY.md](SUMMARY.md).

### Glossary (terms used throughout)

- **Cursor models** — `composer-2.5` and `composer-2.5-fast`, the LLMs reached
  through the **Cursor** IDE's headless `cursor-agent` CLI (the `cursor` provider),
  billed under the Cursor Pro+ subscription, so **$0 marginal** per item.
- **ChatGPT / Claude plan models** — `codex` (ChatGPT plan, via the `codex` CLI)
  and `claude` (Claude plan, via the `claude` CLI); also $0 marginal.
- **cmp-0628** — the **run-label prefix** for this benchmark sweep: `cmp` =
  "compare", `0628` = the date (June 28). Each model writes to
  `$DATA_ROOT/runs/cmp-0628-<model>/`; `gpt gen-model-benchmarks --runs 'cmp-0628-*'`
  aggregates them. It distinguishes this sweep from the earlier `cmp-oct2`
  (June 26) sweep. Both run over the **same** 27 bundles from the `oct2024` export.
- **etalon / reference** — the model used as the accuracy answer key
  (`ref=cmp-0628-codex`); its accuracy is 100% by construction.

---

## Contents

1. [Goal and central question](#1-goal-and-central-question)
2. [Executive verdict](#2-executive-verdict)
3. [Methodology — and how to read the metric](#3-methodology--and-how-to-read-the-metric)
4. [Results](#4-results)
5. [Findings](#5-findings)
6. [Economic analysis — the $1,400 question](#6-economic-analysis--the-1400-question)
7. [Recommendation](#7-recommendation)
8. [Open questions](#8-open-questions)
9. [Next steps](#9-next-steps)
10. [Reproducibility](#10-reproducibility)

---

## 1. Goal and central question

A used **RTX 3090 (24 GB)** was bought for ~**$1,400** and can still be returned.
This test answers one decision:

> **Does running the ADOS summarizer locally on the RTX 3090 produce results good
> enough to justify $1,400, versus the cloud models already included in a
> Cursor / ChatGPT / Claude plan?**

On the *same* work it must establish **quality** (completeness *and* correctness),
**speed**, **reliability** (does an item finish), and **cost** (with measured
GPU power, not an estimate).

## 2. Executive verdict

**Hard to justify for this workload.** The plan-covered cloud models finished
**93–100%** of items (`composer-2.5`/`composer-2.5-fast` 27/27, `claude` 26/27,
`codex` 25/27 — the two CLI misses look like a transient network/CLI drop, not a
quality limit). The best local model (`llama3.1:8b`) finished 26/27 and the rest
≤25/27, so **reliability is now close**. The decisive gap is **accuracy**: with
correctness adjudicated against `codex`, the cloud models classify correctly
(composer-2.5 80%, composer-2.5-fast 76%, claude 54%) while **most local models score near-zero accuracy**
despite clean JSON — they fill the schema with the wrong archetype/domain. Only
the big local reasoners classify well (`gemma4:31b` 74%, `qwen3.6:35b` 65%,
`qwen3.6:27b` 61%, `gpt-oss:20b` 50%), and those are the slowest (33–46 s/item)
and most power-hungry (1.8–3.2 Wh/item).

Because the cloud models are **$0 marginal on a plan you already have**, local
inference does not buy better *results* — it adds a $1,400 capital cost. **Every
installed local model ran on the 24 GB card**, so 24 GB is not the limiter; the
GPU buys *local capability*, not bigger models. Marginal electricity is
negligible (**measured** 0.22–3.20 Wh/item ≈ $0.00004–$0.0006/item), so the
decision turns entirely on the $1,400 capital cost.

Keep the card only if **at least one** holds: (1) privacy/offline is
non-negotiable; (2) volume × rate-limits exceed the plan; (3) the GPU is already
amortised by other work. If kept, the local pick depends on the axis you weight —
see §7.

## 3. Methodology — and how to read the metric

### 3.1 Test design (apples-to-apples)

The deterministic build (Extract → Cluster → Bundle, no LLM) was built **once**
from the `oct2024` export; every model was pointed at the **same** 27 bundles.
Each model ran under its own `--run-label` (`cmp-0628-*`) into an isolated output
+ trace; `--num-ctx 16384` and the bundle set were held constant. The 12 local
models ran with `--meter-power` to record **measured** GPU watt-hours per item,
behind a `bench_monitor.py` GPU preflight + 30 s health watch (§3.6).

### 3.2 Models under test

All 16 models ran on this `cmp-0628` sweep: 12 local generation models on the GPU
(all installed Ollama generation tags, embeddings excluded), the two Cursor models
(`composer-2.5`, `composer-2.5-fast`), `codex`, and `claude`. The CPU-only build of
`qwen2.5-coder:3b` remains `skip` in the model bank (unusably slow).

### 3.3 Metric definitions

- **`completion`** = `LLM_OK / 27` (reliability). A failed item is written with
  the deterministic prior and excluded from depth/accuracy, so completion is the
  honest reliability signal — never folded into the quality number.
- **`depth-on-success`** = mean of four 0–100 fill axes (goal, objective-set
  depth capped at 3, requirement-set depth capped at 3, archetype-field fill)
  over **completed items only**. A **completeness** proxy, not correctness.
- **`accuracy`** = fraction of a model's completed items whose
  (primary archetype, primary domain) **matches the `codex` reference**, over
  slugs both classified. This is the **correctness** axis (FR-B3).
- **`schema-valid`** = clean schema-shaped JSON rate (a coder-model strength,
  distinct from reliability).
- **`s/item`** / **`warm s/it`** = wall-seconds per completed item, and the same
  with the one-time VRAM load (`load_duration`) removed.
- **`Wh/item`** = **measured** GPU energy per completed item, integrated from
  `nvidia-smi --query-gpu=power.draw` at 1 Hz (FR-B6).

### 3.4 What `depth%` does NOT measure (read this)

`depth%` rewards a **fully filled** record. It does **not** check whether the
content is **right** — and this run proves the gap is real, not theoretical:
`qwen3:8b` fills 85% of the schema but only **9%** of its classifications match
the reference; the `qwen2.5-coder` family is ≤22% accuracy with 93% clean JSON.
So `depth%` reads as *"did the model emit clean, fully-populated schema JSON"* — a
coder-model strength — while **`accuracy%` is the axis that tracks whether the
model understood the work.**

### 3.5 Why this matters — completion, depth, and accuracy are three different things

The earliest 10-item run blended reliability into a single "quality%", which made
larger models look worse. This run separates all three axes and adds accuracy,
which resolves the question:

1. **Failed items are excluded, not scored 0** (closing the old artifact): depth
   and accuracy are computed over completed items only; completion is reported
   beside them.
2. **On depth, size is roughly flat** once failures are excluded (big reasoners
   76–89%, coders 52–74%; only `gemma3:1b` collapses at 27%) — the old "bigger is
   worse" ordering does not hold.
3. **On accuracy, size clearly *wins* locally.** The only local models that
   classify correctly are the big reasoners (`gemma4:31b` 74%, `qwen3.6:35b` 65%,
   `qwen3.6:27b` 61%, `gpt-oss:20b` 50%); the small/coder models fill fields but
   mislabel (≤22%). So the defensible conclusion is: **report completion, depth,
   and accuracy separately; never blend them; the real weakness of *small* local
   models is correctness, and of *big* local models is speed + power.**

Caveats unchanged: `codex` is the accuracy *key* (100% by construction, not an
independent ground truth), n = 27 single run with no repeats, and one domain /
one user.

### 3.6 Fixes applied across the test (result integrity)

| Problem | Fix |
|---|---|
| Weak models emit a bare string where the schema expects an object, crashing the run | `build_item` coerces malformed fields to the deterministic prior; regression tests added |
| Reasoning/instruct models wrap JSON in prose the parser drops → counted as failures | Ollama provider sets `format=json` with **retry-on-parse-miss** (FR-B4) before recording an honest failure |
| `cursor-agent` blocked on an interactive "trust this directory?" prompt | Cursor provider passes `--trust` (headless) |
| Cost/power were estimated (`chars/4`, ~350 W) | Token-exact cloud cost + **measured** GPU Wh/item via `--meter-power` (FR-B6) |
| A reboot could restart `ollama.service` CPU-only (no GPU), silently invalidating power | `bench_monitor.py` GPU **preflight** + 30 s health **watch** (CPU spill / GPU idle / VRAM full / error lines); autofix `systemctl restart ollama` before the next model |
| A cloud benchmark could leak PII or blow the plan budget | Web search disabled on `codex`/`claude` (answer from the prompt alone); `--budget-usd 5` token-equivalent cap; cloud pre-send scrubber gates the call (NFR-P3) |

## 4. Results

### 4.1 Master table (four separated axes — NOT blended)

| Model | Where | compl% | depth* | **acc%** | json% | s/item | warm s/it | gen tok/s | **Wh/item** | Marginal $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **codex** | ChatGPT plan | 93 | 98 | **100** ¹ | 93 | 27.3 | — | 27.1 | — | $0 (plan) |
| **composer-2.5** | Cursor plan | **100** | 99 | 80 | 100 | 27.1 | — | 31.2 | — | $0 (plan) |
| **composer-2.5-fast** | Cursor plan | **100** | 99 | 76 | 100 | 14.4 | — | 59.6 | — | $0 (plan) |
| **claude** | Claude plan | 96 | 98 | 54 | 96 | 38.5 | — | 20.9 | — | $0 (plan) |
| gemma4:31b | RTX 3090 | 93 | 89 | **74** | 93 | 45.7 | 35.9 | 12.9 | 3.197 | $0 local |
| qwen3.6:35b | RTX 3090 ² | 93 | 80 | 65 | 93 | 33.4 | 19.2 | 16.4 | 1.788 | $0 local |
| qwen3.6:27b | RTX 3090 | 93 | 88 | 61 | 93 | 41.1 | 36.7 | 14.3 | 3.146 | $0 local |
| gpt-oss:20b | RTX 3090 | 81 | 76 | 50 | 81 | 20.4 | 19.6 | 22.4 | 2.115 | $0 local |
| qwen2.5-coder:14b | RTX 3090 | 93 | 74 | 22 | 93 | 12.9 | 12.6 | 32.8 | 1.200 | $0 local |
| qwen2.5vl:7b | RTX 3090 | 93 | 66 | 17 | 89 | 6.5 | 6.1 | 56.7 | 0.599 | $0 local |
| qwen3:8b | RTX 3090 | 93 | 85 | 9 | 93 | 8.7 | 8.3 | 50.7 | 0.759 | $0 local |
| qwen2.5-coder:3b | RTX 3090 | 93 | 52 | 9 | 93 | 3.9 | 3.7 | 95.4 | 0.354 | $0 local |
| qwen2.5-coder:7b | RTX 3090 | 93 | 70 | 4 | 93 | 6.2 | 6.0 | 64.8 | 0.598 | $0 local |
| qwen2.5-coder:1.5b | RTX 3090 | 93 | 69 | 0 | 93 | **2.9** | **2.7** | **134.0** | **0.215** | $0 local |
| llama3.1:8b | RTX 3090 | 96 | 57 | 0 | 96 | 7.8 | 7.2 | 39.8 | 0.628 | $0 local |
| gemma3:1b | RTX 3090 | 89 | 27 | 0 | 11 | 6.1 | 4.9 | 54.9 | 0.316 | $0 local |

¹ `codex` is the accuracy reference, so its 100% is by construction. ² `qwen3.6:35b`
loads ~23 GB — fits only near the VRAM edge at 16k ctx.

**Columns / formulas** (reliability, depth, and correctness are SEPARATE — never blended)

- **compl%** (completion) = LLM_OK / attempted × 100 — reliability; a failed item is written with the deterministic prior and excluded from depth/accuracy.
- **depth\*** (depth-on-success) = mean of four 0–100 fill axes (goal, min(objectives,3)/3, min(requirements,3)/3, archetype-field fill) over **completed items only** — completeness, not correctness.
- **acc%** (accuracy) = items whose (primary archetype, primary domain) match the `codex` reference / items both classified × 100 — correctness.
- **json%** (schema-valid) = schema-shaped clean-JSON items / attempted × 100.
- **s/item** = wall-seconds / completed (includes one-time load); **warm s/it** = (wall − `load_duration`) / completed (cloud has no local load, so "—").
- **gen tok/s** = generated tokens / generation-seconds.
- **Wh/item** = measured GPU energy per completed item (∫ `nvidia-smi power.draw` at 1 Hz ÷ completed); cloud draws no local GPU, so "—".
- **Marginal $** = incremental cost per item: $0 on a plan you hold; energy-only for local.

### 4.2 The numbers tell three different stories

- **Reliability (completion):** Cursor composer 100% · best local 96%
  (`llama3.1`) · `claude` 96% · most local 93% · `codex` 93% · `gpt-oss` 81%.
  Cloud and the best local are now within a couple of items of each other.
- **Depth on success:** cloud 98–99% · local 27–89%, roughly flat in size once
  failures are excluded.
- **Accuracy:** cloud 54–80% (`codex` = key at 100) · local **0–74%**, and
  **monotone in reasoning capability** — the big reasoners classify, the small
  coders do not.

### 4.3 VRAM fit (does 24 GB constrain the choice?)

Everything up to `qwen2.5-coder:14b` fits comfortably; `gpt-oss:20b`,
`qwen3.6:27b`, `gemma4:31b` (~17–20 GB) fit; `qwen3.6:35b` fits only near the edge
(~23 GB at 16k ctx). **Every installed model ran on the GPU.** **24 GB is not the
binding constraint.**

## 5. Findings

1. **Cloud plan models win on accuracy; reliability is now close.** Completion is
   93–100% cloud vs 81–96% local, but the decisive gap is accuracy: 54–80% cloud
   vs ≤74% local (most local far lower). For an unattended run that classifies
   correctly, cloud is still ahead.
2. **Accuracy and depth are different axes.** `qwen3:8b` is high-depth (85%) but
   low-accuracy (9%); the coder family is high-JSON but ≤22% accuracy. **Field
   fill ≠ understanding.** Only big reasoners (`gemma4:31b`, `qwen3.6`,
   `gpt-oss:20b`) classify correctly locally.
3. **Structured-output enforcement helped reliability** but did not close the gap:
   even with `format=json` + retry, local tops at 96% completion and `gpt-oss`
   still failed 5/27.
4. **24 GB is not the limiter.** Every model ran on the card.
5. **Local marginal cost is trivial and measured.** 0.22–3.20 Wh/item ≈
   $0.00004–$0.0006/item at $0.20/kWh. The deciding cost is the $1,400 capital
   outlay, not energy.
6. **The local speed deficit is largely a load artifact.** Warm, the fast local
   models beat the cloud per item (`qwen2.5-coder:1.5b` 2.7 s/it, `qwen3:8b`
   8.3 s/it) — but the cloud finishes nearly every item and classifies it right,
   while the *accurate* local reasoners are the slowest (33–46 s/item).

## 6. Economic analysis — the $1,400 question

| Option | Up-front | Marginal / item | Reliability | Accuracy | Notes |
|---|---|---|---:|---:|---|
| Cursor plan (`composer-2.5-fast`) | $0 (plan) | **$0** | 100% | 76% | highest reliability, $0 |
| codex (ChatGPT plan) | $0 (plan) | $0 | 93% | ref | accuracy key |
| claude (Claude plan) | $0 (plan) | $0 | 96% | 54% | $0 marginal |
| RTX 3090 local (`gemma4:31b`) | **$1,400** | ~$0.0006 ¹ | 93% | 74% | best local accuracy; 45.7 s/item |
| RTX 3090 local (`qwen3:8b`) | **$1,400** | ~$0.0002 ¹ | 93% | 9% | fast/deep but mislabels |
| Paid API (untested) | $0 | per-token (~$0.8–$7 / run) | — | — | quality ceiling unmeasured |

¹ **Measured**: `gemma4:31b` 3.197 Wh/item, `qwen3:8b` 0.759 Wh/item; at $0.20/kWh.

**Columns / formulas**

- **Up-front** = one-time capital cost (the $1,400 card, or $0 for a plan you already hold).
- **Marginal / item** = incremental cost to process one more item: $0 on a plan; energy-only for local (Wh/item ÷ 1000 × $/kWh); per-token for a metered API.
- **Reliability / Accuracy** = completion% / accuracy% as defined in §3.3.

Against a **$0-marginal, higher-accuracy** plan you already pay for, the GPU never
pays back for this task. It only pencils out vs a **rented** cloud GPU at
sustained very high local volume, or where always-available private inference is
mandatory. (A full break-even table is in [SUMMARY.md](SUMMARY.md) §3.3.)

## 7. Recommendation

- **Quality + a plan exists:** `composer-2.5-fast` (100% completion, 76% accuracy,
  14.4 s/item, $0) or `codex` (100% accuracy key, 93% completion).
- **Keep-vs-return:** return for this workload **unless** privacy, volume, or
  amortisation applies.
- **If kept,** pick by the axis you weight — there is a real local trade-off:
  - **Correctness:** `gemma4:31b` (74% acc, 89% depth) or `qwen3.6:27b` (61%/88%),
    accepting 41–46 s/item and ~3.1–3.2 Wh/item.
  - **Speed / bulk first passes:** `qwen2.5-coder:1.5b` (2.7 warm s/it, 0.215
    Wh/item) — but treat its *classification* as unreliable (0% accuracy here).
  - **Balance:** `qwen3:8b` is fast and deep, but verify archetype/domain
    downstream (9% accuracy).

## 8. Open questions

Re-ordered so the questions that could still move the verdict come first. Several
earlier questions are now **resolved** (struck through).

1. ~~Is the local quality ordering a metric artifact?~~ **Resolved:** depth and
   accuracy are reported separately; on accuracy, big reasoners win locally (§3.5).
2. ~~How much of the completion gap closes with enforced structured output?~~
   **Resolved:** `format=json` + retry is in; local still tops at 96%, so the gap
   is real, not a parsing artifact.
3. ~~Depth vs correctness at scale.~~ **Partly resolved:** accuracy is now
   measured against `codex` over 27 items; still adjudicated against a cloud key,
   not a hand-checked gold set.
4. **Cloud completion <100% this run.** `codex` (25/27) and `claude` (26/27) each
   missed a couple of items, consistent with a transient CLI/network drop (a
   network disconnect was noted during the codex run). A clean re-run should
   confirm whether cloud returns to 27/27.
5. ~~Cursor rows are stale.~~ **Resolved:** `composer-2.5` (100/99/80) and
   `composer-2.5-fast` (100/99/76) were re-run on `cmp-0628`; all four cloud rows
   are now from one June-28 harness.
6. **`codex` is the accuracy key, not ground truth.** A hand-adjudicated 20–30
   item gold set would let cloud models (incl. codex) be scored independently.
7. **Small sample (n = 27), single run, no variance.** A 2–3 point gap between
   adjacent models is inside the noise.
8. **Single domain / single user.** All bundles are one Oct-2024 export.
9. **Free-tier cloud only.** `gpt-5`, `claude-sonnet-4`, etc. were not run, so the
   paid quality/cost ceiling is unmeasured.
10. **Privacy cost of the cloud option.** The pre-send scrubber (`--scrub-cloud`,
    NFR-P3) exists and gates cloud calls, but the depth/accuracy cost of redaction
    was not measured.

## 9. Next steps

Ordered by how much they sharpen the decision.

1. **Confirm cloud reliability (addresses §8.4):** re-run `codex`/`claude` to check
   the 25–26/27 completion was a transient drop, not a regression.
2. **Hand-adjudicate a gold set (addresses §8.6):** label 20–30 items by hand so
   every model — including `codex` — gets an independent accuracy score.
3. **Scale and repeat (addresses §8.7):** re-run the top candidates 3× and report
   mean ± spread to put error bars on the 2–3 point gaps.
4. **Measure the redaction cost (addresses §8.10):** run the cloud models with
   `--scrub-cloud` on and compare depth/accuracy to the un-redacted run.
5. **Add paid cloud baselines (addresses §8.9):** `gpt-5-mini`, `claude-haiku-4`
   to map the quality/cost frontier above the free tier.

## 10. Reproducibility

`$DATA_ROOT` is the data root (here `~/chatgpt-reconstructor-data`). All commands
are read-only except `gpt summarize` (writes only under its `--run-label`).

```bash
# 1. Build once (deterministic, no LLM) — reused by every model run.
./gpt run --zip "$GPT_ZIP_OCT2024"

# 2. Monitored sweep — 12 local models (power-metered) + codex + claude + the
#    two Cursor models. Per model: GPU preflight, 30 s health watch, $5 budget cap.
scripts/bench_sweep.sh cmp-0628 all

# 3. Read the numbers back (read-only) and regenerate the verdict file:
./gpt metrics perf    "$DATA_ROOT"/runs/cmp-0628-*/summarize_trace.jsonl
./gpt metrics quality "$DATA_ROOT"/runs/cmp-0628-*/reconstructed_projects.json \
  --correctness ref=cmp-0628-codex
./gpt gen-model-benchmarks --runs 'cmp-0628-*' --reference ref=cmp-0628-codex
```

**Artifacts (private; under `$DATA_ROOT`, gitignored):** per-run
`reconstructed_projects.json` + `summarize_trace.jsonl` + `power_trace.jsonl`;
driver log `benchmark_cmp-0628.log`; per-model logs `benchlogs_cmp-0628/`; GPU
health traces `health_cmp-0628/`.

> **Note on this revision.** The §4 table reports **completion, depth-on-success,
> accuracy, and measured Wh/item in separate columns** over the 27-bundle
> `oct2024` export from the `cmp-0628` sweep (2026-06-28), replacing the earlier
> `cmp-oct2` run (2026-06-26). **All 16 models — the 12 local models, both Cursor
> `composer-2.5*` models, `codex`, and `claude` — are fresh on this sweep.** The
> per-model verdicts in `config/generated/model_benchmarks.json` are regenerated
> from this metric via `gpt gen-model-benchmarks --runs 'cmp-0628-*' --reference
> ref=cmp-0628-codex` (alias: `gpt gen-model-notes`; FR-D2).
