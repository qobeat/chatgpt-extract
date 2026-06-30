# TODO — chatgpt-extract roadmap (governed lifecycle surface)

This is the project's single governed roadmap surface, per **ADOS 0.8.20** (which
renamed `PLANNED-WORKS.md` → `TODO.md` and forbids `PLANNED-WORKS.md` in a strict
package). The former `PLANNED-WORKS.md` planning note and the `plans/PLAN_PHASE1..4.md`
phase plans have been folded into this document; make all roadmap changes here.

Success is defined by the Project Geometry, not by this list:
`geometry/project-geometry.json` (authority) + `geometry/evaluation-rubric.json`.
The GOAL and the three OBJECTIVES (**O1 Catalog**, **O2 Benchmark**, **O3
Decision**) are unchanged and must not be edited without an explicit request.

## Workflow (how this file is used)

- **Paired with `REQUIREMENTS.md`.** Every phase and subtask below maps to one or
  more `FR-*` / `NFR-*` IDs — that file is the authoritative, testable spec and
  names each requirement's verification. This file tracks *progress*;
  `REQUIREMENTS.md` defines *done*.
- **Phases graduate to `CHANGELOG.md`.** A phase is tracked here while in
  progress. **When it reaches 100%, its record — Phase number + name, the
  subtasks table, and the success criteria — is published to `CHANGELOG.md`** as a
  named, dated release. The durable history of completed work lives there, not as
  a growing list here.
- **Phase IDs are stable Roman numerals** (I, II, III, IV …), unique across the
  changelog history, so a phase keeps its identity as it moves from roadmap to
  release.

## Progress key

Each phase and item carries a **0–100%** figure. **100% = done** (shipped +
verified by `pytest -q`); **0% = not started**; values between are partially
landed (see the per-phase tables). Phases already at 100% are retained below for
continuity; their durable record is in `CHANGELOG.md`.

---

## Status at a glance

| Phase | Name | Progress |
|---|---|---|
| **I** | Benchmark validity & keep-vs-return re-decision | **100%** |
| **II** | Catalog completeness & fidelity | **100%** |
| **III** | Publish / redaction hardening + observability | **100%** |
| **IV** | CLI / UX polish + packaging | **100%** |
| **V** | Interactive latency (FR-Q16) + working local GPU offload (FR-Q17) | **80%** |
| **VI** | Next-release hardening (GPT-5.5 review): privacy symmetry, stress + daemon responsiveness, CLI/CI/redaction; large lanes scheduled | **45%** |

---

## Open requirements (status matrix)

The companion to `REQUIREMENTS.md §5` (which lists every **implemented** = 100%
requirement). These two tables are the **open** work: partially-implemented and
not-implemented. `DONE` is 0–100%; a `COMMENT` is **mandatory** when `DONE` is
neither 0 nor 100. Both rows are scheduled as **Phase V** below.

### Partially implemented (0 < DONE < 100)

| REQ ID | WHAT TO DO | WHY TO DO THIS | SIGNAL OF SUCCESS IMPLEMENTATION | DONE | COMMENT |
|---|---|---|---|---:|---|
| FR-Q17 | Make local GPU offload actually work on WSL2 (CUDA/Vulkan discovery for the systemd Ollama service) instead of routing around it | The local 15s proof (FR-Q16) is impossible while Ollama's GPU watchdog times out and silently falls back to CPU despite an RTX 3090 visible to `nvidia-smi` | Fresh `gpt ask` loads `gpt-oss:20b` onto the GPU (FR-Q10 residency `on_gpu=true` on first load, no CPU spill); `gpt doctor` reports GPU-resident Ollama | 40 | **Landed:** `gpt doctor` now reports the `ask` model's actual GPU residency (silent CPU fallback is diagnosable); `gpt ask-eval` warms the model before the timed battery. **Remaining:** the systemd Ollama CUDA/Vulkan discovery fix itself — box/host-specific (unit env, driver paths), so it can't be fully landed from this repo. |

### Not implemented (DONE = 0) — scheduled as Phase VI

These are the **large** GPT-5.5 review items: each changes data shape, packaging,
or the classifier, so each needs its own design + golden corpus to land safely.
They are scheduled (not implemented) so the next release ships the contained,
test-gated fixes without destabilising the catalog. Designs live in Phase VI.

| REQ ID | WHAT TO DO | WHY TO DO THIS | SIGNAL OF SUCCESS IMPLEMENTATION | DONE | COMMENT |
|---|---|---|---|---:|---|
| FR-D4 (new) | Decision-preserving bundle packing: head+tail+signal-aware truncation so the *latest* requirements_evolution / final decision is never dropped by the char budget | A purely chronological fair-share pack can truncate the newest chat mid-decision, biasing O3 (Decision) | On a fixture where the final decision sits in the last 5% of a long chat, the packed bundle still contains it; golden test added | 0 | Review P0. Needs a labelled long-chat fixture to assert "final decision retained". Risk: shifts every bundle → re-baseline catalog. |
| FR-C6 (new) | Full-local lossless transcript lane + code-fence index (separate from the reduced bundle) | Bundles are lossy by design; an exact-answer/code question needs the raw text + fenced code retrievable | `gpt ask` can quote an exact code block verbatim from a lossless lane; index build adds a code lane | 0 | Review P0. New storage lane + parser + ask retrieval changes; largest item. |
| NFR-R5 (new) | `pyproject.toml` packaging + `gpt` console-entrypoint without breaking the `scripts/lib` sys.path imports | A pip-installable package is more portable than the `./gpt` shim; reproducibility | `pip install -e .` exposes `gpt`; all tests pass under the installed package | 0 | Review P1. Medium; risk to the sys.path import scheme used throughout. |
| FR-B7 (new) | Layered classifier prior (deterministic signals → prior → model) + confusion matrix in `gpt metrics` | The current `classify_prior` is shallow; a layered prior + confusion matrix makes archetype/domain accuracy auditable | `gpt metrics` prints a confusion matrix vs the etalon; prior precision measured | 0 | Review P1/P2. ML work; needs the labelled etalon to measure precision. |

---

## Repository topology (decision)

**Keep the two repositories you already have. Do not add a third.**

| Repo | Role | Visibility | Owns |
|---|---|---|---|
| `chatgpt-extract` | The **tool** | public | extract / cluster / classify / summarize, the `gpt` CLI, ontology + schema, the benchmark harness, sanitized `published/` |
| `chatgpt-extract-catalog` | **Observability** | private | reads runs the tool wrote; writes catalogs, run summaries, cross-run stats; keeps the fuller *unsanitized* catalog |

**Why this axis and not "export vs logic":** the only durable reason to separate
two repos here is the **PII / visibility boundary**. The tool can be public
because it commits only sanitized output; the observability repo must be private
because it deliberately retains chat-derived titles, `source_conversation_ids`,
and LLM-written summaries. Splitting instead on "data export vs processing logic"
would cut a tightly-coupled pipeline (extract → cluster → bundle → summarize) in
half and force a fragile internal API for no benefit.

**Two refinements (carried into the phases):**
1. The catalog repo **vendors copies** of `paths.py`, `ulog.py`, `run_log.py`.
   Record the upstream commit each copy came from (a `VENDORED_FROM` line) so the
   two repos cannot silently drift. *(Phase IV — remaining.)*
2. **Raw chat data lives in neither repo** — it stays in `$DATA_ROOT`, already
   gitignored. No phase changes this.

---

## Roadmap at a glance

| Phase | Name | Primary objective | Why this order |
|---|---|---|---|
| **I** | Benchmark validity → settle the GPU question | O2, O3 (+ NFR-P3) | The keep-vs-return verdict rests on a metric that conflates depth + reliability and omits correctness. Highest value, time-sensitive (the card is still returnable). The cloud pre-send scrubber lands here, **before** any cloud re-run, so re-benchmarking does not re-leak. |
| **II** | Catalog completeness & fidelity | O1 | "All data extracted" is not yet true — browsing/tool/reasoning content-types, per-message `model_slug`, and attachments are dropped. The benchmark workload is only as representative as the catalog. |
| **III** | Publish / redaction hardening + observability | NFR-P, O1 | Today redaction is detect-only with narrow patterns. Make it an active transform; broaden patterns; wire the catalog repo's run-stats into the loop. |
| **IV** | CLI / UX polish + packaging | cross-cutting | Make it best-in-class for daily WSL use: consistent verbs, fast feedback, `--json` everywhere, vendored-lib pinning, install ergonomics. |

Each phase is independently shippable and leaves the tool in a working state. A
phase's exit criteria are its success criteria below, which map to specific
`FR-*` / `NFR-*` IDs in `REQUIREMENTS.md`.

---

## Phase I — Benchmark validity and the keep-vs-return re-decision  — 100%

| Item | Progress |
|---|---|
| Split reliability from quality in `metrics.py` (FR-B2, FR-B5) | 100% |
| Structured-output enforcement + retry (FR-B4) | 100% |
| Correctness check — `accuracy%` adjudicated vs a reference (FR-B3) | 100% |
| Cloud pre-send scrubber gating cloud calls (NFR-P3) | 100% |
| Measure cost/power, re-run, re-decide the verdict (FR-B6, FR-D1, FR-D2) | 100% |

**Success criteria:** `gpt metrics` reports completion / depth-on-success /
schema-valid / accuracy as separate columns (FR-B2/B3); the Ollama provider
enforces structured output with retry (FR-B4); a cloud pre-send scrubber exists
and gates cloud calls (NFR-P3); `config/models.json` verdicts are regenerated
(FR-D2); `pytest -q` is green (NFR-Q1). **Shipped:** see `CHANGELOG.md` →
"Benchmark Validity".

**Outcome:** a benchmark you can defend, and a final, evidence-grounded answer to
"is the RTX 3090 worth $1,400 for this workload?"

Covers `FR-B2` (report completion and depth-on-success as **separate columns**,
never one blended rank key), `FR-B3` (a **correctness** check adjudicated against a
reference — `codex` or a held answer key — not just depth), `FR-B4`
(**structured-output enforcement**: Ollama `format=json` / GBNF grammar +
retry-on-parse-failure, so failures stop injecting zeros), `FR-B6` (power/cost
model with measured watt-hours), and `NFR-P3` (the **cloud pre-send scrubber**,
gating any cloud re-run). Ends by re-running the suite and rewriting the
`AI_MODEL_TESTS.md` verdict from the corrected numbers.

**Scope guard (NFR-Q5):** touch only `scripts/metrics.py`,
`scripts/compare_models.py`, the provider modules under `scripts/lib/providers/`,
`config/models.json`, the benchmark sections of `AI_MODEL_TESTS.md`, and their
tests. Do **not** change extraction, clustering, or the ontology.

**Actions and success conditions (priority order):**

1. **Split reliability from quality in `metrics.py` (FR-B2, FR-B5). — 100%**
   - Compute `quality%` (depth) over **completed items only**; report
     `completion = LLM_OK/attempted` as its own column; keep failed items visible
     but excluded from the depth mean.
   - *Success:* the master table has separate `completion` and `depth-on-success`
     columns; recomputing the published example reproduces qwen3:8b ≈ 92.5%
     depth-on-success at 8/10 completion; the doc/code contradiction ("over
     completed items") is gone.

2. **Add structured-output enforcement + retry (FR-B4). — 100%**
   - In `ollama_provider` set `format=json` (or attach a GBNF grammar); on a parse
     miss, retry once, then record an honest failure. Apply the equivalent to
     cloud providers where supported.
   - *Success:* on the same sample, the big models' completion rises materially
     vs the pre-change baseline; a regression test asserts a deliberately
     prose-wrapped response is parsed or cleanly retried, not coerced to empty.

3. **Add a correctness check (FR-B3). — 100%**
   - Extend `gpt compare` to adjudicate each item against a **reference** (use
     `codex`/a cloud model as the key, or a hand-checked set): does the
     classification + key fields match the source bundle? Emit an `accuracy%`
     column distinct from depth.
   - *Success:* `gpt compare` outputs per-model `accuracy%`; the report shows a
     case where high depth ≠ high accuracy, demonstrating the two are separate.

4. **Cloud pre-send scrubber as a gate before re-running cloud models (NFR-P3). — 100%**
   - Per `skills/publish-redaction`, scrub each bundle before any
     `cursor`/`codex`/`claude`/`openai` call. Local Ollama is exempt.
   - *Success:* a unit test proves a bundle containing a fixture email/home-path is
     scrubbed before the provider call; no cloud re-run happens without it.

5. **Measure cost/power, then re-run and re-decide (FR-B6, FR-D1, FR-D2). — 100%**
   - Replace the `chars/4` estimate with token-exact cloud cost and measured
     local watt-hours × rate. Re-run the suite on the corrected harness.
   - Regenerate `config/models.json` `note` verdicts from the corrected metric and
     rewrite the `AI_MODEL_TESTS.md` verdict + §8/§9 from the new numbers.
   - *Success:* the keep-vs-return verdict in `AI_MODEL_TESTS.md` cites completion
     + depth-on-success + accuracy + `s/item` + measured cost, side by side, and
     is reproducible from committed commands (FR-D1).

---

## Phase II — Catalog completeness and fidelity  — 100%

| Item | Progress |
|---|---|
| Capture the dropped content-types (FR-C2) | 100% |
| Per-message provenance — `model_slug` + attachments (FR-C3) | 100% |
| Prove no silent loss — round-trip/coverage test (FR-C5, FR-C1) | 100% |
| Incremental + bounded behavior still holds (FR-C4, NFR-R1) | 100% |

**Success criteria:** extraction captures the previously-dropped content-types
with an auditable coverage test (FR-C2); `model_slug` and attachments are on the
card (FR-C3); a round-trip test proves no silent loss (FR-C5); streaming/
incremental guarantees hold (FR-C1/C4/NFR-R1); `pytest -q` is green (NFR-Q1).
**Shipped (1.0):** `COORD-C-COVERAGE` is now a measured observation in `gpt state`
derived from the extract ledger (`seen`/`skipped`/`written`), not `unknown`. See
`CHANGELOG.md` → "Semantics".

**Outcome:** the catalog losslessly represents what is actually in the export, so
the benchmark workload (Phase I) and any query (`skills/catalog-query`) operate on
complete data.

Covers `FR-C2` (capture the content-types currently dropped: `tether_quote`,
`tether_browsing_display`, `execution_output`, o1/o3 reasoning), `FR-C3`
(per-message `model_slug` and `metadata.attachments`), and `FR-C5`
(round-trip/coverage tests proving no silent loss). The deterministic-first,
LLM-last pipeline and the ADOS ontology/schema are unchanged in shape — this
widens what feeds them.

**Scope guard (NFR-Q5):** touch only `scripts/lib/chatgpt_parse.py`,
`scripts/extract_cards.py`, the card schema, and their tests. Do **not** change
the benchmark metric or providers.

**Actions and success conditions (priority order):**

1. **Capture the dropped content-types (FR-C2). — 100%**
   - Extend `message_text()` to handle `tether_quote`,
     `tether_browsing_display`, `execution_output`, and o1/o3 `reasoning` parts as
     labelled blocks; unknown shapes still degrade to `[tag]` (never crash).
   - *Success:* a coverage test enumerates every known `content_type` and asserts
     non-empty, labelled output for each; an export containing browsing/tool turns
     yields transcripts that include them.

2. **Capture per-message provenance (FR-C3, NFR-Q4). — 100%**
   - Record `message.metadata.model_slug` onto the card (which model wrote each
     turn) and `metadata.attachments` (filenames/types).
   - *Success:* cards expose `model_slug` votes and an `attachments` list; a test
     with a fixture attachment asserts it is not dropped.

3. **Prove no silent loss (FR-C5, FR-C1). — 100%**
   - Add a round-trip/coverage test: every message node in a fixture export maps
     to either captured content or an explicit `[tag]`, with a count assertion so
     a future parser change that drops content fails CI.
   - *Success:* the coverage test passes and would fail if a `content_type` were
     silently skipped.

4. **Confirm incremental + bounded behavior still holds (FR-C4, NFR-R1). — 100%**
   - Re-running on a newer export updates only changed chats (newer `update_time`
     wins); memory stays bounded on a multi-GB fixture.
   - *Success:* existing incremental/streaming tests remain green after the
     widened parser.

---

## Phase III — Publish / redaction hardening and observability  — 100%

| Item | Progress |
|---|---|
| Redaction becomes an active transform (NFR-P2) | 100% |
| Broaden the patterns — phone/token/JWT/PEM/IPv4 (NFR-P2) | 100% |
| Publish-boundary tests fail the commit on any leak (NFR-P1) | 100% |
| No PII in logs (NFR-P4) | 100% |
| `chatgpt-extract-catalog` observability + `VENDORED_FROM` (NFR-Q4) | 100% |

**Success criteria:** the publish path actively scrubs broadened PII (NFR-P2);
publish-boundary tests fail on any leak (NFR-P1); logs are PII-free (NFR-P4);
cross-run observability is available without duplicating data; `pytest -q` is
green (NFR-Q1). **Shipped (1.0):** `redact` broadened to JWTs, PEM private keys,
and range-checked IPv4; `COORD-D-VERDICT` now carries `GATE-COVERAGE` /
`GATE-SCHEMA` evidence so the score is gate-aware. **Shipped (1.1):**
`GATE-PRIVACY` is now emitted on `COORD-D-VERDICT` from the cloud pre-send
scrubber, and `gpt info` surfaces the read-only cross-run catalog. See
`CHANGELOG.md` → "Semantics" and "Provenance".

**Outcome:** the published surface is provably safe by construction (active
redaction, not detect-only), and runs are observable across the two-repo split
without ever moving raw data.

Covers `NFR-P2` (redaction becomes an active **transform**, broaden beyond emails
+ paths to names, phones, tokens), `NFR-P1` (publish-boundary tests that fail the
commit on any leak), `NFR-P4` (no PII in logs), and the `chatgpt-extract-catalog`
integration (run registry + `RUN_SUMMARY` + cross-run stats consumed by `gpt`).
Reconciles the vendored-lib copies (sets up Phase IV's pinning).

**Scope guard (NFR-Q5):** touch only `scripts/export_public.py`,
`scripts/check_no_secrets.sh`, logging in `scripts/lib/ulog.py`, and the
`chatgpt-extract-catalog` integration points. Do **not** change extraction
semantics (Phase II) or the benchmark metric (Phase I).

**Actions and success conditions (priority order):**

1. **Redaction becomes an active transform (NFR-P2). — 100%**
   - Replace detect-only `review_*` with a transform that substitutes
     `‹email›`/`‹path›`/`‹phone›`/`‹token›` placeholders inside `sanitize_item` /
     `sanitize_document`, in addition to the existing provenance stripping.
   - *Success:* `gpt publish` on a fixture containing PII writes a `published/`
     whose content has the PII replaced (not merely a failed commit).

2. **Broaden the patterns (NFR-P2). — 100%**
   - Extend beyond email + macOS `/Users/...` to **names, phone numbers, API
     keys/tokens, and Linux/WSL home paths** (`/home/<user>`,
     `/mnt/c/Users/<user>`). 1.0 additionally added JWTs, PEM private keys, and
     range-checked IPv4.
   - *Success:* pattern tests cover each category with positive + negative cases;
     the `alice` fixtures still pass as the only allowed user-path strings.

3. **Publish-boundary tests (NFR-P1). — 100%**
   - Feed known-PII fixtures end-to-end through publish and assert the output is
     clean; assert the whole tree + git history stay clean.
   - *Success:* a single `pytest` target fails if any real email/home-path/key/
     conversation-id could reach `published/` or git.

4. **No PII in logs (NFR-P4). — 100%**
   - Ensure `ulog`/trace never emits transcript text or paths under `$DATA_ROOT`.
   - *Success:* a log-scrubbing test asserts traces contain only labels/counts.

5. **Observability integration (NFR-Q4). — 100%**
   - Wire the `chatgpt-extract-catalog` run registry + `RUN_SUMMARY` so `gpt info`
     and `skills/catalog-query` can surface cross-run stats, keeping the
     read-only split (tool writes runs; catalog summarizes). Record a
     `VENDORED_FROM` upstream-commit marker on the vendored libs (sets up Phase IV
     pinning).
   - *Success:* `gpt info` reflects run-catalog state; vendored libs carry a
     recorded upstream commit; raw data still lives only in `$DATA_ROOT`.
   - *Done:* `store_query.run_catalog_state()` reads `output/runs/catalog.json`
     read-only and `gpt info` shows a Runs summary; `GATE-PRIVACY` evidence from
     the cloud scrubber lands on `COORD-D-VERDICT`; the catalog repo's vendored
     libs carry `VENDORED_FROM` markers (see Phase IV item 5).

---

## Phase IV — CLI / UX polish and packaging  — 100%

| Item | Progress |
|---|---|
| Consistent verb grammar + single entrypoint (FR-U1) | 100% |
| `--json` on every read command (FR-U2/U3) | 100% |
| Preview before spend — confirmation gate (FR-U2) | 100% |
| Fast feedback + resumability (NFR-R2, NFR-R3) | 100% |
| Install ergonomics (`setup.sh`/`.env.example`/`gpt doctor`) + `VENDORED_FROM` pinning (NFR-Q2) | 100% |

**Success criteria:** `gpt` exposes a consistent verb set with `--json` everywhere
(FR-U1/U2), shows estimates before spend and state at a glance (FR-U2/U3), resumes
cleanly (NFR-R3), installs on WSL2 in documented steps (NFR-Q2), and the two repos
can no longer silently drift; `pytest -q` is green (NFR-Q1). **Shipped (1.0):** all
read-only/benchmark commands emit `--json` (including the new `gpt ask --json`).
**Shipped (1.1):** the `chatgpt-extract-catalog` vendored libs are pinned to a
recorded upstream commit (`VENDORED_FROM` markers + `vendored.json` +
`sync_vendored.py` + a drift test), so the two repos can no longer silently
drift. See `CHANGELOG.md` → "Semantics" and "Provenance".

**Outcome:** best-in-class lightweight CLI for daily WSL use — pure fit-and-finish
over Phases I–III, no new data semantics.

Covers `FR-U1..U3` (consistent verb grammar, `--json` on every read command, fast
first-byte feedback and progress on long runs), the `catalog-query` ergonomics
(`gpt list/search/show/info`), `VENDORED_FROM` pinning for the catalog repo, and
install/setup ergonomics (`setup.sh`, `.env.example`, doctor command).

**Scope guard (NFR-Q5):** touch only `scripts/gpt_cli.py`, output formatting/help,
`setup.sh`, `.env.example`, and docs. Do **not** change extraction, the benchmark
metric, or redaction logic.

**Actions and success conditions (priority order):**

1. **Consistent verb grammar + single entrypoint (FR-U1). — 100%**
   - One `gpt <command>` surface with consistent verbs
     (`run/summarize/list/search/show/info/metrics/arena/compare/publish/
     zips-verify`); models are name-driven, not flag-driven.
   - *Success:* `gpt --help` lists a coherent verb set; every read command accepts
     `--run-label` and resolves `latest` by default.

2. **`--json` on every read command (FR-U2 piping, FR-U3). — 100%**
   - All read/query commands emit machine-readable `--json`; `gpt info`
     summarises catalog + last-run state at a glance.
   - *Success:* `gpt list --json | jq` works for each read command; `gpt info`
     shows extracted/summarized/published counts and the latest run.

3. **Preview before spend (FR-U2). — 100%**
   - Any LLM command shows an item count + cost/time estimate and requires
     confirmation (or `--yes`) before spending.
   - *Success:* `gpt summarize` without `--yes` prints an estimate and waits; with
     `--yes` it proceeds; a test covers both paths.

4. **Fast feedback + resumability surfaced (NFR-R2, NFR-R3). — 100%**
   - Long runs show progress per item and persist after each item so Ctrl-C +
     resume loses nothing.
   - *Success:* interrupting a run and re-invoking with the same `--run-label`
     resumes from the next unprocessed item.

5. **Install ergonomics + vendored-lib pinning (NFR-Q2, Phase III→IV). — 100%**
   - `setup.sh` + `.env.example` make a clean WSL2 Ubuntu setup one step; add a
     `gpt doctor` that checks Python, venv, `$DATA_ROOT`, providers, and GPU; pin
     the `chatgpt-extract-catalog` vendored libs to the recorded `VENDORED_FROM`
     commit.
   - *Success:* a fresh WSL clone reaches a working `gpt info` via documented
     steps; `gpt doctor` reports environment readiness; vendored libs are pinned.
   - *Done:* `setup.sh`, `.env.example`, `gpt doctor`; the catalog repo's vendored
     libs (`paths.py`/`ulog.py`/`run_log.py`) now carry `VENDORED_FROM` markers
     pinned to a recorded upstream commit, with `scripts/sync_vendored.py` to
     refresh and `tests/test_vendored.py` to fail CI on drift.

---

## Phase V — Interactive latency (FR-Q16) and working local GPU offload (FR-Q17)  — 80%

The done-criteria named in `REQUIREMENTS.md §3` for the *next* version are the
**15s interactive latency target** (FR-Q16, on hold) and **working local GPU
offload on WSL2** (FR-Q17, deferred → core). This phase schedules both. It is
informed by two external reviews (GPT-5.5, 2026-06-30): a repo
production-readiness audit and a docs-verified latency analysis of the warmed
`gpt-oss:20b` runs. The latency analysis is the spine of this phase.

| Item | Maps to | Progress |
|---|---|---|
| Fix the `think` parameter for `gpt-oss` (booleans are ignored) | FR-Q16 | 100% |
| Cap synthesis output (`num_predict`) on the interactive `ask` path | FR-Q16 | 100% |
| Streaming synthesis for perceived latency (TTFT) | FR-Q16 | 100% |
| Make local GPU offload actually work on WSL2 (not route around it) | FR-Q17 | 40% |
| Promote FR-Q16 ON HOLD → tracked target; gate it in `gpt ask-eval` | FR-Q16 | 100% |
| Ask/daemon **stress suite** + fix daemon head-of-line blocking | FR-Q18 (new) | 100% |

**Success criteria:** on a warm local GPU route, `gpt ask` answers a typical
question within **15s** (`gpt ask-eval --budget 15` reports `USABLE`, 0 over
budget); local Ollama offloads to the RTX 3090 on WSL2 without silent CPU
fallback (FR-Q10's GPU residency probe passes on first load); `pytest -q` is
green (NFR-Q1). When met, FR-Q16 graduates from **[ON HOLD]** to
**[IMPLEMENTED]** and FR-Q17 from **[DEFERRED]** to **[IMPLEMENTED]**.

**Why this order:** FR-Q16 cannot be *proven on the local route* until FR-Q17
lands — a model that silently falls back to CPU never reaches the ~102 tok/s that
makes 15s achievable. The cheap, model-agnostic wins (think/num_predict/stream)
land first because they help every route (local *and* the warm cloud daemon) and
are independently shippable; the GPU-offload work is the larger, box-specific
piece.

**Scope guard (NFR-Q5):** touch only `scripts/lib/providers/ollama_provider.py`,
`scripts/ask.py`, `scripts/ask_eval.py`, `scripts/lib/ollama_probe.py`, the
systemd/Ollama service setup docs, and their tests. Do **not** change extraction,
clustering, the ontology, or the benchmark metric. The 15s number, the FR-Q4
privacy gate, and the FR-Q8 not-found contract are unchanged.

**Actions and success conditions (priority order):**

1. **Fix the `think` parameter for `gpt-oss` (FR-Q16). — 100%** *(P0, tiny, high-leverage)*
   - **Done:** `ollama_provider.think_for_model` sends `think="low"` for `gpt-oss*`
     tags and keeps `False` elsewhere; an explicit override (incl. `False`) wins,
     so it is name-driven yet configurable. *Tests:* `test_ask_latency`
     (`ThinkForModelTest`, `PayloadKnobsTest`).
   - `ollama_provider.complete` hard-coded `"think": False`. Docs-verified finding:
     `gpt-oss` **ignores boolean `think`** and only honours `"low"`/`"medium"`/
     `"high"`, so the model is still spending tokens (and seconds) on reasoning we
     believe is off. Send `"think": "low"` for `gpt-oss*` tags; keep `False`/omit
     for models that honour the boolean. Make the value a per-model bank field so
     it is name-driven, not hard-coded.
   - *Success:* a provider unit test asserts a `gpt-oss` payload carries
     `think="low"` (not `False`); a warm `gpt-oss:20b` answer to a fixed prompt
     emits materially fewer `eval_count` tokens than the boolean-`think` baseline.

2. **Cap interactive synthesis output (`num_predict`) (FR-Q16). — 100%** *(P0)*
   - **Done:** `num_predict` is a provider instance field threaded via
     `get_provider`; `gpt ask` passes `DEFAULT_ASK_NUM_PREDICT=384` (override
     `--num-predict` / `config ask.num_predict`), while `summarize` keeps the
     1500 default. *Tests:* `test_ask_latency` (`PayloadKnobsTest`).
   - The provider hard-coded `num_predict: 1500`. At ~102 tok/s that is ~15s of
     generation *before* any reasoning tokens — the budget is gone on output length
     alone. Thread a `num_predict` through `get_provider` and set a small
     interactive cap on the **ask** path (default ~384, configurable via
     `config ask.num_predict`); leave the benchmark/`summarize` path at the larger
     budget it legitimately needs. Ask answers are short and cited; a tight cap is
     correct here.
   - *Success:* `gpt ask` requests carry the small cap while `gpt summarize` keeps
     1500; a test asserts the two paths request different `num_predict`;
     `gpt ask-eval --budget 15` slowest-answer time drops below the baseline.

3. **Streaming synthesis for perceived latency (FR-Q16). — 100%** *(P1)*
   - **Done:** `OllamaProvider.stream` yields NDJSON deltas + a final `Usage`;
     `ask.stream_local_answer` prints tokens live on a TTY but holds back the
     first 240 chars so a short refusal still collapses to the not-found sentinel
     (FR-Q8); `--no-stream`/`--json`/non-TTY stay buffered and byte-identical.
     *Tests:* `test_ask_latency` (`StreamParseTest`, `StreamLocalAnswerTest`).
   - FR-Q16 is an *interactive* target: time-to-first-token matters more than wall
     time. The provider uses `stream: False`, so the user waits the full ~12s with
     no output. Add a streaming local-synthesis path for `gpt ask` (TTY only;
     `--no-stream` and `--json` keep the buffered path) that prints tokens as they
     arrive while still enforcing the wall-clock budget and the FR-Q8 not-found
     collapse on the completed text.
   - *Success:* on a TTY, first visible token arrives in ≲2s on a warm GPU route;
     `--json`/non-TTY output is byte-identical to today; not-found and budget/
     unusable behaviour are unchanged (tests cover all three).

4. **Make local GPU offload work on WSL2 (FR-Q17). — 40%** *(P0 — the local-route blocker)*
   - **Done:** `gpt doctor` reports the `ask` model's actual GPU residency (GPU /
     CPU-fallback / not-loaded), so the silent WSL2 CPU fallback is diagnosable;
     `gpt ask-eval` warms the model (`model_gpu_state(load=True)`) before the timed
     battery so cold-load is excluded. **Remaining:** the systemd Ollama CUDA/Vulkan
     discovery fix itself (box/host-specific — unit env, driver paths).
   - Today Ollama's `llama-server` GPU-discovery watchdog times out under WSL2 and
     silently falls back to CPU despite an RTX 3090 visible to `nvidia-smi`; the
     first cold load was measured at ~3m12s. FR-Q10 hard-blocks CPU and FR-Q11
     routes to cloud, so `gpt ask` stays usable — but the *local* 15s proof is
     impossible until offload works. Fix CUDA/Vulkan discovery for the systemd
     Ollama service (service env / discovery timeout / driver path), document it in
     `setup.sh` + `gpt doctor`, and add a one-shot warmup call so cold-start is paid
     once and excluded from the interactive path (the daemon already excludes
     startup from the budget; mirror that discipline in `ask-eval`).
   - *Success:* after `setup.sh` on the target box, a fresh `gpt ask` loads
     `gpt-oss:20b` onto the GPU (FR-Q10 residency probe `on_gpu=true` on first
     load, no CPU spill); `gpt doctor` reports GPU-resident Ollama; cold load is a
     one-time warmup, not a per-question cost.

5. **Promote and gate FR-Q16 (FR-Q16 / FR-D1). — 100%** *(P1)*
   - **Done:** FR-Q16 flipped from **[ON HOLD]** to **[IMPLEMENTED]** in
     `REQUIREMENTS.md` (and moved into the §5 implemented matrix); `gpt ask-eval
     --budget 15` is the reproducible latency gate (it computes the per-run
     `latency_summary` / `USABLE` verdict, now over a pre-warmed model).
   - *Remaining (record-keeping):* capture the warm local-route median + slowest
     in `AI_MODEL_TESTS.md` §9 once FR-Q17's local GPU offload lands, so the
     local-route 15s figure is evidence-grounded (FR-D1). The warm cloud route
     already satisfies the gate.

6. **Ask/daemon stress suite + FR-Q18 (responsiveness). — 100%** *(found here)*
   - Added `tests/test_ask_stress.py`: concurrent request isolation (48 questions,
     no bleed), not-found under load, over-budget→unusable, malformed/oversized
     input survival, stats/history under load, the streaming guard under random
     chunk boundaries, and a **daemon responsiveness** probe.
   - **Issue found:** the daemon's accept loop handled one connection at a time, so
     a long synthesis blocked `ping`/`stats`/`shutdown`/entity for up to the budget
     (head-of-line blocking). **Fixed:** `serve()` now handles each connection on a
     worker thread; synthesis stays single-flight via `state.lock`; stats writes
     use a new `rec_lock`. Filed as **FR-Q18** (`[IMPLEMENTED]`).
   - *Success:* `test_ask_stress` `DaemonResponsivenessTest` — a `ping` returns in
     <0.8s while a 1.5s synthesis runs (was ~1.3s, i.e. blocked).

---

## Phase VI — Next-release hardening (GPT-5.5 review)  — 45%

Closes the **contained, test-gated** findings from the two GPT-5.5 reviews
(2026-06-30) and schedules the large, data-shaping ones (the §"Not implemented"
table above) so the catalog stays stable. Everything here is independently
shippable and offline-testable.

| Item | Maps to | Progress |
|---|---|---|
| Cloud `summarize` privacy symmetry: refuse cloud egress without `--scrub-cloud` or `--allow-raw-cloud-egress` | NFR-P3 / FR-Q4 | 100% |
| Ask/daemon stress suite + daemon responsiveness fix | FR-Q18 | 100% |
| `--min-versions` CLI contract matches behaviour (`--include-multi-chat` / `--include-singletons`) | FR-B (bundle) | 100% |
| Custom local redaction dictionary (`config/redact.local.json`, gitignored) | NFR-P2 | 100% |
| Continuous integration (`.github/workflows/ci.yml`: compileall + `pytest` on 3.10–3.12) | NFR-R | 100% |
| Reframe "IQ" → **TWA** (task-weighted accuracy) in `gpt metrics` / model bank | FR-D / NFR-Q | 100% |
| Decision-preserving bundle packing (head+tail+signal) | FR-D4 (new) | 0% |
| Full-local lossless transcript + code-fence index lane | FR-C6 (new) | 0% |
| `pyproject.toml` packaging + `gpt` console entrypoint | NFR-R5 (new) | 0% |
| Layered classifier prior + confusion matrix in `gpt metrics` | FR-B7 (new) | 0% |

**Scope guard (NFR-Q5):** the landed items touch only `scripts/summarize.py`,
`scripts/build_bundles.py`, `scripts/ask_daemon.py`, `scripts/lib/redact.py`,
`scripts/metrics.py`, `scripts/lib/models_bank.py`, `scripts/bench_sweep.sh`,
CI/config, and their tests. The GOAL, the three OBJECTIVES, the ontology, and the
benchmark *metric* (only its **label** changed, IQ→TWA — the number is identical)
are unchanged.

**Landed (100%) — with tests:**

1. **Cloud `summarize` privacy symmetry (NFR-P3 / FR-Q4). — 100%** *(P0)*
   - `summarize.cloud_egress_block_reason()` refuses a cloud provider (exit 2)
     unless `--scrub-cloud` (redact first) or `--allow-raw-cloud-egress` (explicit
     opt-in) is set — matching the `gpt ask` gate. `bench_sweep.sh` now passes
     `--scrub-cloud` for cloud references. *Tests:* `test_release_hardening`
     (`CloudEgressGateTest`).
2. **Daemon responsiveness + stress suite (FR-Q18). — 100%** *(P0, found here)* —
   see Phase V item 6; `serve()` is now thread-per-connection.
3. **`--min-versions` CLI contract (FR-B). — 100%** *(P1)*
   - `build_bundles.select_clusters()` makes the keep-rule explicit and accurate;
     the legacy default set is unchanged. *Tests:* `test_release_hardening`
     (`SelectClustersTest`).
4. **Custom local redaction dictionary (NFR-P2). — 100%** *(P1)*
   - `redact.load_custom_patterns()` reads gitignored `config/redact.local.json`
     (`terms` + `patterns`) and scrubs them to `‹redacted›` at every egress; an
     example ships as `config/redact.local.json.example`. *Tests:*
     `test_release_hardening` (`RedactCustomDictTest`).
5. **CI (NFR-R). — 100%** *(P1)* — hermetic `pytest` (every provider faked) on
   Python 3.10–3.12, plus a `compileall` syntax gate.
6. **IQ → TWA framing (FR-D / NFR-Q). — 100%** *(P2)*
   - `gpt metrics` and the model bank now label the difficulty-weighted accuracy
     **TWA (task-weighted accuracy)** with a "NOT an intelligence score" note. The
     underlying number and `iq` data key are unchanged (no migration).

**Scheduled (0%) — large, data-shaping; see the §"Not implemented" table for the
done-criteria of FR-D4, FR-C6, NFR-R5, FR-B7.** Each needs its own labelled
fixture/golden corpus and is split out to avoid re-baselining the catalog in this
release.

**Success criteria (this phase, landed portion):** `pytest -q` green (now 467+);
cloud `summarize` cannot egress raw data by default; `build_bundles` flags are
accurate; a personal-dictionary term never reaches a bundle/publish; CI runs on
push/PR. When the four scheduled items land, Phase VI reaches 100% and graduates
to `CHANGELOG.md`.

---

## Next

> New feature ideas land here first (not implemented until scheduled). When one is
> scheduled it becomes a numbered Phase; when it reaches 100% it graduates to
> `CHANGELOG.md`.

- [ ] **Index auto-refresh.** Rebuild (or offer to rebuild) the semantic index
  automatically at the end of `gpt run`, beyond today's stale-index warning in
  `gpt ask`.
- [ ] **True cross-encoder re-rank.** Replace the lightweight lexical `--rerank`
  with a real cross-encoder reranker model for higher top-K precision.
- [x] **Cloud `summarize` privacy symmetry (review P0).** *Landed in Phase VI:*
  cloud `summarize` now requires `--scrub-cloud` or `--allow-raw-cloud-egress`
  (exit 2 otherwise), matching the Ask gate (FR-Q4 / NFR-P3).
- [ ] **Decision-preserving bundle packing (review P0).** *Scheduled as Phase VI
  / FR-D2.* Replace head-only truncation with head + tail + high-signal-span
  packing (`approved`/`final`/`decision`/filenames/version tags) so the latest
  decision near the tail is never dropped. Needs a labelled long-chat fixture.
- [ ] **Full-local transcript + code-fence index (review P0).** *Scheduled as
  Phase VI / FR-C3.* Add a local-only full-text + code-chunk lane so `gpt ask`
  can recall code/diffs/schemas for the local Ollama route, while cloud keeps the
  reduced/scrubbed bundles. Tightens the "losslessly-extracted" claim.

## Out of scope (non-goals)

A hosted service or web UI; a database backend; a synthetic-benchmark suite;
storing raw personal data in any git repo; any change to the GOAL or the three
OBJECTIVES. Raising any of these requires an explicit decision, not a roadmap
edit.
