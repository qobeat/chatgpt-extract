# tests/fixtures/ — MANIFEST

Small, committed, **synthetic** fixtures for the deterministic test suite. No
personal data, no `$DATA_ROOT` content, no secrets — these ship in the repo and
are safe to read in CI.

## Files
- `ask_battery.jsonl` — labelled question/expected-answer battery used by
  `gpt ask-eval` and `tests/test_ask_eval.py` to grade retrieval + synthesis.
- `embed_eval.jsonl` — labelled query/relevant-doc pairs used by `gpt embed-eval`
  and `tests/test_*` to compare local embedding models (recall/MRR).

## How an agent CHANGES this folder
- Fixtures must stay synthetic and tiny. Never copy real chat transcripts,
  conversation IDs, or any PII here. Update the consuming test when a fixture's
  shape changes.
