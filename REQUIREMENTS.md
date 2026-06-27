# REQUIREMENTS.md

Requirements the agent building the next versions of **chatgpt-extract** must
satisfy. Each requirement is testable. IDs are stable and are referenced by
`PLANNED-WORKS.md` and the phase plans.

**Conventions.** MUST = mandatory; SHOULD = strong default, deviation must be
justified; MAY = optional. Each requirement names its **verification** (a test,
a command, or an artifact check).

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
  recorded in `PLANNED-WORKS.md`.

---

## 3. Acceptance summary (definition of done for the next version)

A next version is "done" when: extraction reports full content-type coverage
(FR-C2) with no silent drops; `gpt metrics` reports completion / depth-on-success
/ schema-valid / accuracy as separate columns (FR-B2/B3); the Ollama provider
enforces structured output with retry (FR-B4) and the top candidates have been
re-run; the publish path can actively scrub (NFR-P2) and a cloud pre-send
scrubber exists (NFR-P3); the `config/generated/model_benchmarks.json` verdicts are
regenerated from the corrected metric (FR-D2); and `pytest -q` is green (NFR-Q1).
