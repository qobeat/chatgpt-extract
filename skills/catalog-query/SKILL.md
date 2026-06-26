---
name: catalog-query
description: Use when asked to query, list, search, count, or inspect what is already in the reconstructed catalog — projects, chats, categories, archetypes, zip versions, or run stats — without re-running extraction. Triggers on "list my projects", "search the catalog for <topic>", "how many projects are <category>", "show project <slug>", "what runs exist", "catalog stats". Reads the stored run; never re-parses the export.
---

# Catalog Query

Answer questions about the **already-built** catalog by reading the stored run.
Never re-run extraction to answer a query. All functions live in
`scripts/lib/store_query.py` and are surfaced by the `gpt` CLI.

## CLI
```bash
gpt list                       # projects (enriched: dates, versions, category)
gpt list --category controlled_spec_or_schema
gpt search "<keyword>"         # chats whose transcript text contains keyword
gpt search -i -w "<word>"      # -i case-insensitive · -w whole-word match
gpt search -a "<keyword>"      # also match title + filenames mentioned in chat
gpt search -f "usage_events.csv" # chats where that file was attached/seen
gpt search -i usage_events | gpt cat --color  # context windows around each match
gpt search usage_events | gpt cat --context-lines-no 1   # grep style (lineno:line)
gpt search usage_events | gpt cat --max-parts 2 --reverse # last 2 match blocks
gpt cat <chat-id> [--pattern P --color]       # standalone: full chat text for id(s)
gpt show <slug>                # one project's full reconstructed record
gpt info                       # catalog stats (counts, categories, coverage)
gpt zips-verify                # zip ledger status per project
```
All read commands support `--json` for piping (FR-U2). Add `--run-label <label>`
to query a specific run; default resolves `latest`.

## Functions (store_query.py)
- `list_projects_enriched(query, limit)` — projects with dates/versions/category.
- `list_category_tree(categories=...)` — projects grouped by ADOS category.
- `list_projects` / `list_chats(query, limit)` — flat project or chat listings.
- `search_transcripts(pattern, ignore_case, word, scope_all, limit)` — chats by
  transcript text (scope_all also matches title + file_artifacts).
- `search_attachments(pattern, ignore_case, word, limit)` — chats by attachment /
  file_artifact filename.
- `read_transcript(id)` / `chat_meta(id)` / `transcript_path(id)` — chat text, header info, on-disk path (`gpt cat`).
- `build_highlight_regex(pattern, ignore_case, word)` — regex for colorizing hits.
- `search(query, limit)` — legacy keyword search over project + chat titles.
- `summary_state()` / `catalog_state()` — what has been summarized vs extracted.
- `info_stats()` — aggregate counts, category distribution, coverage.
- `zip_status()` — per-project version-zip ledger.

## Cross-run / observability
Cross-run questions ("which run had the most projects", run timings, sizes) are
answered by the **`chatgpt-extract-catalog`** repo (`./runs.sh list`,
`./run_summary.sh`), which reads the same `$DATA_ROOT`. Keep that read-only split:
this tool *writes* runs; the catalog repo *summarizes* them.

## Notes
A query that returns empty usually means nothing has been summarized yet
(`catalog_state` shows extracted-but-not-summarized) — run the `model-benchmark` /
reconstruction summarize step first, don't assume the data is missing.
