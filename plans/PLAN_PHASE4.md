# PLAN — Phase 4: CLI / UX polish & packaging

**Read first (only these):** `PLANNED-WORKS.md` (Phase 4), `REQUIREMENTS.md`
(FR-U1..U3, NFR-Q2, NFR-R2, NFR-R3), `skills/catalog-query/SKILL.md`,
`README.md` (How it works, command reference).

## GOAL of this phase
Make the toolkit best-in-class for daily WSL use: a consistent, fast,
script-only command-line assistant with no new data semantics — pure fit-and-
finish over Phases 1–3.

## Scope guard (NFR-Q5)
Touch only `scripts/gpt_cli.py`, output formatting/help, `setup.sh`,
`.env.example`, and docs. Do **not** change extraction, the benchmark metric, or
redaction logic.

## Actions and success conditions (priority order)

1. **Consistent verb grammar + single entrypoint (FR-U1).**
   - One `gpt <command>` surface with consistent verbs
     (`run/summarize/list/search/show/info/metrics/arena/compare/publish/
     zips-verify`); models are name-driven, not flag-driven.
   - *Success:* `gpt --help` lists a coherent verb set; every read command accepts
     `--run-label` and resolves `latest` by default.

2. **`--json` on every read command (FR-U2 piping, FR-U3).**
   - All read/query commands emit machine-readable `--json`; `gpt info`
     summarises catalog + last-run state at a glance.
   - *Success:* `gpt list --json | jq` works for each read command; `gpt info`
     shows extracted/summarized/published counts and the latest run.

3. **Preview before spend (FR-U2).**
   - Any LLM command shows an item count + cost/time estimate and requires
     confirmation (or `--yes`) before spending.
   - *Success:* `gpt summarize` without `--yes` prints an estimate and waits; with
     `--yes` it proceeds; a test covers both paths.

4. **Fast feedback + resumability surfaced (NFR-R2, NFR-R3).**
   - Long runs show progress per item and persist after each item so Ctrl-C +
     resume loses nothing.
   - *Success:* interrupting a run and re-invoking with the same `--run-label`
     resumes from the next unprocessed item.

5. **Install ergonomics + vendored-lib pinning (NFR-Q2, PLANNED-WORKS Phase 3→4).**
   - `setup.sh` + `.env.example` make a clean WSL2 Ubuntu setup one step; add a
     `gpt doctor` that checks Python, venv, `$DATA_ROOT`, providers, and GPU; pin
     the `chatgpt-extract-catalog` vendored libs to the recorded `VENDORED_FROM`
     commit.
   - *Success:* a fresh WSL clone reaches a working `gpt info` via documented
     steps; `gpt doctor` reports environment readiness; vendored libs are pinned.

## Acceptance criteria
`gpt` exposes a consistent verb set with `--json` everywhere (FR-U1/U2), shows
estimates before spend and state at a glance (FR-U2/U3), resumes cleanly
(NFR-R3), installs on WSL2 in documented steps (NFR-Q2), and the two repos can no
longer silently drift; `pytest -q` is green (NFR-Q1).

## Out of scope
Any change to data extraction, the benchmark metric, or redaction semantics
(Phases 1–3). No web UI, service, or database (non-goals).
