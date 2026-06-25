---
name: project-reconstruction
description: Use when asked to reconstruct a structured history of projects from one or more ChatGPT export .zip files — producing per-project name, slug, dates, version zip files, goal, objectives, requirements and their evolution, quickstart, how-to-use, and how-to-update as JSON. Triggers on "reconstruct my projects from these exports", "build project history JSON", "what projects did I work on and how did they evolve". Input is one or more .zip exports; output is reconstructed_projects.json.
---

# Project Reconstruction

Reconstruct a machine-readable project ledger from raw ChatGPT exports using a
**deterministic-first, LLM-last** pipeline. Heavy lifting (streaming, canonical
path, clustering, version extraction, token reduction) is deterministic; the LLM
only writes fuzzy prose fields, schema-constrained, and **deterministic facts are
merged OVER the model output** so the model can never corrupt a known fact.

## Pipeline
1. **extract_cards.py** (Extract) — see the `chatgpt-export-triage` skill.
2. **cluster_projects.py** (Cluster) — union-find cards into project clusters.
   Strong signal = normalized **zip basename slugs** (`slug-vX.Y.zip`); weak
   signal = title slug. Emits `clusters.json` (members, dates, `version_zip_files`,
   `n_versions`, `file_artifacts`).
3. **build_bundles.py** (Bundle) — one token-capped `.md` bundle per cluster:
   a `DETERMINISTIC FACTS` JSON header + chronological reduced transcripts,
   hard-capped to a char budget so each project fits an LLM context in one shot.
4. **Summarize** — local Ollama (`./ollama.sh --model gpt-oss:20b`, offline) or a
   cloud provider; the LLM fills prose fields only.

## One-shot
```bash
./run.sh --zip "<path-to-latest-export>.zip"
gpt summarize --model qwen3:8b      # or a cloud provider
```

## Output
`reconstructed_projects.json` — per project: name, slug, dates, version zips,
`goal`, `objectives[]` (role: forming/speeding/governance), `requirements[]`,
`primary_archetype` + archetype fields, quickstart / how-to-use / how-to-update.
Validated against `schema/extracted_item_schema.json`.

## Notes / drift
The summarize step must stay robust to malformed model output (weak models emit a
bare string where an object is expected). Coerce to the deterministic prior rather
than crash — but note that coercing to *empty* feeds the quality artifact (see the
`model-benchmark` skill), so the durable fix is **structured-output enforcement**,
not just coercion.
