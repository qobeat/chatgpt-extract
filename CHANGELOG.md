# Changelog

## Unreleased

### Added
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
