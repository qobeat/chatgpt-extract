# config/generated/ — MANIFEST

Machine-generated artifacts. Treat as build output, not hand-edited source.

## How an agent EXECUTES this folder
- Not executed. `lib/models_bank.py` merges `model_benchmarks.json` into the
  model bank at load time so a verdict can travel with a model name.

## How an agent CHANGES this folder
- Do NOT hand-edit. Regenerate from the corrected metric via
  `./gpt gen-model-benchmarks` (`scripts/gen_model_benchmarks.py`), which derives
  verdicts from sweep data so depth/accuracy/completion stay separated (FR-D2).
- Validate against `schema/model_benchmarks.schema.json`
  (`tests/test_gen_model_benchmarks.py`).

## Files
- `model_benchmarks.json` — per-model benchmark verdicts (provenance + separated
  coordinates), regenerated, never blended into one number.
