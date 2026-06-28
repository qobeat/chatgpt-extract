# ontology/ — MANIFEST

The ADOS ontology banks used to classify each catalog item (one Primary
Archetype + one Primary Domain/Subdomain Pair, plus optional secondaries).
See `README.md` here for the drift guards.

## How an agent EXECUTES this folder
- Not executed. Loaded by `scripts/classify.py` (deterministic `classify_prior`)
  and consumed by the LLM classification step in `scripts/summarize.py`. The LLM
  may confirm or override the prior only under the drift guards in `README.md`.

## How an agent CHANGES this folder
- Each bank validates against `schema/ontology_banks.schema.json`. Adding an
  archetype/domain is an ontology change: keep ids stable, update the schema if
  the shape changes, and bump the consuming artifacts' `ontology_version`.
- Read `README.md` before editing — it states the anti-drift rules the
  classifier and evaluator depend on.

## Files
- `archetypes.json` — Primary Archetypes (e.g. software_app, knowledge_qa).
- `domains.json` — Domain / Subdomain pairs.
- `cognitive_types.json` — cognitive-type tags.
- `difficulty.json` — difficulty bands.
- `verifiability.json` — verifiability tags.
- `README.md` — ontology usage + ADOS drift-guard rules (read first).
