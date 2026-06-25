# chatgpt-extract

Turn a ChatGPT data export (`.zip`) into a structured, **ADOS-classified** catalog
of what you actually built and discussed — every item tagged with a **Primary
Archetype** (what kind of thing it is) and a **Primary Domain/Subdomain Pair**
(what knowledge governs it), instead of being forced into a one-size-fits-all
"software project" shape.

Three deterministic build steps do all the parsing/clustering with **zero LLM
and zero network**. The optional final **AI summary** step uses an LLM
(auto-detected from your signed-in CLIs, local Ollama, or pay-per-token
OpenAI / Anthropic) only to classify and write prose — never to invent facts.

## How it works — the four steps

| Step | Name | LLM? | `gpt` command | What it does | ~1 GB zip¹ |
|---|---|---|---|---|---|
| 1 | **Extract** | no | `gpt run --zip …` | Stream zip → transcript + fact card per chat | ~90s |
| 2 | **Cluster** | no | *(in `gpt run`)* | Group chats into projects by version-zip slugs | <5s |
| 3 | **Bundle** | no | *(in `gpt run`)* | Archetype/domain prior + one bundle per project | <10s |
| 4 | **Summarize** | **yes** | `gpt summarize` | LLM prose + classification; facts override model | ~30–90 min² |

Use `gpt all --zip …` to chain `gpt run` + `gpt summarize` in one command.

¹ **Extract** scales ~90s/GB (observed); Cluster and Bundle are seconds on top.
A full `gpt run` on a 1 GB export is typically **~1–2 min** total.  
² **Summarize** is per project (~120 projects for ~2,700 chats in 1 GB),
not per GB — ~28s/item (codex) to ~45s/item (ollama). `gpt` prints a live
estimate before the AI step runs.

**Extract → Cluster → Bundle** are free and offline (one `gpt run`). The
**AI summary** is the only step that uses an LLM, and it always asks before
running (see [Confirmation gate](#confirmation-gate)).

### Data flow and `zip_ledger.json`

```text
  ChatGPT export .zip                         RECONSTRUCTOR_DATA_ROOT
  (Downloads — never in git)                  e.g. ~/chatgpt-reconstructor-data
         │                                              │
         │  gpt run --zip PATH                         │
         └──────────────────────────────────────────────┤
                                                        │
                    ┌───────────────────────────────────┴────────────────────┐
                    │                                                        │
              store/zip_ledger.json                              store/index.json
              (which zips finished Extract)              (each chat → source_zip)
                    │                                                        │
                    └──────────────► cluster → bundle → summarize ──────────┘
```

| Artifact | Location | Role |
|---|---|---|
| **`zip_ledger.json`** | `$DATA_ROOT/store/zip_ledger.json` | Records export `.zip` files that completed a **full** Extract pass (not stopped by `--limit`). Lets `gpt run` warn before re-scanning a 1.5 GB archive. |
| **`index.json`** | `$DATA_ROOT/store/index.json` | One row per chat; `source_zip` is the export basename that **last wrote** that chat. |

`gpt zips` columns (newest export first):

| Column | Meaning |
|---|---|
| **PARSE** | Extract status for this zip (`full`, `partial`, `not_processed`, …) |
| **DATE** / **SIZE** | Export date and file size |
| **OWNS** | Chats in the catalog **today** tagged with this zip |
| **IN ZIP** / **SKIP** / **NEW** | Last `gpt run --zip`: opened · skipped (already up to date) · saved |

Newer cumulative exports supersede older ones, so a large zip can show **OWNS=0**
if a later export already wrote every chat.
| **`cards.jsonl`** | `$DATA_ROOT/store/cards.jsonl` | Same metadata as the index, one JSON object per line. |

Check processing status anytime:

```bash
gpt zips                                          # ledger + chats-by-zip summary
gpt zips --zip "$GPT_ZIP1" --zip "$GPT_ZIP2"      # include zips not yet in ledger
```

Status values: **`full`** (complete Extract pass), **`not_processed`** (on disk,
never in ledger), **`indexed`** (chats in `index.json` tag this zip but ledger
has no entry), **`partial`** (interrupted or `--limit` — not recorded in ledger).

## Repositories and local data

The pipeline splits **code** (git) from **your export data** (local disk only).
Two GitHub repos plus one data folder on your machine:

| Location | Type | Role |
|---|---|---|
| `chatgpt-extract` | **public** repo | Pipeline code, schemas, ontology, `gpt` CLI |
| `chatgpt-extract-catalog` | **private** repo | Run catalog, timing reports, cross-run stats |
| `~/chatgpt-reconstructor-data` | **local folder** | All parsed artifacts — never committed |

Typical paths (WSL example):

```text
~/dev/ADOS/chatgpt-extract              ← clone: run ./gpt here
~/dev/ADOS/chatgpt-extract-catalog      ← clone: ./runs.sh, ./run_summary.sh
~/chatgpt-reconstructor-data            ← RECONSTRUCTOR_DATA_ROOT in .env
${WIN_HOME}/ChatGpt/*.zip               ← raw ChatGPT exports (input only)
```

### What lives where

**`chatgpt-extract` (this repo)** — the tool you invoke. It contains Python
scripts, ADOS ontology, JSON schemas, tests, and `published/` (a **sanitized**
placeholder for GitHub). It does **not** hold your chats. Commands:

- `gpt run` / `gpt summarize` — read/write the **data root** (via `.env`)
- `gpt publish` — copies a redacted `items[]` catalog into `published/projects.json`
  inside this repo for public commit
- `gpt list`, `gpt info`, `gpt search` — query the data root

**`~/chatgpt-reconstructor-data` (data root)** — set by `RECONSTRUCTOR_DATA_ROOT`
in `.env` (see `.env.example`). Every `gpt` invocation loads `.env` and uses this
directory. Heavy, personal artifacts stay here:

| Path | Contents | Committed? |
|---|---|---|
| `store/` | transcripts, cards, clusters, zip ledger | **No** — PII |
| `bundles/` | token-capped LLM input per project | **No** — PII |
| `reconstructed_projects.json` | full internal catalog (`items[]`) | **No** |
| `runs/<label>/` | isolated experiments (e.g. `ollama-legacy`) | metadata only³ |
| `runs/catalog.json` | index of labeled runs | in catalog repo³ |
| `comparisons/` | `gpt compare` reports | **No** |

Use `--run-label` to isolate side-by-side runs under `runs/<label>/`; omit it
for a single flat catalog at the data root (see [Output layout](#output-layout)).

**`chatgpt-extract-catalog` (private repo)** — observability only. It vendors its
own `paths.py` and reads the **same** `RECONSTRUCTOR_DATA_ROOT`; no second copy
of your data. Tools:

| Script | Purpose |
|---|---|
| `./runs.sh list` | Browse labeled runs |
| `./runs.sh show [LABEL]` | Manifest, paths, timings for one run |
| `./run_summary.sh` | Write `RUN_SUMMARY_<timestamp>.md` (counts, sizes, stage times) |

The catalog repo's git policy commits **sanitized run metadata only** —
`run.json`, `RUN_SUMMARY_*.md`, `reconstructed_projects.json`, `store/clusters.json`
under `runs/<label>/` — never transcripts, bundles, or export `.zip`s.

³ When the data root is outside the catalog repo, symlink
`chatgpt-extract-catalog/output` → `~/chatgpt-reconstructor-data` (or copy
`.env` with the same `RECONSTRUCTOR_DATA_ROOT` and commit labeled runs from the
data root). See [Personal shell setup (WSL)](#personal-shell-setup-wsl) for aliases.

### How the three locations connect

```text
  ChatGPT export .zip                    RECONSTRUCTOR_DATA_ROOT
  (Downloads, not in git)                ~/chatgpt-reconstructor-data
         │                                          │
         │  gpt run --zip                           │
         └──────────────────────────────────────────┤
                                                    │
              ┌─────────────────────────────────────┼──────────────────────┐
              │                                     │                      │
         store/ bundles/              reconstructed_projects.json    runs/<label>/
         (local only)                 (local only)                   metadata files
              │                                     │                      │
              ▼                                     ▼                      ▼
        chatgpt-extract                    gpt publish ──►          chatgpt-extract-catalog
        gpt run · summarize · list         published/               runs.sh · run_summary.sh
        (code in public git)               (redacted, public git)   (metadata in private git)
```

**Typical workflow:** drop export in Downloads → `gpt run --zip …` (writes data
root) → `gpt info` / `gpt list` → `gpt summarize` → `gpt publish --review`
(commit `published/` in **chatgpt-extract**) → `./run_summary.sh` in
**chatgpt-extract-catalog** (commit run metadata).

## Fast start

```bash
cp .env.example .env
bash setup.sh                              # Python venv + ijson + jsonschema

# What's the state of things? (run anytime)
./gpt

# Build steps — Extract → Cluster → Bundle, no LLM, no cost
./gpt run --zip "<your-export>.zip"

# AI summary — provider auto-detected; asks before it runs
./gpt summarize --limit 3
```

`./gpt` with no arguments is a **status dashboard**: it tells you what's already
parsed and what to do next, or — if nothing is parsed yet — points at an export
and estimates how long parsing will take.

The primary entrypoint is `./gpt`; **`./reconstruct` is a backward-compatible
alias** that forwards to it.

## Everyday commands

| Command | What it does |
|---|---|
| `gpt` | Smart status: parsed counts + next step, or offer to parse a zip |
| `gpt info` | Export statistics (chats, projects, dates, turns, disk) |
| `gpt list [GLOB]` | List projects (add `--chats` for individual chats) |
| `gpt project GLOB` | Classified projects matching GLOB (categories, archetype; `--chats` for chat rows) |
| `gpt category NAME` | Browse by `app`, `idea`, `project`, or `*` (full tree + chats) |
| `gpt search GLOB` | Top 10 matches across projects + chats |
| `gpt show SLUG` | Details for one project (AI summary item if summarized) |
| `gpt doctor` | Check venv, ijson/jsonschema, and provider readiness |
| `gpt run` | Build steps: Extract → Cluster → Bundle (deterministic, no LLM) |
| `gpt summarize` | AI summary (auto-detects provider, asks first) |
| `gpt all` | `run` + `summarize` in one shot |
| `gpt compare A B` | Head-to-head quality of two summary runs (e.g. ollama vs codex) |
| `gpt metrics perf` / `gpt metrics quality` | Rank models by throughput (tokens/sec) / ADOS completeness from saved runs |
| `gpt arena` | Combined PERFORMANCE + QUALITY leaderboard over every model found in saved data |
| `gpt zips` | Which export zips were processed; chats per `source_zip` |
| `gpt zips-verify` | Verify catalog vs all ledger exports — nothing missed (auto-finds zip paths) |
| `gpt publish` | Redact internal JSON → `published/` for public GitHub commit |
| `gpt diagnose --zip Z` | Inspect an export `.zip` (read-only) |

`GLOB` is case-insensitive: a plain word matches as a substring (`gpt search
meeting`), or use wildcards (`gpt list "*ados*"`). Add `--json` to `list`,
`search`, and `info` for scripting.

```text
$ gpt
gpt · data root ~/chatgpt-reconstructor-data

Catalog      4,113 chats · 180 projects · 2023-09-22 → 2026-06-19
AI summary   not run
Provider     codex (auto-detected) · ~84 min for 180 projects

Next  gpt summarize --limit 3   ·   gpt all
```

## Output conventions & glossary

Every `gpt` command speaks the same language and prints the same shape. This is
the source of truth — code follows these definitions, not the other way around.

### Glossary (canonical nouns)

| Term | Meaning |
|---|---|
| **chat** | One ChatGPT conversation. The single word used everywhere in output (never "conversation"). |
| **project** | A cluster of related chats (grouped by shared version-zip slugs). |
| **export** | A ChatGPT data export `.zip`. "zip" is shorthand for the file itself. |
| **catalog** | The parsed store of all chats/projects (`index.json`). Top-level counts read `Catalog  N chats · M projects`. |
| **AI summary** | The optional LLM classification step (`gpt summarize`). Never bare "summary" or "classified". |
| **item** | One project entry the AI summary classifies (the unit `summarize` / `compare` / `publish` count). |
| **data root** | The `RECONSTRUCTOR_DATA_ROOT` folder holding all parsed artifacts. |

### Formatting

- **Context line.** Each command opens with one compact line — `cmd · key val · key
  val` (e.g. `gpt zips · data root ~/… · ledger ok`), not a stack of header lines.
- **Counts.** Always comma-grouped and pluralized: `4,113 chats`, `1 project`.
- **Key/value lines.** A fixed label column, then the value.
- **Tables.** `gpt zips` and `gpt zips-verify` share the same column names and the
  same long-filename truncation (`…<tail>`).
- **Status tokens.** `ok` (good) and `FAIL` / `MISSING` (problem).
- **Footer.** A single `Next` block lists the suggested follow-up commands.
- **Logs (stderr).** Pipeline steps prefix lines with one of
  `[run] [note] [skip] [next] [done] [error]`; timestamped stage logs use
  `[time] Stage  EVENT  path :: status`.

### `gpt zips-verify` terms

| Term | Meaning |
|---|---|
| **IN ZIP** | Distinct chats physically inside that export right now (from the hash cache, or a fresh scan). |
| **OWNS** | Catalog chats whose `source_zip` is this export today (newer exports supersede older ones). |
| **Catalog chats** | Total unique chats across the whole catalog. |
| **Older-only** | Chats in the catalog but **not** in the newest export — normal if deleted before that export. |
| **Union across all exports** | Unique chats found across every processed export combined. |

`Catalog = newest-covered + Older-only`, and every check passing yields
`VERDICT: OK`. It can only verify completeness relative to the exports you have —
chats OpenAI never exported (temp chats, ones deleted before any export) are
undetectable.

## Personal shell setup (WSL)

These aliases and variables live in `~/.bashrc` on the WSL machine. They assume
`$ADOS_DEV` points at your ADOS dev tree (e.g. `~/dev/ADOS`) and that the
extractor repo is at `$ADOS_DEV/chatgpt-extract`.

### Aliases (current)

| Alias | Expands to | Use |
|---|---|---|
| `gpt` | `$ADOS_DEV/chatgpt-extract/gpt` | Status dashboard + all subcommands |
| `gptz1` | `gpt -zip "$GPT_ZIP1"` | Intended: parse export #1 (Oct 2025) |
| `gptz2` | `gpt -zip "$GPT_ZIP2"` | Intended: parse export #2 (Apr 2026) |
| `gptz3` | `gpt -zip "$GPT_ZIP3"` | Intended: parse export #3 (Jun 2026 — newest) |

The `gpt` CLI expects `--zip` on a subcommand (`run`, `all`, or `diagnose`), not a
bare `-zip` flag. Working forms:

```bash
gptz3 run          # if alias is:  alias gptz3='gpt run --zip "$GPT_ZIP3"'
gptz3 all          # alias gptz3='gpt all --zip "$GPT_ZIP3"'
```

If your aliases still use `-zip`, update them to `--zip` (see suggested aliases
below).

### Environment variables (current)

Set in `~/.bashrc` alongside the aliases:

```bash
# Set WIN_HOME to your Windows user home as mounted in WSL (under /mnt/c/Users).
export GPT_ZIP_DIR="${WIN_HOME}/ChatGpt"
export GPT_ZIP1="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2025-10-17-19-56-33-50c8a5d5e9bf4c209ace185ab57ffc5c.zip"
export GPT_ZIP2="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2026-04-16-04-39-07-9622a6a056494e30ad4e6463364aae4d.zip"
export GPT_ZIP3="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2026-06-20-01-33-17-d9f765de52d44d3e8db4ca36d8dffa3e.zip"
```

`GPT_ZIP_DIR` is the `ChatGpt` folder under your Windows user home, mounted in
WSL — where you move ChatGPT export `.zip` files after requesting a data export.

### Suggested additional aliases

Fix the zip shortcuts first (replace `-zip` with `--zip` on `run` / `all`):

```bash
alias gptz1='gpt run --zip "$GPT_ZIP1"'
alias gptz2='gpt run --zip "$GPT_ZIP2"'
alias gptz3='gpt run --zip "$GPT_ZIP3"'
alias gptz1all='gpt all --zip "$GPT_ZIP1"'
alias gptz2all='gpt all --zip "$GPT_ZIP2"'
alias gptz3all='gpt all --zip "$GPT_ZIP3"'
```

Then add convenience wrappers:

| Alias | Definition | Why |
|---|---|---|
| `gptz` | `gpt run --zip "$GPT_ZIP"` | Parse the rolling “latest” export (see `GPT_ZIP` below) |
| `gptzall` | `gpt all --zip "$GPT_ZIP"` | Full pipeline on latest export |
| `gpts` | `gpt summarize` | Short for the AI summary step |
| `gpts3` | `gpt summarize` | Summarize current data root (after `gptz3 run`) |
| `gptpub` | `gpt publish --review` | Sanitize into `published/` before a GitHub commit |
| `gptdoc` | `gpt doctor` | Quick provider / venv check |
| `gptcmp` | `gpt compare ollama-legacy flat --names ollama codex` | Head-to-head vs the ported legacy run |
| `gptruns` | `$ADOS_DEV/chatgpt-extract-catalog/runs.sh` | Browse labeled runs (companion repo) |

Add a rolling “latest” pointer so you do not have to rename `gptz3` every time
you download a new export:

```bash
export GPT_ZIP="$GPT_ZIP3"   # bump to GPT_ZIP4, etc. when a new export arrives
```

Optional: mirror `default_zips` in
`config/reconstruct.config.local.json` so plain `gpt run` (no `-zip`) picks up
the same file without an alias.

See [Repositories and local data](#repositories-and-local-data) for how the data
root relates to both git repos.

## Common scenarios

Copy-paste command lines for the most common tasks. `./gpt <command> --help`
prints the full option list for any command; `./gpt --help` lists these too.

```bash
# First parse of an export (Extract → Cluster → Bundle; no LLM, no cost)
./gpt run --zip "<your-export>.zip"

# Re-parse / incremental update — a zip whose hash is unchanged is skipped
# entirely (no scan); changed/new exports parse and skip unchanged chats.
./gpt run --zip "<newer-export>.zip"

# Force a re-scan of an unchanged export (rarely needed)
./gpt run --zip "<export>.zip" --force-zip-read

# Quick test on a small subset
./gpt run --zip "<export>.zip" --limit 200

# Isolated, side-by-side experiment under runs/<label>/
./gpt run --zip "<export>.zip" --run-label modeltest

# Inspect results before spending any LLM time
./gpt info
./gpt list "*ados*"
./gpt search meeting

# Preview the AI summary (estimate + item list, ZERO LLM calls)
./gpt summarize --dry-run

# AI summary — quick sample (auto provider; asks first)
./gpt summarize --limit 3

# AI summary with a hard budget cap, non-interactive
./gpt summarize --provider openai --model gpt-5-mini --max-usd 2 --noask

# Everything in one shot (parse + summarize)
./gpt all --zip "<export>.zip"

# Resume a killed summary run
./gpt summarize --resume

# Publish a GitHub-safe export (scan for PII first)
./gpt publish --review
```

Two safety prompts you may see (both bypassed with `--noask` / `--yes`):

- **Already handled.** Each export `.zip` is fingerprinted (size + a hash of its
  first/last 1 MiB) and recorded in `store/zip_ledger.json` after a full parse.
  Re-running `gpt run` on a zip whose hash is unchanged **skips it entirely** (no
  scan), printing a notice; if every provided zip is unchanged, Extract is
  skipped and Cluster/Bundle still refresh from the existing store. Pass
  `--force-zip-read` to re-stream a zip anyway (the parse stays idempotent and
  skips unchanged chats).
- **Long run warning.** Any run estimated to take more than **5 minutes**
  (Extract is ~90s/GB) warns and asks before starting. The AI summary step has
  always asked via its own confirmation gate.

## Parsing a new export (Extract → Cluster → Bundle)

```bash
./gpt run --zip "<your-export>.zip"
```

Deterministic, offline, and free. On a ~1.5 GB / ~4,000-chat export this
takes roughly a minute and writes 180-ish project bundles. Inspect the result
before spending any LLM time:

```bash
./gpt info
./gpt list "*ados*"
```

Optional: set `default_zips` (and `export_search_dirs` for the smart prompt) in
`config/reconstruct.config.local.json` so you can omit `--zip`.

### Output layout

Controlled by `RECONSTRUCTOR_DATA_ROOT` in `.env` (default
`~/chatgpt-reconstructor-data`) and an optional `--run-label`. See
[Repositories and local data](#repositories-and-local-data) for the full
three-location model. **`--run-label` is optional** — omit it for a single
catalog; use it for side-by-side experiments.

| `--run-label` | Store | Bundles | AI summary JSON |
|---|---|---|---|
| *(omitted)* | `$DATA_ROOT/store/` | `$DATA_ROOT/bundles/` | `$DATA_ROOT/reconstructed_projects.json` |
| `my-run` | `$DATA_ROOT/runs/my-run/store/` | `…/bundles/` | `…/reconstructed_projects.json` |
| `latest` | resolves the `runs/latest` pointer | same | same |

`--store`, `--bundles`, and `--out` override these. If `RECONSTRUCTOR_DATA_ROOT`
is unset, `$DATA_ROOT` falls back to the repo's `output/` directory.

## AI summary: providers, auto-detect, and cost

### Provider auto-detect

If you don't pass `--provider`, the AI summary picks the **first available** of:

1. `codex` — OpenAI Codex CLI signed in with ChatGPT (your ChatGPT plan)
2. `ollama` — local models ($0 marginal cost)
3. `claude` — Claude Code CLI signed in with your Claude plan

`gpt doctor` shows which are ready. Force a specific one with `--provider NAME`
(also `openai` / `anthropic` for token-exact API billing).

### Confirmation gate

Because the AI summary can cost money (API providers) or take a long time (every
provider — even local Ollama is far more than a few seconds per item), it always
prints an estimate and asks before running:

```text
About to run the AI summary step (Summarize) — provider 'codex' (ChatGPT plan)
  Items:     180
  Est. time: ~84 min
  Est. cost: covered by your plan/quota (not token-billed)
Proceed? [y/N]
```

- **`--noask`** (alias `--yes`) skips the prompt — required for non-interactive
  use; without it, a non-TTY run refuses rather than spending silently.
- **`--dry-run`** prints the estimate and the item list with **zero** LLM calls.
- API providers show a dollar figure; `--max-usd N` is a hard cap that aborts
  before exceeding it.

### When to use which provider

| Provider | Billing | Best for |
|---|---|---|
| `codex` | ChatGPT plan | Default; reliable on **large** bundles (e.g. `ados-profile`) where local models choke |
| `ollama` | Local, $0 | Small/medium bundles, no quota; patient/offline runs |
| `claude` | Claude plan | If you prefer Claude; draws the monthly Agent SDK credit pool |
| `openai` / `anthropic` | API, token-exact | Token-exact cost accounting (`--max-usd`, ledger) |
| `cursor` | Cursor plan | Usage-based agent; Auto unlimited on Pro |

Approximate full-run costs (~180 items): `openai gpt-5-mini` ~$0.8, `gpt-5`
~$4.5, `anthropic claude-haiku-4` ~$2, `claude-sonnet-4` ~$7. Subscription CLIs
(`codex`/`claude`/`cursor`) draw on your plan instead. Pricing lives in
`config/pricing.json` (approximate, dated, editable).

Circuit breakers trip on consecutive failures, HTTP 429/5xx (with backoff), or
budget breach; remaining items are marked `skipped_breaker`, partial results are
written, and every call is traced to `summarize_trace.jsonl`.

Smoke-test results: [`docs/validation-smoke-20260624.md`](docs/validation-smoke-20260624.md).

## Installing subscription CLIs (Ubuntu / WSL)

`bash setup.sh` installs only the Python venv (`ijson`, `jsonschema`). The
subscription providers below are **separate** command-line tools that must be on
your `PATH` inside the shell where you run `./gpt` (for WSL, that means inside
WSL — not PowerShell on Windows).

Ensure `~/.local/bin` is on your PATH (add to `~/.bashrc` if needed):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### OpenAI Codex CLI (`--provider codex`)

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
# or, if you already use Node.js:  npm install -g @openai/codex
codex --version
codex login            # choose "Sign in with ChatGPT" (NOT an API key)
codex login status
```

Headless/WSL without a browser: `codex login --device-auth`. Signing in with an
API key would switch Codex to API pricing; the ChatGPT account session is what
bills against your plan.

### Cursor Agent CLI (`--provider cursor`)

This pipeline shells out to **`cursor-agent`** (or `agent`), not the editor's
`cursor` command.

| What you have | What this package needs |
|---|---|
| Cursor desktop on Windows + WSL Remote | The IDE's `cursor` remote CLI — **not sufficient alone** |
| `cursor` on PATH in WSL | Same — editor helper, not the agent runtime |
| `cursor-agent` / `agent` on PATH | **This** — non-interactive agent used by the AI summary |

```bash
curl https://cursor.com/install -fsS | bash   # or: cursor agent --version (lazy install)
agent --version
agent login
```

If the binary lives elsewhere, set `CURSOR_AGENT_BIN` in `.env`.

### Claude Code CLI (`--provider claude`, optional)

```bash
curl -fsSL https://claude.ai/install.sh | bash
# or APT: see https://code.claude.com/docs/en/install
claude --version
claude setup-token     # run where you have a browser; copy the token
# in .env:  CLAUDE_CODE_OAUTH_TOKEN="..."   and keep ANTHROPIC_API_KEY unset
```

> The Cursor IDE, its extensions, and the Windows desktop app do **not** expose a
> programmatic session to this pipeline — only the WSL-local CLIs do.

## Command reference

Run `./gpt <command> --help` for the live argparse text.

### `gpt run` — Extract → Cluster → Bundle (deterministic)

| Option | Default | Description |
|---|---|---|
| `--zip PATH` | `default_zips` in local config | Export `.zip`; repeat for multiple. Required unless configured. |
| `--run-label LABEL` | *(none — flat layout)* | Isolate under `runs/<label>/`; updates `runs/latest`. |
| `--limit N` | `0` (all) | Process only first N new/changed chats. |
| `--store PATH` / `--bundles PATH` | from layout | Override directories. |
| `--min-slug-votes N` | `3` | Min chats sharing a slug to cluster. |
| `--merge-cap N` | `12` | Stop generic title slugs absorbing more than N chats. |
| `--char-budget N` | `48000` | Max characters per LLM bundle. |
| `--min-versions N` | `1` | Bundle only projects with ≥ N version zips (`0` = all). |
| `--noask` / `--yes` | off | Skip the pre-run warning (long run and/or already-handled zip). |
| `--force-zip-read` | off | Re-stream a zip even if its content hash is already in the ledger. By default an unchanged (hash-matched) export is **skipped** without scanning. |
| `--verbose` | off | Per-file logging during Extract. |

### `gpt summarize` — AI summary (LLM)

| Option | Default | Description |
|---|---|---|
| `--provider NAME` | **auto-detect** `codex→ollama→claude` | Or `openai`/`anthropic`/`cursor`. |
| `--model ID` | config / provider default | Required for API providers; optional for `cursor`/`codex`/`claude`. |
| `--run-label LABEL` | *(none — flat layout)* | Read bundles from `runs/<label>/`. `latest` = most recent labeled run. |
| `--store` / `--bundles` / `--out PATH` | from layout | Override locations. |
| `--limit N` | `0` (all) | Summarize only first N qualifying projects. |
| `--dry-run` | off | Estimate + slugs; **zero LLM calls** (no gate). |
| `--resume` | off | Reuse items already in the output JSON (matching bundle hash) and only summarize the rest. Output is saved after every item, so a killed run continues from where it stopped. |
| `--noask` / `--yes` | off | Skip the confirmation gate. |
| `--max-usd N` / `--max-usd-per-item N` | none | Hard budget caps. |
| `--max-consecutive-failures N` | `3` | Circuit breaker threshold. |
| `--min-versions N` | `1` | Only projects with ≥ N version zips (or ≥ 2 chats). |
| `--max-chars N` | `char_budget_per_bundle` | Truncate bundle text sent to the LLM. |
| `--num-ctx N` / `--host URL` | `32768` / `localhost:11434` | Ollama context / host. |
| `--timeout SEC` | `300` | Per-item LLM timeout. |
| `--no-preflight` / `--no-validate` | off | Skip provider checks / jsonschema validation. |

### `gpt all` — all four steps

`run` flags plus AI summary flags: `--provider`, `--model`, `--num-ctx`,
`--max-usd`, `--noask`, and `--limit-summarize N` (cap the AI summary separately
from the Extract `--limit`).

```bash
./gpt all --zip "<export>.zip"                          # auto provider, asks first
./gpt all --zip "<export>.zip" --provider openai --model gpt-5-mini --max-usd 2 --noask
```

### `gpt list` / `gpt project` / `gpt category` / `gpt search` / `gpt info` / `gpt show`

| Command | Key options |
|---|---|
| `gpt list [GLOB]` | `--chats`, `--all`, `--limit N`, `--run-label`, `--json` |
| `gpt project GLOB` | `--chats`, `--limit N`, `--run-label`, `--json` — requires GLOB (`gpt project` prints help) |
| `gpt category NAME` | `app` · `idea` · `project` · `*` — `--no-chats`, `--limit N`, `--json` (`gpt category` prints help) |
| `gpt search GLOB` | `--limit N` (default 10), `--run-label`, `--json` |
| `gpt info` | `--run-label`, `--json` |
| `gpt show SLUG` | `--run-label` |

**Browse buckets** (from `gpt summarize`; chats inherit the project's label):

| Category | Rule |
|---|---|
| `app` | `primary_archetype` is `software_app` |
| `idea` | `knowledge_qa`, `research_analysis`, or `content_writing`, and not durable |
| `project` | `is_durable_project` (multi-session / iterated work) |

An item can appear in more than one bucket (e.g. a durable app is both `app` and
`project`). `gpt category *` lists all three plus **uncategorized** singleton
chats (not grouped into a summarized project).

```bash
gpt project "*sat*" --chats
gpt category app
gpt category *
```

### `gpt zips` — export processing status

| Option | Default | Description |
|---|---|---|
| `--zip PATH` | *(none)* | Also check these exports (repeatable); shows `not_processed` if absent from ledger. |
| `--run-label` | flat layout | Read ledger/index under `runs/<label>/store/`. |
| `--json` | off | Machine-readable report. |

### `gpt zips-verify` — catalog completeness

Opens every export recorded in `zip_ledger.json`, counts chats in each
zip, and checks the catalog index. Zip paths are discovered from
`default_zips`, `export_search_dirs` in local config, and `GPT_ZIP*` /
`GPT_ZIP_DIR` environment variables — no `--zip` needed.

```bash
gpt zips-verify
```

Exit code `0` = all checks pass; `1` = gaps found or no ledger data.

| Option | Default | Description |
|---|---|---|
| `--run-label` | flat layout | Use `runs/<label>/store/`. |
| `--json` | off | Machine-readable report. |
| `--force-zip-read` | off | Re-open every export instead of reusing the per-zip hash cache. |

Conversation ids are cached per export under `store/zip_scan_cache.json`, keyed
by the same content fingerprint as the ledger (size + a hash of the first/last
1 MiB). When an export's fingerprint is unchanged, `zips-verify` reuses the
cached ids instead of re-streaming the archive — so repeat runs are near-instant.
The cache is populated automatically during `gpt run`; a cache miss simply scans
the archive once and stores the result. Pass `--force-zip-read` to ignore the
cache.

### `gpt compare` — head-to-head run quality

Compare two AI-summary runs over the **same** projects (joined on `slug`) — e.g.
to judge `ollama` vs `codex` output quality.

```bash
./gpt compare A B [--names ollama codex] [--out report.md] [--json]
```

`A` and `B` are each a path to a `reconstructed_projects.json`, a `--run-label`,
or `flat` (the default unlabeled run). It reports two kinds of metric:

- **Prose quality** (both runs authored these): goal/objectives/requirements
  fill, archetype-field coverage, description length. This is the real
  provider-vs-provider signal.
- **Classification agreement**: how often the runs agree on primary archetype
  and domain. If a side's items are tagged `classification_source:
  "deterministic_prior"` (e.g. the ported legacy ollama run, which never had an
  LLM classify), agreement reflects how often the *other* run kept the prior —
  not an LLM-vs-LLM match. The report calls this out.

A markdown report is written under `$DATA_ROOT/comparisons/` and echoed to the
console; `--json` prints the raw numbers instead. See
[Comparing ollama vs codex](#comparing-ollama-vs-codex).

### `gpt metrics` — PERFORMANCE / QUALITY ranking tables

Rank every model that produced saved data by a single comparable unit. Both
subcommands are read-only and auto-discover the usual locations (and de-duplicate
the `runs/latest` symlink); pass explicit paths to scope them.

```bash
./gpt metrics perf [TRACE ...] [--json]            # throughput tokens/sec from summarize_trace.jsonl
./gpt metrics quality [PATH|LABEL=PATH ...] [--json] # ADOS completeness % from reconstructed_projects.json
```

| Subcommand | Unit | Reads | Ranks by |
|---|---|---|---|
| `perf` | tokens/sec (+ gen tok/s, s/item, completion rate) | `summarize_trace.jsonl` | end-to-end throughput |
| `quality` | ADOS completeness % (goal/objectives/requirements/archetype-fields) | `reconstructed_projects.json` | completeness |

See [AI agents / AI models: performance and quality comparison](#ai-agents--ai-models-performance-and-quality-comparison)
for the units rationale and a worked example.

### `gpt arena` — combined leaderboard

Print the **PERFORMANCE and QUALITY tables together** for every model that has
already produced data in the saved artifacts (`summarize_trace.jsonl` files +
`reconstructed_projects.json` outputs). It is read-only and **runs nothing** —
it is `gpt metrics perf` + `gpt metrics quality` aggregated per model.

```bash
./gpt arena                          # all models discovered in saved data
./gpt arena qwen2.5-coder:14b codex  # filter to named models (exact/substring)
./gpt arena --json                   # machine-readable
```

- The model list comes **only** from what is in the data — there is no point
  naming a model that has not classified any of the available bundles. To add a
  model to the arena, generate its data first (`gpt summarize --provider … [--model …]`).
- PERFORMANCE aggregates every trace per model; QUALITY aggregates every output
  per model, **de-duplicated by slug**, so each model appears once.

### `gpt publish` — GitHub-safe export (optional)

**Do you need it?** Only if you want to commit a **public, redacted** catalog to
the `chatgpt-extract` GitHub repo. Your real data stays in
`$DATA_ROOT/reconstructed_projects.json` (gitignored, may contain PII). `gpt
publish` copies summaries into `published/projects.json` inside this repo —
stripping chat IDs, raw signals, and bundle hashes — so you can share
*what you built* without leaking chat provenance.

Skip it entirely if you never push catalog data to GitHub.

```bash
gpt publish --review    # write published/projects.json + PII scan
```

The command prints a clear before/after summary and suggested `git` next steps.

| Option | Default | Description |
|---|---|---|
| `--in PATH` | `$DATA_ROOT/reconstructed_projects.json` | Input JSON (`items[]` schema). |
| `--out PATH` | `published/projects.json` | Sanitized output in this repo. |
| `--md` | off | Also write `published/projects/<slug>.md`. |
| `--review` | off | Scan for PII/personal paths; exit 1 if found. |

### Environment & config

| Variable / file | Purpose |
|---|---|
| `.env` | `VENV_DIR`, `RECONSTRUCTOR_DATA_ROOT`, API keys, CLI binary overrides. |
| `config/reconstruct.config.local.json` | `default_zips`, `export_search_dirs`, `data_root`, Ollama defaults (gitignored). |
| `config/reconstruct.config.json` | Committed defaults (`char_budget_per_bundle`, …). |

## Output schema & ontology

- **`schema/extracted_item_schema.json`** — internal items (with provenance).
- **`schema/extracted_item_public_schema.json`** — sanitized, GitHub-safe.
- **`ontology/`** — the ADOS **Reference Model Bank**: `archetypes.json`,
  `domains.json`, and the drift guards. See `ontology/README.md`.

Each item carries `primary_archetype`, `primary_domain_pair`, optional secondary
pairs, an ADOS `goal`, `objectives` (forming/speeding/governance), and
archetype-conditioned `archetype_fields` (e.g. a `software_app` has
quickstart/how_to_use/how_to_update; a `study_education_resource` has
audience/topics_covered; `media_generation` has subject/style).

## Privacy

Raw exports, transcripts, bundles, and `reconstructed_projects.json` are
gitignored. `gpt publish --review` strips chat IDs and scans for emails
and personal paths before anything reaches `published/`.

## Tests

```bash
python -m pytest tests/ -q     # or: python -m unittest discover -s tests
```

## AI agents / AI models: performance and quality comparison

### Summary: PERFORMANCE and QUALITY rankings

**PERFORMANCE** — end-to-end throughput, higher is faster:

| Rank | Model | Throughput (tokens/sec) |
|---|---|---|
| 1 | qwen2.5-coder:14b | **645.1** |
| 2 | gpt-oss:20b | 289.9 |
| 3 | codex | 278.8 |

(Exact figures from `gpt metrics perf` on the saved traces; see below.)

**QUALITY** — ADOS completeness, higher is better:

| Rank | Model | ADOS completeness (%) | items |
|---|---|---|---|
| 1 | codex | **100** | 183 |
| 2 | qwen2.5-coder:14b | 81 | 12 |
| 3 | gpt-oss:20b | 64 | 6 |

Both tables are exactly what **`gpt arena`** prints, aggregated over every model
found in the saved data (run it yourself — no arguments needed).

> The rankings invert: the local models lead on throughput, codex is more
> complete. But "faster" is nuanced — only **qwen** is faster *per item* (14.7 s
> vs codex 26.1 s); **gpt-oss** is actually *slower per item* (37.7 s) and only
> edges codex on tokens/sec because it ingests big bundles quickly while
> generating slowly. Reliability breaks the tie — completion rate
> (`LLM_OK / (LLM_OK+LLM_FAIL)`) is **codex 100%** (184/184), **qwen 86%**
> (18/21), **gpt-oss 55%** (6/11): only codex finished the 235 KB `ados-profile`
> bundle. The full worked example (per-slug evidence) is
> [below](#worked-example-on-real-saved-data-codex-vs-local-ollama).

Reproduce both tables anytime with [`gpt arena`](#gpt-arena--combined-leaderboard) —
it reads the saved data and ranks whatever models are present (it runs nothing).

When you want to judge one provider/model against another (e.g. **ollama vs
codex**, or two local Ollama models), two things have to be true for the result
to mean anything:

1. **Both runs must classify the exact same chats** — otherwise you are
   comparing different work, not different providers.
2. **You must be able to read the source chat text** behind each item — so you
   can decide whether a classification is actually *correct*, not just whether
   the two providers *agree*.

This section covers both, end to end, on a small sample (10 items shown).

### Models compared (and how to use each)

These are the models that actually generated the data analyzed below (all on the
same June 2026 export bundles):

| Model | Provider | How to invoke | Cost | When to use |
|---|---|---|---|---|
| **codex** (ChatGPT-plan default) | `codex` CLI | `--provider codex` (also the auto-detect default) | Plan/quota | Large or high-stakes bundles; richest prose |
| **gpt-oss:20b** | local `ollama` | `--provider ollama --model gpt-oss:20b` | $0 | Patient/offline runs; bigger local model |
| **qwen2.5-coder:14b** | local `ollama` | `--provider ollama --model qwen2.5-coder:14b` | $0 | Fast bulk classification of small/medium bundles |

### How these numbers are measured and reproduced

**Measurement units — how each is calculated (and why they are comparable):**

- **Throughput = (input_tokens + output_tokens) ÷ wall-clock seconds**, summed
  over every successfully classified item (`LLM_OK`). Reported in **tokens/sec**.
  This normalizes for bundle size and output verbosity, so it is the fair
  "LLM work done per second" across a remote agent and local GPU models. Two
  related rates come from the same fields: **generation rate** (output tokens ÷
  sec — codex leads at 40.9 vs qwen 30.4 vs gpt-oss 13.6, because it writes more)
  and **per-item latency** (sec ÷ item — qwen 14.7 s, codex 26.1 s, gpt-oss
  37.7 s). Throughput (in+out)/s is the headline because it counts ingestion +
  generation as one comparable unit.
- **ADOS completeness = mean of four 0–100% field-fill rates** — goal,
  objectives, requirements, and archetype-field coverage — averaged over the
  model's completed items. Reported as a **percent**. It is comparable because
  every item is scored against the *same* ontology field contract regardless of
  provider; it measures how fully the structured ADOS record was filled (it is a
  completeness proxy for quality, not human-judged correctness — for correctness
  you adjudicate disagreements against the source, see the worked example).

**Command to collect the data (reproduce these runs).** Build once, then
summarize the same slugs with each model — every run you do adds that model to
the arena:

```bash
./gpt run --zip "$GPT_ZIP3"                              # build once (no LLM)
SHARED="--store $DATA_ROOT/store --bundles $DATA_ROOT/bundles --limit 10 --noask"
./gpt summarize $SHARED --run-label cmp-codex  --provider codex
./gpt summarize $SHARED --run-label cmp-oss20b --provider ollama --model gpt-oss:20b
./gpt summarize $SHARED --run-label cmp-qwen14 --provider ollama --model qwen2.5-coder:14b
```

**Command to view both tables** for every model now present in the saved data
(read-only; runs nothing):

```bash
./gpt arena                          # leaderboard over all processed models
./gpt arena qwen2.5-coder:14b codex  # optional: restrict to named models
```

**Files with the collected data** (what the numbers above were read from):

| Data | Location |
|---|---|
| Per-item timing + tokens (codex) | `$DATA_ROOT/summarize_trace.jsonl` |
| Per-item timing + tokens (all 3 models) | `output/runs/new-parser-20260624/summarize_trace.jsonl`, `output/runs/legacy-eval/summarize_trace.jsonl` |
| Classified output (codex catalog) | `$DATA_ROOT/reconstructed_projects.json` |
| Classified output (qwen / gpt-oss) | `output/runs/new-parser-20260624/reconstructed_ollama_6.json`, `…/reconstructed_projects.json` |

(With the reproduce commands above, each labeled run's data is instead at
`$DATA_ROOT/runs/<label>/summarize_trace.jsonl` and `…/reconstructed_projects.json`.)

**Command to extract the PERFORMANCE numbers (tokens/sec) from the traces:**

```bash
# Auto-discovers $DATA_ROOT/summarize_trace.jsonl + output/runs/*/summarize_trace.jsonl
./gpt metrics perf
# …or point it at specific traces, and/or emit JSON:
./gpt metrics perf "$DATA_ROOT/summarize_trace.jsonl" --json
```

Real output:

```text
rank  model                           tok/s  gen tok/s  s/item  completed
   1  ollama:qwen2.5-coder:14b        645.1       30.4    14.7   18/21
   2  ollama:gpt-oss:20b              289.9       13.6    37.7    6/11
   3  codex                           278.8       40.9    26.1  184/184
```

**Command to extract the QUALITY numbers (ADOS completeness) from the outputs:**

```bash
# Auto-discover, or pass LABEL=PATH pairs for clean per-model labels:
./gpt metrics quality \
  "codex=$DATA_ROOT/reconstructed_projects.json" \
  "qwen2.5-coder:14b=output/runs/new-parser-20260624/reconstructed_ollama_6.json" \
  "gpt-oss:20b=output/runs/new-parser-20260624/reconstructed_projects.json"
```

Real output:

```text
rank  model                         compl%  goal   obj   req    af  items
   1  codex                           100%   100   100   100    99    181
   2  qwen2.5-coder:14b                71%    83    83    67    50      6
   3  gpt-oss:20b                      60%    67    67    67    42      3
```

> `gpt metrics` is read-only and de-duplicates symlinked runs (e.g. `runs/latest`).
> The `quality` call above scopes to three explicit files (a controlled subset);
> **`gpt arena`** instead aggregates *all* saved runs per model and de-duplicates
> by slug, so its item counts (and therefore completeness) can differ. Numbers
> shift with sample size and model/prompt versions — re-run after any change.

### 1. Ensure both providers see identical chats

The deterministic build (**Extract → Cluster → Bundle**) has no LLM and does not
depend on the provider, so you build **once** and point both AI-summary runs at
the same bundles. `gpt summarize --limit N` then selects the **first N
qualifying clusters from `clusters.json`** — same filter, same on-disk order,
every time — so the slug set is byte-for-byte identical across providers:

```326:330:scripts/summarize.py
    clusters = [c for c in clusters
                if c.get("n_versions", 0) >= args.min_versions
                or c.get("n_conversations", 0) >= 2]
    if args.limit > 0:
        clusters = clusters[: args.limit]
```

`gpt compare` then **joins the two outputs on `slug`**, so only items both runs
produced are scored — the overlap *is* your controlled sample.

Each run writes into its **own labeled directory** under `$DATA_ROOT/runs/<label>/`
(raw output + an isolated timing trace + run logs), while `--store`/`--bundles`
point both runs at the single shared flat build so nothing is re-parsed. This is
the defined, durable location for the raw results — see
[Where the results live](#where-the-results-live--the-proof-trail) below.

```bash
# Build once (deterministic, provider-independent) — reused by both runs.
./gpt run --zip "$GPT_ZIP3"
./gpt doctor                         # confirm ollama (and the other provider) are ready

# Preview the exact 10 slugs that --limit 10 will pick — ZERO LLM calls.
./gpt summarize --limit 10 --dry-run

# Reuse the one shared build for every run (no re-parsing, identical bundles).
SHARED="--store $DATA_ROOT/store --bundles $DATA_ROOT/bundles --limit 10 --max-chars 48000 --noask"

# Each provider lands in its own runs/<label>/ dir (output + isolated trace).
./gpt summarize $SHARED --run-label cmp-ollama-20b --provider ollama --model gpt-oss:20b
./gpt summarize $SHARED --run-label cmp-codex      --provider codex

# Head-to-head over the shared 10 slugs (compare accepts run-labels directly).
./gpt compare cmp-ollama-20b cmp-codex --names ollama codex
```

Rules that keep it apples-to-apples:

- **Use `--limit N` (not hand-picked slugs)** so both runs draw the identical
  prefix of `clusters.json`. `gpt compare` reports `n_overlap` — confirm it
  equals your sample size (10) and that `only A` / `only B` are both `0`.
- **Hold every other knob fixed** across the two runs: `--limit`, `--max-chars`
  (context the model sees), `--min-versions`, and the bundle set. Only
  `--provider`/`--model` should differ.
- **`--run-label` per run + shared `--store`/`--bundles`** reuses the single flat
  build (no rebuilding bundles) yet keeps each run's output **and** its
  `summarize_trace.jsonl` isolated in its own directory — the proof trail below.
- **Performance numbers** (per-item seconds, input/output tokens, $) are logged
  live (`LLM done <slug> … 41s in=… out=…`) and persisted to
  `$DATA_ROOT/runs/<label>/summarize_trace.jsonl` — one trace file per labeled
  run, so the ollama timing is never mixed with the other provider's.

> Want a fixed, hand-picked set instead of "the first 10"? That needs a small
> `--slugs a,b,c` selector in `summarize.py` (not yet implemented) — ask if you
> want it added.

### Comparing two ollama models (same provider, different `--model`)

Everything above works **unchanged** to compare two local models against each
other — the only variable that moves is `--model`. Keep `--provider ollama`,
hold `--limit`, `--max-chars`, `--num-ctx`, and `--host` fixed, and give each
model its own labeled run directory:

```bash
# Same shared build, same context window — only the model differs.
SHARED="--store $DATA_ROOT/store --bundles $DATA_ROOT/bundles --limit 10 \
  --max-chars 48000 --num-ctx 32768 --provider ollama --noask"

./gpt summarize $SHARED --run-label cmp-oss20b  --model gpt-oss:20b
./gpt summarize $SHARED --run-label cmp-llama8b  --model llama3.1:8b

# Head-to-head; --names labels the report columns.
./gpt compare cmp-oss20b cmp-llama8b --names oss20b llama8b
```

Notes specific to model-vs-model:

- **Pull the models first** so the timed run is not skewed by a download:
  `ollama pull gpt-oss:20b` and `ollama pull llama3.1:8b`. `gpt doctor` reports
  which Ollama models are available.
- **`--num-ctx` is the fairness knob here.** A smaller model often has a smaller
  practical context; if you shrink `--num-ctx` for one, shrink it for both, or
  the larger-context model gets an unfair information advantage. Keep
  `--max-chars` identical too so neither model is fed a longer bundle.
- **`--names` matters** because both sides report `provider: ollama` — pass
  distinct display names (e.g. the model tags) so the report columns are
  readable.
- **Speed vs quality is the whole point:** the per-item timing in each run's
  `$DATA_ROOT/runs/<label>/summarize_trace.jsonl` (and the live `LLM done … Ns`
  log) gives you the speed axis; the prose-quality and classification tables
  from `gpt compare`, plus the source-text review below, give you the quality
  axis.

Extending to **three or more** models is just more labeled runs. `gpt compare`
is pairwise, so compare each candidate against your reference model in turn
(`oss20b` vs `llama8b`, `oss20b` vs `mistral`, …); the shared reference keeps
every pairwise report on the same 10 chats.

### 2. Review the source chat text behind each classification

The chats each item was built from are **provider-independent** — they live in
the shared build, so you review them once and apply the judgment to both runs.
Three artifacts, from summary to raw:

| What to read | Where | Use |
|---|---|---|
| Classification + prose | each provider's output JSON, or `gpt show SLUG` | What the model *decided* (archetype, domain, goal, description) |
| **Bundle** (`<slug>.md`) | `$DATA_ROOT/bundles/<slug>.md` | **The exact text the LLM saw** — deterministic facts header + reduced transcripts, one block per chat |
| Per-chat transcript | `$DATA_ROOT/store/transcripts/<conversation_id>.txt` | The full reduced, code-stripped transcript of a single chat |

The bundle is the highest-leverage file: it is literally the model's input, so
reading it tells you whether the chosen archetype/domain is defensible. Each
chat inside it is delimited by a header you can scan:

```text
--- conversation <id> | <create_date> | <title> ---
```

Workflow to confirm quality for one item:

```bash
# List the source chats for a project (ids, titles, dates, turn counts).
./gpt project "<slug>" --chats

# Show what the model decided + the bundle path it was built from.
./gpt show <slug>

# Read the exact LLM input (deterministic facts + reduced transcripts).
less "$DATA_ROOT/bundles/<slug>.md"

# Drill into one specific source chat in full.
less "$DATA_ROOT/store/transcripts/<conversation_id>.txt"
```

The `source_conversation_ids` field on every item (and `member_ids` on the
cluster) is the authoritative map from an item back to its raw chats, so you can
always trace a classification to the exact conversations that produced it.

To see what a **specific** run decided for a slug, add its label:
`gpt show --run-label cmp-codex <slug>` reads that run's output JSON, while
`gpt project "<slug>" --chats` (flat) lists the shared source chats.

Put the two together: read the bundle to form your own verdict, then check it
against each provider's output (or the disagreement table from `gpt compare`).
Where the providers disagree, the bundle text is the tie-breaker that tells you
*which one was right* — turning provider "agreement" into provider "accuracy".

### Worked example on real saved data (codex vs local Ollama)

The runs below are **real, already on disk** in this workspace: a fresh parse of
the June 2026 export (`new-parser-20260624`, 4,113 chats → 180 project bundles)
was summarized by **codex** and by two local **Ollama** models —
`gpt-oss:20b` and `qwen2.5-coder:14b` — over the **same bundles**. Per-item
timing for all three is in their `summarize_trace.jsonl`; the codex catalog is
the full 181-item run at the data root.

#### Faster — read the trace (real per-item seconds)

Every run records wall-clock seconds, input/output tokens per item:

```bash
# Per-model timing on the same first slugs (LLM_OK = succeeded).
python3 - <<'PY'
import json, collections
runs = collections.defaultdict(list)
for line in open("output/runs/new-parser-20260624/summarize_trace.jsonl"):
    e = json.loads(line); p = e.get("payload", {})
    if e["event_type"] == "LLM_OK":
        runs[e["run_id"]].append((e["message"], p["secs"], p["in_tok"], p["out_tok"]))
for rid, rows in runs.items():
    print(rid, "—", ", ".join(f"{s}={sec}s" for s, sec, *_ in rows))
PY
```

Real output (same three "smoke" slugs, plus more for qwen):

```text
ollama:gpt-oss:20b       — repo-snapshot=22.9s, holiday-portrait-transformation=18.7s
ollama:qwen2.5-coder:14b — repo-snapshot=11.7s, holiday-portrait-transformation=9.5s,
                            aidossdlc=18.3s, displaydiag-20251201=19.4s, funny-artist-names=15.5s
codex:                   — ados-profile=30.7s, repo-snapshot=30.6s
```

Across the full codex catalog (182 traced calls) codex averaged **26.1 s/item**
(median 25.4 s, min 10.8 s, max 63.7 s). On the identical `repo-snapshot`
bundle, `qwen2.5-coder:14b` finished in **11.7 s** and `gpt-oss:20b` in 22.9 s
vs codex's 30.6 s.

**Speed verdict:** `qwen2.5-coder:14b` is the clear winner — faster per item
(14.7 s vs codex 26.1 s aggregate) *and* highest throughput, at $0. `gpt-oss:20b`
is more mixed: it wins on some items (repo-snapshot 22.9 s) but is slower per item
on average (37.7 s). And speed only counts on items a model can actually
complete — see the reliability finding below.

#### Smarter — quality + reliability (real `gpt compare`)

```bash
# True LLM-vs-LLM: the 6-item qwen run vs the codex catalog, joined on slug.
./gpt compare output/runs/new-parser-20260624/reconstructed_ollama_6.json flat \
  --names qwen-14b codex
```

Real report (abridged):

```text
- Joined on slug: 6 shared (only qwen-14b: 0 · only codex: 175)

## Prose quality (over shared projects — both runs authored these)
| Metric                     | qwen-14b | codex |
|----------------------------|----------|-------|
| Goal filled                |   83%    | 100%  |
| Avg objectives / item      |   1.7    |  3.5  |
| Requirements filled        |   67%    | 100%  |
| Archetype-field coverage   |   50%    | 100%  |
| Avg description chars       |    85    |  177  |
| ADOS-classified            |   83%    | 100%  |

## Classification agreement (shared projects)
- Primary archetype agree: 33% (6 comparable)
- Primary domain agree:    33%

### Top archetype disagreements (slug — qwen-14b → codex)
| slug          | qwen-14b                 | codex                   |
|---------------|--------------------------|-------------------------|
| ados-profile  | software_app             | controlled_spec_or_schema |
| aidossdlc     | study_education_resource | controlled_spec_or_schema |
| repo-snapshot | runtime_package          | software_app            |
```

The agreement rate (33%) only tells you they **differ** — it cannot tell you
**who is right**. For that, open the source (the tie-breaker from
[section 2](#2-review-the-source-chat-text-behind-each-classification)). Real
example, `repo-snapshot` (12 chats, 2 versions — a React/Vite SAT-prep app):

```text
$ ./gpt show repo-snapshot
# ScholaSpark SAT Navigator repository snapshot  (repo-snapshot)
archetype : software_app
domain    : education/sat_preparation
goal      : Maintain and prepare ScholaSpark SAT Navigator for release as a
            reliable, secure, maintainable SAT preparation app …
```

Reading the bundle confirms it is a shipped SAT-prep **app**, so:

| Model | repo-snapshot archetype | Correct? | archetype_fields filled |
|---|---|---|---|
| codex | `software_app` (domain `education`) | **yes** | 4/4 |
| gpt-oss:20b | `software_app` (domain `education`) | yes | 1/4 |
| qwen2.5-coder:14b | `runtime_package` (domain `software_engineering`) | **no** — labeled the repo tooling, not the product | 0/3 |

`qwen` tripped exactly the drift guard the ontology warns about (picking the
visible implementation over what is *delivered*). On `holiday-portrait-transformation`
all three agreed (`media_generation` / `arts_creative`), but codex still wrote 3
objectives to the local models' 1 — richer even when the label matches.

#### The decisive finding: reliability on a hard item

The mega-cluster `ados-profile` is a **235 KB** bundle (304 chats). Both local
models **failed** it; codex did not:

```text
ollama:gpt-oss:20b        ados-profile -> empty response
ollama:qwen2.5-coder:14b  ados-profile -> non-JSON response
codex:                    ados-profile -> OK (controlled_spec_or_schema / ai_ml, 30.7s)
```

A failed item still gets written with the deterministic prior and empty prose,
so it silently *looks* classified — which is why you check `n_failed` and the
trace, not just the item count.

#### How to read it — the conclusion

Combine the three axes into one verdict:

| Axis | How you measured it | Result here |
|---|---|---|
| **Faster** | `gpt metrics perf` (tokens/sec + s/item) | **qwen** clearly (645 tok/s, 14.7 s/item vs codex 279 tok/s, 26.1 s); gpt-oss mixed; $0 |
| **Smarter (prose)** | `gpt compare` prose-quality table | **codex** (objectives 3.5 vs 1.7, fields 100% vs 50%, descriptions 2× longer) |
| **Smarter (classification)** | disagreements adjudicated against the source bundle | **codex** (correct on `repo-snapshot`; `qwen` mislabeled it) |
| **Reliable** | `n_failed` + `LLM_FAIL` events | **codex** (completed `ados-profile`; both local models failed) |

So on this data: **Ollama (`qwen2.5-coder:14b`) is the faster, zero-cost
classifier and is adequate on small/medium bundles, but codex is the *smarter*
one — fuller prose, more defensible archetypes, and the only one that survives
the largest bundle.** The practical policy this supports is exactly the
[provider table](#when-to-use-which-provider): local Ollama for the bulk of
small/medium projects, codex for the big or high-stakes clusters. Re-run the
commands above after any model/prompt change to confirm the trade-off still
holds.

### Where the results live — the proof trail

Every comparison run lands in a **defined, durable location** so results are
reproducible and citable later. There are two tiers: the **raw artifacts**
(private, full detail, may contain chat PII) and a **committed summary**
(sanitized, safe to publish as evidence).

**Raw artifacts — private, under the data root** (gitignored; see
[What lives where](#what-lives-where)):

| Artifact | Path | What it proves |
|---|---|---|
| Classified output | `$DATA_ROOT/runs/<label>/reconstructed_projects.json` | Exactly what that provider/model produced for the sample |
| **Timing/cost trace** | `$DATA_ROOT/runs/<label>/summarize_trace.jsonl` | Per-item seconds, input/output tokens, $, and circuit-breaker events — the performance record |
| Run manifest + logs | `$DATA_ROOT/runs/<label>/run.json` | The exact command line, flags, and stage timings |
| Comparison report | `$DATA_ROOT/comparisons/<A>-vs-<B>.md` | The head-to-head quality + agreement tables |

Pin the report path explicitly if you want a stable filename:

```bash
./gpt compare cmp-oss20b cmp-codex --names oss20b codex \
  --out "$DATA_ROOT/comparisons/20260624-oss20b-vs-codex.md"
```

**Committed proof — sanitized, in git.** The raw artifacts above are never
committed (they hold chat content). To keep a durable, shareable record, follow
the repo's existing evidence convention and write a **sanitized markdown
summary** to this repo's `docs/`, dated like the smoke-test log
([`docs/validation-smoke-20260624.md`](docs/validation-smoke-20260624.md)):

```text
docs/comparison-<YYYYMMDD>-<topic>.md     # e.g. docs/comparison-20260624-oss20b-vs-codex.md
```

Include the run labels, models, sample size (the shared 10 slugs), the per-item
latency/archetype/domain tables, and your verdict — but no raw transcript text.
This is the artifact you cite as proof in commits, issues, or the CHANGELOG.

For run **metadata** (not the prose), the companion **catalog** repo commits
sanitized `runs/<label>/run.json`, `RUN_SUMMARY_*.md`, `clusters.json`, and
`reconstructed_projects.json` via `./run_summary.sh` (see
[chatgpt-extract-catalog](#what-lives-where)) — so the labeled comparison runs
are tracked there too, without leaking transcripts.

## Comparing ollama vs codex

The legacy `ollama` output from the old `chatgpt-project-reconstructor` repo has
been **ported once** into the new ADOS `items[]` schema and lives as a
self-contained run at `$DATA_ROOT/runs/ollama-legacy/` (the old repo is no longer
referenced). Compare it against a current `codex` run:

```bash
# After the codex run finishes (writes $DATA_ROOT/reconstructed_projects.json):
./gpt compare ollama-legacy flat --names ollama codex
```

The ported ollama items keep their original prose (goal/objectives/requirements)
but their archetype/domain is the **deterministic prior** — the legacy run never
had an LLM classify — so treat classification agreement accordingly (the report
flags this). The prose-quality table is the apples-to-apples provider signal.

> The one-time porter (`scripts/port_legacy.py`) is not part of the supported
> pipeline; it was run once to migrate the legacy `projects[]` output.
