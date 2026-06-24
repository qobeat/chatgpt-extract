# Published project summaries

This directory contains **sanitized, AI-generated item summaries** intended
for GitHub. They are derived from your local pipeline output but stripped of
personal data before commit. Each item carries an ADOS Primary Archetype and a
Primary Domain/Subdomain Pair.

## What is included

- `projects.json` — redacted item catalog (schema: `schema/extracted_item_public_schema.json`)
- `projects/<slug>.md` — optional per-item markdown (generate with `--md`)

## What is never published here

- Raw ChatGPT export `.zip` files
- Conversation transcripts (`store/transcripts/`)
- LLM context bundles (`bundles/*.md`)
- `source_conversation_ids` or other chat provenance

## How to update

From the project root, after the AI summary (Summarize) completes:

```bash
python scripts/export_public.py --md --review
git diff published/
git add published/
git commit -m "Update sanitized project summaries"
```

The `--review` flag scans for emails and user home paths. Skim `goal` and the
`archetype_fields` manually — the LLM may mention names or internal URLs.

## Redaction policy

| Field | Published? |
|-------|------------|
| `slug`, `title`, dates, counts | Yes |
| `primary_archetype`, `primary_domain_pair`, secondaries | Yes |
| `goal`, `objectives`, `requirements`, `archetype_fields` | Yes (review manually) |
| `version_zip_files` | Basename only |
| `file_artifacts` | Yes |
| `source_conversation_ids`, `signal_summary`, `bundle_sha` | **No** |
