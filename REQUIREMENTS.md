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
  §3.5.) The difficulty-weighted accuracy column MUST be labelled **TWA
  (task-weighted accuracy)** — explicitly **not** an "IQ"/intelligence score — to
  avoid over-claiming; the number itself is unchanged.
  *Verify:* `gpt metrics quality --json` emits the three fields; a fixture with
  known failures yields the arithmetic the spec predicts; the rendered table
  header reads `TWA`.
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
- **FR-Q16 — 15s interactive latency target. [IMPLEMENTED]** (MAIN-REQ-TIMEBUDGET;
  formerly mislabelled "REQ-5a".) The most capable available route SHOULD answer
  within **15s** — the architectural proof that the design (routing + warm daemon)
  is correct. The latency machinery now ships: the Ollama provider sends
  `think="low"` for `gpt-oss` (booleans are ignored there, so `False` did not
  suppress reasoning), the interactive `ask` path caps generation at
  `num_predict=384` (vs the summarizer's 1500), and local synthesis **streams**
  to the terminal (lower perceived latency; `--no-stream`/`--json` stay buffered).
  The warm daemon's cloud route (claude ~2.2s, codex ~5s warm) meets 15s today;
  the **local-GPU** proof is gated on FR-Q17.
  *Verify:* `tests/test_ask_latency.py` (`think_for_model`, payload knobs,
  streaming guard); `gpt ask-eval --budget 15` reports a `USABLE`/`slowest_ms`
  verdict on the warm route (a one-time model warm-up precedes the timed battery).
- **FR-Q17 — Local GPU offload actually works on WSL2. [DEFERRED]** (F3.) Today
  Ollama's llama-server GPU-discovery watchdog times out under WSL2 and silently
  falls back to CPU despite an RTX 3090 visible to `nvidia-smi`; FR-Q10 hard-blocks
  CPU and FR-Q11 routes to cloud so `gpt ask` stays usable. **Landed so far:**
  `gpt doctor` now reports the `ask` model's *actual* GPU residency (so the silent
  CPU fallback is diagnosable), and `gpt ask-eval` pays the one-time cold load
  before the timed battery. **Remaining (the requirement proper):** make local GPU
  offload *work* — fix CUDA/Vulkan discovery for the systemd Ollama service — not
  merely route around it. This last step is box/host-specific (systemd unit env,
  driver paths), so it is tracked as the open part in `TODO.md`.
- **FR-Q18 — Daemon stays responsive under load. [IMPLEMENTED]** (Found by the
  Ask stress suite.) The warm daemon MUST handle each connection on its own
  thread so a long synthesis (up to the wall-clock budget) never blocks
  `ping`/`stats`/`shutdown` or a deterministic entity answer — no head-of-line
  blocking. Synthesis stays **single-flight** (one resident engine, serialised by
  `state.lock`); stats writes are serialised by a separate `rec_lock`; a malformed
  or hostile request MUST never take the daemon down; concurrent distinct
  questions MUST NOT bleed into each other.
  *Verify:* `tests/test_ask_stress.py` — `DaemonResponsivenessTest` (ping is fast
  during a 1.5s synthesis), `RequestIsolationTest` (48 concurrent questions, no
  bleed), `MalformedInputTest`, `StatsUnderLoadTest`, `NotFoundUnderLoadTest`,
  `BudgetUnusableTest`, `StreamGuardStressTest`.

**Exit codes (Ask).** `0` answered (incl. the grounded `Not found in chat data.`);
`2` bad usage / privacy gate (cloud without `--scrub-cloud`); `3` `EXIT_UNUSABLE`
(over budget); `4` `EXIT_NO_GPU` (no GPU, CPU not permitted, no cloud engine).

**Crosswalk (discussion → stable ID).** REQ-1/2/3 → FR-Q6; REQ-4/REQ-Output1 →
FR-Q7; REQ-Output2 → FR-Q8; REQ-5 → FR-Q9; REQ-6 → FR-Q10; REQ-7 → FR-Q11;
REQ-7a/REQ-Models1 → FR-Q12; REQ-Doc2 → FR-Q13; REQ-Daemon1–7 / F1 → FR-Q14;
F4 → FR-Q15; MAIN-REQ-TIMEBUDGET → FR-Q16; F3 → FR-Q17; STRESS-DAEMON-HOL →
FR-Q18; REQ-Doc1 → FR-U4; REQ-Persist1 / F2 → this file.

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
  **MUST transform, not only warn**, when run with a `--scrub` flag. The pattern
  set MUST also support a **user-supplied local dictionary** of personal literals
  (`config/redact.local.json`, gitignored: `terms` + `patterns`) so names, a
  school, an HOA, or a private codename — which no generic pattern can know — are
  scrubbed to `‹redacted›` at every egress.
  *Verify:* `test_export_public` + `--scrub` placeholder test; `test_release_hardening`
  (`RedactCustomDictTest`) for the local dictionary.
- **NFR-P3 — Cloud pre-send scrubber + egress symmetry. [IMPLEMENTED]** Before any bundle is
  sent to a **cloud** provider, the agent MUST offer (and, under a privacy flag,
  enforce) a redaction pass over the bundle, so personal transcripts are not sent
  off-machine unredacted. The local Ollama path MUST remain fully offline.
  **Egress symmetry with `gpt ask` (FR-Q4):** `gpt summarize` MUST **refuse** a
  cloud provider (exit 2) unless `--scrub-cloud` (redact first) or an explicit
  `--allow-raw-cloud-egress` opt-in is given — it MUST NOT silently send raw
  bundles. `bench_sweep.sh` scrubs its cloud reference runs accordingly.
  *Verify:* with the privacy flag set, a cloud provider call receives a scrubbed
  bundle (planted PII absent); `test_release_hardening` (`CloudEgressGateTest`)
  for the refuse/scrub/opt-in gate.
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
item *index auto-refresh at the end of `gpt run`*.

The **15s interactive latency target** (FR-Q16) is now implemented: the Ollama
provider sends `think="low"` for `gpt-oss` (its booleans are ignored), the
interactive `ask` path caps `num_predict` at 384, local synthesis streams, and
`gpt ask-eval --budget 15` is the reproducible latency gate. The remaining
done-criteria for the **next** version are **working local GPU offload on WSL2**
(FR-Q17 — diagnostics + warm-up landed; the systemd CUDA/Vulkan discovery fix is
the open, box-specific part) and a true cross-encoder re-rank.

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

---

## 5. Implemented requirements (status matrix)

Every requirement at **DONE = 100%** (shipped + verified by `pytest -q`). The
open requirements — partially-implemented (FR-Q16) and not-implemented
(FR-Q17) — live in `TODO.md` as two companion tables. `DONE` is 0–100%; a
`COMMENT` is mandatory when `DONE` is neither 0 nor 100 (none here, since this
table is 100%-only).

| REQ ID | WHAT TO DO | WHY TO DO THIS | SIGNAL OF SUCCESS IMPLEMENTATION | DONE | COMMENT |
|---|---|---|---|---:|---|
| FR-C1 | Stream any export `.zip` (sharded/single) with bounded memory; reconstruct canonical `current_node→root`; never crash on object-valued parts | Real exports are multi-GB and branched; naive parsers OOM or crash | Parsing tests pass on sharded + single fixtures; memory bounded on ≥1 GB | 100 | — |
| FR-C2 | Handle or explicitly tag-and-log every `content_type`; unknown → labelled placeholder + `ulog` warning | No silent drops; catalog must be auditable | Coverage report lists every `content_type` with count + handled/placeholder flag | 100 | — |
| FR-C3 | Capture per-message `model_slug`, attachment filenames, tool authors; never capture `user.json` PII | Answer "which model wrote this / what was attached" without leaking PII | Card schema test asserts fields exist; `user.json` PII never appears | 100 | — |
| FR-C4 | Update only changed chats on re-run (newer `update_time` wins); safe to interrupt/resume | Repeated cumulative exports must be cheap and idempotent | Unchanged re-run = no rescan; changed re-run updates only the delta | 100 | — |
| FR-C5 | Copy dates/zip files/ids/counts verbatim, merged **over** LLM output | LLM must never invent deterministic facts | `test_content_coverage` round-trip; `build_item` copies facts verbatim | 100 | — |
| FR-B1 | Build deterministic stage once; run every model on the **same** bundles under its own `--run-label` | Apples-to-apples comparison with no cross-run overwrite | Two runs leave isolated `runs/<label>/`; identical slug set | 100 | — |
| FR-B2 | Report completion%, depth-on-success%, schema-valid% as **distinct** columns | Don't conflate reliability with quality | `gpt metrics quality --json` emits the three fields | 100 | — |
| FR-B3 | Adjudicate accuracy% vs a reference alongside depth% | Field-fill ≠ correctness | `gpt metrics quality --correctness ref=<run>` produces an accuracy column | 100 | — |
| FR-B4 | Request structured output (`format=json`) + bounded retry before `LLM_FAIL` | Stop counting parse misses as quality failures | Provider test asserts `format=json` + exactly one retry on malformed | 100 | — |
| FR-B5 | Keep a failed item visible (deterministic fallback) but **flagged** | Distinguish a real LLM record from a fallback downstream | Record carries `classification_source`/`llm_ok`; metrics exclude fallbacks | 100 | — |
| FR-B6 | Record token-exact cloud cost + measured GPU Wh/item | Decide GPU value on measured, not estimated, cost | Metered run writes a power trace; metrics report $/1k items + Wh/item | 100 | — |
| FR-D1 | Make `AI_MODEL_TESTS.md` regenerable from `$DATA_ROOT` by read-only commands | The keep-vs-return verdict must be reproducible | §10 commands reproduce the §4 tables | 100 | — |
| FR-D2 | Generate verdicts into typed `config/generated/model_benchmarks.json` | Verdicts must be data-derived, not hand-written | `gen_model_benchmarks --check` matches the metric; schema-valid | 100 | — |
| FR-D3 | Express every sweep in one format grouped by workload; `gpt state --all` + `gpt report` | Never average across workloads | `test_report` workload grouping; `docs/cross-sweep-report.md` | 100 | — |
| FR-Q1 | `gpt index`: local incremental embedding index (`vectors`/`chunks`/`manifest`) | Local, $0, cheap refresh after a new export | `test_embeddings` `BuildIndexTest` (ordering, offsets, incremental reuse) | 100 | — |
| FR-Q2 | `gpt ask`: retrieve top-K, answer from context only, inline `[n]` + Sources | Grounded, cited answers | `test_embeddings` `PromptTest`; `test_ask_live` | 100 | — |
| FR-Q3 | Combine cosine similarity with recency decay; `--since`, `--half-life 0` | Latest chats win on near-ties | `test_embeddings` `RecencyTest`/`RetrieveTest` | 100 | — |
| FR-Q4 | Default local; refuse cloud unless `--scrub-cloud` (redact question + context) | No silent data egress off the box | `test_ask_privacy` (offline gate) | 100 | — |
| FR-Q5 | Clear, actionable message when numpy is missing; rest of CLI unaffected | Dependency-light graceful degradation | `gpt doctor` numpy line; numpy imported lazily | 100 | — |
| FR-Q6 | Clean answer + bottom status line; references note under `Sources:` | Readable interactive output | `ask.status_line`/`format_sources`; `test_ask_live` | 100 | — |
| FR-Q7 | Hide Sources by default; show with `--show-sources` (`--details` alias) | Less clutter by default | `test_ask_route` source-visibility tests | 100 | — |
| FR-Q8 | Empty/non-grounded reply → exactly `Not found in chat data.` | No freelance guessing | `ask.is_not_found`; `test_ask_route`/`test_ask_daemon` | 100 | — |
| FR-Q9 | `--budget` wall-clock cap (default 60s); over → `[unusable]` exit 3; `--budget 0` off | Never hang; flag too-slow models honestly | `test_ask_budget`; `test_ask_route` `BudgetDefaultTest` | 100 | — |
| FR-Q10 | Refuse local CPU Ollama (`--require-gpu` default; `--allow-cpu` opt out) via `/api/ps` | CPU inference is too slow for interactive use | `ollama_probe.model_gpu_state`; `test_ask_route` GPU-block tests | 100 | — |
| FR-Q11 | Auto-route to the most capable available engine (local GPU → codex → claude → cursor) | Use the best available route, privacy-gated | `ask_route`; `test_ask_route` `PlanRouteTest`/`RouteIntegrationTest` | 100 | — |
| FR-Q12 | `--list-models` with ready-to-paste commands + per-model flags | No question-aware routing; the user picks the model | `ask.format_model_commands`; `test_ask_route` `ListModelsTest` | 100 | — |
| FR-Q13 | Plain-language `--scrub-cloud` help | A non-expert must understand the egress trade-off | `gpt ask --help` | 100 | — |
| FR-Q14 | One warm router-aware daemon, default on, startup excluded from budget | Amortise cold-start; keep each request isolated | `ask_daemon`; `test_ask_daemon` (socket round-trip, model switching) | 100 | — |
| FR-Q15 | Embedder-gated index step after Bundle; `gpt ask` self-heals a small delta | The catalog must not silently out-grow the index | `run.py` `maybe_index`; `ask.auto_refresh_index` | 100 | — |
| FR-Q16 | Answer within 15s on the best route: `think="low"` for `gpt-oss`, cap interactive `num_predict`, stream local synthesis | The architectural proof that routing + warm daemon is correct; interactive UX | `test_ask_latency`; `gpt ask-eval --budget 15` `USABLE` on the warm route | 100 | Latency machinery + warm-cloud route meet 15s; the **local-GPU** proof depends on FR-Q17 (open in `TODO.md`). |
| FR-Q18 | Handle each daemon connection on its own thread; keep synthesis single-flight; survive hostile input; no cross-question bleed | A long synthesis must not block `ping`/`stats`/`shutdown` (head-of-line blocking, found by the stress suite) | `test_ask_stress` (responsiveness, isolation, malformed input, stats-under-load) | 100 | — |
| FR-U1 | Single `gpt <command>` entrypoint; name-driven model resolution | One coherent surface; models by name, not flags | `gpt --help`; model bank resolution | 100 | — |
| FR-U2 | Estimate + confirmation gate; honour `--noask`/`--max-usd` | Preview before spend; budget trips stop cleanly | `test_confirm` (both paths) | 100 | — |
| FR-U3 | `gpt info` one-screen state; read-only offline query commands | State at a glance; safe to inspect offline | `test_store_query` | 100 | — |
| FR-U4 | Update README + `--help` in the same change as any big change | Docs must track behaviour | README Ask section + command table; `gpt ask --help` | 100 | — |
| FR-U5 | CLI flags reflect actual behaviour: `gpt bundle` selection is explicit (`--min-versions` / `--include-multi-chat` / `--include-singletons`), not a misleading single flag | A flag whose help understates its effect is a correctness/trust bug | `test_release_hardening` (`SelectClustersTest`); `gpt bundle --help` | 100 | — |
| NFR-P1 | Gitignore raw data; `check_no_secrets.sh` blocks staging personal paths/zips | Data must never enter git | `test_check_no_secrets`; `test_repo_hygiene` | 100 | — |
| NFR-P2 | `gpt publish` strips provenance, basenames zips, `--scrub` transforms PII, and scrubs a user-supplied local dictionary (`config/redact.local.json`) | Published surface must be safe by construction, incl. personal literals no generic pattern can know | `test_export_public` + planted-PII scrub test; `test_release_hardening` (`RedactCustomDictTest`) | 100 | — |
| NFR-P3 | Cloud pre-send scrubber over bundles; local Ollama exempt; **cloud `summarize` refuses raw egress** without `--scrub-cloud`/`--allow-raw-cloud-egress` (symmetry with FR-Q4) | No unredacted transcripts off the box, by default | Scrubbed-bundle test; `test_release_hardening` (`CloudEgressGateTest`) | 100 | — |
| NFR-P4 | No transcript content or home paths in `ulog`/trace | PII must not leak through logs | Log-scan test over a sample run | 100 | — |
| NFR-R1 | Bounded memory on large archives (ijson streaming; documented fallback) | Must handle multi-GB archives | Memory-ceiling streaming test | 100 | — |
| NFR-R2 | Full build + `--limit 50` local summary within documented time; kill spilled/hung models | Must run on the Dell 5820 / RTX 3090 box | Per-model timeout clean-kill test | 100 | — |
| NFR-R3 | Persist after each item so a killed run resumes without re-spend | Resumability of every LLM run | Resume-from-next-item test | 100 | — |
| NFR-R4 | Index build is local, offline, incremental | $0 marginal refresh after a new export | `test_embeddings` incremental-reuse; embeds hit only local `/api/embed` | 100 | — |
| NFR-Q1 | `pytest -q` passes; deterministic core covered | Test-gated changes | `pytest -q` green | 100 | — |
| NFR-Q2 | Run on WSL2 with a venv + standard CLIs; heavy deps optional | WSL-first, dependency-light | `setup.sh`; graceful degradation when optional deps absent | 100 | — |
| NFR-Q3 | `ontology_version` on outputs; bump + documented migration on schema change | Schema-versioned, migratable outputs | `port_legacy.py` migration pattern | 100 | — |
| NFR-Q4 | Every record traceable to source + LLM/fallback origin | Auditability | Internal provenance + FR-B5 flag | 100 | — |
| NFR-Q5 | Confine changes to the target pillar; GOAL/OBJECTIVES locked | No scope drift | Explicit decision recorded in `TODO.md` for any GOAL/OBJECTIVES change | 100 | — |
| NFR-Q6 | Continuous integration runs the (hermetic) test suite on every push/PR | Test-gating must be enforced automatically, not by hand | `.github/workflows/ci.yml`: `compileall` + `pytest -q` on Python 3.10–3.12 | 100 | — |
