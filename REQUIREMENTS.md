# REQUIREMENTS.md

Requirements the agent building the next versions of **chatgpt-extract** must
satisfy. Each requirement is testable. IDs are stable and are referenced by
`TODO.md` (the consolidated roadmap, including the former phase plans) and
`CHANGELOG.md`.

**Conventions.** MUST = mandatory; SHOULD = strong default, deviation must be
justified; MAY = optional. Each requirement names its **verification** (a test,
a command, or an artifact check). A **[IMPLEMENTED]** tag means the requirement
is satisfied in the current tree (see `CHANGELOG.md` for the release); untagged
requirements remain targets for the next version. A **[DEFERRED]** /
**[ON HOLD]** tag marks an intentionally-postponed requirement.

---

## 1. Functional requirements

### Pillar 1 — Catalog (extraction & classification)

- **FR-C1 — Lossless canonical extraction. [IMPLEMENTED]** The extractor MUST stream any
  ChatGPT export `.zip` (single or sharded `conversations-NNN.json`) with bounded
  memory, reconstruct the canonical `current_node → root` branch, and never crash
  on object-valued multimodal `parts`.
  *Verify:* existing `test_*` parsing tests pass on a sharded and a single-file
  fixture; memory stays bounded on a ≥1 GB fixture.
- **FR-C2 — Content-type coverage is explicit and auditable. [IMPLEMENTED]** The extractor
  MUST handle, or **explicitly tag-and-log** (never silently drop), every
  `content_type` present in the export, including at minimum: `text`,
  `multimodal_text`, `code`, `user_editable_context`, and the browsing/tool/
  reasoning families (`tether_quote`, `tether_browsing_display`,
  `execution_output`, reasoning/thoughts). Unknown shapes MUST degrade to a
  labelled placeholder and emit a one-line `ulog` warning.
  *Verify:* a `gpt diagnose`/coverage report lists every `content_type` seen with
  a count and a handled/placeholder flag; no shape produces an empty transcript
  without a warning.
- **FR-C3 — Capture available message metadata. [IMPLEMENTED]** The extractor SHOULD capture
  per-message `model_slug`, `metadata.attachments` (filenames only), and tool/
  plugin author names into the card, so the catalog can answer "which model
  produced this" and "what files were attached." It MUST NOT capture
  `user.json` PII (email, name, account id) into any artifact.
  *Verify:* a card schema test asserts the new fields exist when present in the
  source and that `user.json`-derived PII never appears.
- **FR-C4 — Incremental, idempotent store. [IMPLEMENTED]** Re-running extraction on a newer
  cumulative export MUST update only changed chats (newer `update_time` wins) and
  MUST be safe to interrupt and resume.
  *Verify:* re-run on an unchanged export performs no rescan (ledger hash short-
  circuit); re-run on a changed export updates only the delta.
- **FR-C5 — Deterministic facts are authoritative. [IMPLEMENTED]** Dates, `version_zip_files`,
  `file_artifacts`, ids, and counts MUST be copied verbatim into the final record
  and merged **over** any LLM output. The LLM MUST never be trusted to produce
  them.
  *Verify:* `tests/test_content_coverage.py`
  (`BuildCardIntegrationTest::test_round_trip_no_silent_drop`);
  `summarize.py::build_item` copies the deterministic facts from the cluster
  verbatim (the LLM is never consulted for them, so it cannot overwrite them).

### Pillar 2 — Benchmark (model/provider evaluation)

- **FR-B1 — Apples-to-apples harness. [IMPLEMENTED]** The benchmark MUST build the
  deterministic stage once and run every model against the **same** bundles, each
  under its own `--run-label`, with held-constant context and no cross-run
  overwrite.
  *Verify:* two model runs leave isolated `runs/<label>/` outputs; the slug set is
  identical across runs.
- **FR-B2 — Separate reliability from quality. [IMPLEMENTED]** `gpt metrics` MUST report
  **completion%**, **depth-on-success%** (failed items excluded), and a
  **schema-valid-JSON rate** as **distinct columns**, and MUST NOT collapse them
  into a single blended rank key. (Closes the artifact in `AI_MODEL_TESTS.md`
  §3.5.)
  *Verify:* `gpt metrics quality --json` emits the three fields; a fixture with
  known failures yields the arithmetic the spec predicts.
- **FR-B3 — Correctness measurement. [IMPLEMENTED]** The benchmark MUST provide a correctness
  path: surface archetype/domain disagreements vs a reference (`gpt compare`),
  support adjudication of a labelled sample against source bundles, and report an
  **accuracy%** alongside depth%.
  *Verify:* `gpt metrics quality --correctness ref=<run>` produces an accuracy
  column on a labelled fixture.
- **FR-B4 — Enforced structured output with retry. [IMPLEMENTED]** Each provider that emits
  JSON MUST request structured output where the backend supports it (Ollama
  `format=json` / a JSON grammar) and MUST retry on parse failure (bounded
  retries) before recording `LLM_FAIL`.
  *Verify:* a provider unit test asserts `format=json` is set and that a single
  malformed response triggers exactly one retry.
- **FR-B5 — Honest failure recording. [IMPLEMENTED]** A failed item MUST remain visible (the
  deterministic-prior fallback is retained) but MUST be **flagged** so downstream
  metrics and the catalog can distinguish a real LLM record from a fallback.
  *Verify:* the per-item record carries a `classification_source`/`llm_ok` flag;
  `gpt metrics` excludes fallbacks from depth-on-success.
- **FR-B6 — Cost and power capture. [IMPLEMENTED]** The benchmark SHOULD record token-exact
  cloud cost where the provider returns usage, and MUST support metering GPU power
  (`nvidia-smi --query-gpu=power.draw`) during a run to compute Wh/item.
  *Verify:* a metered run writes a power trace; `gpt metrics` can report $/1,000
  items and Wh/item.

### Pillar 3 — Decision

- **FR-D1 — Reproducible verdict. [IMPLEMENTED]** The decision report (`AI_MODEL_TESTS.md`)
  MUST be regenerable from artifacts under `$DATA_ROOT` by documented read-only
  commands, and MUST state the keep-vs-return rule as explicit conditions.
  *Verify:* running the §10 commands reproduces the §4 tables.
- **FR-D2 — Verdicts are data-derived. [IMPLEMENTED]** The per-model benchmark verdicts MUST be
  generated from the corrected metric (FR-B2/B3) into the typed, machine-owned
  `config/generated/model_benchmarks.json` (NOT hand-written into the curated
  `config/models.json`), and MUST be regenerated when the metric changes.
  *Verify:* `scripts/gen_model_benchmarks.py` writes the sidecar and `--check`
  asserts it matches the latest metric; the file validates against
  `schema/model_benchmarks.schema.json`.
- **FR-D3 — Unified cross-sweep format. [IMPLEMENTED]** Every historical sweep
  MUST be expressible in **one latest format**, with scores grouped by
  **workload** (the input set) and never averaged across workloads. `gpt state
  --all` MUST emit a schema-valid ADOS Project State per `(workload, model)`
  into `$DATA_ROOT/states/<workload>__<model>.json`; `gpt report` MUST render a
  cross-sweep markdown report grouped by workload, with columns mapped to named
  Project Geometry coordinates (reusing the `gpt metrics` declared-column
  guard).
  *Verify:* `tests/test_report.py` (workload grouping, full `(workload, model)`
  coverage, columns map to declared coordinates, same model in two workloads is
  never merged); `gpt state --all` over `$DATA_ROOT/runs` then `gpt report`
  produces `docs/cross-sweep-report.md`.

### Pillar 4 — Ask (semantic retrieval & answering)

Answer free-form questions over the user's own chat history ("what is the
latest ADOS README.md format?", "what are the ados-evaluate skills?"), grounded
in the most recent chats on the topic. Implemented as the local agent
`gpt index` (build) + `gpt ask` (answer).

- **FR-Q1 — Local semantic index. [IMPLEMENTED]** `gpt index` MUST embed the
  reduced transcripts (chunked) with a **local** Ollama embedding model
  (`/api/embed`; bge-m3 by default), and persist `vectors.npy`, `chunks.jsonl`
  (chat id, title, update_date, char span, text) and `manifest.json` (model,
  dim, per-chat content hash) under `$DATA_ROOT/index/`. It MUST be incremental
  — re-embedding only chats whose content hash changed — with `--rebuild` to
  force a full pass.
  *Verify:* `tests/test_embeddings.py` (`BuildIndexTest`: ordering, manifest
  offsets, write/load round-trip, incremental reuse, re-embed on change,
  `--rebuild`).
- **FR-Q2 — Grounded, cited answers. [IMPLEMENTED]** `gpt ask` MUST retrieve the
  top-K chunks for the question, answer using **only** the retrieved context,
  print inline `[n]` citations, and back them with a **Sources** list (title ·
  date · `id=`). When the retrieved context does not contain the answer it MUST
  NOT guess (see **FR-Q11**); Sources are shown on demand (see **FR-Q10**). If no
  index exists it MUST tell the user to run `gpt index`.
  *Verify:* `tests/test_embeddings.py` (`PromptTest`); `tests/test_ask_live.py`
  (`AskSynthesisLiveTest`, opt-in) asserts a cited answer + Sources end to end.
- **FR-Q3 — Recency-aware ranking. [IMPLEMENTED]** Ranking MUST combine cosine
  similarity with an exponential **recency** weight (configurable half-life) so
  the *latest* chats win on near-ties; `--since` MUST drop older chats and
  `--half-life 0` MUST disable decay.
  *Verify:* `tests/test_embeddings.py` (`RecencyTest`, `RetrieveTest`
  recency tie-break + `--since`); `tests/test_ask_live.py` separates topics by
  meaning with decay disabled.
- **FR-Q4 — Local-first, privacy-gated. [IMPLEMENTED]** `gpt ask` MUST default
  to a local provider (no data egress). A cloud/CLI provider MUST be refused
  unless `--scrub-cloud`, which redacts PII (the `redact.py` pattern set, NFR-P2)
  from the question **and** retrieved context before anything leaves the box.
  *Verify:* `tests/test_ask_privacy.py` (offline) — a cloud provider returns
  exit 2 with no embed/provider call unless `--scrub-cloud`; with the flag,
  planted email/path PII is replaced by typed placeholders in the prompt the
  provider receives; the local Ollama path needs no flag and passes the raw
  context through.
- **FR-Q5 — Degrades without numpy. [IMPLEMENTED]** `gpt index`/`gpt ask` MUST
  fail with a clear, actionable message when numpy is missing; the rest of the
  CLI MUST import and run unaffected (numpy imported lazily).
  *Verify:* `gpt doctor` reports the numpy line; `scripts/lib/embeddings.py`
  imports cleanly and only the vector-math helpers require numpy.

#### Ask v1.2 — output, routing, GPU, and the warm daemon

The requirements below were raised and implemented in this iteration. The
crosswalk maps the discussion IDs (REQ-*) to the stable FR-Q IDs. Key files:
[scripts/ask.py](scripts/ask.py), [scripts/ask_daemon.py](scripts/ask_daemon.py),
[scripts/lib/ask_route.py](scripts/lib/ask_route.py),
[scripts/lib/ollama_probe.py](scripts/lib/ollama_probe.py),
[scripts/lib/warm_engine.py](scripts/lib/warm_engine.py),
[scripts/lib/models_bank.py](scripts/lib/models_bank.py), [run.py](run.py).

- **FR-Q6 — Answer output is clean and informative. [IMPLEMENTED]**
  (REQ-1/REQ-2/REQ-3.) The answer MUST print with no stray blank line; a bottom
  **status line** MUST carry start time, duration (s), token budget, and model
  name; the `(N references across M chats)` note MUST sit under the `Sources:`
  header, not inside the answer sentence.
  *Verify:* `ask.status_line` / `ask.format_sources`; exercised by
  `tests/test_ask_live.py`.
- **FR-Q7 — Sources on demand. [IMPLEMENTED]** (REQ-4/REQ-Output1.) The cited
  Sources list (chat title + `id=` + char span) MUST be hidden by default and
  shown with `--show-sources`; the former `--details` flag MUST keep working as a
  hidden alias.
  *Verify:* `tests/test_ask_route.py`
  (`test_show_sources_controls_source_visibility`, `test_details_alias_still_works`).
- **FR-Q8 — No guessing: "Not found in chat data." [IMPLEMENTED]**
  (REQ-Output2.) If retrieval is empty, or any engine (local or cloud) returns a
  non-grounded / "couldn't find it" reply, `gpt ask` MUST emit exactly
  `Not found in chat data.` (no sources, exit 0) rather than a freelance guess.
  *Verify:* `ask.is_not_found`; `tests/test_ask_route.py`
  (`test_no_hits_reports_not_found`, `test_model_refusal_collapses_to_not_found`,
  `NotFoundUnitTest`); `tests/test_ask_daemon.py` (`test_no_hits_returns_not_found`).
- **FR-Q9 — Wall-clock budget (design driver, not a fixed kill). [IMPLEMENTED]**
  (REQ-5.) `--budget` is a wall-clock cap on synthesis defaulting to **60s**;
  `--budget 0` MUST disable the abort (indicator only); a model that exceeds the
  budget MUST be reported `[unusable]` (exit code 3), never left to hang; a live
  "working…" indicator MUST show a slow synthesis is alive on a TTY.
  *Verify:* `tests/test_ask_budget.py` (`test_over_budget_synthesis_is_unusable`);
  `tests/test_ask_route.py` (`BudgetDefaultTest`, `test_budget_zero_disables_unusable_abort`).
- **FR-Q10 — GPU residency hard-block. [IMPLEMENTED]** (REQ-6.) `gpt ask` MUST
  refuse to run local Ollama on CPU (too slow for interactive use): `--require-gpu`
  is the default and `--allow-cpu` opts out. Residency MUST be detected from
  Ollama `/api/ps` VRAM share. A hard block with no fallback MUST exit `EXIT_NO_GPU` (4).
  *Verify:* `scripts/lib/ollama_probe.py` (`model_gpu_state`);
  `tests/test_ask_route.py` (`test_forced_ollama_without_gpu_is_blocked`,
  `test_allow_cpu_skips_gpu_probe`).
- **FR-Q11 — Capability router. [IMPLEMENTED]** (REQ-7.) With routing on (default),
  `gpt ask` MUST auto-route to the most capable **available** engine: local GPU
  Ollama, else the best signed-in cloud engine in `codex → claude → cursor` order.
  `--no-route` MUST force an explicit `--provider`; `--prefer` MUST reorder the
  cloud try-list. A forced cloud provider MUST still pass the FR-Q4 privacy gate.
  *Verify:* `scripts/lib/ask_route.py`; `tests/test_ask_route.py`
  (`PlanRouteTest`, `RouteIntegrationTest`).
- **FR-Q12 — Model table + `--list-models`. [IMPLEMENTED]** (REQ-7a/REQ-Models1.)
  Because every question is one business area, there is no question-aware routing;
  instead `gpt ask --list-models` MUST list each bank model with a ready-to-paste
  `gpt ask "…"` command carrying the right per-model flags (local shows
  `[--allow-cpu]`, cloud shows `--scrub-cloud`). The table is the model bank
  (`config/models.json` via `models_bank`).
  *Verify:* `ask.format_model_commands`; `tests/test_ask_route.py`
  (`ListModelsTest`).
- **FR-Q13 — Plain-language privacy flag. [IMPLEMENTED]** (REQ-Doc2.)
  `--scrub-cloud` help MUST be written so a non-expert understands it: it lets
  chat data leave THIS computer (blanks personal info, then a cloud/CLI model over
  the internet answers); off = data never leaves the machine.
  *Verify:* `gpt ask --help`.
- **FR-Q14 — Warm, router-aware daemon (default on). [IMPLEMENTED]**
  (REQ-Daemon1–7 / F1.) One **single** shared daemon MUST hold the index, embedder,
  entities, and at most one warm CLI engine resident, owning the router so it
  serves both local Ollama and cloud engines and **switches the active engine/
  model on change**. It MUST be the default (`gpt ask` auto-starts and reuses it;
  `--no-daemon` opts out; `--daemon` requires an already-running one), be
  single-instance, exclude its one-time startup from the answer budget, report
  whether it was used and its **pid** in the status line, never generate in the
  background (no idle token cost) while keeping each request isolated (no
  cross-question bleed), and expose detailed status via `gpt ask --stats`
  (pid, uptime, CPU, token budget, time-in-answers, requests served, history).
  *Verify:* `scripts/ask_daemon.py`; `tests/test_ask_daemon.py` (socket round-trip,
  stats/history, not-found, gate rc, warm-engine model switching).
- **FR-Q15 — No stale index by design. [IMPLEMENTED]** (F4.) The catalog MUST NOT
  be able to out-grow the index silently. `gpt run`/`gpt all` MUST run an
  incremental, embedder-gated index step after Bundle; `gpt ask` MUST self-heal a
  small catalog/index delta inline (incremental re-embed) and only defer a very
  large delta to an explicit `gpt index`. The alarming "run gpt index" nag is
  removed.
  *Verify:* `run.py` (`maybe_index`, embedder-gated, best-effort); `ask.index_delta`
  + `ask.auto_refresh_index`.
- **FR-Q16 — 15s interactive latency target. [ON HOLD]** (MAIN-REQ-TIMEBUDGET;
  formerly mislabelled "REQ-5a".) The most capable available route SHOULD answer
  within **15s** — the architectural proof that the design (routing + warm daemon)
  is correct. Held until the items above settle; tracked with `--budget 15` +
  `gpt ask-eval`.
- **FR-Q17 — Local GPU offload actually works on WSL2. [DEFERRED]** (F3.) Today
  Ollama's llama-server GPU-discovery watchdog times out under WSL2 and silently
  falls back to CPU despite an RTX 3090 visible to `nvidia-smi`; FR-Q10 hard-blocks
  CPU and FR-Q11 routes to cloud so `gpt ask` stays usable. Next release MUST make
  local GPU offload work (CUDA/Vulkan discovery for the systemd Ollama service),
  not merely route around it. Promoted to a core requirement for that release.

**Exit codes (Ask).** `0` answered (incl. the grounded `Not found in chat data.`);
`2` bad usage / privacy gate (cloud without `--scrub-cloud`); `3` `EXIT_UNUSABLE`
(over budget); `4` `EXIT_NO_GPU` (no GPU, CPU not permitted, no cloud engine).

**Crosswalk (discussion → stable ID).** REQ-1/2/3 → FR-Q6; REQ-4/REQ-Output1 →
FR-Q7; REQ-Output2 → FR-Q8; REQ-5 → FR-Q9; REQ-6 → FR-Q10; REQ-7 → FR-Q11;
REQ-7a/REQ-Models1 → FR-Q12; REQ-Doc2 → FR-Q13; REQ-Daemon1–7 / F1 → FR-Q14;
F4 → FR-Q15; MAIN-REQ-TIMEBUDGET → FR-Q16; F3 → FR-Q17; REQ-Doc1 → FR-U4;
REQ-Persist1 / F2 → this file.

### Cross-cutting — CLI / UX

- **FR-U1 — Single entrypoint, name-driven models. [IMPLEMENTED]** `gpt <command>` MUST remain
  the one entrypoint; `--model <name>` MUST resolve provider + options from the
  model bank (+ `models.local.json`).
- **FR-U2 — Preview before spend. [IMPLEMENTED]** Any LLM command MUST show an estimate and a
  confirmation gate; `--noask` and `--max-usd` MUST be honoured; a budget trip
  MUST stop cleanly and resumably.
- **FR-U3 — State at a glance. [IMPLEMENTED]** `gpt info` MUST summarise catalog state and last
  run in one screen; query commands (`list/search/category/show`) MUST be
  read-only and work offline.
- **FR-U4 — Docs track big changes. [IMPLEMENTED]** (REQ-Doc1.) Any big change MUST
  update the README and `--help` in the same change. Covered this iteration for
  daemon-default, `--show-sources`, `--list-models`, `--scrub-cloud` wording, the
  not-found contract, routing/GPU, and the no-stale-index design.
  *Verify:* `README.md` Ask section + command table; `gpt ask --help`.

---

## 2. Non-functional requirements

### Privacy & security

- **NFR-P1 — Data never enters git. [IMPLEMENTED]** Raw exports, transcripts, bundles, and the
  full internal JSON MUST be gitignored; the `check_no_secrets.sh` pre-commit
  hook MUST block staging of any personal path or export zip.
  *Verify:* `test_check_no_secrets` + `test_repo_hygiene`; the hook fails on a
  staged `output/` path.
- **NFR-P2 — Publish boundary actively redacts. [IMPLEMENTED]** `gpt publish` MUST drop
  provenance fields, basename-only zip paths, and `--review` MUST fail the export
  on any detected email / home path. The detector pattern set MUST be broadened
  beyond emails+paths to include phone numbers, obvious tokens/keys, and
  **MUST transform, not only warn**, when run with a `--scrub` flag.
  *Verify:* `test_export_public` + a new test that `--scrub` replaces a planted
  email/path/phone with a placeholder.
- **NFR-P3 — Cloud pre-send scrubber. [IMPLEMENTED]** Before any bundle is sent to a **cloud**
  provider, the agent MUST offer (and, under a privacy flag, enforce) a redaction
  pass over the bundle, so personal transcripts are not sent off-machine
  unredacted. The local Ollama path MUST remain fully offline.
  *Verify:* with the privacy flag set, a cloud provider call receives a scrubbed
  bundle (planted PII absent from the payload).
- **NFR-P4 — No PII in logs. [IMPLEMENTED]** `ulog`/trace output MUST NOT contain transcript
  content or home paths.
  *Verify:* a log-scan test over a sample run.

### Performance & resource

- **NFR-R1 — Bounded memory on large archives. [IMPLEMENTED]** Extraction MUST stay within a
  fixed memory ceiling regardless of archive size (ijson streaming; documented
  fallback warning when ijson is absent).
- **NFR-R2 — Runs on the target box. [IMPLEMENTED]** The full deterministic build + a
  `--limit 50` local summary MUST complete on the Dell 5820 / RTX 3090 / 120 GB
  RAM within documented time, and any model that spills to CPU or hangs MUST be
  killed by a per-model timeout.
- **NFR-R3 — Resumability. [IMPLEMENTED]** Every LLM run MUST persist after each item so a
  killed run resumes without re-spending.
- **NFR-R4 — Index build is local, offline, incremental. [IMPLEMENTED]**
  Building the semantic index MUST run entirely against the local Ollama host
  (no cloud, $0 marginal cost) and re-embed only changed chats on a re-run, so
  refreshing after a new export is cheap.
  *Verify:* `tests/test_embeddings.py` incremental-reuse test; embeddings hit
  only `/api/embed` on the configured local host.

### Quality, portability, maintainability

- **NFR-Q1 — Tests green, deterministic core covered. [IMPLEMENTED]** `pytest -q` MUST pass;
  schema round-trip, redaction, secrets hook, provider detection, and the
  corrected metric MUST be covered.
- **NFR-Q2 — WSL-first, dependency-light. [IMPLEMENTED]** The toolkit MUST run on WSL2 Ubuntu
  with a Python venv and standard CLIs; heavy/optional deps (ijson, provider
  CLIs) MUST be optional with graceful degradation.
- **NFR-Q3 — Schema-versioned outputs. [IMPLEMENTED]** Internal and public JSON MUST carry an
  `ontology_version`; schema changes MUST bump it and keep a documented migration
  (`port_legacy.py` pattern).
- **NFR-Q4 — Auditability. [IMPLEMENTED]** Every catalog record MUST be traceable to its source
  (provenance kept internally, dropped on publish) and to whether it was
  LLM-produced or a deterministic fallback (FR-B5).
- **NFR-Q5 — No scope drift. [IMPLEMENTED]** Changes MUST be confined to the pillar they target;
  the GOAL and OBJECTIVES (README) MUST NOT change without an explicit decision
  recorded in `TODO.md`.

---

## 3. Acceptance summary

The original definition of done — full content-type coverage (FR-C2) with no
silent drops; `gpt metrics` reporting completion / depth-on-success / schema-valid
/ accuracy as separate columns (FR-B2/B3); enforced structured output with retry
(FR-B4); an actively-scrubbing publish path (NFR-P2) and a cloud pre-send scrubber
(NFR-P3); regenerated `config/generated/model_benchmarks.json` verdicts (FR-D2);
and a green `pytest -q` (NFR-Q1) — **has been met as of `1.0.0` "Semantics"**.
Every requirement above now carries `[IMPLEMENTED]`.

As of `1.1.0` "Provenance", `GATE-PRIVACY` evidence is surfaced on
`COORD-D-VERDICT` from the cloud pre-send scrubber, `gpt info` reflects the
read-only cross-run catalog, and the catalog repo's vendored libs are pinned via
`VENDORED_FROM` — completing roadmap Phases III and IV.

As of `1.2.0` "Ask routing", the Ask pillar gained a capability router (FR-Q11),
a GPU residency hard-block (FR-Q10), a flexible wall-clock budget (FR-Q9), a
single warm router-aware daemon that is on by default (FR-Q14), `--show-sources`
(FR-Q7), `--list-models` (FR-Q12), the grounded "Not found in chat data." contract
(FR-Q8), and **no stale index by design** (FR-Q15) — closing the former "Next"
item *index auto-refresh at the end of `gpt run`*. The done-criteria for the
**next** version are: the **15s interactive latency target** (FR-Q16, on hold),
**working local GPU offload on WSL2** (FR-Q17, deferred → core), and a true
cross-encoder re-rank.

## 4. Implemented in the current release

Satisfied in this tree (verified by `pytest -q` — green):

- **`GATE-PRIVACY` evidence (NFR-P3, 1.1.0)** — `gpt summarize` persists the
  cloud pre-send scrubber result (`cloud_provider`/`scrub_cloud`/`scrub_hits`)
  to the run manifest and `gpt state` emits a `GATE-PRIVACY` native on
  `COORD-D-VERDICT`: local providers pass offline, cloud providers pass only with
  recorded scrub hits, an unscrubbed cloud call fails. *Tests:*
  `tests/test_project_state.py` (`PrivacyGateTest`).
- **Cross-run observability in `gpt info` (NFR-Q4, 1.1.0)** — `gpt info` reads
  `output/runs/catalog.json` read-only (written by `chatgpt-extract-catalog`) and
  shows a Runs summary, preserving the tool-writes / catalog-summarizes split.
  *Tests:* `tests/test_store_query.py`.
- **Vendored-lib pinning (NFR-Q2, 1.1.0)** — the catalog repo's vendored
  `paths.py`/`ulog.py`/`run_log.py` carry `VENDORED_FROM` markers pinned to a
  recorded upstream commit, refreshed by `scripts/sync_vendored.py` and guarded
  by `tests/test_vendored.py`. *(Catalog repo.)*
- **Ask / semantic answering agent (FR-Q1–FR-Q5, NFR-R4)** — `gpt index` builds
  a local, incremental embedding index; `gpt ask` answers questions from your
  chats with recency-weighted retrieval, inline citations, a Sources list, and a
  local-first privacy gate (`--scrub-cloud` for any off-box provider).
  *Tests:* `tests/test_embeddings.py` (20), `tests/test_ask_privacy.py` (offline
  privacy gate), `tests/test_ask_live.py` (live, skipped when Ollama is down).
- **Ask routing, GPU gate, budget, daemon (FR-Q6–FR-Q15, 1.2.0)** — clean output
  + status line; `--show-sources`; grounded "Not found in chat data."; flexible
  `--budget` (default 60, `--budget 0` off, over-budget → exit 3) with a live
  working indicator; GPU residency hard-block (`--allow-cpu` to opt out); a
  capability router (local GPU → codex → claude → cursor; `--no-route`/`--prefer`);
  `--list-models`; a single warm router-aware daemon on by default (auto-start,
  reuse, single-instance, startup excluded from budget, pid in status, `--stats`,
  model switching); and a self-healing index (no stale index by design). *Tests:*
  `tests/test_ask_route.py`, `tests/test_ask_daemon.py`, `tests/test_ask_budget.py`,
  `tests/test_warm_engine.py`, `tests/test_ask_privacy.py`, `tests/test_ask_live.py`.
- **Unified cross-sweep format (FR-D3)** — `gpt state --all` re-expresses every
  historical sweep as ADOS Project States per `(workload, model)`; `gpt report`
  renders `docs/cross-sweep-report.md` grouped by workload (never averaged
  across workloads). `--reference` is threaded through the batch path so
  `COORD-B-ACCURACY` populates per workload. *Tests:* `tests/test_report.py`.
- **Measured catalog coverage (COORD-C-COVERAGE)** — `gpt state` derives
  extraction coverage from the extract ledger (`seen`/`skipped`/`written`) for
  both the single and `--all` paths; `--coverage` overrides. *Tests:*
  `tests/test_project_state.py` (`CoverageFromStoreTest`).
- **Gate-aware verdict + broadened redaction (NFR-P2/P3)** — `COORD-D-VERDICT`
  carries `GATE-COVERAGE` / `GATE-SCHEMA` evidence; `redact` also catches JWTs,
  PEM private-key blocks, and range-checked IPv4. *Tests:*
  `tests/test_project_state.py`, `tests/test_redact.py`.
- **Catalog pillar (FR-C1–FR-C5)** — bounded-memory streaming extraction;
  explicit, auditable content-type coverage (`tether_*`, `execution_output`,
  reasoning) with labelled placeholders for unknown shapes; per-message
  `model_slug` + attachments on the card; incremental idempotent store;
  deterministic facts copied verbatim over LLM output. *Tests:*
  `tests/test_content_coverage.py`, `tests/test_extract_limit.py`.
- **Benchmark pillar (FR-B1–FR-B6)** — apples-to-apples per-run isolation;
  separate completion / depth-on-success / schema-valid columns; adjudicated
  `accuracy%` vs a reference; enforced `format=json` + bounded retry; honest
  failure flags (`llm_ok` / `classification_source`); token-exact cost + metered
  GPU Wh/item. *Tests:* `tests/test_metrics_quality.py`,
  `tests/test_structured_output.py`, `tests/test_cost.py`, `tests/test_power.py`.
- **Decision pillar (FR-D1, FR-D2)** — a reproducible `AI_MODEL_TESTS.md` verdict
  regenerable from committed read-only commands; data-derived per-model verdicts
  in the typed `config/generated/model_benchmarks.json` (schema-checked, upsert).
  *Tests:* `tests/test_gen_model_benchmarks.py`.
- **CLI / UX (FR-U1–FR-U4)** — single `gpt` entrypoint with name-driven model
  resolution; preview-before-spend confirmation gate; `gpt info` state at a glance
  with read-only `--json` query commands; docs kept in step with big changes.
  *Tests:* `tests/test_confirm.py`, `tests/test_store_query.py`,
  `tests/test_provider_detect.py`.
- **Privacy / resilience (NFR-P1–P4, NFR-R1–R4, NFR-Q1–Q5)** — secrets never
  enter git; publish actively redacts (`--scrub`) and `--review` fails on a leak;
  cloud pre-send scrubber gate; PII-free logs; bounded memory; clean-kill of a
  spilled/hung local model; resumable runs; schema-versioned outputs. *Tests:*
  `tests/test_check_no_secrets.py`, `tests/test_repo_hygiene.py`,
  `tests/test_publish_boundary.py`, `tests/test_log_scrub.py`,
  `tests/test_clean_kill.py`, `tests/test_schema_validation.py`.
- **Governance (geometry adoption)** — the governed ADOS Project Geometry +
  Evaluation Rubric validated by `tests/test_geometry_valid.py` /
  `tests/test_rubric_gates.py`. See `CHANGELOG.md`.
