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
² **Summarize** is per project (~120 projects for ~2,700 conversations in 1 GB),
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
| **`index.json`** | `$DATA_ROOT/store/index.json` | One row per conversation; `source_zip` is the export basename that **last wrote** that chat. |

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
/mnt/c/.../Downloads/ChatGpt/*.zip      ← raw ChatGPT exports (input only)
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
| `gpt zips` | Which export zips were processed; chats per `source_zip` |
| `gpt zips-verify` | Verify catalog vs all ledger exports — nothing missed (auto-finds zip paths) |
| `gpt publish` | Redact internal JSON → `published/` for public GitHub commit |
| `gpt diagnose --zip Z` | Inspect an export `.zip` (read-only) |

`GLOB` is case-insensitive: a plain word matches as a substring (`gpt search
meeting`), or use wildcards (`gpt list "*ados*"`). Add `--json` to `list`,
`search`, and `info` for scripting.

```text
$ gpt
chatgpt-extract — data root: ~/chatgpt-reconstructor-data

Parsed:    4,113 chats · 180 projects · 2023-09-22 → 2026-06-19
AI summary: not run

Provider:  codex (auto-detected)
Estimate:  ~84 min for 180 items

Next:  gpt summarize --limit 3   # quick sample (asks first)
       gpt all                   # full catalog
```

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
export GPT_ZIP_DIR=/mnt/c/Users/kirae/Downloads/ChatGpt
export GPT_ZIP1="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2025-10-17-19-56-33-50c8a5d5e9bf4c209ace185ab57ffc5c.zip"
export GPT_ZIP2="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2026-04-16-04-39-07-9622a6a056494e30ad4e6463364aae4d.zip"
export GPT_ZIP3="$GPT_ZIP_DIR/6b94875b2e20aa132cdc6640b12b92b460721b0ec39d1f5ea5a6a27f2e8cba94-2026-06-20-01-33-17-d9f765de52d44d3e8db4ca36d8dffa3e.zip"
```

`GPT_ZIP_DIR` is the Windows Downloads folder mounted in WSL — where ChatGPT
export `.zip` files land after you request a data export.

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

# Re-parse / incremental update — unchanged chats are skipped automatically.
# If a .zip was already fully processed, gpt notifies you before re-scanning.
./gpt run --zip "<newer-export>.zip"

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
  Re-running `gpt run` on a zip that was already processed prints a notice (and,
  if every provided zip is already done, asks before re-scanning) — the parse is
  still idempotent and skips unchanged conversations.
- **Long run warning.** Any run estimated to take more than **5 minutes**
  (Extract is ~90s/GB) warns and asks before starting. The AI summary step has
  always asked via its own confirmation gate.

## Parsing a new export (Extract → Cluster → Bundle)

```bash
./gpt run --zip "<your-export>.zip"
```

Deterministic, offline, and free. On a ~1.5 GB / ~4,000-conversation export this
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
| `--limit N` | `0` (all) | Process only first N new/changed conversations. |
| `--store PATH` / `--bundles PATH` | from layout | Override directories. |
| `--min-slug-votes N` | `3` | Min conversations sharing a slug to cluster. |
| `--merge-cap N` | `12` | Stop generic title slugs absorbing more than N chats. |
| `--char-budget N` | `48000` | Max characters per LLM bundle. |
| `--min-versions N` | `1` | Bundle only projects with ≥ N version zips (`0` = all). |
| `--noask` / `--yes` | off | Skip the pre-run warning (long run and/or already-handled zip). |
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
| `--min-versions N` | `1` | Only projects with ≥ N version zips (or ≥ 2 conversations). |
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

Opens every export recorded in `zip_ledger.json`, counts conversations in each
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

### `gpt publish` — GitHub-safe export (optional)

**Do you need it?** Only if you want to commit a **public, redacted** catalog to
the `chatgpt-extract` GitHub repo. Your real data stays in
`$DATA_ROOT/reconstructed_projects.json` (gitignored, may contain PII). `gpt
publish` copies summaries into `published/projects.json` inside this repo —
stripping conversation IDs, raw signals, and bundle hashes — so you can share
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
gitignored. `gpt publish --review` strips conversation IDs and scans for emails
and personal paths before anything reaches `published/`.

## Tests

```bash
python -m pytest tests/ -q     # or: python -m unittest discover -s tests
```

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
