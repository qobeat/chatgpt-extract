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

**GOAL.** Decide, with reproducible evidence, whether a solo AI-founder should
**keep a purchased RTX 3090 (24 GB, ~$1,400, still returnable)** for local LLM
inference — by benchmarking local Ollama models against flagship, plan-covered
cloud models on the founder's *own* real ChatGPT history, which serves at once as
(a) a private, queryable knowledge **catalog** and (b) the benchmark **workload**.
"Better" is decided on **separated, measured axes — reliability, depth,
correctness ("IQ"), speed, energy, and privacy — that are never blended**, where a
model's **IQ is its difficulty-weighted correctness** at classifying and answering
the chats, scored against an **etalon** (the consensus of strong reference models,
or the single strongest reference model where consensus is unavailable).

The GPU question is the *first* decision this instrument settles; the machinery
generalises to the next hardware or model you weigh.

This is one system, three pillars (**Catalog · Benchmark · Decision**), carried by
four measurable objectives:

| # | Pillar | Objective (measurable) | Output / done when |
|---|---|---|---|
| **O1** | Catalog | Losslessly extract + classify **100%** of items from each export into the faceted ADOS schema, with **zero silent content-type drops** and deterministic facts copied verbatim. | `$DATA_ROOT/store`, `reconstructed_projects.json`, `gpt list/search`; coverage report + schema round-trip pass. |
| **O2** | Benchmark | Run every model on the **same** bundles and report **six separated axes** (completion · depth-on-success · IQ/accuracy · schema-valid · s/item · Wh/item) with no blended rank key. | `runs/cmp-*/`, `gpt metrics`, `gpt arena`. |
| **O3** | Benchmark | Score each model's **difficulty-weighted accuracy vs the etalon**, decomposed by cognitive skill and difficulty tier, on items with a **reliable** ground truth (inter-judge agreement above threshold). | `gpt metrics quality --by-skill --by-difficulty`; etalon κ reported. |
| **O4** | Decision | Convert the axes into an explicit keep-vs-return / local-vs-cloud / which-model verdict with the **economics** (capex vs $0-marginal plan, and vs paid-API break-even). | `AI_MODEL_TESTS.md` verdict + per-model verdicts in `config/generated/model_benchmarks.json`. |

The test is "objective" only if it ends in **numbers that force a verdict** — see
the 14 decision questions (Q1–Q14, each with a numeric answer) and the
pre-committed verdict rule in `docs/REDESIGN-PROPOSAL.md` §3.

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

### The model bank — hand-curated config + a generated benchmark sidecar

The bank is split so machine-owned numbers never live in a hand-edited file. Three
files, each with one schema (JSON Schema Draft 2020-12 is the contract; see
`schema/`):

- **`config/models.json` (hand-curated)** — maps each **name** to its **provider**,
  runtime options (`num_ctx`, `skip`/`skip_reason`), and a structured **`billing`**
  object. Validated by `schema/models_bank.schema.json`.
- **`config/plans.json` (hand-curated, normalized)** — the subscription-plan
  registry (one dated, sourced price per plan: `verified_at` + `source_url`).
  `billing.plan_id` in `models.json` references it, so a price lives in exactly one
  place. Validated by `schema/plans.schema.json`.
- **`config/generated/model_benchmarks.json` (generated, committed)** — typed
  per-model verdicts (`completion_pct`, `depth_on_success_pct`, `accuracy_pct`/`iq`,
  `sec_per_item`, `wh_per_item`, …) keyed by `provider:name`. Written by
  `scripts/gen_model_benchmarks.py`; never hand-edited. Validated by
  `schema/model_benchmarks.schema.json`.

`scripts/lib/models_bank.py` loads all three at runtime (plus the gitignored
`config/models.local.json` and live Ollama discovery) and **joins** the plan and
benchmark sidecars onto each entry, so `gpt summarize --model <name>` resolves
offline and `gpt summarize` (no args) prints the catalog with billing + verdicts.

**`billing`** is one of `{kind: "local"}` (Ollama, electricity only),
`{kind: "subscription", plan_id, metered?}` (covered by a plan), or
`{kind: "token"}` (pay-per-token; rate in `config/pricing.json`). The reliability,
depth, and correctness axes are kept **separate** (never blended into one rank —
FR-B2 / `AI_MODEL_TESTS.md` §3.5).

Why **generated**: verdicts stay reproducible and honest (never a hand-typed
blended score; `--check` fails CI if stale). Why **committed**: the CLI needs the
bank offline, and the benchmark **runs** live under the private, gitignored
`$DATA_ROOT`, so the committed *typed* sidecar is the only reviewable, diffable
form of the verdicts without shipping personal data.

Regenerate after a new sweep with, e.g.:

```bash
gpt gen-model-benchmarks --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex
gpt gen-model-benchmarks --check   # CI guard: exit 1 if the sidecar is stale
```

| Billing | Examples | Marginal cost |
|---|---|---|
| **subscription** (covered by a plan in `config/plans.json`) | `codex` (ChatGPT Pro), `composer-2.5`/`composer-2.5-fast`/`auto` (Cursor Pro+), `claude` (Claude Pro) | **$0** marginal on the plan |
| **local** (Ollama on the RTX 3090) | `qwen3:8b`, `qwen2.5-coder:1.5b`, … | ~$0 (electricity) |
| **token** (pay-per-token) | `gpt-5-mini`, `gpt-5`, `claude-haiku-4`, `claude-sonnet-4` | per-token (rate in `config/pricing.json`) |

Provider auto-detect picks a signed-in CLI if present; a confirmation gate shows
the estimate and asks before spending. See the README sections retained from the
original for per-CLI install (`codex`, `cursor-agent`, `claude`).

---

## Benchmark summary — is the RTX 3090 worth it?

Full report and methodology: **`AI_MODEL_TESTS.md`**. One-paragraph version:

On this structured-extraction workload (27 bundles from the `oct2024` export),
the **free plan-covered cloud models** (`codex`, `composer-2.5`,
`composer-2.5-fast`, `claude`) finish **all 27/27** items *and* classify them
correctly, at **$0 marginal** on a plan you already pay for. With **accuracy now
measured** against a `codex` reference, most local models emit clean schema JSON
with the **wrong** archetype/domain (≤20% accuracy); only the big reasoners
classify well (`gemma4:31b` 68%, `qwen3.6:35b` 64%, `qwen3.6:27b` 60%), and those
are the slowest (30–39 s/item) and most power-hungry. **Every installed local
model runs on the 24 GB card** — so 24 GB is **not** the binding constraint; the
GPU buys *local capability*, not better output. Marginal cost is negligible
either way: **measured** GPU energy is 0.24–2.91 Wh/item (≈$0.00005–$0.0006/item).

**Keep the card only if** (a) privacy/offline is non-negotiable, (b) volume ×
rate-limits exceed what the plan serves, or (c) it is already amortised by other
GPU work (gaming/training/media). Otherwise the $1,400 buys little for *this*
task, because the alternative is higher-reliability, higher-accuracy, and $0.

> **Read the metric correctly.** Completion, depth-on-success, and accuracy are
> three different things and are reported in **separate** columns (never blended).
> Field-fill depth ≠ correctness: a model can fill every field and still mislabel
> the work (`qwen3:8b` is 85% depth but 16% accuracy). See `AI_MODEL_TESTS.md`
> §3–§5 and `docs/benchmark-oct2024.md`.

---

## Command reference (condensed)

| Command | Does | Cost |
|---|---|---|
| `gpt info` | State of catalog + last run | $0 |
| `gpt run --zip X` | Extract → Cluster → Bundle | $0 |
| `gpt summarize [--limit N] [--model M] [--provider P] [--run-label L] [--num-ctx C] [--max-usd $] [--noask]` | AI summary (the only LLM step) | varies |
| `gpt all --zip X` | All four steps | varies |
| `gpt list` / `project` / `category` / `show` / `info` | Browse/query the catalog | $0 |
| `gpt search [-i] [-w] [-a] PATTERN` | Find chats by transcript text (`-i` case-insensitive, `-w` whole-word, `-a` also title + filenames) | $0 |
| `gpt search -f PATTERN` | Find chats by attachment / file_artifact name (e.g. `gpt search -f usage_events.csv`) | $0 |
| `gpt cat [IDS] [--color]` | Print chat text for id(s). Standalone = whole transcript; piped from `gpt search` = context windows around each match (`--before/--after/--context-lines-no/--max-parts/--max-lines/--reverse`). `--color` highlights (alias `gpt chat`) | $0 |
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
