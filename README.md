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

> Run summaries, the run catalog, and cross-run stats live in the companion
> **private** repo `chatgpt-extract-catalog`.

## How it works — the four steps

| Step | Name | LLM? | What it does |
|---|---|---|---|
| 1 | **Extract** | no | Stream the export into a reduced transcript + a deterministic *card* per conversation (dates, version zips, file artifacts, content **signals**). Junk "zips" (attachment hashes, bare `0.zip`) are dropped so they can't pollute version counts. |
| 2 | **Cluster** | no | Union-find over real version-zip slugs to group conversations into projects. A `--merge-cap` guard stops a generic title slug absorbing dozens of unrelated chats. |
| 3 | **Bundle** | no | Attach a deterministic archetype/domain *prior* to each project, then pack each project into one token-capped bundle. |
| 4 | **Summarize** (AI summary) | **yes** | Confirm/override the classification under ADOS drift guards and fill only the **archetype-conditioned** fields. Deterministic facts are merged *over* the model output. |

**Extract → Cluster → Bundle** are free and offline (one `gpt run`). The
**AI summary** is the only step that uses an LLM, and it always asks before
running (see [Confirmation gate](#confirmation-gate)).

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
| `gpt search GLOB` | Top 10 matches across projects + chats |
| `gpt show SLUG` | Details for one project (AI summary item if summarized) |
| `gpt doctor` | Check venv, ijson/jsonschema, and provider readiness |
| `gpt run` | Build steps: Extract → Cluster → Bundle (deterministic, no LLM) |
| `gpt summarize` | AI summary (auto-detects provider, asks first) |
| `gpt all` | `run` + `summarize` in one shot |
| `gpt compare A B` | Head-to-head quality of two summary runs (e.g. ollama vs codex) |
| `gpt publish` | Sanitize into `published/` for GitHub |
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
`~/chatgpt-reconstructor-data`) and an optional `--run-label`. **`--run-label`
is optional** — omit it for a single catalog; use it for side-by-side
experiments.

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

### `gpt list` / `gpt search` / `gpt info` / `gpt show`

| Command | Key options |
|---|---|
| `gpt list [GLOB]` | `--chats`, `--all`, `--limit N`, `--run-label`, `--json` |
| `gpt search GLOB` | `--limit N` (default 10), `--run-label`, `--json` |
| `gpt info` | `--run-label`, `--json` |
| `gpt show SLUG` | `--run-label` |

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

### `gpt publish` — GitHub-safe export

| Option | Default | Description |
|---|---|---|
| `--in PATH` | `$DATA_ROOT/reconstructed_projects.json` | Input JSON (`items[]` schema). |
| `--out PATH` | `published/projects.json` | Sanitized output. |
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
