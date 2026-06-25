# PLAN — Phase 3: Publish / redaction hardening & observability

**Read first (only these):** `PLANNED-WORKS.md` (Phase 3), `REQUIREMENTS.md`
(NFR-P1, NFR-P2, NFR-P4, NFR-Q4), `skills/publish-redaction/SKILL.md`,
`skills/catalog-query/SKILL.md`, `README.md` (Privacy model, Repositories).

## GOAL of this phase
Make the published surface provably safe by construction (active redaction, not
detect-only), and make runs observable across the two-repo split without ever
moving raw data.

## Scope guard (NFR-Q5)
Touch only `scripts/export_public.py`, `scripts/check_no_secrets.sh`, logging in
`scripts/lib/ulog.py`, and the `chatgpt-extract-catalog` integration points. Do
**not** change extraction semantics (Phase 2) or the benchmark metric (Phase 1).

## Actions and success conditions (priority order)

1. **Redaction becomes an active transform (NFR-P2).**
   - Replace detect-only `review_*` with a transform that substitutes
     `‹email›`/`‹path›`/`‹phone›`/`‹token›` placeholders inside `sanitize_item` /
     `sanitize_document`, in addition to the existing provenance stripping.
   - *Success:* `gpt publish` on a fixture containing PII writes a `published/`
     whose content has the PII replaced (not merely a failed commit).

2. **Broaden the patterns (NFR-P2).**
   - Extend beyond email + macOS `/Users/...` to **names, phone numbers, API
     keys/tokens, and Linux/WSL home paths** (`/home/<user>`,
     `/mnt/c/Users/<user>`).
   - *Success:* pattern tests cover each category with positive + negative cases;
     the `alice` fixtures still pass as the only allowed user-path strings.

3. **Publish-boundary tests (NFR-P1).**
   - Feed known-PII fixtures end-to-end through publish and assert the output is
     clean; assert the whole tree + git history stay clean.
   - *Success:* a single `pytest` target fails if any real email/home-path/key/
     conversation-id could reach `published/` or git.

4. **No PII in logs (NFR-P4).**
   - Ensure `ulog`/trace never emits transcript text or paths under `$DATA_ROOT`.
   - *Success:* a log-scrubbing test asserts traces contain only labels/counts.

5. **Observability integration (PLANNED-WORKS Phase 3, NFR-Q4).**
   - Wire the `chatgpt-extract-catalog` run registry + `RUN_SUMMARY` so `gpt info`
     and `skills/catalog-query` can surface cross-run stats, keeping the
     read-only split (tool writes runs; catalog summarizes). Record a
     `VENDORED_FROM` upstream-commit marker on the vendored libs (sets up Phase 4
     pinning).
   - *Success:* `gpt info` reflects run-catalog state; vendored libs carry a
     recorded upstream commit; raw data still lives only in `$DATA_ROOT`.

## Acceptance criteria
The publish path actively scrubs broadened PII (NFR-P2); publish-boundary tests
fail on any leak (NFR-P1); logs are PII-free (NFR-P4); cross-run observability is
available without duplicating data; `pytest -q` is green (NFR-Q1).

## Out of scope
Benchmark metric (Phase 1); content-type coverage (Phase 2); CLI grammar/polish
(Phase 4).
