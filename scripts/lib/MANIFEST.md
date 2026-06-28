# scripts/lib/ — MANIFEST

Shared, importable helpers for the `scripts/` commands. No CLI here — these are
libraries imported after `scripts/lib` is put on `sys.path`.

## How an agent EXECUTES this folder
- Nothing is run directly. Modules are imported by the command scripts. The one
  exception is `activate_env.sh`, which is *sourced* (not executed) by the
  `./gpt` / `./run.sh` wrappers to activate the venv and load `.env`.
- To exercise a helper in isolation, import it from within the venv, e.g.
  `python -c "import sys; sys.path.insert(0,'scripts/lib'); import redact; ..."`.

## How an agent CHANGES this folder
- Keep these dependency-light and side-effect-free on import (numpy is imported
  lazily in `embeddings.py`; jsonschema/ijson are optional with graceful
  degradation). A module must import cleanly even when its optional dep is absent.
- Pure functions where possible, so commands stay testable. Every behavioural
  change needs a `tests/test_*.py` and `pytest -q` green.
- `paths.py` is the ONLY place that resolves data locations — never hardcode
  paths elsewhere. `redact.py` is the single PII pattern set for every egress
  boundary; broaden it here, not in callers.

## Files
- `paths.py` — resolve `$DATA_ROOT`, run-labels, store/bundles/index dirs.
- `activate_env.sh` — sourced venv + `.env` activation (sets `$PYTHON`).
- `chatgpt_parse.py` — parse ChatGPT export JSON → canonical messages/transcript.
- `store_query.py` — read-only catalog queries (list/search/info/transcripts).
- `zip_ledger.py` — per-zip "already handled" ledger (seen/added/skipped/written).
- `zip_scan_cache.py`, `zip_verify.py` — zip scan cache + completeness verify.
- `embeddings.py` — local Ollama embeddings, chunker, recency, cosine/top-k.
- `redact.py` — PII detect (`find`) + active scrub (`scrub`) for publish + cloud.
- `ollama_probe.py` — discover local Ollama models + roles; host reachability.
- `provider_detect.py` — auto-pick an available provider.
- `cost.py`, `power.py` — token/$ estimation and GPU energy integration.
- `models_bank.py` — load + merge the model bank (`config/models*.json` + generated).
- `rubric.py` — evaluation-rubric helpers (axes/gates/weights).
- `confirm.py` — spend/time confirmation gates (`--noask`, `--max-usd`).
- `run_log.py` — per-run command + stage logging under the data root.
- `interrupt.py` — clean Ctrl-C handling + child signal propagation.
- `trace.py`, `ulog.py`, `uio.py` — tracing, scrubbed logging, and terminal UI.
- `providers/` — provider backends (see `providers/MANIFEST.md`).
