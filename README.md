# chatgpt-extract

**A solo founder's home-lab decision instrument.** It turns your own ChatGPT
export history into (1) a private, queryable catalog of everything you have
built, and (2) a realistic benchmark harness that uses that same real work to
decide which model, provider, and hardware are actually worth paying for.

> The benchmark is grounded in *your* tasks, not synthetic prompts — so a
> keep-vs-return call on a GPU, or a local-vs-cloud model choice, rests on how
> the tools perform on the work you actually do.

---

## Goal and objectives

**GOAL.** Make grounded build-vs-buy and model-selection decisions for a solo
AI-founder's home lab, using my own real ChatGPT history as both the knowledge
base and the benchmark workload.

This is one system with three objectives (the "three pillars"):

| # | Objective | Pillar | Output |
|---|---|---|---|
| **O1** | Losslessly extract and classify my ChatGPT exports into a private, queryable ADOS project catalog. | **Catalog** | `$DATA_ROOT/store`, `reconstructed_projects.json`, queryable via `gpt list/search/...` |
| **O2** | Benchmark models and providers on that *same* real workload — measuring depth **and** correctness (kept separate), reliability, speed, and cost. | **Benchmark** | `runs/cmp-*/`, `gpt metrics`, `gpt arena`, `AI_MODEL_TESTS.md` |
| **O3** | Convert the benchmark into an explicit, reproducible keep-vs-return / local-vs-cloud / which-model decision, with the economics. | **Decision** | `AI_MODEL_TESTS.md` verdict + the per-model verdicts in `config/models.json` |

O3 is why O1 and O2 exist together: the GPU question ("is the RTX 3090 worth
$1,400 for this?") is just the *first* decision this instrument answers, and the
machinery generalises to the next hardware or model you weigh.

**Non-goals.** Not a database; not a hosted service; not a synthetic-benchmark
suite; not a place to store raw personal data in git.

### Repositories

Two repos, split on the **PII / visibility** boundary (not export-vs-logic):

| Repo | Role | Visibility |
|---|---|---|
| `chatgpt-extract` (this one) | **The tool** — extract, classify, benchmark, the `gpt` CLI, ontology/schema, sanitized `published/`. | public |
| `chatgpt-extract-catalog` | **Observability only** — reads the runs this tool writes; keeps the fuller, *unsanitized* catalog for cross-run stats. | private |

Both read the same `$DATA_ROOT`; **raw chat data lives in neither repo.** Don't
add a third "data" repo. (See `PLANNED-WORKS.md` for the topology rationale.)

---

## How it works — four steps, deterministic-first, LLM-last

```
.zip export ──► Extract ──► Cluster ──► Bundle ──►  Summarize (LLM)  ──► catalog
                (stream)    (union-    (token-cap   (only fuzzy prose       │
                            find)      .md/project) fields; facts merged ──► publish (redacted)
                                                    OVER the model)
```

1. **Extract** (`extract_cards.py`) — stream each multi-GB `.zip` with `ijson`,
   follow `current_node → root` to keep only the **canonical** branch (discarded
   regenerations dropped), reduce transcripts (code bodies → one-line
   placeholders, ~80–95% token saving). Incremental: re-running on a newer export
   updates only changed chats (newer `update_time` wins).
2. **Cluster** (`cluster_projects.py`) — union-find cards into projects. Strong
   signal = normalised zip basename slugs (`slug-vX.Y.zip`); weak signal = title
   slug. Emits `clusters.json` with deterministic facts.
3. **Bundle** (`build_bundles.py`) — one token-capped `.md` per cluster: a
   `DETERMINISTIC FACTS` header + chronological reduced transcripts, hard-capped
   so each project fits a context window in one shot.
4. **Summarize** (`summarize.py`) — the *only* LLM step, schema-constrained. The
   model writes fuzzy prose (goal, objectives, requirements, archetype fields);
   deterministic facts (dates, zip files, ids) are **merged over** the model and
   are never trusted to the model. This is what keeps the catalog auditable.

Steps 1–3 have no LLM and no cost, so they are built **once** and every model in
the benchmark is pointed at the **same** bundles.

---

## Fast start

```bash
bash setup.sh                       # venv + deps (ijson strongly recommended)
cp .env.example .env                # set RECONSTRUCTOR_DATA_ROOT to a private path
./gpt info                          # what's the state of things? (run anytime)

./gpt run --zip /path/to/export.zip # Extract → Cluster → Bundle (no LLM, no cost)
./gpt summarize --limit 10 --noask  # AI summary (provider auto-detected; asks first)

./gpt list                          # browse the catalog
./gpt arena                         # combined model leaderboard
```

`$DATA_ROOT` defaults to `~/chatgpt-reconstructor-data`. Everything personal
lives there and is gitignored.

---

## Privacy model (important)

Privacy is enforced by a **boundary**, not by masking everything everywhere:

- **Local catalog is raw and complete by design.** Transcripts, bundles, and
  `reconstructed_projects.json` under `$DATA_ROOT` are *not* masked — you need
  the real content to work with it. They never enter git (`output/`, `data/`,
  `*.zip`, `transcripts/`, `bundles/`, `reconstructed_projects.json` are all
  gitignored).
- **The publish boundary is where redaction happens.** `gpt publish`
  (`export_public.py`) drops provenance fields (`source_conversation_ids`,
  `member_ids`, `signal_summary`, `bundle_sha`, `cost_usd`), reduces zip paths to
  basenames, and with `--review` scans free text for emails / home paths and
  **fails** the commit if any are found.
- **A pre-commit hook** (`check_no_secrets.sh`) blocks staging of any personal
  path or export zip as a second line of defence.

> ⚠️ **Cloud-provider caveat.** When you benchmark a *cloud* provider
> (`cursor`, `codex`, `claude`, or any API model), the raw, un-redacted bundle —
> your actual transcripts — is sent to that provider. Local Ollama keeps
> everything on the machine; cloud does not. Choose providers with that in mind
> (see `REQUIREMENTS.md` NFR-P3 for the planned pre-send scrubber).

**Current published surface:** `published/projects.json` is an empty placeholder
until you run `gpt publish`. As of this writing the repo contains **no personal
data** — verified across the whole tree and the full git history.

---

## Models, providers, and cost

Hand `gpt summarize` a **model name** and the provider + required options are
filled from the model bank (`config/models.json`); add personal entries in
`config/models.local.json` (gitignored).

| Tier | Examples | Marginal cost |
|---|---|---|
| **Plan** (use existing subscriptions) | `composer-2.5`, `composer-2.5-fast`, `codex`, `claude` | **$0** on the plan |
| **Local** (Ollama on the RTX 3090) | `qwen3:8b`, `qwen2.5-coder:1.5b`, … | ~$0 (electricity) |
| **API** (pay-per-token) | `gpt-5-mini`, `gpt-5`, `claude-haiku-4`, `claude-sonnet-4` | per-token (~$0.8–$7 / full run) |

Provider auto-detect picks a signed-in CLI if present; a confirmation gate shows
the estimate and asks before spending. See the README sections retained from the
original for per-CLI install (`codex`, `cursor-agent`, `claude`).

---

## Benchmark summary — is the RTX 3090 worth it?

Full report and methodology: **`AI_MODEL_TESTS.md`**. One-paragraph version:

On this structured-extraction workload, the **free plan-covered cloud models**
(`composer-2.5-fast`, `codex`) finish **every** item and produce the fullest
records, at **$0 marginal** on a plan you already pay for. **Every installed
local model runs on the 24 GB card** (even the 23 GB one, barely) — so 24 GB is
**not** the binding constraint; the GPU buys *local capability*, not bigger-is-
better headroom. The honest keep-vs-return rule:

**Keep the card only if** (a) privacy/offline is non-negotiable, (b) volume ×
rate-limits exceed what the plan serves, or (c) it is already amortised by other
GPU work (gaming/training/media). Otherwise the $1,400 buys little for *this*
task, because the alternative is both higher-reliability and $0.

> **Read the metric correctly.** The local "quality" gap is mostly a
> *reliability* gap, not a content gap: the headline metric scores failed items
> as zero and rewards field-fill depth over correctness. On successful items
> only, the larger models are competitive-to-better. Fix structured-output
> enforcement before drawing model-quality conclusions. See `AI_MODEL_TESTS.md`
> §3 and §8.

---

## Command reference (condensed)

| Command | Does | Cost |
|---|---|---|
| `gpt info` | State of catalog + last run | $0 |
| `gpt run --zip X` | Extract → Cluster → Bundle | $0 |
| `gpt summarize [--limit N] [--model M] [--provider P] [--run-label L] [--num-ctx C] [--max-usd $] [--noask]` | AI summary (the only LLM step) | varies |
| `gpt all --zip X` | All four steps | varies |
| `gpt list` / `project` / `category` / `search` / `show` / `info` | Browse/query the catalog | $0 |
| `gpt zips` / `zips-verify` | Export processing status / catalog completeness | $0 |
| `gpt compare A B` | Head-to-head run quality (archetype/domain disagreements) | $0 |
| `gpt metrics perf\|quality [paths]` | Speed / ADOS-record tables | $0 |
| `gpt arena` | Combined leaderboard | $0 |
| `gpt publish [--md] [--review]` | GitHub-safe redacted export | $0 |

All commands are read-only except `gpt summarize` (writes only under its own
`--run-label`) and `gpt publish` (writes only `published/`).

---

## Output schema & ontology

Per-item internal schema (`schema/extracted_item_schema.json`): classification
(`primary_archetype`, `primary_domain_pair`, secondaries, `confidence`), meaning
(`goal`, `objectives[]`, `requirements[]`, `requirements_evolution[]`,
`deliveries[]`, `archetype_fields{}`), and deterministic facts (`start_date`,
`end_date`, `n_conversations`, `n_passes`, `version_zip_files[]`,
`file_artifacts[]`, `source_conversation_ids[]`). The public schema
(`extracted_item_public_schema.json`) is the same classification minus provenance.
Ontology (archetypes + domains) lives in `ontology/`.

---

## Tests

`pytest -q` — covers schema round-trip, the secrets hook, redaction, provider
detection, zip ledger/verify, slug parsing, cost, and the sanitiser. The repo is
green on a single squashed commit.

## See also

- `AI_MODEL_TESTS.md` — the benchmark, corrected.
- `REQUIREMENTS.md` — what the next version must satisfy.
- `PLANNED-WORKS.md` — roadmap and phases.
- `skills/` — agent skills for extending and querying this project.
