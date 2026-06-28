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

## Next

> New feature ideas land here first (not implemented until scheduled). When one is
> scheduled it becomes a numbered Phase; when it reaches 100% it graduates to
> `CHANGELOG.md`.

- [ ] **Index auto-refresh.** Rebuild (or offer to rebuild) the semantic index
  automatically at the end of `gpt run`, beyond today's stale-index warning in
  `gpt ask`.
- [ ] **True cross-encoder re-rank.** Replace the lightweight lexical `--rerank`
  with a real cross-encoder reranker model for higher top-K precision.

## Out of scope (non-goals)

A hosted service or web UI; a database backend; a synthetic-benchmark suite;
storing raw personal data in any git repo; any change to the GOAL or the three
OBJECTIVES. Raising any of these requires an explicit decision, not a roadmap
edit.
