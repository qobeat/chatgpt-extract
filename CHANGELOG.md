# Changelog

## Unreleased

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
- **Read-only commands**: `gpt list [GLOB]`, `gpt search GLOB`, `gpt info`,
  `gpt show SLUG`, `gpt doctor` (`scripts/gpt_cli.py` + `scripts/lib/store_query.py`).
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

### Added
- **Local Ollama benchmark on an RTX 3090 (24 GB)** in the README: all 14
  installed generation models + the two free Cursor models run over the same
  10-item sample, with a quality/speed/reliability table and an economic verdict
  on whether the $1,400 GPU beats the free plan-covered cloud models (it does not
  for this workload). Model-bank `note`s now carry each model's benchmark verdict;
  the CPU-only build is marked `skip` (unusably slow). `models_bank` renders
  skipped entries distinctly.

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
- **Model bank listing**: the `free` tag moved off the left of each command and
  into the trailing `#` comment, so every printed line is a copy-pasteable
  `gpt summarize --model <name>` (`scripts/lib/models_bank.py`).

### Added (earlier)
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

## 2.0.0 — ADOS archetype extraction + multi-provider LLM

Major redesign. Split out of the former `chatgpt-project-reconstructor` monorepo
into this lean public `chatgpt-extract` plus the private `chatgpt-extract-catalog`
(run catalog, summaries, cross-run stats).

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
