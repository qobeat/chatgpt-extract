# tests/ — MANIFEST

The deterministic test suite. `pytest -q` MUST be green before any release
(NFR-Q1) and runs **fully offline with zero skips**; the one live lane is opt-in
(`GPT_ASK_LIVE=1`) and is not collected otherwise (see `conftest.py`).

## How an agent EXECUTES this folder
- From the repo root in the venv: `python -m pytest -q` (or a single file:
  `python -m pytest tests/test_embeddings.py -q`).
- Offline by design: embedders, index loaders, and providers are faked, so no
  network, no `$DATA_ROOT`, no API keys are needed.
- Live, opt-in checks: `tests/test_ask_live.py` exercises a real local Ollama
  (retrieval + a full grounded answer). `conftest.py` does NOT collect it unless
  `GPT_ASK_LIVE=1`, so the default run stays skip-free.

## How an agent CHANGES this folder
- Every behavioural change to `scripts/` needs a matching test here. Prefer pure
  functions + injected fakes over hitting real services. Keep the core
  deterministic (seed/fixed `now`) so results are reproducible.
- Mirror the pillar you changed (extraction, benchmark, catalog/ask, privacy,
  governance). Don't weaken privacy or schema tests to make a change pass.
- New live/integration tests must be opt-in (gate collection in `conftest.py`), so
  the default suite never skips or depends on a backend.

## Files (by area)
- Extraction / parsing: `test_classify.py`, `test_content_coverage.py`,
  `test_slug_parsing.py`, `test_shard_accounting.py`, `test_extract_limit.py`,
  `test_interrupt.py`, `test_clean_kill.py`.
- Zips / store: `test_zip_verify.py`, `test_zip_ledger.py`,
  `test_zip_scan_cache.py`, `test_store_query.py`, `test_paths.py`,
  `test_paths_run_label.py`.
- Benchmark / metrics / governance: `test_metrics_quality.py`,
  `test_metrics_geometry.py`, `test_eval_facets.py`, `test_rubric_gates.py`,
  `test_geometry_valid.py`, `test_project_state.py`, `test_report.py`,
  `test_cost.py`, `test_power.py`, `test_gen_model_benchmarks.py`.
- Providers / structured output: `test_providers.py`, `test_provider_detect.py`,
  `test_structured_output.py`, `test_ollama_probe.py`.
- Catalog / Ask (semantics): `test_embeddings.py`, `test_ask_route.py`,
  `test_ask_latency.py` (FR-Q16 knobs + FR-Q19 status line), `test_ask_daemon.py`,
  `test_ask_stress.py` (FR-Q18/Q20 stress battery), `test_ask_budget.py`,
  `test_ask_privacy.py` (offline FR-Q4 privacy gate + `--json`/keyword fallback),
  `test_ask_live.py` (opt-in live Q&A via `GPT_ASK_LIVE=1`).
- Privacy / publish: `test_redact.py`, `test_export_public.py`,
  `test_publish_boundary.py`, `test_log_scrub.py`, `test_check_no_secrets.py`,
  `test_repo_hygiene.py`, `test_summarize_sanitize.py`.
- Release governance (ADOS audit 2.1.0 closure): `test_release_hardening.py`
  (cloud egress gate, bundle CLI contract, custom redaction),
  `test_release_coherence.py` (NFR-Q7 identity agreement, no foreign slug),
  `test_doc_governance.py` (NFR-Q8 link integrity + MANIFEST coverage).
- Schema: `test_schema_roundtrip.py`, `test_schema_validation.py`.

(Run `python -m pytest --collect-only -q` for the authoritative current list.)
