# REQUIREMENTS.md

Requirements the agent building the next versions of **chatgpt-extract** must
satisfy. Each requirement is testable. IDs are stable and are referenced by
`TODO.md`, `CHANGELOG.md`, and the phase plans.

**Conventions.** MUST = mandatory; SHOULD = strong default, deviation must be
justified; MAY = optional. Each requirement names its **verification** (a test,
a command, or an artifact check). A **[IMPLEMENTED]** tag means the requirement
is satisfied in the current tree (see `CHANGELOG.md` for the release); untagged
requirements remain targets for the next version.

---

## 1. Functional requirements

### Pillar 1 — Catalog (extraction & classification)

- **FR-C1 — Lossless canonical extraction.** The extractor MUST stream any
  ChatGPT export `.zip` (single or sharded `conversations-NNN.json`) with bounded
  memory, reconstruct the canonical `current_node → root` branch, and never crash
  on object-valued multimodal `parts`.
  *Verify:* existing `test_*` parsing tests pass on a sharded and a single-file
  fixture; memory stays bounded on a ≥1 GB fixture.
- **FR-C2 — Content-type coverage is explicit and auditable.** The extractor
  MUST handle, or **explicitly tag-and-log** (never silently drop), every
  `content_type` present in the export, including at minimum: `text`,
  `multimodal_text`, `code`, `user_editable_context`, and the browsing/tool/
  reasoning families (`tether_quote`, `tether_browsing_display`,
  `execution_output`, reasoning/thoughts). Unknown shapes MUST degrade to a
  labelled placeholder and emit a one-line `ulog` warning.
  *Verify:* a `gpt diagnose`/coverage report lists every `content_type` seen with
  a count and a handled/placeholder flag; no shape produces an empty transcript
  without a warning.
- **FR-C3 — Capture available message metadata.** The extractor SHOULD capture
  per-message `model_slug`, `metadata.attachments` (filenames only), and tool/
  plugin author names into the card, so the catalog can answer "which model
  produced this" and "what files were attached." It MUST NOT capture
  `user.json` PII (email, name, account id) into any artifact.
  *Verify:* a card schema test asserts the new fields exist when present in the
  source and that `user.json`-derived PII never appears.
- **FR-C4 — Incremental, idempotent store.** Re-running extraction on a newer
  cumulative export MUST update only changed chats (newer `update_time` wins) and
  MUST be safe to interrupt and resume.
  *Verify:* re-run on an unchanged export performs no rescan (ledger hash short-
  circuit); re-run on a changed export updates only the delta.
- **FR-C5 — Deterministic facts are authoritative.** Dates, `version_zip_files`,
  `file_artifacts`, ids, and counts MUST be copied verbatim into the final record
  and merged **over** any LLM output. The LLM MUST never be trusted to produce
  them.
  *Verify:* `test_schema_roundtrip` + an assertion that LLM output cannot
  overwrite a deterministic fact.

### Pillar 2 — Benchmark (model/provider evaluation)

- **FR-B1 — Apples-to-apples harness.** The benchmark MUST build the
  deterministic stage once and run every model against the **same** bundles, each
  under its own `--run-label`, with held-constant context and no cross-run
  overwrite.
  *Verify:* two model runs leave isolated `runs/<label>/` outputs; the slug set is
  identical across runs.
- **FR-B2 — Separate reliability from quality.** `gpt metrics` MUST report
  **completion%**, **depth-on-success%** (failed items excluded), and a
  **schema-valid-JSON rate** as **distinct columns**, and MUST NOT collapse them
  into a single blended rank key. (Closes the artifact in `AI_MODEL_TESTS.md`
  §3.5.)
  *Verify:* `gpt metrics quality --json` emits the three fields; a fixture with
  known failures yields the arithmetic the spec predicts.
- **FR-B3 — Correctness measurement.** The benchmark MUST provide a correctness
  path: surface archetype/domain disagreements vs a reference (`gpt compare`),
  support adjudication of a labelled sample against source bundles, and report an
  **accuracy%** alongside depth%.
  *Verify:* `gpt metrics quality --correctness ref=<run>` produces an accuracy
  column on a labelled fixture.
- **FR-B4 — Enforced structured output with retry.** Each provider that emits
  JSON MUST request structured output where the backend supports it (Ollama
  `format=json` / a JSON grammar) and MUST retry on parse failure (bounded
  retries) before recording `LLM_FAIL`.
  *Verify:* a provider unit test asserts `format=json` is set and that a single
  malformed response triggers exactly one retry.
- **FR-B5 — Honest failure recording.** A failed item MUST remain visible (the
  deterministic-prior fallback is retained) but MUST be **flagged** so downstream
  metrics and the catalog can distinguish a real LLM record from a fallback.
  *Verify:* the per-item record carries a `classification_source`/`llm_ok` flag;
  `gpt metrics` excludes fallbacks from depth-on-success.
- **FR-B6 — Cost and power capture.** The benchmark SHOULD record token-exact
  cloud cost where the provider returns usage, and MUST support metering GPU power
  (`nvidia-smi --query-gpu=power.draw`) during a run to compute Wh/item.
  *Verify:* a metered run writes a power trace; `gpt metrics` can report $/1,000
  items and Wh/item.

### Pillar 3 — Decision

- **FR-D1 — Reproducible verdict.** The decision report (`AI_MODEL_TESTS.md`)
  MUST be regenerable from artifacts under `$DATA_ROOT` by documented read-only
  commands, and MUST state the keep-vs-return rule as explicit conditions.
  *Verify:* running the §10 commands reproduces the §4 tables.
- **FR-D2 — Verdicts are data-derived.** The per-model benchmark verdicts MUST be
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
  print inline `[n]` citations, and list **Sources** (title · date · `id=`). If
  no index exists it MUST tell the user to run `gpt index`.
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

### Cross-cutting — CLI / UX

- **FR-U1 — Single entrypoint, name-driven models.** `gpt <command>` MUST remain
  the one entrypoint; `--model <name>` MUST resolve provider + options from the
  model bank (+ `models.local.json`).
- **FR-U2 — Preview before spend.** Any LLM command MUST show an estimate and a
  confirmation gate; `--noask` and `--max-usd` MUST be honoured; a budget trip
  MUST stop cleanly and resumably.
- **FR-U3 — State at a glance.** `gpt info` MUST summarise catalog state and last
  run in one screen; query commands (`list/search/category/show`) MUST be
  read-only and work offline.

---

## 2. Non-functional requirements

### Privacy & security

- **NFR-P1 — Data never enters git.** Raw exports, transcripts, bundles, and the
  full internal JSON MUST be gitignored; the `check_no_secrets.sh` pre-commit
  hook MUST block staging of any personal path or export zip.
  *Verify:* `test_check_no_secrets` + `test_repo_hygiene`; the hook fails on a
  staged `output/` path.
- **NFR-P2 — Publish boundary actively redacts.** `gpt publish` MUST drop
  provenance fields, basename-only zip paths, and `--review` MUST fail the export
  on any detected email / home path. The detector pattern set MUST be broadened
  beyond emails+paths to include phone numbers, obvious tokens/keys, and
  **MUST transform, not only warn**, when run with a `--scrub` flag.
  *Verify:* `test_export_public` + a new test that `--scrub` replaces a planted
  email/path/phone with a placeholder.
- **NFR-P3 — Cloud pre-send scrubber.** Before any bundle is sent to a **cloud**
  provider, the agent MUST offer (and, under a privacy flag, enforce) a redaction
  pass over the bundle, so personal transcripts are not sent off-machine
  unredacted. The local Ollama path MUST remain fully offline.
  *Verify:* with the privacy flag set, a cloud provider call receives a scrubbed
  bundle (planted PII absent from the payload).
- **NFR-P4 — No PII in logs.** `ulog`/trace output MUST NOT contain transcript
  content or home paths.
  *Verify:* a log-scan test over a sample run.

### Performance & resource

- **NFR-R1 — Bounded memory on large archives.** Extraction MUST stay within a
  fixed memory ceiling regardless of archive size (ijson streaming; documented
  fallback warning when ijson is absent).
- **NFR-R2 — Runs on the target box.** The full deterministic build + a
  `--limit 50` local summary MUST complete on the Dell 5820 / RTX 3090 / 120 GB
  RAM within documented time, and any model that spills to CPU or hangs MUST be
  killed by a per-model timeout.
- **NFR-R3 — Resumability.** Every LLM run MUST persist after each item so a
  killed run resumes without re-spending.
- **NFR-R4 — Index build is local, offline, incremental. [IMPLEMENTED]**
  Building the semantic index MUST run entirely against the local Ollama host
  (no cloud, $0 marginal cost) and re-embed only changed chats on a re-run, so
  refreshing after a new export is cheap.
  *Verify:* `tests/test_embeddings.py` incremental-reuse test; embeddings hit
  only `/api/embed` on the configured local host.

### Quality, portability, maintainability

- **NFR-Q1 — Tests green, deterministic core covered.** `pytest -q` MUST pass;
  schema round-trip, redaction, secrets hook, provider detection, and the
  corrected metric MUST be covered.
- **NFR-Q2 — WSL-first, dependency-light.** The toolkit MUST run on WSL2 Ubuntu
  with a Python venv and standard CLIs; heavy/optional deps (ijson, provider
  CLIs) MUST be optional with graceful degradation.
- **NFR-Q3 — Schema-versioned outputs.** Internal and public JSON MUST carry an
  `ontology_version`; schema changes MUST bump it and keep a documented migration
  (`port_legacy.py` pattern).
- **NFR-Q4 — Auditability.** Every catalog record MUST be traceable to its source
  (provenance kept internally, dropped on publish) and to whether it was
  LLM-produced or a deterministic fallback (FR-B5).
- **NFR-Q5 — No scope drift.** Changes MUST be confined to the pillar they target;
  the GOAL and OBJECTIVES (README) MUST NOT change without an explicit decision
  recorded in `TODO.md`.

---

## 3. Acceptance summary (definition of done for the next version)

A next version is "done" when: extraction reports full content-type coverage
(FR-C2) with no silent drops; `gpt metrics` reports completion / depth-on-success
/ schema-valid / accuracy as separate columns (FR-B2/B3); the Ollama provider
enforces structured output with retry (FR-B4) and the top candidates have been
re-run; the publish path can actively scrub (NFR-P2) and a cloud pre-send
scrubber exists (NFR-P3); the `config/generated/model_benchmarks.json` verdicts are
regenerated from the corrected metric (FR-D2); and `pytest -q` is green (NFR-Q1).

## 4. Implemented in the current release

Satisfied in this tree (verified by `pytest -q` — green):

- **Ask / semantic answering agent (FR-Q1–FR-Q5, NFR-R4)** — `gpt index` builds
  a local, incremental embedding index; `gpt ask` answers questions from your
  chats with recency-weighted retrieval, inline citations, a Sources list, and a
  local-first privacy gate (`--scrub-cloud` for any off-box provider).
  *Tests:* `tests/test_embeddings.py` (20), `tests/test_ask_privacy.py` (4,
  offline privacy gate), `tests/test_ask_live.py` (live, skipped when Ollama is
  down).
- **Ask enhancements (FR-Q follow-ups)** — `gpt ask --json`, `--rerank` lexical
  re-rank, chunk-level citations (Sources carry char offsets), a stale-index
  warning, and a keyword-scan fallback when no index exists (degrades instead of
  erroring). *Tests:* `tests/test_embeddings.py`, `tests/test_ask_privacy.py`.
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
- **Prior release (FR-D2, NFR-R2, geometry adoption)** — data-derived verdicts,
  the local-model clean-kill, `gemma4:31b num_ctx=16384`, and the governed ADOS
  Project Geometry + Evaluation Rubric. See `CHANGELOG.md`.
