# published/ — MANIFEST

The ONLY sanitized, git-committable output surface. Everything here is
publish-safe: no conversation ids, no home paths, no raw transcripts.

## How an agent EXECUTES this folder
- Not executed. Written ONLY by `./gpt publish` (`scripts/export_public.py`),
  which drops provenance, enforces basename-only zip paths, and (with `--scrub`)
  actively redacts email/path/phone/token/IP via `redact.scrub`.

## How an agent CHANGES this folder
- Do NOT hand-write personal data here. Regenerate via `gpt publish --review`
  (review fails the export on any detected email / home path).
- The committed placeholder MUST stay empty (`n_items: 0`, `items: []`) until a
  real, reviewed export is intended — `tests/test_repo_hygiene.py` and
  `test_publish_boundary.py` enforce the boundary.

## Files
- `projects.json` — sanitized catalog (public item schema; empty placeholder by
  default).
- `projects/<slug>.md` — optional sanitized per-project markdown (when exported).
- `README.md` — what the published surface is and how it is produced.
