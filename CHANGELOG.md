# Changelog

Releases are **named** (following the dev-pack convention, e.g. "ADOS Geometry")
and dated from git history, newest first. Commit refs are noted per release.
Personal data under `$DATA_ROOT` is never part of a release. Implemented
requirements are tracked in `REQUIREMENTS.md`; the forward roadmap is `TODO.md`.

Numbered releases **restart at `1.0.0`** with this repo's first standalone
release ("Semantics"). The bottom entry predates the split from the
`chatgpt-project-reconstructor` monorepo and is kept under its name **without a
number**, so the version line reads monotonically newest-to-oldest.

Each release records the **Phase** it shipped (the roadmap phase from `TODO.md`,
by Roman numeral where it maps to one), the **success criteria** it met, and a
**subtasks table** (every shipped subtask is 100%). This is the destination of a
phase once `TODO.md` shows it at 100%; the four roadmap phases are **I** Benchmark
validity, **II** Catalog completeness, **III** Publish/redaction hardening +
observability, **IV** CLI/UX + packaging. Releases that predate or sit outside the
four phases (foundation, governance) carry a descriptive Phase label instead of a
numeral.

## 1.1.0 — Provenance — 2026-06-28

Closes the last of the four roadmap phases. The decision verdict is now
privacy-gated end to end (`GATE-PRIVACY` is emitted, not just defined), `gpt
info` surfaces the cross-run catalog read-only, and the libraries shared with the
private `chatgpt-extract-catalog` repo are pinned to a recorded upstream commit
so the two repos can no longer drift silently. With this, **Phase III** and
**Phase IV** reach 100%.

**Phase:** III Publish/redaction + observability (GATE-PRIVACY evidence +
catalog observability), IV CLI/UX + packaging (`VENDORED_FROM` pinning).

**Success criteria (met):** `COORD-D-VERDICT` carries `GATE-PRIVACY` evidence
derived from the cloud pre-send scrubber (local providers pass offline, cloud
providers pass only with recorded `scrub_hits`, an unscrubbed cloud call fails)
(NFR-P3); `gpt info` reflects run-catalog state by reading
`output/runs/catalog.json` without ever writing it (NFR-Q4); the catalog repo's
vendored libs carry a `VENDORED_FROM` upstream-commit marker and a drift test
(NFR-Q2); `pytest -q` green in both repos (NFR-Q1).

**Subtasks**

| Item | Progress |
|---|---|
| `GATE-PRIVACY` evidence on `COORD-D-VERDICT` from the cloud scrubber (NFR-P3) | 100% |
| `gpt info` surfaces the read-only cross-run catalog (NFR-Q4) | 100% |
| `VENDORED_FROM` pinning of the catalog repo's vendored libs (NFR-Q2) | 100% |

### Added
- **`GATE-PRIVACY` emission.** `gpt summarize` now persists the cloud pre-send
  scrubber evidence (`cloud_provider`, `scrub_cloud`, `scrub_hits`) onto the run
  manifest, and `gpt state` turns it into a `GATE-PRIVACY` native on
  `COORD-D-VERDICT`. The shared `CLOUD_PROVIDERS` set moved to
  `scripts/lib/providers/__init__.py` so the gate and the observation cannot
  drift. *Tests:* `tests/test_project_state.py` (`PrivacyGateTest`).
- **Cross-run observability in `gpt info`.** A read-only
  `store_query.run_catalog_state()` reads `output/runs/catalog.json` (written by
  the observability repo) and `gpt info` shows a Runs summary (count + latest +
  recent labels), preserving the read-only split. *Tests:*
  `tests/test_store_query.py`.
- **Vendored-lib pinning (`chatgpt-extract-catalog`).** Each vendored lib
  (`paths.py`, `ulog.py`, `run_log.py`) carries a `# VENDORED_FROM:` marker;
  `scripts/sync_vendored.py` re-syncs from a sibling checkout and stamps the
  upstream commit; `scripts/lib/vendored.json` + `tests/test_vendored.py` fail CI
  on any in-place edit. Pre-existing drift in `paths.py`/`ulog.py` was resolved.

## 1.0.0 — Semantics — 2026-06-28

First named release. Ask your own chat history in natural language, unify every
benchmark sweep into one latest format, and ship the catalog/decision
governance end to end (measured extraction coverage, gate-aware verdicts,
privacy-gated `gpt ask`). The release version is defined as this top changelog
heading (see `MANIFEST.md` → VERSION).

**Phase:** II Catalog completeness (measured coverage), III Publish/redaction
(broadened redaction + gate-aware verdict), IV CLI/UX (`--json` everywhere) +
**Pillar 4 — Ask** (`gpt index`/`gpt ask`) and the unified cross-sweep format
(FR-D3).

**Success criteria (met):** `gpt ask` answers from the local index with recency
ranking, citations, and a privacy gate (FR-Q1–Q5, NFR-R4); `gpt state --all` +
`gpt report` express every sweep in one workload-grouped format (FR-D3);
`COORD-C-COVERAGE` is measured and `COORD-D-VERDICT` is gate-aware; `pytest -q`
green (NFR-Q1).

**Subtasks**

| Item | Progress |
|---|---|
| `gpt index` / `gpt ask` — local, cited, recency-ranked, privacy-gated (FR-Q1–Q5) | 100% |
| `gpt ask` follow-ups — `--json`, `--rerank`, char-offset citations, stale-index warning, keyword fallback | 100% |
| Unified cross-sweep — `gpt state --all` + `gpt report` grouped by workload (FR-D3) | 100% |
| Measured catalog coverage — `COORD-C-COVERAGE` (Phase II) | 100% |
| Gate-aware verdict + broadened redaction — JWT/PEM/IPv4 (Phase III) | 100% |
| `--json` on every read/benchmark command (Phase IV) | 100% |

### Added (1.0 follow-ups)
- **`gpt ask` enhancements (FR-Q follow-ups).** `--json` machine-readable
  output; `--rerank` lexical-overlap re-rank of the top-K; chunk-level
  citations (Sources carry char offsets); a stale-index warning when the
  catalog has grown past the index; and a keyword-scan fallback so `gpt ask`
  degrades gracefully instead of erroring when no index exists.
  *Tests:* `tests/test_embeddings.py` (offsets, rerank), `tests/test_ask_privacy.py`
  (`--json`, keyword fallback).
- **Measured extraction coverage (COORD-C-COVERAGE).** `gpt state` now derives
  catalog coverage from the extract ledger (`seen`/`skipped`/`written`) for both
  the single and `--all` paths instead of leaving it `unknown`; `--coverage`
  still overrides. *Tests:* `tests/test_project_state.py` (`CoverageFromStoreTest`).
- **Gate-aware verdict.** `COORD-D-VERDICT` carries mandatory-gate evidence
  (`GATE-COVERAGE`, `GATE-SCHEMA`) as native observations, so a failed gate is
  visible on the decision coordinate. *Tests:* `tests/test_project_state.py`.
- **Broadened redaction (NFR-P2/P3).** `redact` now also catches JWTs, PEM
  private-key blocks, and range-checked IPv4 addresses (version strings are not
  mistaken for IPs). *Tests:* `tests/test_redact.py`.

### Changed
- The `reconstruct` backward-compatible alias moved to `scripts/reconstruct`
  (invoke `./scripts/reconstruct ...`); `./gpt` remains the primary entrypoint.

### Added
- **`gpt ask` / `gpt index` — answer questions from your own chats (semantic,
  local, cited).** `gpt index` embeds reduced transcripts (chunked) with a local
  Ollama model (bge-m3 by default, `/api/embed`) into
  `$DATA_ROOT/index/{vectors.npy,chunks.jsonl,manifest.json}`, incrementally
  (re-embeds only chats whose content hash changed; `--rebuild` forces full).
  `gpt ask "what is the latest ADOS README.md format?"` embeds the question,
  retrieves the top-K chunks ranked by **similarity × recency** (so the latest
  chats win on near-ties; `--since` / `--half-life` tune it), and answers using
  only that context with inline `[n]` citations and a Sources list. Local-first:
  a cloud/CLI provider is refused unless `--scrub-cloud`, which redacts PII
  (NFR-P2 patterns) from the question + context first. New `scripts/lib/
  embeddings.py`, `scripts/index.py`, `scripts/ask.py`; tests in
  `tests/test_embeddings.py` (20), an offline privacy-gate suite
  `tests/test_ask_privacy.py` (4: cloud refused without `--scrub-cloud`, PII
  scrubbed before egress, local stays raw, no-index guidance), and live checks
  in `tests/test_ask_live.py`.
  Requirements FR-Q1–FR-Q5, NFR-R4. (`numpy` is now a dependency for these two
  commands; the rest of the CLI runs without it.)
- **`gpt state --all` + `gpt report` — one unified format for every sweep
  (FR-D3).** `gpt state --all` discovers every sweep under `$DATA_ROOT/runs`,
  maps each run-label to a **workload** (e.g. `cmp-oct2-*` → `oct2024-cmp`,
  `perf*-20260626` → `jun2026-perf`), and emits a schema-valid ADOS Project
  State per `(workload, model)` into `$DATA_ROOT/states/`. `gpt report` renders
  `docs/cross-sweep-report.md`: one coordinate-mapped table per workload, never
  averaging across workloads (different input sets aren't comparable). New
  `scripts/report.py`; workload + grouping tests in `tests/test_report.py`.

## ADOS Geometry — 2026-06-28

The evaluation instrument becomes a governed, drift-proof ADOS Project Geometry.
*(commit `a4712b6`; jun2026 173-bundle perf sweep doc landed just before in
`dda7b78`/`17c98e6`.)*

**Phase:** Governance (cross-cutting; not one of the four roadmap phases). Adopts
the **ADOS 0.8.20** lifecycle: `CHANGE-LOGS.md` → `CHANGELOG.md`,
`PLANNED-WORKS.md` → `TODO.md`, and `PLANNED-WORKS.md` forbidden in a strict
package (see `ados-vocabulary/ADOS-MAPPING.md`).

**Success criteria (met):** the evaluation is a schema-valid ADOS Project Geometry
+ Evaluation Rubric a validator enforces (`tests/test_geometry_valid.py`,
`tests/test_rubric_gates.py`); `gpt metrics` refuses an undeclared column; the
governed lifecycle surfaces are `CHANGELOG.md` + `TODO.md`.

**Subtasks**

| Item | Progress |
|---|---|
| ADOS Project Geometry — 8 coordinates / 3 deliveries, schema-valid | 100% |
| Evaluation Rubric — 5 axes Σ=100 + 3 mandatory gates | 100% |
| `gpt state` — append-only ADOS Project State | 100% |
| `gpt metrics` geometry-aware (declared-column guard) | 100% |
| ESSAY.md normative + `ADOS-MAPPING.md` vocabulary | 100% |
| Lifecycle naming (ADOS 0.8.20) — `TODO.md` / `CHANGELOG.md` | 100% |

### Added
- **ADOS Project Geometry: the benchmark is now a governed, drift-proof
  contract.** The evaluation is expressed as a schema-valid ADOS Project Geometry
  (`geometry/project-geometry.json`; 8 Project Coordinates across 3 Deliveries,
  each with explicit `measures` / `does_not_measure` / anchors / `coordinate_kind`)
  plus an Evaluation Rubric (`geometry/evaluation-rubric.json`; 5 scoring axes
  Σ=100 and 3 mandatory gates — GATE-PRIVACY/GATE-COVERAGE *fail*, GATE-SCHEMA
  *cap_50*). The five ADOS schemas live in `schema/ados/`. So the separation of
  reliability / depth / correctness is something a validator checks
  (`tests/test_geometry_valid.py`), not a convention a future edit can erode.
- **`gpt state` — append-only ADOS Project State.** Emits a schema-valid
  observation of each provider against the named coordinates from the same
  artifacts `gpt metrics` reads (`scripts/project_state.py`), so the tables
  become typed observations rather than prose that can re-blend.
- **`gpt metrics` is geometry-aware.** Every rendered quality/perf column is
  bound to a declared Project Coordinate; an undeclared column is refused until
  its `measures` / `does_not_measure` is declared in the Geometry — the durable
  guard against silently re-blending the quality axes (the original
  "smarter models score worse" bug). Rubric scoring with gate enforcement lives
  in `scripts/lib/rubric.py`.
- **ESSAY.md is now an ADOS normative document** (metadata header per PILLAR-17;
  `AUTHORITY_REF: project-geometry.json`), and `ados-vocabulary/ADOS-MAPPING.md`
  records the controlled-vocabulary mapping.
- **jun2026 perf sweep recorded** (`docs/benchmark-20260626.md`): the 173-bundle
  local run with measured Wh/item, used later as the `jun2026-perf` workload.

### Changed
- **Lifecycle naming (ADOS 0.8.20):** governed roadmap moved to `TODO.md`;
  `PLANNED-WORKS.md` demoted to an informal planning note (no longer a governed
  surface). `CHANGELOG.md` + `TODO.md` are the governed lifecycle surfaces.
- **`config/generated/model_benchmarks.json` regenerated** from one named sweep
  (`gpt gen-model-benchmarks --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex`):
  verdicts reproduce byte-for-byte from committed commands (FR-D2), confirming
  the canonical oct2024 27-bundle sweep is not conflated with jun2026.

### Fixed
- **Clean kill of a spilled/hung local model (NFR-R2).** Ollama socket timeouts
  are now terminal: `providers/base.py::_post_json` takes `retry_on_timeout` /
  `max_attempts`, and `ollama_provider` fails fast on a timeout (one clean kill)
  instead of retrying the 300 s timeout ~4×. Regression test in
  `tests/test_clean_kill.py`.
- **`gemma4:31b` now pins `num_ctx: 16384`** in the model bank, so a bare
  `gpt summarize --model gemma4:31b` stays 100% on the 24 GB GPU instead of
  falling back to `num_ctx=32768` and risking a CPU spill.

## Benchmark Validity — 2026-06-26

The correctness-aware benchmark metric and the structured/typed model bank — the
release where "depth ≠ correctness" was settled with accuracy + measured power.
*(commits `87821ce`, `ef75dad`.)*

**Phase:** I — Benchmark validity & the keep-vs-return re-decision.

**Success criteria (met):** `gpt metrics` reports completion / depth-on-success /
schema-valid / accuracy as separate columns (FR-B2/B3); structured output is
enforced with retry (FR-B4); a cloud pre-send scrubber gates cloud calls (NFR-P3);
`config/generated/model_benchmarks.json` verdicts are regenerated from the
corrected metric (FR-D2); the `AI_MODEL_TESTS.md` verdict is reproducible from
committed commands (FR-D1); `pytest -q` green (NFR-Q1).

**Subtasks**

| Item | Progress |
|---|---|
| Split reliability from quality — separate columns (FR-B2/B5) | 100% |
| Structured-output enforcement + retry (FR-B4) | 100% |
| Correctness — `accuracy%` adjudicated vs a reference (FR-B3) | 100% |
| Cloud pre-send scrubber gate (NFR-P3) | 100% |
| Token-exact cost + measured GPU Wh/item (FR-B6) | 100% |
| Data-derived verdicts regenerated; verdict reproducible (FR-D1/D2) | 100% |

### Added
- **Model bank redesign: structured billing + typed/generated benchmarks +
  faceted IQ.** `config/models.json` is now purely hand-curated with a structured
  `billing` object (`local` / `subscription` / `token`); subscription prices are
  normalized into a new `config/plans.json` registry (dated + sourced) and
  referenced by `billing.plan_id`. The free-text `note` verdicts move to a typed,
  machine-owned `config/generated/model_benchmarks.json` written by the renamed
  `scripts/gen_model_benchmarks.py` (alias `gpt gen-model-notes` kept) with
  **upsert** semantics (update/add, never delete). New ontology banks
  (`ontology/{cognitive_types,difficulty,verifiability}.json`) plus deterministic
  facet priors in `classify.py` and `gpt metrics quality --by-skill /
  --by-difficulty` + difficulty-weighted **IQ** (subjective items excluded). Every
  data file now validates against a JSON Schema in `schema/` (`models_bank`,
  `plans`, `model_benchmarks`, `pricing`, `ontology_banks`); new tests cover the
  upsert, schema validity, and cross-field invariants.
- **oct2024 benchmark finalized with accuracy + measured power.** The
  `AI_MODEL_TESTS.md` verdict and master table are rebuilt on the 27-bundle
  `oct2024` export (replacing the earlier 10-item run), now reporting
  **completion, depth-on-success, accuracy (adjudicated vs a `codex` reference),
  schema-validity, load-separated speed, and *measured* GPU Wh/item** as separate
  columns. Adding correctness flips the read: most local models emit clean JSON
  with the wrong archetype/domain (`qwen3:8b` 85% depth but 16% accuracy), and
  only the big reasoners (`gemma4:31b`, `qwen3.6`) classify well. The detailed
  companion write-up is `docs/benchmark-oct2024.md`. Verdict unchanged: the
  $1,400 card is not justified for this workload on output alone.
- **`gpt gen-model-benchmarks --runs GLOB --reference ref=<run>`**
  (`scripts/gen_model_benchmarks.py`; alias `gpt gen-model-notes`): the per-model
  verdicts can be regenerated from **one defined sweep** (e.g. `cmp-oct2-*`)
  instead of every run under `$DATA_ROOT`, and include an accuracy verdict. Makes
  FR-D2 regeneration reproducible; tests in `tests/test_gen_model_benchmarks.py`.

### Changed
- **`gpt arena` / `gpt metrics perf` now rank by real per-item speed**
  (`s/item`, lower is faster) instead of total `(input+output) tokens/sec`
  (`scripts/metrics.py`). Total throughput was inflated by how fast a model
  *ingests* large input bundles, so a model could top the table while actually
  finishing each item slower; ranking by `s/item` puts genuinely faster models
  on top and removes the ranking-inversion caveat from the README.
- **`gpt arena` / `gpt metrics quality` now grade objective and requirement
  depth** (count capped at 3, where 3 objectives map to the
  forming/speeding/governance triad) instead of scoring mere presence
  (`scripts/metrics.py`), so a single thin objective no longer scores like a
  full, governed set and the quality score better reflects model strength.

## gpt CLI & Subscription Providers — 2026-06-25

The single `gpt` entrypoint, read-only query commands, clean interrupts, and
plan-covered CLI providers. *(commits `66db9c7`, `eaa50d7`, `f054c5c`,
`fe086ce`, `e7f9193`, `fcc017d`, `6e0d16e`.)*

**Phase:** IV — CLI / UX polish & packaging (the foundation; `--json`-everywhere
and packaging landed later in "Semantics").

**Success criteria (met):** one `gpt <command>` entrypoint with name-driven models
(FR-U1); read-only query commands work offline; a confirmation gate previews
spend before any LLM call (FR-U2); Ctrl-C exits cleanly with an exit code `130`
(NFR-R2); `pytest -q` green (NFR-Q1).

**Subtasks**

| Item | Progress |
|---|---|
| `gpt` single entrypoint + name-driven model bank (FR-U1) | 100% |
| Read-only query commands (`list/search/show/info/...`) (FR-U3) | 100% |
| Confirmation / preview-before-spend gate (FR-U2) | 100% |
| Clean Ctrl-C handling across the pipeline (NFR-R2) | 100% |
| Subscription CLI providers (`codex`/`claude`) + auto-detect | 100% |

### Added
- **Local Ollama benchmark on an RTX 3090 (24 GB)** in the README: all 14
  installed generation models + the two free Cursor models run over the same
  10-item sample, with a quality/speed/reliability table and an economic verdict
  on whether the $1,400 GPU beats the free plan-covered cloud models (it does not
  for this workload). Model-bank `note`s now carry each model's benchmark verdict;
  the CPU-only build is marked `skip` (unusably slow). `models_bank` renders
  skipped entries distinctly.
- **Clean Ctrl+C handling** (`scripts/lib/interrupt.py`): interrupting any `gpt`
  command now prints a single `[interrupted] ^C · <command>` line instead of a
  Python traceback, and exits with the standard code `130`. When a command
  tracks progress it is included, e.g. `gpt search · 1,234 / 4,122 chats` or
  `gpt summarize · 12 / 181 items`. Nested pipeline subprocesses
  (`gpt run` → `extract`/`cluster`/`classify`/`bundle`, `gpt summarize`) relay
  the interrupt quietly so there are no stacked tracebacks across the process
  tree. New tests in `tests/test_interrupt.py`.
- **Model bank** (`config/models.json` + `scripts/lib/models_bank.py`): a single
  place mapping each model **name** to its **provider** and required options.
  `gpt summarize --model <name>` now resolves the provider, `--num-ctx`, and
  `--host` from the bank, so a model name alone is enough. `gpt summarize` with
  no arguments (or `--list-models`) prints the whole bank as a pick-list;
  installed Ollama models are auto-discovered and merged in. Personal additions
  go in `config/models.local.json` (gitignored).
- **`gpt` entrypoint** (with `reconstruct` kept as an alias) and a smart,
  no-arg status dashboard that reports parsed counts + next step, or points at
  an export and estimates parse time when nothing is parsed yet.
- **Read-only query commands**: `gpt list [GLOB]`, `gpt search GLOB`, `gpt cat`,
  `gpt info`, `gpt show SLUG`, `gpt doctor` (`scripts/gpt_cli.py` +
  `scripts/lib/store_query.py`).
- **Provider auto-detect** (`scripts/lib/provider_detect.py`): when `--provider`
  is omitted, the AI summary uses the first available of `codex → ollama → claude`.
- **Confirmation gate** (`scripts/lib/confirm.py`): all AI summary runs print a
  time/cost estimate and ask `[y/N]` first; `--noask` (alias `--yes`) bypasses,
  non-interactive runs refuse without it. `run --summarize` gained
  `--limit-summarize` and now forwards `--limit` correctly.
- `export_search_dirs` config key for the smart status zip suggestion; tests for
  store queries, provider detection, and the gate.
- **Clearer step names** in CLI output and docs: the opaque "Stage 1–4" labels
  are now **Extract → Cluster → Bundle** (deterministic) and **Summarize**
  (the AI summary step).
- **`gpt sum`** alias for `gpt summarize` (`scripts/gpt_cli.py`).
- **Subscription CLI providers** for Stage 4 so runs can use existing plans
  instead of pay-per-token APIs: `codex` (`codex exec`, ChatGPT plan) and
  `claude` (`claude -p`, Claude plan) join the existing `cursor` provider.
  The `claude` provider forces subscription auth via `CLAUDE_CODE_OAUTH_TOKEN`
  and drops `ANTHROPIC_API_KEY` from the child env so it cannot silently fall
  back to API billing.
- `--provider codex|claude` (model optional, like `cursor`); pricing entries
  marked `"subscription": true` so the estimator prints "covered by your
  plan/quota" instead of a misleading dollar figure.
- README "Use your subscription plans" runbook; `.env.example` gains `CODEX_BIN`,
  `CLAUDE_BIN`, `CLAUDE_CODE_OAUTH_TOKEN`; new `tests/test_providers.py`.

### Changed
- **Model bank listing**: the `free` tag moved off the left of each command and
  into the trailing `#` comment, so every printed line is a copy-pasteable
  `gpt summarize --model <name>` (`scripts/lib/models_bank.py`).

### Fixed
- **Summarize crash on malformed model output**: weak models (e.g. `gemma3:1b`)
  sometimes emit a bare string/list where the schema expects an object/array
  (`"primary_archetype": "software_app"`), which raised
  `AttributeError: 'str' object has no attribute 'get'` and aborted the entire
  run. `build_item` (and the live log line) now coerce such fields to the
  deterministic prior via `_as_obj`/`_as_list`/`_as_text`, and the cleaners no
  longer iterate a stray string character-by-character. New regression tests in
  `tests/test_summarize_sanitize.py`.
- **Cursor provider blocked headless**: `cursor-agent` prompted "Do you trust the
  contents of this directory?" and failed every item in `--print` mode. The
  provider now passes `--trust` (`scripts/lib/providers/cursor_provider.py`).
- **Summarize schema validation**: smaller models (e.g. `llama3.1:8b`) emitted
  `""`/`null` for OPTIONAL fields, ending a clean run in schema errors
  (`objectives[].role`, `deliveries[].materiality` empty-enum;
  `deliveries[].kind` null). `build_item` now sanitizes LLM output — blank/invalid
  optional enums and strings are dropped (the schema accepts an enum member or the
  field's absence), text-less `objectives`/name-less `deliveries`/change-less
  `requirements_evolution`/id-less `secondary_archetypes`/domain-less
  `secondary_domain_pairs` entries are pruned, and `confidence` is clamped to
  `[0, 1]`. New `tests/test_summarize_sanitize.py`.

## Initial public split — ADOS archetype extraction + multi-provider LLM — 2026-06-24

Major redesign. Split out of the former `chatgpt-project-reconstructor` monorepo
into this lean public `chatgpt-extract` plus the private `chatgpt-extract-catalog`
(run catalog, summaries, cross-run stats). *(initial public commit `5b7c90a`;
this work was `2.0.0` of the predecessor monorepo — the standalone repo restarts
its own version line at `1.0.0` above.)*

**Phase:** Foundation (pre-roadmap; establishes the pipeline the four phases
build on).

**Success criteria (met):** every item carries an ADOS Primary Archetype +
Primary Domain/Subdomain Pair conforming to `schema/extracted_item_schema.json`;
the deterministic-first, LLM-last pipeline runs across `ollama`/`openai`/
`anthropic`/`cursor` with a pre-run cost estimate + budget gate; raw data stays
out of git.

**Subtasks**

| Item | Progress |
|---|---|
| ADOS-grounded ontology (archetypes / domains) + versioned bank | 100% |
| Archetype-conditioned schema (`if/then`, objectives, deliveries) | 100% |
| Deterministic classify prior (`classify.py`) from signals | 100% |
| Multi-provider Stage 4 (`ollama`/`openai`/`anthropic`/`cursor`) | 100% |
| Cost control + circuit breakers + traceability | 100% |

### Added
- **ADOS-grounded ontology** (`ontology/archetypes.json`, `ontology/domains.json`,
  `ontology/README.md`) — a versioned Reference Model Bank. Every item now gets a
  **Primary Archetype** + **Primary Domain/Subdomain Pair** instead of a forced
  software-project shape.
- **New schema** `schema/extracted_item_schema.json` (+ public variant) with
  archetype-conditioned fields enforced via `if/then`, ADOS objectives
  (forming/speeding/governance), and deliveries (material/supporting).
- **`scripts/classify.py`** — deterministic archetype/domain prior (auditable),
  fed by new per-conversation **signals** from `extract_cards`.
- **Multi-provider Stage 4** (`scripts/summarize.py`, `scripts/lib/providers/`):
  `ollama` (local, $0), `openai`, `anthropic`, `cursor`.
- **Cost control** (`config/pricing.json`, `scripts/lib/cost.py`): pre-run USD
  estimate + budget gate (`--max-usd`, `--max-usd-per-item`), per-call ledger.
- **Circuit breakers**: consecutive-failure, 429/5xx backoff, cumulative-spend.
- **Traceability** (`scripts/lib/trace.py`): atomic writes, JSONL call trace,
  optional jsonschema validation (patterns reused from `ollama-test`).

### Changed
- Stage 1 now drops junk "zips" (attachment hashes, bare-numeric downloads) so
  they cannot inflate version/Pass counts.
- Stage 2 adds a `--merge-cap` guard so a generic title slug can no longer absorb
  dozens of unrelated chats into a catch-all blob (the old `ados-profile`).
- `summarize` replaces `summarize_ollama`; `reconstruct summarize` and `ollama.sh`
  now drive the provider-agnostic summarizer.
- `export_public.py` rewritten for the `items[]` schema (renders archetype/domain).

### Removed
- Legacy `schema/project_history_schema.json` (+ public) — replaced (Option A).
- Run catalog / run summaries (`runs.py`, `collect_run_stats.py`, `run_catalog.py`)
  moved to `chatgpt-extract-catalog`. `reconstruct runs|summary` now point there.
