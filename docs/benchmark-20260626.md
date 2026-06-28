# Benchmark — jun2026 export (2026-06-26), tests + build perf + codex vs gemma4:31b

**Date run:** 2026-06-27 · **Export:** `…-2026-06-26-….zip` (1.49 GB, 4,178
conversations) · **Workload:** 173 project bundles (the same set for every model)
· **Hardware:** Dell 5820 / RTX 3090 24 GB / WSL2 Ubuntu · **venv:** Python
3.12.3, ijson 3.5.0, pytest 9.1.1.

This session ran, in order: (1) the full test suite, (2) a timed deterministic
build (Extract → Cluster → Classify → Bundle) on the new export, (3) an
investigation of how Ollama places models on the GPU, and (4) a two-model Stage-4
sweep — `codex` (cloud, ChatGPT plan) and `gemma4:31b` (local, power-metered) —
each isolated under its own `--run-label`, reading the **same** bundles (FR-B1).

All raw artifacts live under `$DATA_ROOT` (gitignored); paths below are
run-label-relative.

---

## 1. Test suite — PASS

```
python -m pytest -q  →  223 passed, 18 subtests passed in 3.24s
```

Covers schema round-trip, secrets hook, redaction, provider detection, the zip
ledger/verify, slug parsing, cost, the corrected metric, and the sanitiser
(NFR-Q1).

---

## 2. Deterministic build performance (`run-label perf-20260626`)

Isolated full extract of all 4,178 chats from the 1.49 GB export. Stage timings
from `.run_manifest.json`; wall/peak-RSS from `/usr/bin/time -v`.

| Stage | Time | Output |
|---|---:|---|
| extract | 35.31 s | 4,178 cards (ijson stream) — added 4,178, **0 skipped, 0 errors** |
| cluster | 0.37 s | 3,641 clusters (merge-cap guard split generic slugs) |
| classify | 0.39 s | `classify_prior` on all 3,641 clusters |
| bundle | 0.41 s | 173 project bundles, ~1,212,786 tokens total |
| **wall (build)** | **36.78 s** | peak RSS **92.5 MiB**, 90% CPU |

Derived (extraction dominates, 96% of wall):

- **~42 MB/s** (~118 chats/s) streaming a 1.49 GB zip.
- **~3.5× faster** than the tool's own conservative 90 s/GB estimate (predicted
  ~134 s; actual 35 s extract).
- Memory: 92.5 MiB peak vs 1.49 GB input → confirms bounded-memory streaming
  (NFR-R1); no full-file load.
- Lossless: 0 skipped / 0 errors → 100% item coverage (O1 / FR-C1).

Outputs verified consistent: `index.json` 4,178 · `cards.jsonl` 4,178 ·
`clusters.json` 3,641 · 173 `.md` bundles · store 106 MB, bundles 5.2 MB.

---

## 3. How Ollama runs models — GPU placement investigation

The Ollama provider (`scripts/lib/providers/ollama_provider.py`) posts to
`/api/chat` with `format=json`, `keep_alive=24h`, `temperature=0.1`,
`num_predict=1500`, and `num_ctx` — and **never sets `num_gpu`**. GPU placement is
therefore **Ollama's automatic offload decision**, driven by model weights +
KV-cache size (a function of `num_ctx`) vs the 24 GB ceiling.

**Live evidence for `gemma4:31b` at `--num-ctx 16384`:**

| Signal | Value | Meaning |
|---|---|---|
| `ollama ps` PROCESSOR | **100% GPU** | fully on-card, no CPU spill |
| VRAM used | 23.5 / 24.6 GiB | fits at 16k ctx, ~1 GB headroom |
| GPU util / power | up to 91% / 339 W | actively generating on GPU |
| trace `load_ms` | ~500 ms (warm) | `keep_alive` keeps it resident; load paid once |
| trace `eval_ms` | 15–25 s | pure GPU generation per item |

**24 GB fit (derived from disk size + the live gemma placement; not yet probed
per-model):**

| Model | Weights | 100% GPU? | Note |
|---|---:|---|---|
| `qwen3.6:35b` | 23 GB | ❌ unlikely | weights ≈ full card; KV cache must spill → explains its "slowest" rank |
| `gemma4:31b` | 19 GB | ✅ at 16k ctx (proven) · ⚠️ risky at 32k | what ran here |
| `qwen3.6:27b` | 17 GB | ✅ likely ≤16k ctx | ~7 GB headroom |
| `gpt-oss:20b` | 13 GB | ✅ even at its 32k bank ctx | comfortable |
| ≤14b family | ≤9 GB | ✅ easily | — |

**Finding:** "every model runs on the card" ≠ "every model runs 100% on GPU". 24 GB
**is** the binding constraint for `qwen3.6:35b`, and for gemma/27b if `num_ctx`
grows. Also: `gemma4:31b` has **no `num_ctx` in the model bank**, so a bare
`gpt summarize --model gemma4:31b` falls back to the config default `num_ctx=32768`,
which roughly doubles the KV cache and would likely push it past 24 GB → partial
CPU spill. Recommend adding a `num_ctx: 16384` bank entry for `gemma4:31b`.

### Requirements compliance (Ollama path)

| Req | Status | Evidence / caveat |
|---|---|---|
| FR-B4 structured output + bounded retry | ✅ | `format=json` set; parse-miss re-request (`--max-parse-retries`) |
| FR-B6 GPU power → Wh/item | ✅ | `power.py` integrates `nvidia-smi power.draw`; this run wrote `power_trace.jsonl` (6,291 samples) |
| FR-B5 honest failure recording | ✅ | 9 gemma failures kept as `llm_ok:false` (deterministic-prior fallback), not hidden |
| NFR-P3 local stays offline | ✅ | Ollama run has no scrubber and makes no off-machine call |
| NFR-R2 kill model that spills/hangs | ⚠️ partial | `--timeout` (300 s) is a socket timeout in `_post_json` and **retries up to 4×** on `TimeoutError`, so a CPU-spilled item can burn ~4×300 s before failing rather than one clean kill. Current mitigation is manual (`:3b-cpu` is `skip:true`). |

---

## 4. Stage-4 sweep — codex vs gemma4:31b (173 shared bundles)

Each axis reported separately; never blended (FR-B2). `compl%` = LLM_OK / 173.
`depth*` = mean fill over **completed** items only. `acc%` = archetype/domain
agreement vs the `codex` reference. `Wh/item` = **measured** GPU energy
(local only). `$/1k` = measured cloud cost per 1,000 items.

| model | where | compl% | depth* | json% | arch-agree | dom-agree | s/item | warm s/it | gen tok/s | **Wh/item** | $/1k |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| codex | cloud (ChatGPT plan) | **100%** (173/173) | 99% | 100% | ref | ref | 25.6 | — | 38.0 | — | $0 (plan) |
| `gemma4:31b` | RTX 3090 local | **95%** (164/173) | 96% | 95% | 80% | 76% | 38.4 | 37.9 | 20.1 | **3.503** | $0 local |

- **codex** (`run-label perf-20260626`, `--scrub-cloud`): scrubber redacted **435
  PII matches across 173 bundles before any cloud call** (NFR-P3). Wall ~78.9 min.
- **gemma4:31b** (`run-label perf-gemma4-20260626`, `--num-ctx 16384`,
  `--meter-power`): wall ~111 min; **574.5 Wh** total over 111.3 min →
  **3.503 Wh/item** (≈$0.0007/item at $0.20/kWh). 100% on GPU throughout.
- **Agreement:** 80% primary-archetype, 76% primary-domain vs codex over 173
  comparable; 35 archetype disagreements (gemma tends to over-assign
  `software_app`/`automation_or_diagnostic_script` where codex picks more specific
  archetypes like `controlled_spec_or_schema`, `ai_agent_prompt`, `advisory_*`).
  Full slug-level disagreement table: `$DATA_ROOT/comparisons/codex-vs-ollama.md`.

### Failures and recovery

| run | failures | kind | action |
|---|---|---|---|
| codex | 1 (`…-music-generator`, a ~3 KB bundle) | transient `timed out after 300s` (≈20 min in, **before** a brief network drop) | **backfilled**: dropped the `llm_ok:false` item, re-ran `--resume` → re-summarized only that slug → **173/173, 0 failed**. Backup kept at `reconstructed_projects.json.bak-prebackfill`. |
| gemma4:31b | 9 | `non-JSON response after retries` — genuine model-capability misses (incl. the ~338 KB mega-bundle that exceeds a local context window) | **kept as honest failures** (FR-B5). Not backfilled: re-running would reproduce them and dishonestly inflate completion%. |

**Network-disconnect note.** A user-reported network drop during the codex run did
**not** corrupt it: the run advanced through the window with no failure cluster,
the lone failure predated the drop, and the shared HTTP layer retries transient
`URLError`/`TimeoutError` with exponential backoff. Per-item persistence
(`reconstructed_projects.json` rewritten after every item) plus `--resume` make the
pipeline resumable without re-spend (NFR-R3).

---

## 5. Reproduce

```bash
# (1) tests
python -m pytest -q

# (2) timed deterministic build (isolated; does not touch the main catalog)
/usr/bin/time -v ./gpt run --zip "<2026-06-26 export>.zip" --run-label perf-20260626 --noask

# (4) Stage-4 sweep — same bundles, separate labels
./gpt summarize --provider codex --run-label perf-20260626 --scrub-cloud --noask
./gpt summarize --provider ollama --model gemma4:31b --num-ctx 16384 --meter-power --noask \
  --store  "$DATA_ROOT/runs/perf-20260626/store" \
  --bundles "$DATA_ROOT/runs/perf-20260626/bundles" \
  --run-label perf-gemma4-20260626

# metrics (read-only)
./gpt metrics perf    "$DATA_ROOT"/runs/perf-20260626/summarize_trace.jsonl \
                      "$DATA_ROOT"/runs/perf-gemma4-20260626/summarize_trace.jsonl
./gpt metrics quality "$DATA_ROOT"/runs/perf-20260626/reconstructed_projects.json \
                      "$DATA_ROOT"/runs/perf-gemma4-20260626/reconstructed_projects.json
./gpt compare perf-20260626 perf-gemma4-20260626
```

---

## 6. Artifacts (under `$DATA_ROOT`, gitignored)

| Path | Contents |
|---|---|
| `runs/perf-20260626/` | store, 173 bundles, `.run_manifest.json` (build timings), codex Stage-4 output + trace |
| `runs/perf-gemma4-20260626/` | gemma Stage-4 output + trace + `power_trace.jsonl` |
| `comparisons/codex-vs-ollama.md` | full archetype/domain disagreement table |

**Not done (deliberate):** `config/generated/model_benchmarks.json` was **not**
regenerated — that sidecar is keyed by `provider:name` and currently holds the
`oct2024` verdicts; overwriting it from this single jun2026 two-model run would
conflate workloads. Regenerate intentionally with
`gpt gen-model-benchmarks --runs 'perf-*' --reference ref=perf-20260626` if these
verdicts should supersede.
