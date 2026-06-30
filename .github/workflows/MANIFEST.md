# .github/workflows/ — MANIFEST

GitHub Actions automation for the repo. Governed source (NFR-Q6 CI lives here).

## Files
- `ci.yml` — Continuous integration: byte-compiles `scripts`/`tests` (syntax
  gate), then runs the hermetic `pytest -q` suite on Python 3.10–3.12 on every
  push and pull request. The suite runs offline with **zero skips** (the live
  Ask lane is opt-in via `GPT_ASK_LIVE=1`; see `tests/conftest.py`).

## How an agent CHANGES this folder
- Keep CI hermetic: no network, no `$DATA_ROOT`, no API keys. Every provider is
  faked in tests. If you add a job, it must keep `pytest -q` green and skip-free.
