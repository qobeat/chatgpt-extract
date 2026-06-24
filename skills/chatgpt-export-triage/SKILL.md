---
name: chatgpt-export-triage
description: Use when given a ChatGPT export .zip and asked to extract, filter, flatten, or inspect its conversations into text/JSON without unpacking the multi-GB archive. Triggers on "triage this export", "pull transcripts from conversations.json", "flatten my ChatGPT zip", "extract chats matching <keyword>". Input is a .zip; output is reduced text transcripts + a compact JSON card per conversation.
---

# ChatGPT Export Triage

Turn a raw OpenAI ChatGPT export `.zip` into clean, token-light artifacts
**deterministically** (no LLM, no full extraction, bounded memory).

## When to use
- You have a `conversations.json`-bearing `.zip` (native ChatGPT data export).
- You need transcripts or per-chat facts, not a database.

## How it works
The export is a JSON array of conversations; each conversation is a DAG in
`mapping`. Naive dumps mix discarded regenerations and crash on multimodal
`parts`. This skill streams element-by-element, follows `current_node -> root`
to keep only the **canonical branch**, and extracts content across
`content_type` shapes (text, multimodal_text, code/canvas, user_editable_context).

## Run
```bash
bash setup.sh
./run.sh --zip /path/to/export.zip
# or explicitly:
python3 scripts/extract_cards.py --zip /path/to/export.zip --out output/store
```
Outputs (under `$RECONSTRUCTOR_DATA_ROOT/store/` or `output/store/`):
- `transcripts/<conversation_id>.txt` — reduced transcript
  (assistant code bodies replaced by `‹code lang Nln :: first-line›` placeholders).
- `index.json` — incremental store keyed by conversation id
  (re-running on a newer export updates only changed chats; newer `update_time` wins).
- `cards.jsonl` — one compact card per chat: title, dates,
  `zip_files` (filename+slug+version), `file_artifacts`, `slug_votes`.

## Token discipline
Stripping assistant code bodies is the dominant saving (often 80–95%).
Requirements/intent live in user turns + assistant prose, which are preserved.

## Notes / drift
Core schema (`conversations.json` → array → `{id,title,create_time,update_time,
mapping,current_node}`) is stable, but OpenAI adds new `content_type`s over time
(reasoning, canvas, web/deep-research). Unknown shapes degrade to `[tag]` rather
than crashing. If transcripts look empty for a chat type, inspect one node with
`Get-JsonHead.ps1` / `python -c` and extend `message_text()` in
`scripts/lib/chatgpt_parse.py`.
