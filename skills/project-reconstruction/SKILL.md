---
name: project-reconstruction
description: Use when asked to reconstruct a structured history of projects from one or more ChatGPT export .zip files — producing per-project name, slug, dates, version zip files, goal, objectives, requirements and their evolution, quickstart, how-to-use, and how-to-update as JSON. Triggers on "reconstruct my projects from these exports", "build project history JSON", "what projects did I work on and how did they evolve", "extract project versions and requirements from my ChatGPT zips". Input is one or more .zip exports; output is reconstructed_projects.json.
---

# Project Reconstruction

Reconstruct a machine-readable project ledger from raw ChatGPT exports using a
**deterministic-first, LLM-last** pipeline. Heavy lifting (streaming, canonical
path, clustering, version extraction, token reduction) is deterministic; the LLM
only writes fuzzy prose fields, schema-constrained.

## Pipeline
1. **extract_cards.py** (Stage 1) — stream each `.zip`, emit reduced transcripts
   + compact cards + incremental store. (See `chatgpt-export-triage` skill.)
2. **cluster_projects.py** (Stage 2) — union-find cards into project clusters.
   Strong signal = normalized **zip basename slugs** (your project versions
   arrive as `slug-vX.Y.zip`); weak signal = title slug. Emits `clusters.json`
   with deterministic facts: members, dates, `version_zip_files`, `n_versions`,
   `file_artifacts`.
3. **build_bundles.py** (Stage 3) — one token-capped `.md` bundle per cluster:
   a `DETERMINISTIC FACTS` JSON header + chronological reduced transcripts,
   hard-capped to a char budget so each project fits an LLM context in one shot.
4. **LLM summary** (Stage 4):
   - Local Ollama: `./ollama.sh --model gpt-oss:20b`
     (offline; deterministic facts are merged over the model output).

## One-shot (deterministic stages)
```bash
./run.sh --zip "<path-to-latest-export>.zip"
# then Stage 4 (Ollama)
./ollama.sh --model qwen2.5-coder:14b
```

## Output paths
With `.env` / `RECONSTRUCTOR_DATA_ROOT` set, artifacts live under that data root.
Without it, defaults are under `output/` (gitignored):

- `$DATA_ROOT/store/` — transcripts, cards, clusters
- `$DATA_ROOT/bundles/` — LLM context bundles
- `$DATA_ROOT/reconstructed_projects.json` — full internal JSON

Sanitized GitHub copy: `published/projects.json` via `python scripts/export_public.py --review`.

## Output schema (full internal JSON)
Per project: `project_name, slug, start_date, end_date, n_conversations,
n_versions, version_zip_files[], file_artifacts[], source_conversation_ids[],
goal, objectives[], requirements[], requirements_evolution[{date,change}],
quickstart, how_to_use, use_case, how_to_update`.

## Reusable across future exports
The store is keyed by conversation id. Point Stage 1 at a new export; only
new/changed chats are re-processed (newer `update_time` wins). Re-cluster and
re-summarize only affected slugs. Because exports are cumulative full snapshots,
you can pass just the newest `.zip`.

## Authority / hallucination control
`version_zip_files`, `file_artifacts`, dates, and ids are deterministic and must
be copied verbatim into the final JSON — the LLM is never trusted to produce
them. This is what keeps reconstruction auditable.

## Tuning
- Over-merged projects → raise `--min-slug-votes`.
- Truncated transcripts in a bundle → raise `--char-budget` (watch model ctx).
- Wrong clustering for a project that never shipped as a zip → it clusters on
  title slug; rename the chat or add a slug alias in a post-step.
