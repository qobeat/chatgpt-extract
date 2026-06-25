# AI Model Tests — Is the RTX 3090 24 GB worth $1,400 for this workload?

**Verdict (one line):** For ADOS structured-extraction summarization, the
free, plan-covered cloud models finish every item and produce the fullest
records at **$0 marginal**, so the **$1,400 card is not justified on output
alone** — keep it only for privacy/offline, very high volume, or if it is
already amortised by other GPU work. **The local "quality" gap is mostly a
reliability gap, not a content gap** (see §3.5) — do not read it as "big models
are dumb."

| | |
|---|---|
| **Date** | 2026-06-25 |
| **Hardware under test** | NVIDIA GeForce RTX 3090, 24 GB (≈$1,400 used) |
| **Host** | WSL2 (Ubuntu) + Ollama; Cursor / ChatGPT via signed-in plan |
| **Task** | Classify + summarize project bundles into the ADOS ontology (`gpt summarize`) |
| **Sample** | First 10 clusters from `clusters.json` (identical bundles for every model) |
| **Context window** | `--num-ctx 16384` (held constant) |
| **Models** | 12 local Ollama generation models (GPU) + 1 CPU build + 2 free Cursor models, with `codex` as a cloud reference |
| **Raw data** | `$DATA_ROOT/runs/cmp-*/`, `benchmark_combined.json`, `benchmark_results.log`, `benchmark_cursor.log` |

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
> Cursor / ChatGPT plan?**

On the *same* work it must establish **quality** (completeness *and* correctness),
**speed**, **reliability** (does an item finish), and **cost**.

## 2. Executive verdict

**Hard to justify for this workload.** The two free Cursor models
(`composer-2.5`, `composer-2.5-fast`) and `codex` finished **10/10** items; the
best local model (`qwen3:8b`) finished **8/10**. Because the cloud models are
**$0 marginal on a plan you already have**, local inference does not buy better
*results* — it adds a $1,400 capital cost. **Every installed local model ran on
the 24 GB card**, so 24 GB is not the limiter; the GPU buys *local capability*,
not bigger models.

Keep the card only if **at least one** holds: (1) privacy/offline is
non-negotiable; (2) volume × rate-limits exceed the plan; (3) the GPU is already
amortised by other work. If kept, the local pick is **`qwen3:8b`** (quality) or
**`qwen2.5-coder:1.5b`** (speed). But see §3.5 before trusting the local
*quality* ordering.

## 3. Methodology — and how to read the metric

### 3.1 Test design (apples-to-apples)

The deterministic build (Extract → Cluster → Bundle, no LLM) was built **once**;
every model was pointed at the **same** bundles. `gpt summarize --limit 10`
selects the first 10 qualifying clusters (same filter, same on-disk order);
each model ran under its own `--run-label` (`cmp-*`) into an isolated output +
trace; `--num-ctx 16384` and the bundle set were held constant. Item 1 is the
235 KB `ados-profile` mega-bundle, so every model's reliability is tested on the
single hardest input.

### 3.2 Models under test

12 unique local generation models on the GPU (all installed Ollama generation
tags, embeddings excluded), the CPU-only build of `qwen2.5-coder:3b`, the two
free Cursor models, and `codex` as a cloud reference. Two installed tags are
byte-identical duplicates and were tested once (`qwen2.5-coder:latest`==`:7b`;
`qwen3.6:27b-q4_K_M`==`:27b`).

### 3.3 Metric definitions

- **`s/item`** = wall-seconds ÷ completed item (rank key for speed; lower faster).
- **`gen tok/s`** = output tokens ÷ wall-seconds.
- **`completion`** = `LLM_OK / attempted` (reliability). A failed item is still
  written with the deterministic prior and empty prose, so completion is the
  honest reliability signal.
- **`depth%`** = mean of four 0–100 fill axes (goal present, objective-set depth
  capped at 3, requirement-set depth capped at 3, archetype-field fill). It is a
  **completeness proxy, not correctness** (§3.4–3.5).

### 3.4 What `depth%` does NOT measure (read this)

`depth%` rewards a **fully filled** record. It does **not** check whether the
content is **right**. A model can fill every field *wrongly* and score 100%; a
model that writes one dense, correct objective instead of three scores low
because the axis counts entries (capped at 3), not quality. So `depth%` is best
read as *"did the model emit clean, fully-populated schema JSON,"* which is a
**coder-model strength**, not a general-intelligence measure.

### 3.5 Why this matters — completion and depth must be separated

**Two distortions inflate the apparent local-quality gap, both pushing larger
models down:**

1. **Failed items are scored as zero, not excluded.** A failed item is written
   with empty goal/objectives/requirements and an empty archetype-field set, and
   the quality table **includes it** (denominator = 10). Larger models fail more
   often, so each failure injects a 0 — **double-counting reliability inside the
   "quality" number.**
2. **Format adherence favours coder models.** Reasoning/instruct models
   (`qwen3.6`, `gpt-oss`, `gemma`) tend to wrap JSON in prose/markdown that the
   parser drops; the field coerces to the empty prior → low depth, independent of
   reasoning quality.

**Corrected view — depth on *successful* items only** (= `depth% × 10 ÷
completed`, recomputed from the published aggregates):

| rank | model | success-depth | params | finished |
|---:|---|---:|---:|---:|
| 1 | qwen3:8b | 92.5% | 8B | 8/10 |
| 2 | qwen3.6:27b | 90.0% | 27B | 6/10 |
| 3 | gemma4:31b | 90.0% | 31B | 5/10 |
| 4 | qwen3.6:35b | 83.3% | 35B | 6/10 |
| 5 | gpt-oss:20b | 82.9% | 20B | 7/10 |
| 6 | qwen2.5-coder:1.5b | 81.2% | 1.5B | 8/10 |

Mean success-depth: **big (≥20B) 86.5% vs mid (7–14B) 72.0%.** The "bigger is
worse" ordering **inverts** once reliability is removed from the quality number.

**Do not over-read this either:** success-depth is computed over *different,
fewer* items per model (the big models may have finished only the easier
bundles — survivorship bias), n = 10 with no repeats, and it is still depth, not
correctness. The defensible conclusion is: **report completion and
depth-on-success separately; never blend them into one rank key; the real
weakness of big local models on this box is reliability, not content.**

### 3.6 Fixes applied mid-test (result integrity)

| Problem | Fix |
|---|---|
| Weak models emit a bare string where the schema expects an object, crashing the run | `build_item` coerces malformed fields to the deterministic prior; regression tests added |
| `cursor-agent` blocked on an interactive "trust this directory?" prompt | Cursor provider passes `--trust` (headless) |
| `qwen2.5-coder:3b-cpu` ran ~5.5 min on item 1 | Killed and marked `skip` in the model bank |

## 4. Results

### 4.1 Master table (completion first, then depth — NOT blended)

| Model | Where | Completed | depth% (all 10, fail=0) | **success-depth** | s/item | gen tok/s | Marginal $ |
|---|---|---:|---:|---:|---:|---:|---|
| **composer-2.5-fast** | Cursor (free) | **10/10** | 100 | **100** | 16.9 | 67.1 | $0 (plan) |
| **composer-2.5** | Cursor (free) | **10/10** | 100 | **100** | 42.9 | 26.2 | $0 (plan) |
| _codex (ref)_ | ChatGPT (free) | _184/184_ | _100_ | _100_ | _26.1_ | _40.9_ | _$0 (plan)_ |
| qwen3:8b | RTX 3090 | 8/10 | 74 | 92.5 | 9.8 | 49.8 | $0 local |
| qwen3.6:27b | RTX 3090 | 6/10 | 54 | 90.0 | 25.9 | 24.0 | $0 local |
| gemma4:31b | RTX 3090 | 5/10 | 45 | 90.0 | 31.1 | 19.1 | $0 local |
| qwen3.6:35b | RTX 3090 ¹ | 6/10 | 50 | 83.3 | 9.8 | 57.4 | $0 local |
| gpt-oss:20b | RTX 3090 | 7/10 | 58 | 82.9 | 16.8 | 26.0 | $0 local |
| qwen2.5-coder:1.5b | RTX 3090 | 8/10 | 65 | 81.2 | **4.3** | **123.1** | $0 local |
| qwen2.5-coder:14b | RTX 3090 | 8/10 | 59 | 73.8 | 14.4 | 29.2 | $0 local |
| qwen2.5vl:7b | RTX 3090 | 8/10 | 56 | 70.0 | 7.3 | 60.7 | $0 local |
| qwen2.5-coder:7b | RTX 3090 | 8/10 | 53 | 66.2 | 7.1 | 56.5 | $0 local |
| llama3.1:8b | RTX 3090 | 8/10 | 46 | 57.5 | 7.8 | 46.6 | $0 local |
| qwen2.5-coder:3b | RTX 3090 | 8/10 | 44 | 55.0 | 4.5 | 78.9 | $0 local |
| gemma3:1b | RTX 3090 | 7/10 | 8 | 11.4 | 2.6 | 78.0 | $0 local |
| qwen2.5-coder:3b-cpu | CPU only | killed | — | — | ~330 ² | — | skipped |

¹ `qwen3.6:35b` loaded at **24.0 GB of 24.6 GB** — fits only at the edge with 16k
ctx. ² CPU build ~5.5 min on item 1 (~130× the GPU).

### 4.2 The two numbers tell different stories

- **Reliability (completion):** cloud 100% · best local 80% · big local 50–70%.
  This is the real, defensible local-vs-cloud gap.
- **Content depth on success:** cloud 100% · local 55–92%, and **not monotone in
  size** — once failures are excluded, the size penalty largely disappears (§3.5).

### 4.3 VRAM fit (does 24 GB constrain the choice?)

Everything up to `qwen2.5-coder:14b` (8.4 GB) fits comfortably; `gpt-oss:20b`,
`qwen3.6:27b`, `gemma4:31b` (~17–20 GB) fit; `qwen3.6:35b` fits only at the edge
(24.0/24.6 GB at 16k ctx). **Every installed model ran on the GPU**; the only
hard failure was the CPU build. **24 GB is not the binding constraint.**

## 5. Findings

1. **Cloud free models win on reliability.** 10/10 vs best-local 8/10. This —
   not raw depth — is the honest gap, and it is decisive for an unattended run.
2. **"Bigger local = worse quality" is mostly an artifact.** Once failed items
   are excluded, big models are competitive-to-better on depth (§3.5). The
   problem is **completion**, which is largely a **harness** issue (no
   structured-output enforcement), not a model-IQ issue.
3. **24 GB is not the limiter.** Every model ran; only the CPU build failed.
4. **Local's real edge is $0-marginal speed when "good enough" is OK.**
   `qwen2.5-coder:1.5b` = 4.3 s/item at 123 gen tok/s, 8/10 — ideal for cheap,
   private, high-volume first passes.
5. **Local reliability is the quiet tax** — and the silent fallback to the
   deterministic prior hides it inside the catalog unless completion is read.

## 6. Economic analysis — the $1,400 question

| Option | Up-front | Marginal / item | Reliability | Notes |
|---|---|---|---:|---|
| Cursor free (`composer-2.5-fast`) | $0 (plan) | **$0** | 100% | highest reliability, $0 |
| codex (ChatGPT plan) | $0 (plan) | $0 | 100% | reference |
| RTX 3090 local (`qwen3:8b`) | **$1,400** | ~$0.0002 ¹ | 80% | privacy/offline; $0 at margin |
| Paid API (untested) | $0 | per-token (~$0.8–$7 / run) | — | quality ceiling unmeasured |

¹ ≈350 W at ~10 s/item ≈ 0.001 kWh ≈ $0.0002/item at $0.20/kWh.

Against a **$0-marginal, higher-reliability** plan you already pay for, the GPU
never pays back for this task. It only pencils out vs a **rented** cloud GPU
(~$0.30/GPU-hr → ~4,600 GPU-hours ≈ ~2 M items to break even) — i.e. only at
sustained very high local volume or for always-available private inference.

## 7. Recommendation

- **Quality + a plan exists:** `composer-2.5-fast` (100% completion, 16.9 s/item,
  $0) or `codex`.
- **Keep-vs-return:** return for this workload **unless** privacy, volume, or
  amortisation applies.
- **If kept:** `qwen3:8b` for quality-sensitive work, `qwen2.5-coder:1.5b` for
  fast private bulk first passes. **Before** standardising on a *small* model for
  quality reasons, do §8.1 + §9.1 — the small-model quality edge may be a metric
  artifact.

## 8. Open questions

Each maps to a Next Step in §9. Re-ordered so the metric-validity questions —
the ones that could change the verdict — come first.

1. **Is the local quality ordering real or a metric artifact?** `depth%` blends
   reliability (fail=0) and rewards fill over correctness; on success-only depth
   the size penalty inverts (§3.5). Until completion and correctness are measured
   separately, **no local model-quality ranking is trustworthy.** *(highest
   priority — it gates Findings 2 and the "standardise on qwen3:8b/1.5b" advice.)*
2. **How much of the completion gap closes with enforced structured output?** No
   JSON grammar / `format=json` / retry-on-parse-fail was used; parse misses were
   counted as model failures. This is the single most likely confound in the
   whole test.
3. **Depth vs correctness at scale.** Correctness was spot-checked once
   (README example), never measured. A model can score 100% depth with wrong
   content.
4. **Small sample (n = 10), single run, no variance.** A 2–3 point gap between
   adjacent models is inside the noise; the verdict is stated more strongly than
   n = 10 supports.
5. **Single domain / single user.** All bundles are one June-2026 export; results
   may not generalise to code-heavy or prose-heavy corpora.
6. **Free-tier cloud only.** `gpt-5`, `claude-sonnet-4`, etc. were not run, so the
   paid quality/cost ceiling is unmeasured.
7. **Privacy cost of the cloud option is unpriced.** Cloud runs send raw,
   un-redacted transcripts off-machine — a real cost the $-table ignores.
8. **`num_ctx` fixed at 16k; cloud cost is a `chars/4` estimate; electricity is
   estimated, not metered; one GPU only.** All limit the precision of the
   economics but not the direction.

## 9. Next steps

Ordered by how much they sharpen the decision. Each is a concrete, runnable task;
they are the seed of `PLAN_PHASE2.md` (Benchmark) and `PLAN_PHASE3.md` (Decision).

1. **Make the metric trustworthy before re-ranking** *(addresses §8.1–8.3)*.
   In `metrics.py quality`: (a) split output into **completion%**, **depth-on-
   success%** (failures excluded), and report them in separate columns — never
   one blended rank key; (b) add a **schema-valid-JSON rate** column so a parse
   miss is distinguishable from a thin-but-valid record; (c) add a `--correctness`
   path that uses `gpt compare` against `codex` to surface archetype/domain
   disagreements, adjudicate a 20–30 item sample against the source bundles, and
   report **accuracy%** beside depth%.
2. **Enforce structured output, then re-run the top candidates** *(addresses
   §8.2)*. Add Ollama `format=json` (or a GBNF grammar) and **retry-on-parse-
   failure** in the Ollama provider; re-run `qwen3:8b`, `qwen3.6:27b`,
   `gpt-oss:20b`, `qwen2.5-coder:1.5b`, `composer-2.5-fast`, `codex`. Expectation:
   local completion rises toward 100% and the local-vs-cloud gap narrows to its
   true size.
3. **Scale and repeat** *(addresses §8.4)*. Re-run the top 4 at `--limit 50` (or
   all 181), **3× each**, report mean ± spread.
4. **Meter real power and cost** *(addresses §8.8)*. Log
   `nvidia-smi --query-gpu=power.draw` during a full run → true Wh/item and
   $/1,000 items; express $1,400 as a break-even in months vs a rented GPU.
5. **Add paid cloud baselines** *(addresses §8.6)*. Run `gpt-5-mini` and
   `claude-haiku-4` to map the quality/cost frontier above the free tier.
6. **Price the privacy option** *(addresses §8.7)*. Implement the pre-send
   scrubber (REQUIREMENTS NFR-P3) so the cloud path can be run on redacted
   bundles, and record what redaction costs in depth/correctness.
7. **Sweep `num_ctx` and bundle size; broaden the corpus; characterise sustained
   load** *(addresses §8.5, §8.8)*. 8k/16k/32k, larger `--max-chars`, a
   code-heavy and a prose-heavy export, and a full 181-item run logging
   throughput + thermals.

## 10. Reproducibility

`$DATA_ROOT` is the data root (here `~/chatgpt-reconstructor-data`). All commands
are read-only except `gpt summarize` (writes only under its `--run-label`).

```bash
# 0. Build once (deterministic, no LLM) — reused by every model run.
./gpt run --zip "$GPT_ZIP3"

# 1. Same 10 slugs, same context, isolated per model:
SHARED="--limit 10 --noask --num-ctx 16384 \
  --store $DATA_ROOT/store --bundles $DATA_ROOT/bundles"
./gpt summarize $SHARED --run-label cmp-qwen3-8b        --model qwen3:8b
./gpt summarize $SHARED --run-label cmp-cursor-fast --provider cursor --model composer-2.5-fast
# …one per model; see `./gpt summarize --list-models`…

# 2. Read the numbers back (read-only):
./gpt metrics perf    "$DATA_ROOT"/runs/cmp-*/summarize_trace.jsonl
./gpt metrics quality "$DATA_ROOT"/runs/cmp-*/reconstructed_projects.json
./gpt arena
```

**Artifacts (private; under `$DATA_ROOT`, gitignored):** per-run
`reconstructed_projects.json` + `summarize_trace.jsonl`; driver logs
`benchmark_results.log` / `benchmark_cursor.log`; joined `benchmark_combined.json`.

> **Note on this revision.** The §4 table now reports **completion and
> depth-on-success in separate columns** rather than a single blended `quality%`,
> and §3.5/§8.1 explain why the previous single-number ranking made larger models
> look worse than they are. The per-model verdicts in `config/models.json` should
> be regenerated after Next Step 1–2.
