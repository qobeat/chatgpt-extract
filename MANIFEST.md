# MANIFEST.md — Agent Execution Contract

> For the Cursor agent (or any coding agent) running this package locally.
> Follow GOAL/OBJECTIVES exactly. Do not change them without an explicit ask.

## VERSION (source of truth)
The **current release version is the heading of the top entry in
[`CHANGELOG.md`](CHANGELOG.md)** — nothing else. As of this manifest that is
**`1.1.0` — "Provenance"**. Do not invent a version anywhere else; read it from
the changelog. A release is "named and dated" (e.g. `1.0.0 — Semantics —
2026-06-28`).

## RELEASE PROCEDURE (how to cut a release)
A release is a documentation + version event, not a code event — code lands
continuously and stays green (`pytest -q`). To cut release `X.Y.Z` named `NAME`:

1. **Gate:** `pytest -q` is green; `./gpt doctor` is clean on the target box.
2. **`CHANGELOG.md`** — add a new top entry `X.Y.Z — NAME — YYYY-MM-DD` with
   `Added` / `Changed` / `Fixed` subsections. This top heading *becomes* the
   current version (the source of truth above). Bump per semver: breaking →
   major, additive → minor, fix-only → patch.
3. **`REQUIREMENTS.md`** — tag every newly satisfied requirement `[IMPLEMENTED]`
   with its verifying test; move done items into "§4 Implemented in the current
   release".
4. **`TODO.md`** — remove shipped items from "Next"; durable record lives in the
   changelog, not a growing list here.
5. **`README.md`** — update the command table and any runbook for new commands.
6. **`MANIFEST.md`** (this file + per-folder manifests) — update the VERSION line
   and any changed file inventory.
7. Do **not** edit GOAL/OBJECTIVES, the Project Geometry, or the evaluation
   rubric as part of a release (those change only by explicit decision).

Files that MUST agree on the release after a cut: `CHANGELOG.md` (authority),
`REQUIREMENTS.md` §4, `README.md` command table, this `MANIFEST.md` VERSION line.

## GOAL
Produce a full internal `reconstructed_projects.json` under
`$RECONSTRUCTOR_DATA_ROOT` (or `output/` if unset): a structured, auditable
catalog of the user's ChatGPT history reconstructed from export `.zip` file(s),
where **every item carries an ADOS Primary Archetype + Primary Domain/Subdomain
Pair**, conforming to `schema/extracted_item_schema.json`.

For GitHub, run `scripts/export_public.py` to write sanitized summaries to
`published/projects.json` (no conversation IDs).

## OBJECTIVES
1. Process each provided `.zip` without full extraction or whole-file JSON load.
2. Keep only the canonical conversation branch; drop discarded regenerations.
3. Cluster deterministically over **real** version-zip slugs; drop junk zips
   (attachment hashes, bare-numeric downloads) and guard generic mega-merges.
4. Classify each item with the ADOS ontology bank (`ontology/`): one Primary
   Archetype + one Primary Domain/Subdomain Pair, plus optional secondaries.
5. Use the LLM ONLY for classification and archetype-conditioned prose; copy
   deterministic facts verbatim. Estimate cost before any paid call and obey the
   `--max-usd` cap + circuit breakers.

## PRECONDITIONS
- Python 3.10+. Run `bash setup.sh` or `pip install -r requirements.txt`.
- Load paths from `.env` (`VENV_DIR`, `RECONSTRUCTOR_DATA_ROOT`) or
  `config/reconstruct.config.local.json` (`data_root`, `default_zips`).
- API providers (token-exact) need keys in `.env` (`OPENAI_API_KEY`,
  `ANTHROPIC_API_KEY`, `CURSOR_API_KEY`). Default provider is local Ollama ($0).
- Subscription CLI providers run on your existing plan instead of API billing:
  `cursor` (run `agent login`), `codex` (run `codex login`), `claude` (run
  `claude setup-token` → `CLAUDE_CODE_OAUTH_TOKEN`, keep `ANTHROPIC_API_KEY`
  unset). See README → "Use your subscription plans".
- Zip path(s) via `--zip`, else `default_zips` in local config, else STOP and ask.
- If a `.zip` is missing on disk, STOP and report it. Do not fabricate data.

## PLAN (actions → success condition)
1. `./gpt run --zip "<zip1>" [--zip "<zip2>" ...]`
   (or the backward-compatible alias `./scripts/reconstruct run --zip ...`)
   - SUCCESS: `$DATA_ROOT/store/{index.json,cards.jsonl,clusters.json}` (clusters
     carry `signal_summary` + `classify_prior`) and `$DATA_ROOT/bundles/*.md` +
     `INDEX.json` exist; non-zero cluster count.
2. Present `clusters.json` summary BEFORE the AI summary (slugs, n_conversations,
   n_passes, classify_prior). Cheap checkpoint.
3. AI summary (Summarize) — LLM classify + summarize:
   - `./gpt summarize --provider ollama --model gpt-oss:20b`
     (or API: `--provider openai|anthropic --model ... --max-usd N --yes`;
     or plan-billed CLI: `--provider cursor|codex|claude` — no key, model optional)
   - SUCCESS: full JSON validates against `schema/extracted_item_schema.json`;
     every item has `slug`, `primary_archetype.id`, `primary_domain_pair.domain`,
     `goal`, `source_conversation_ids`, and archetype-contract keys in
     `archetype_fields`; deterministic fields match `clusters.json`.
4. (Optional GitHub publish) `python scripts/export_public.py --md --review`
   - SUCCESS: `published/projects.json` has no `source_conversation_ids`; review
     passes with no PII warnings.

## AUTHORITY RULES (anti-hallucination)
- DETERMINISTIC (copied, never generated): `version_zip_files`, `file_artifacts`,
  `start_date`, `end_date`, `n_conversations`, `n_passes`,
  `source_conversation_ids`, `slug`, `signal_summary`.
- LLM-OWNED: `title`, `description`, `is_durable_project`, `primary_archetype`,
  `secondary_archetypes`, `primary_domain_pair`, `secondary_domain_pairs`,
  `confidence`, `goal`, `objectives` (forming/speeding/governance), `requirements`,
  `requirements_evolution`, `deliveries`, `archetype_fields`.
- The deterministic `classify_prior` is a candidate only; the LLM must confirm or
  override it under the ADOS drift guards in `ontology/README.md`.
- If LLM output conflicts with deterministic facts, deterministic wins.

## DRIFT / STOP CONDITIONS
- Empty transcripts for a whole content-type → likely a new OpenAI `content_type`.
  STOP, report it, propose extending `message_text()` in
  `scripts/lib/chatgpt_parse.py`.
- ijson unavailable AND zip > 200 MB → warn; install ijson first.
- Cost estimate exceeds `--max-usd`, or a breaker trips → STOP, write partials,
  report `breaker_reason` and `skipped_breaker`.
- Do not modify files outside this package. Do not alter GOAL/OBJECTIVES.
- Never commit transcripts, bundles, export zips, or full internal JSON to git.

## OUTPUT INVENTORY
```
$DATA_ROOT/store/index.json                   incremental store (id-keyed)
$DATA_ROOT/store/cards.jsonl                  per-conversation facts + signals
$DATA_ROOT/store/transcripts/<id>.txt         reduced transcripts (LOCAL ONLY)
$DATA_ROOT/store/clusters.json                clusters + signal_summary + prior
$DATA_ROOT/bundles/<slug>.md                  token-capped LLM bundles (LOCAL ONLY)
$DATA_ROOT/summarize_trace.jsonl              per-call cost/breaker trace
$DATA_ROOT/reconstructed_projects.json        full internal deliverable (items[])
published/projects.json                       sanitized GitHub deliverable
published/projects/<slug>.md                  optional sanitized markdown
```
