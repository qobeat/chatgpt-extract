# tests/ — MANIFEST

The deterministic test suite. `pytest -q` MUST be green before any release
(NFR-Q1). Tests run offline by default; live tests skip when Ollama is absent.

## How an agent EXECUTES this folder
- From the repo root in the venv: `python -m pytest -q` (or a single file:
  `python -m pytest tests/test_embeddings.py -q`).
- Offline by design: embedders, index loaders, and providers are faked, so no
  network, no `$DATA_ROOT`, no API keys are needed.
- Live, opt-in checks: `tests/test_ask_live.py` exercises a real local Ollama and
  auto-skips when none is reachable; its slow synthesis case runs only under
  `GPT_ASK_LIVE_SYNTH=1`.

## How an agent CHANGES this folder
- Every behavioural change to `scripts/` needs a matching test here. Prefer pure
  functions + injected fakes over hitting real services. Keep the core
  deterministic (seed/fixed `now`) so results are reproducible.
- Mirror the pillar you changed (extraction, benchmark, catalog/ask, privacy,
  governance). Don't weaken privacy or schema tests to make a change pass.
- New live/integration tests must skip cleanly when their backend is unavailable.

## Files (by area)
- Extraction / parsing: `test_classify.py`, `test_content_coverage.py`,
  `test_slug_parsing.py`, `test_extract_limit.py`, `test_interrupt.py`,
  `test_clean_kill.py`.
- Zips / store: `test_zip_verify.py`, `test_zip_ledger.py`,
  `test_zip_scan_cache.py`, `test_store_query.py`, `test_paths.py`,
  `test_paths_run_label.py`.
- Benchmark / metrics / governance: `test_metrics_quality.py`,
  `test_metrics_geometry.py`, `test_eval_facets.py`, `test_rubric_gates.py`,
  `test_geometry_valid.py`, `test_project_state.py`, `test_report.py`,
  `test_cost.py`, `test_power.py`, `test_gen_model_benchmarks.py`.
- Providers / structured output: `test_providers.py`, `test_provider_detect.py`,
  `test_structured_output.py`, `test_ollama_probe.py`.
- Catalog / Ask (semantics): `test_embeddings.py`, `test_ask_privacy.py`
  (offline FR-Q4 privacy gate + `--json`/keyword fallback), `test_ask_live.py`
  (gated live Q&A).
- Privacy / publish: `test_redact.py`, `test_export_public.py`,
  `test_publish_boundary.py`, `test_log_scrub.py`, `test_check_no_secrets.py`,
  `test_repo_hygiene.py`, `test_summarize_sanitize.py`.
- Schema: `test_schema_roundtrip.py`, `test_schema_validation.py`.

(Run `python -m pytest --collect-only -q` for the authoritative current list.)
