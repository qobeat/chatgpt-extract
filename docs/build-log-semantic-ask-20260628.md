# Build log — Semantic "ask my chats" + unified cross-sweep format (2026-06-28)

Implements the plan `semantic_ask_and_unified_sweeps`. Two shippable features,
both local-first. `pytest -q` green throughout; each change confined to its
target (NFR-Q5).

## Feature A — Semantic answering agent (FR-Q1–FR-Q5, NFR-R4)

The "agent that answers questions about my chats" is `gpt index` (build) +
`gpt ask` (answer) — no separate service needed.

1. **Dependency (A1).** `numpy>=1.24` added to `requirements.txt` + `setup.sh`;
   `gpt doctor` now reports it (`numpy  ok (gpt index/ask) · 2.5.0`). numpy is
   imported lazily so the rest of the CLI is unaffected when it is absent.
2. **Library (A2) — `scripts/lib/embeddings.py`.** Local Ollama `/api/embed`
   client (`embed_texts`/`embed_one`), embedding-model resolver (bge-m3
   preferred, qwen3-embedding fallback), deterministic overlapping
   `chunk_transcript`, `recency_weight` (exponential half-life), and
   `cosine_sims`/`top_indices`.
3. **`gpt index` (A3) — `scripts/index.py`.** Walks `iter_cards()` +
   `read_transcript()`, chunks, embeds, writes
   `$DATA_ROOT/index/{vectors.npy,chunks.jsonl,manifest.json}`. Incremental by
   per-chat SHA-1 content hash (reuses unchanged chats; `--rebuild` forces full).
4. **`gpt ask` (A4) — `scripts/ask.py`.** Embeds the question, retrieves top-K
   by **similarity × recency** (`--since`, `--half-life`), assembles a grounded
   prompt with `[n]` citations, synthesizes via a generation provider (local
   Ollama default; `--scrub-cloud` redacts PII via `redact.scrub` before any
   off-box provider), prints answer + Sources (title · date · `id=`).
5. **Tests (A5) — `tests/test_embeddings.py` (20).** Chunker, recency,
   cosine/top-k, incremental index round-trip (fake embedder), retrieval
   recency tie-break + `--since`, prompt/citation assembly.

### Live verification (real Ollama, this box)
- Embedder auto-selected: `bge-m3:latest` (1024-dim).
- `gpt ask "what is the latest ADOS README.md format?"` over a tiny real index
  returned a grounded, cited answer (synthesis via `gpt-oss:20b`).
- `tests/test_ask_live.py`: retrieval tests for the example questions
  ("ADOS README.md format", "ados-evaluate skills") pass; the unrelated-topic
  test passes with recency disabled (proving semantic separation); the full
  synthesis path passes under `GPT_ASK_LIVE_SYNTH=1` with a small local model.
  All live tests **skip** automatically when Ollama is unreachable.

## Feature B — Unified cross-sweep format (FR-D3)

1. **Batch state (B1) — `scripts/project_state.py`.** `WORKLOADS` map +
   `workload_for()`; `--all` discovers every sweep under `$DATA_ROOT/runs`,
   infers model + workload, and writes a schema-valid Project State per
   `(workload, model)` to `$DATA_ROOT/states/<workload>__<model>.json`. States
   stay exactly the strict ADOS schema (workload lives in the filename +
   `evidence_refs`).
2. **Report (B2) — `scripts/report.py` (`gpt report`).** Loads `states/*.json`,
   groups by workload, renders `docs/cross-sweep-report.md` with
   coordinate-mapped columns and the same declared-column guard as
   `gpt metrics`. Never averages across workloads.
3. **Tests (B3) — `tests/test_report.py`.** Workload mapping, grouping, full
   `(workload, model)` coverage, columns map to declared coordinates, and the
   same model in two workloads is kept separate (no averaging).

Ran on this box: `gpt state --all` → 19 states from 20 sweeps across 2
workloads (`oct2024-cmp`, `jun2026-perf`); `gpt report` → `docs/cross-sweep-
report.md`.

## Docs

- `REQUIREMENTS.md`: new **Pillar 4 — Ask** (FR-Q1–FR-Q5), **FR-D3**, **NFR-R4**,
  all tagged `[IMPLEMENTED]`, plus a "§4 Implemented in the current release".
- `CHANGELOG.md`, `TODO.md` (moved to Done), `README.md` (command table + an
  "Ask your chats" section).

## Honored constraints
- Local-first, $0, no egress unless `--scrub-cloud` (privacy gate).
- No data deleted; index/states are additive under the gitignored `$DATA_ROOT`.
- `pytest -q` green; new code linted clean.
