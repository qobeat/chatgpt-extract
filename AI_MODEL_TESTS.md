# AI Model Tests — Is the RTX 3090 24 GB worth $1,400 for this workload?

**Verdict (one line):** For ADOS structured-extraction summarization, the
free, plan-covered cloud models finish every item, classify it correctly, and
cost **$0 marginal** on a plan you already have, so the **$1,400 card is not
justified on output alone** — keep it only for privacy/offline, very high volume,
or if it is already amortised by other GPU work. With **accuracy now measured**
(not just field-fill), the local gap is a **reliability *and* correctness** gap:
most local models emit clean schema JSON with the **wrong** archetype/domain, and
only the big reasoning models (`gemma4:31b`, `qwen3.6`) classify well — and they
are the slowest, heaviest ones (§3.5, §5).

| | |
|---|---|
| **Date** | 2026-06-26 |
| **Hardware under test** | NVIDIA GeForce RTX 3090, 24 GB (≈$1,400 used) |
| **Host** | WSL2 (Ubuntu) + Ollama; Cursor / ChatGPT / Claude via signed-in plan |
| **Task** | Classify + summarize project bundles into the ADOS ontology (`gpt summarize`) |
| **Sample** | All 27 project bundles from the `oct2024` export (identical bundles for every model) |
| **Context window** | `--num-ctx 16384` (held constant) |
| **Models** | 12 local Ollama generation models (GPU) + 2 free Cursor models + `codex` + `claude` |
| **Metrics** | completion · depth-on-success · **accuracy vs `codex`** · schema-valid · s/item (load-separated) · **measured Wh/item** |
| **Raw data** | `$DATA_ROOT/runs/cmp-oct2-*/`, `benchmark_cmp-oct2.log`, `benchmark_cmp-oct2_power.log` |

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
> enough to justify $1,400, versus the free cloud models already included in a
> Cursor / ChatGPT / Claude plan?**

On the *same* work it must establish **quality** (completeness *and* correctness),
**speed**, **reliability** (does an item finish), and **cost** (now with measured
GPU power, not an estimate).

## 2. Executive verdict

**Hard to justify for this workload.** The plan-covered cloud models
(`codex`, `composer-2.5`, `composer-2.5-fast`, `claude`) finished **27/27** items;
the best local model (`llama3.1:8b`) finished 26/27 and the rest ≤25/27. More
decisively, with **accuracy now adjudicated against `codex`**, the cloud models
classify correctly (composer 81%, claude 59%) while **most local models score
near-zero accuracy** despite clean JSON — they fill the schema with the wrong
archetype/domain. Only the big local reasoners classify well (`gemma4:31b` 68%,
`qwen3.6:35b` 64%, `qwen3.6:27b` 60%), and those are the slowest (30–39 s/item)
and most power-hungry (2.4–2.9 Wh/item).

Because the cloud models are **$0 marginal on a plan you already have**, local
inference does not buy better *results* — it adds a $1,400 capital cost. **Every
installed local model ran on the 24 GB card**, so 24 GB is not the limiter; the
GPU buys *local capability*, not bigger models. Marginal electricity is
negligible (**measured** 0.24–2.91 Wh/item ≈ $0.00005–$0.0006/item), so the
decision turns entirely on the $1,400 capital cost.

Keep the card only if **at least one** holds: (1) privacy/offline is
non-negotiable; (2) volume × rate-limits exceed the plan; (3) the GPU is already
amortised by other work. If kept, the local pick depends on the axis you weight —
see §7.

## 3. Methodology — and how to read the metric

### 3.1 Test design (apples-to-apples)

The deterministic build (Extract → Cluster → Bundle, no LLM) was built **once**
from the `oct2024` export; every model was pointed at the **same** 27 bundles.
Each model ran under its own `--run-label` (`cmp-oct2-*`) into an isolated output
+ trace; `--num-ctx 16384` and the bundle set were held constant. The 12 local
models were then re-run with `--meter-power` to record **measured** GPU
watt-hours per item.

### 3.2 Models under test

12 local generation models on the GPU (all installed Ollama generation tags,
embeddings excluded), the two free Cursor models, `codex`, and `claude`. The
CPU-only build of `qwen2.5-coder:3b` remains `skip` in the model bank (unusably
slow).

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
`qwen3:8b` fills 85% of the schema but only **16%** of its classifications match
the reference; the `qwen2.5-coder` family is near-0% accuracy with 93% clean JSON.
So `depth%` reads as *"did the model emit clean, fully-populated schema JSON"* — a
coder-model strength — while **`accuracy%` is the axis that tracks whether the
model understood the work.**

### 3.5 Why this matters — completion, depth, and accuracy are three different things

The earlier 10-item run blended reliability into a single "quality%", which made
larger models look worse. This run separates all three axes and adds accuracy,
which resolves the question:

1. **Failed items are excluded, not scored 0** (closing the old artifact): depth
   and accuracy are computed over completed items only; completion is reported
   beside them.
2. **On depth, size is roughly flat** once failures are excluded (big 79–90%,
   mid 56–72%) — the old "bigger is worse" ordering does not hold.
3. **On accuracy, size clearly *wins* locally.** The only local models that
   classify correctly are the big reasoners (`gemma4:31b` 68%, `qwen3.6:35b` 64%,
   `qwen3.6:27b` 60%, `gpt-oss:20b` 57%); the small/coder models fill fields but
   mislabel (≤20%). So the defensible conclusion is: **report completion, depth,
   and accuracy separately; never blend them; the real weakness of *small* local
   models is correctness, and of *big* local models is reliability+speed.**

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
| A reboot restarted `ollama.service` in CPU-only mode (no GPU), invalidating power | Detect via `ollama ps` = `100% CPU` / ≈2.4 tok/s; `sudo systemctl restart ollama` re-attaches the RTX 3090 |

## 4. Results

### 4.1 Master table (four separated axes — NOT blended)

| Model | Where | compl% | depth* | **acc%** | json% | s/item | warm s/it | gen tok/s | **Wh/item** | Marginal $ |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| **codex** | ChatGPT (free) | **100** | 99 | **100** ¹ | 100 | 15.2 | — | 49.3 | — | $0 (plan) |
| **composer-2.5** | Cursor (free) | **100** | 99 | 81 | 100 | 18.7 | — | 46.0 | — | $0 (plan) |
| **claude** | Claude (free) | **100** | 98 | 59 | 100 | 24.5 | — | 34.0 | — | $0 (plan) |
| **composer-2.5-fast** | Cursor (free) | **100** | 98 | 81 | 100 | 12.7 | — | 64.4 | — | $0 (plan) |
| llama3.1:8b | RTX 3090 | 96 | 59 | 0 | 96 | 7.3 | 5.3 | 44.5 | 0.540 | $0 local |
| gemma4:31b | RTX 3090 | 93 | 90 | **68** | 93 | 39.0 | 30.8 | 14.6 | 2.912 | $0 local |
| qwen3.6:27b | RTX 3090 | 93 | 88 | 60 | 93 | 29.7 | 22.3 | 19.8 | 2.360 | $0 local |
| qwen3:8b | RTX 3090 | 93 | 85 | 16 | 93 | 8.8 | 6.8 | 49.7 | 0.696 | $0 local |
| qwen3.6:35b | RTX 3090 ² | 93 | 79 | 64 | 93 | 20.3 | 10.8 | 27.3 | 1.086 | $0 local |
| qwen2.5-coder:7b | RTX 3090 | 93 | 72 | 4 | 93 | 7.6 | 5.7 | 53.9 | 0.614 | $0 local |
| qwen2.5-coder:1.5b | RTX 3090 | 93 | 67 | 0 | 93 | **3.5** | **3.0** | **120.7** | **0.252** | $0 local |
| qwen2.5vl:7b | RTX 3090 | 93 | 67 | 16 | 93 | 7.6 | 5.4 | 50.4 | 0.577 | $0 local |
| qwen2.5-coder:14b | RTX 3090 | 93 | 65 | 20 | 93 | 14.1 | 10.2 | 27.7 | 1.059 | $0 local |
| qwen2.5-coder:3b | RTX 3090 | 93 | 56 | 8 | 93 | 4.5 | 3.6 | 81.9 | 0.378 | $0 local |
| gemma3:1b | RTX 3090 | 89 | 21 | 0 | 7 | 3.6 | 2.4 | 79.9 | 0.239 | $0 local |
| gpt-oss:20b | RTX 3090 | 85 | 78 | 57 | 85 | 22.0 | 16.3 | 21.1 | 1.856 | $0 local |

¹ `codex` is the accuracy reference, so its 100% is by construction. ² `qwen3.6:35b`
loads ~23 GB — fits only near the VRAM edge at 16k ctx.

### 4.2 The numbers tell three different stories

- **Reliability (completion):** cloud 100% · best local 96% (llama3.1) · most
  local 93% · `gpt-oss` 85%. The real, defensible local-vs-cloud reliability gap.
- **Depth on success:** cloud 98–99% · local 21–90%, roughly flat in size once
  failures are excluded.
- **Accuracy:** cloud 59–81% (codex = key) · local **0–68%**, and **monotone in
  reasoning capability** — the big reasoners classify, the small coders do not.

### 4.3 VRAM fit (does 24 GB constrain the choice?)

Everything up to `qwen2.5-coder:14b` fits comfortably; `gpt-oss:20b`,
`qwen3.6:27b`, `gemma4:31b` (~17–20 GB) fit; `qwen3.6:35b` fits only near the edge
(~23 GB at 16k ctx). **Every installed model ran on the GPU.** **24 GB is not the
binding constraint.**

## 5. Findings

1. **Cloud free models win on reliability *and* accuracy.** 27/27 completion and
   59–81% accuracy vs best-local 26/27 and ≤68% accuracy (most local far lower).
   This is the honest, decisive gap for an unattended run.
2. **Accuracy and depth are different axes.** `qwen3:8b` is high-depth (85%) but
   low-accuracy (16%); the coder family is high-JSON but near-0 accuracy. **Field
   fill ≠ understanding.** Only big reasoners (`gemma4:31b`, `qwen3.6`) classify
   correctly locally.
3. **Structured-output enforcement helped reliability** but did not close the gap:
   even with `format=json` + retry, local tops out at 96% completion and
   `gpt-oss` still failed 4/27.
4. **24 GB is not the limiter.** Every model ran on the card.
5. **Local marginal cost is trivial and now measured.** 0.24–2.91 Wh/item ≈
   $0.00005–$0.0006/item at $0.20/kWh. The deciding cost is the $1,400 capital
   outlay, not energy.
6. **The local speed deficit is largely a load artifact.** Warm, the fast local
   models beat the cloud per item (`qwen2.5-coder:1.5b` 3.0 s/it, `qwen3:8b`
   6.8 s/it) — but the cloud finishes every item and classifies it right.

## 6. Economic analysis — the $1,400 question

| Option | Up-front | Marginal / item | Reliability | Accuracy | Notes |
|---|---|---|---:|---:|---|
| Cursor free (`composer-2.5-fast`) | $0 (plan) | **$0** | 100% | 81% | highest reliability, $0 |
| codex (ChatGPT plan) | $0 (plan) | $0 | 100% | ref | accuracy key |
| claude (Claude plan) | $0 (plan) | $0 | 100% | 59% | $0 marginal |
| RTX 3090 local (`gemma4:31b`) | **$1,400** | ~$0.0006 ¹ | 93% | 68% | best local accuracy; 39 s/item |
| RTX 3090 local (`qwen3:8b`) | **$1,400** | ~$0.0001 ¹ | 93% | 16% | fast/deep but mislabels |
| Paid API (untested) | $0 | per-token (~$0.8–$7 / run) | — | — | quality ceiling unmeasured |

¹ **Measured**: `gemma4:31b` 2.912 Wh/item, `qwen3:8b` 0.696 Wh/item; at $0.20/kWh.

Against a **$0-marginal, higher-reliability, higher-accuracy** plan you already
pay for, the GPU never pays back for this task. It only pencils out vs a
**rented** cloud GPU at sustained very high local volume, or where
always-available private inference is mandatory.

## 7. Recommendation

- **Quality + a plan exists:** `composer-2.5-fast` (100% completion, 81% accuracy,
  12.7 s/item, $0) or `codex`.
- **Keep-vs-return:** return for this workload **unless** privacy, volume, or
  amortisation applies.
- **If kept,** pick by the axis you weight — there is a real local trade-off:
  - **Correctness:** `gemma4:31b` (68% acc, 90% depth) or `qwen3.6:27b` (60%/88%),
    accepting 30–39 s/item and ~2.4–2.9 Wh/item.
  - **Speed / bulk first passes:** `qwen2.5-coder:1.5b` (3.0 warm s/it, 0.25
    Wh/item) — but treat its *classification* as unreliable (0% accuracy here).
  - **Balance:** `qwen3:8b` is fast and deep, but verify archetype/domain
    downstream (16% accuracy).

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
4. **`codex` is the accuracy key, not ground truth.** A hand-adjudicated 20–30
   item gold set would let cloud models (incl. codex) be scored independently.
5. **Small sample (n = 27), single run, no variance.** A 2–3 point gap between
   adjacent models is inside the noise.
6. **Single domain / single user.** All bundles are one Oct-2024 export.
7. **Free-tier cloud only.** `gpt-5`, `claude-sonnet-4`, etc. were not run, so the
   paid quality/cost ceiling is unmeasured.
8. **Privacy cost of the cloud option.** The pre-send scrubber (`--scrub-cloud`,
   NFR-P3) exists and gates cloud calls, but the depth/accuracy cost of redaction
   was not measured.

## 9. Next steps

Ordered by how much they sharpen the decision.

1. **Hand-adjudicate a gold set (addresses §8.4):** label 20–30 items by hand so
   every model — including `codex` — gets an independent accuracy score.
2. **Scale and repeat (addresses §8.5):** re-run the top candidates 3× and report
   mean ± spread to put error bars on the 2–3 point gaps.
3. **Measure the redaction cost (addresses §8.8):** run the cloud models with
   `--scrub-cloud` on and compare depth/accuracy to the un-redacted run.
4. **Add paid cloud baselines (addresses §8.7):** `gpt-5-mini`, `claude-haiku-4`
   to map the quality/cost frontier above the free tier.
5. **Broaden the corpus (addresses §8.6):** a code-heavy and a prose-heavy export
   to test whether the accuracy ordering generalises.

## 10. Reproducibility

`$DATA_ROOT` is the data root (here `~/chatgpt-reconstructor-data`). All commands
are read-only except `gpt summarize` (writes only under its `--run-label`).

```bash
# 1. Build once (deterministic, no LLM) — reused by every model run.
./gpt run --zip "$GPT_ZIP_OCT2024"

# 2. Main sweep (all 16 models) + power-metered re-run of the 12 local models:
bash "$DATA_ROOT"/bench_oct2024.sh       cmp-oct2
bash "$DATA_ROOT"/bench_oct2024_power.sh cmp-oct2

# 3. Read the numbers back (read-only):
./gpt metrics perf    "$DATA_ROOT"/runs/cmp-oct2-*/summarize_trace.jsonl
./gpt metrics quality "$DATA_ROOT"/runs/cmp-oct2-*/reconstructed_projects.json \
  --correctness ref=cmp-oct2-codex
python scripts/gen_model_notes.py --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex
```

**Artifacts (private; under `$DATA_ROOT`, gitignored):** per-run
`reconstructed_projects.json` + `summarize_trace.jsonl` + `power_trace.jsonl`;
driver logs `benchmark_cmp-oct2.log` / `benchmark_cmp-oct2_power.log`. A
detailed companion write-up lives in `docs/benchmark-oct2024.md`.

> **Note on this revision.** The §4 table now reports **completion,
> depth-on-success, accuracy, and measured Wh/item in separate columns** over the
> 27-bundle `oct2024` export, replacing the earlier 10-item run. The per-model
> verdicts in `config/models.json` are regenerated from this metric via
> `gpt gen-model-notes --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex` (FR-D2).
