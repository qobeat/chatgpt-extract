---
name: publish-redaction
description: Use when asked to publish a sanitized catalog, audit for personal-data leaks, harden masking, or decide what is safe to commit to a public repo. Triggers on "publish a redacted catalog", "is there PII in what I'm committing", "scrub before sending to the cloud", "harden the redaction". Enforces the privacy boundary: raw data stays in $DATA_ROOT; only sanitized output is ever committed.
---

# Publish & Redaction

Privacy here is a **boundary**, not mask-everything-everywhere. The local catalog
is raw and complete by design; redaction happens only at two egress points:
**(a) committing to the public repo**, and **(b) sending a bundle to a cloud
model**. This skill governs both.

## (a) Publish boundary — `scripts/export_public.py`
```bash
python scripts/export_public.py --md --review   # scan, then write published/
```
- `sanitize_document` / `sanitize_item` **strip provenance** —
  `source_conversation_ids`, `member_ids`, `signal_summary`, `bundle_sha`,
  `cost_usd` — and `basename_only()` normalizes zip paths to filenames.
- `--review` (`review_text` / `review_document`) **detects** leaks and fails the
  commit before `published/projects.json` is written.
- The `check_no_secrets.sh` pre-commit hook + `.gitignore` (`output/`, `*.zip`,
  `transcripts/`, `bundles/`, `reconstructed_projects.json`, `.env*`) are the
  defense-in-depth backstop.

## Known weakness to fix (NFR-P2)
Redaction is **detect-only** and the patterns are **narrow** — only emails and
macOS `/Users/...` paths (`export_public.py` patterns list). Harden it:
- Make redaction an **active transform** (replace with `‹email›`/`‹path›`
  placeholders), not just a detector that fails the commit.
- Broaden patterns beyond email + macOS path to **names, phone numbers, tokens/
  keys, and Linux/WSL home paths** (`/home/<user>`, `/mnt/c/Users/<user>`).
- Add publish-boundary tests (NFR-P1) that feed known-PII fixtures through and
  assert the published output is clean.

## (b) Cloud pre-send scrubber (NFR-P3) — currently MISSING
`summarize.py` sends the **raw bundle** to cloud providers (`cursor`, `codex`,
`claude`, `openai`) with no scrubbing — i.e. your real transcripts leave the
machine. Local Ollama is exempt (offline). Add a scrubber that runs on the bundle
**before** any cloud provider call, reusing the (hardened) redaction transform
above, and gate every cloud benchmark/summarize behind it. See the
`model-benchmark` skill's privacy gate.

## Invariant
Verify after any change: `published/` and the whole git tree contain **no** real
email, home path, key, or conversation id; the only user-path strings are the
`alice` test fixtures. Raw chat data never appears in either repo.
