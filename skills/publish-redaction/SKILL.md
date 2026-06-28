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
python scripts/export_public.py --md --scrub --review   # scrub, write, then verify
```
- `sanitize_document` / `sanitize_item` **strip provenance** —
  `source_conversation_ids`, `member_ids`, `signal_summary`, `bundle_sha`,
  `cost_usd` — and `basename_only()` normalizes zip paths to filenames.
- `--scrub` makes redaction an **active transform**: `sanitize_item(scrub=True)`
  calls `redact.scrub_obj`, replacing residual PII with `‹email›`/`‹path›`/
  `‹phone›`/`‹token›` placeholders in the written `published/` (not merely a
  failed commit).
- `--review` (`review_text` / `review_document` → `redact.find`) **detects** any
  remaining leak and exits non-zero, as a final gate.
- The `check_no_secrets.sh` pre-commit hook + `.gitignore` (`output/`, `*.zip`,
  `transcripts/`, `bundles/`, `reconstructed_projects.json`, `.env*`) are the
  defense-in-depth backstop.

## Redaction pattern set (NFR-P2) — shipped
`scripts/lib/redact.py` is the single, broadened pattern set shared by both
egress points (`find` detects; `scrub`/`scrub_obj` actively substitute
placeholders). It covers emails, Linux/WSL + macOS home paths
(`/home/<user>`, `/mnt/c/Users/<user>`, `/Users/<user>`), phone numbers,
API keys/tokens, JWTs, PEM private-key blocks, and range-checked IPv4. Broaden
it **here**, never in callers; cover each category with positive + negative cases
in `tests/test_redact.py`, and keep the `alice` fixtures the only allowed
user-path strings. Publish-boundary tests (`tests/test_publish_boundary.py`,
NFR-P1) feed known-PII fixtures end-to-end and fail if anything reaches
`published/` or git.

## (b) Cloud pre-send scrubber (NFR-P3) — shipped
`summarize.py` gates every **cloud** provider (`cursor`, `codex`, `claude`,
`openai`, `anthropic` — the shared `providers.CLOUD_PROVIDERS` set) behind
`--scrub-cloud`: each bundle is run through `redact.scrub` **before** any
off-machine call, and the result (`cloud_provider` / `scrub_cloud` /
`scrub_hits`) is persisted to the run manifest. Local Ollama is exempt (offline).
`gpt state` turns that evidence into a `GATE-PRIVACY` observation on
`COORD-D-VERDICT` (local pass; cloud passes only with recorded scrub hits; an
unscrubbed cloud call fails). See the `model-benchmark` skill's privacy gate.

## Invariant
Verify after any change: `published/` and the whole git tree contain **no** real
email, home path, key, or conversation id; the only user-path strings are the
`alice` test fixtures. Raw chat data never appears in either repo.
