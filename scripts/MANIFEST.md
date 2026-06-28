# scripts/ — MANIFEST

CLI commands and the build pipeline. Every `gpt <cmd>` dispatches here.

## How an agent EXECUTES this folder
- Always go through the repo-root entrypoint: `./gpt <command> [args]` (it
  activates the venv via `lib/activate_env.sh`, then calls `gpt_cli.py`).
- Do not run the step scripts with the system `python3`; use the venv
  (`~/.venvs/chatgpt-extract`) or `./gpt`, since they need numpy/jsonschema/ijson.
- Read-only commands (`list/search/show/info/project/category/zips`,
  `metrics/arena/report/compare`, `ask`) are safe to run anytime; `--json` is
  available on all of them for scripting.
- Spending/writing commands (`run`, `summarize`, `state`, `index`, `publish`)
  write only under `$DATA_ROOT` (or `published/`) and honour confirm gates.

## How an agent CHANGES this folder
- One command = one module; keep changes confined to the pillar they target
  (NFR-Q5). Add new commands by registering them in `gpt_cli.py`'s dispatch map.
- Keep `main(argv) -> int` and wrap entrypoints with `interrupt.run_cli` so
  Ctrl-C exits cleanly. Pure logic stays unit-testable (inject embedders /
  providers); add a matching `tests/test_*.py`.
- Never hardcode personal paths; resolve via `lib/paths.py`. Run `pytest -q`
  green before finishing.

## Files
- `gpt_cli.py` — single entrypoint; subcommand dispatch, help, `doctor`, and the
  read-only query commands (`list/search/show/info/project/category/zips`).
- `extract_cards.py` — Extract: stream export zip(s) → per-chat cards + reduced
  transcripts (ijson, bounded memory).
- `cluster_projects.py` — Cluster: group chats into projects over version slugs.
- `classify.py` — deterministic `classify_prior` per cluster from the ontology.
- `build_bundles.py` — Bundle: token-capped LLM bundles per project.
- `summarize.py` — AI summary step (multi-provider; cost gate; cloud pre-send scrub).
- `run.py` is at the repo root and orchestrates Extract→Cluster→Classify→Bundle.
- `index.py` — `gpt index`: build/refresh the local semantic embedding index.
- `ask.py` — `gpt ask`: recency-weighted retrieval + grounded, cited answer
  (local-first; `--scrub-cloud` gate; `--json`/`--rerank`; keyword fallback).
- `metrics.py` — quality/perf tables (completion/depth/accuracy/schema/speed/energy).
- `arena.py` — combined leaderboard; `compare_runs.py` / `compare_models.py` —
  head-to-head diffs; `timing_report.py` — latency report.
- `project_state.py` — emit ADOS Project State(s) per (workload, model);
  measures COORD-C-COVERAGE and gate evidence. `report.py` — cross-sweep report.
- `gen_model_benchmarks.py` — regenerate `config/generated/model_benchmarks.json`.
- `export_public.py` — sanitized publish to `published/`. `diagnose.py` — env probe.
- `recover_rollouts.py`, `port_legacy.py` — recovery / schema-migration utilities.
- `reconstruct` — backward-compatible shell alias forwarding to `./gpt`.
- `check_no_secrets.sh` — pre-commit hook blocking personal paths / export zips.
- `lib/` — shared library modules (see `lib/MANIFEST.md`).
