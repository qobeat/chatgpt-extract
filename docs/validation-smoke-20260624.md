# Validation smoke tests — 2026-06-24

Manual smoke tests run on WSL to verify (1) Codex Stage 4 against **old-run**
bundles and (2) the **new parser** (Stages 1–3) plus Ollama Stage 4 on a fresh
extract from the June 2026 ChatGPT export.

## Inputs

| Item | Path |
|---|---|
| Old run (Stages 1–3 + legacy JSON) | `../chatgpt-project-reconstructor/output/runs/legacy-20260622/` |
| ChatGPT export zip | `…/ChatGpt/…-2026-06-20-01-33-17-….zip` (1.5 GB, 4113 conversations) |
| Codex CLI | `codex` 0.142.0, logged in with ChatGPT |
| Ollama | `gpt-oss:20b`, `qwen2.5-coder:14b` on `localhost:11434` |

## Test 1 — Codex on old-run bundles (3 items)

**Command:**

```bash
python scripts/summarize.py \
  --provider codex \
  --store ../chatgpt-project-reconstructor/output/runs/legacy-20260622/store \
  --bundles ../chatgpt-project-reconstructor/output/runs/legacy-20260622/bundles \
  --out output/runs/codex-old-smoke/reconstructed_projects.json \
  --limit 3 --timeout 600
```

**Result: PASS** — 3/3 items, schema validation OK, ~85 s wall time.

| Slug | Latency | Primary archetype | Primary domain |
|---|---|---|---|
| `ados-profile` | 29 s | `controlled_spec_or_schema` | `software_engineering` |
| `new-chat` | 26 s | `knowledge_qa` | `general_knowledge` |
| `skip-today-s-meeting-request` | 24 s | `content_writing` | `personal_productivity` |

**Notes:**

- Old clusters lack `signal_summary`; `classify_prior` is computed on the fly.
- Output uses the **new ADOS schema** (`items[]`), not the legacy `projects[]` shape.
- Artifacts: `output/runs/codex-old-smoke/` (gitignored under `output/`).

Codex handled the large `ados-profile` bundle (~235 KB markdown) where local
Ollama models failed in Test 3.

## Test 2 — New parser (Stages 1–3)

**Command:**

```bash
unset RECONSTRUCTOR_DATA_ROOT   # use repo output/, not ~/.env data root
python run.py \
  --zip "<2026-06-20-export>.zip" \
  --run-label new-parser-20260624
```

**Result: PASS** — ~34 s wall time.

| Stage | Output |
|---|---|
| extract_cards | 4113 cards, `signals` on every card, ijson backend |
| cluster_projects | 3652 clusters (merge-cap guard split generic slugs) |
| classify | `classify_prior` on all clusters |
| build_bundles | 180 project bundles |

**New vs old run (`legacy-20260622`):**

| Metric | Old | New parser |
|---|---|---|
| Cards | 4113 | 4113 |
| Clusters | 3610 | 3652 |
| Bundles | 180 | 180 |
| Per-card `signals` | no | **yes** |
| Cluster `signal_summary` | no | **yes** |
| Cluster `classify_prior` | no | **yes** |

Example `ados-profile` signal summary: 7447 turns, 1275 version zips, code/data/doc
file classes present.

Artifacts: `output/runs/new-parser-20260624/` (store, bundles, logs).

## Test 3 — Ollama on new-parser bundles

**Commands:**

```bash
# gpt-oss:20b — 2/3 OK (ados-profile: empty response)
python scripts/summarize.py --provider ollama --model gpt-oss:20b \
  --run-label new-parser-20260624 --limit 3 --num-ctx 32768

# qwen2.5-coder:14b — 5/6 OK on first six versioned clusters
python scripts/summarize.py --provider ollama --model qwen2.5-coder:14b \
  --run-label new-parser-20260624 --limit 6 --num-ctx 16384 \
  --out output/runs/new-parser-20260624/reconstructed_ollama_6.json
```

**Result: PASS with known limitation** — parser + Ollama pipeline works; only the
mega-cluster `ados-profile` (304 conversations, ~235 KB bundle, est. ~31k input
tokens for first three items combined) fails local models.

| Slug | gpt-oss:20b | qwen2.5-coder:14b | Archetype (qwen) |
|---|---|---|---|
| `ados-profile` | empty response | non-JSON response | (deterministic stub only) |
| `repo-snapshot` | OK | OK | `runtime_package` |
| `holiday-portrait-transformation` | OK | OK | `media_generation` |
| `aidossdlc` | — | OK | `study_education_resource` |
| `displaydiag-20251201` | — | OK | `automation_or_diagnostic_script` |
| `funny-artist-names` | — | OK | `knowledge_qa` |

Schema validation passed on written JSON (failed items keep deterministic fields
and empty LLM prose).

## Conclusions

1. **Codex + old bundles** — works; reuse `legacy-20260622` store/bundles for
   ADOS re-summarization without re-parsing the zip.
2. **New parser** — produces signals, priors, and the same 180-bundle project
   set; ready for Stage 4.
3. **Ollama** — reliable on typical bundles; use Codex/OpenAI/Anthropic for
   `ados-profile`-scale clusters, or raise `--max-chars` / split strategy later.

## Reproduce

From repo root, using the project venv:

```bash
# Codex smoke (old data)
python scripts/summarize.py --provider codex \
  --store ../chatgpt-project-reconstructor/output/runs/legacy-20260622/store \
  --bundles ../chatgpt-project-reconstructor/output/runs/legacy-20260622/bundles \
  --out output/runs/codex-old-smoke/reconstructed_projects.json \
  --limit 3

# Full new parse (omit unset if .env pins RECONSTRUCTOR_DATA_ROOT elsewhere)
unset RECONSTRUCTOR_DATA_ROOT
python run.py --zip "<export.zip>" --run-label new-parser-20260624

# Ollama smoke (new data)
python scripts/summarize.py --provider ollama --model qwen2.5-coder:14b \
  --run-label new-parser-20260624 --limit 6 --num-ctx 16384
```
