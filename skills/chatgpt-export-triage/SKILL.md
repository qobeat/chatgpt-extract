---
name: chatgpt-export-triage
description: Use when given a ChatGPT export .zip and asked to extract, filter, flatten, or inspect its conversations into text/JSON without unpacking the multi-GB archive. Triggers on "triage this export", "pull transcripts from conversations.json", "flatten my ChatGPT zip", "extract chats matching <keyword>", "why is this chat type empty". Input is a .zip; output is reduced text transcripts + a compact JSON card per conversation.
---

# ChatGPT Export Triage

Turn a raw OpenAI ChatGPT export `.zip` into clean, token-light artifacts
**deterministically** (no LLM, no full extraction, bounded memory).

## When to use
- You have a `conversations.json`-bearing `.zip` (native ChatGPT data export),
  possibly sharded as `conversations-NNN.json`.
- You need transcripts or per-chat facts, not a database.

## How it works
The export is a JSON array of conversations; each conversation is a DAG in
`mapping`. This skill streams element-by-element with `ijson`, follows
`current_node -> root` to keep only the **canonical branch**, and extracts content
across `content_type` shapes. Unknown shapes degrade to `[tag]` rather than
crashing.

## Run
```bash
bash setup.sh
./run.sh --zip /path/to/export.zip
# explicit:
python3 scripts/extract_cards.py --zip /path/to/export.zip --out output/store
```
Outputs (under `$RECONSTRUCTOR_DATA_ROOT/store/`):
- `transcripts/<conversation_id>.txt` — reduced transcript (assistant code bodies
  replaced by `‹code lang Nln :: first-line›` placeholders).
- `index.json` — incremental store keyed by conversation id (re-run updates only
  changed chats; newer `update_time` wins).
- `cards.jsonl` — one compact card per chat: title, dates, `zip_files`,
  `file_artifacts`, `slug_votes`.

## Token discipline
Stripping assistant code bodies is the dominant saving (often 80–95%).
Requirements/intent live in user turns + assistant prose, which are preserved.

## Coverage — what to extend (FR-C2 / FR-C3)
The core schema is stable, but several content-types are currently dropped and
should be captured so the catalog is lossless. When transcripts look thin for a
chat type, inspect one node (`python -c "import json,sys;..."`) and extend
`message_text()` in `scripts/lib/chatgpt_parse.py`:

- **Browsing / tools:** `tether_quote`, `tether_browsing_display`,
  `execution_output` (code-interpreter results) — preserve as labelled blocks.
- **Reasoning:** o1/o3 `reasoning` parts — keep a marker even if body is summarised.
- **Per-message provenance:** capture `message.metadata.model_slug` onto the card
  (needed to attribute which model wrote what), and `metadata.attachments`
  (filenames/types) so attached files are not silently lost.

Add a coverage test (`tests/test_slug_parsing.py` style) asserting each known
`content_type` produces non-empty output, so regressions surface as failures.
