# PLAN — Phase 2: Catalog completeness & fidelity

**Read first (only these):** `PLANNED-WORKS.md` (Phase 2), `REQUIREMENTS.md`
(FR-C1..C5, NFR-R1, NFR-Q4), `skills/chatgpt-export-triage/SKILL.md`,
`skills/project-reconstruction/SKILL.md`, `skills/catalog-query/SKILL.md`,
`README.md` (How it works, Objective O1).

## GOAL of this phase
Make the catalog losslessly represent what is actually in the export, so the
benchmark workload (Phase 1) and any query (`skills/catalog-query`) are operating
on complete data.

## Scope guard (NFR-Q5)
Touch only `scripts/lib/chatgpt_parse.py`, `scripts/extract_cards.py`, the card
schema, and their tests. Do **not** change the benchmark metric or providers.

## Actions and success conditions (priority order)

1. **Capture the dropped content-types (FR-C2).**
   - Extend `message_text()` to handle `tether_quote`,
     `tether_browsing_display`, `execution_output`, and o1/o3 `reasoning` parts as
     labelled blocks; unknown shapes still degrade to `[tag]` (never crash).
   - *Success:* a coverage test enumerates every known `content_type` and asserts
     non-empty, labelled output for each; an export containing browsing/tool turns
     yields transcripts that include them.

2. **Capture per-message provenance (FR-C3, NFR-Q4).**
   - Record `message.metadata.model_slug` onto the card (which model wrote each
     turn) and `metadata.attachments` (filenames/types).
   - *Success:* cards expose `model_slug` votes and an `attachments` list; a test
     with a fixture attachment asserts it is not dropped.

3. **Prove no silent loss (FR-C5, FR-C1).**
   - Add a round-trip/coverage test: every message node in a fixture export maps
     to either captured content or an explicit `[tag]`, with a count assertion so
     a future parser change that drops content fails CI.
   - *Success:* the coverage test passes and would fail if a `content_type` were
     silently skipped.

4. **Confirm incremental + bounded behavior still holds (FR-C4, NFR-R1).**
   - Re-running on a newer export updates only changed chats (newer `update_time`
     wins); memory stays bounded on a multi-GB fixture.
   - *Success:* existing incremental/streaming tests remain green after the
     widened parser.

## Acceptance criteria
Extraction captures the previously-dropped content-types with an auditable
coverage test (FR-C2); `model_slug` and attachments are on the card (FR-C3); a
round-trip test proves no silent loss (FR-C5); streaming/incremental guarantees
hold (FR-C1/C4/NFR-R1); `pytest -q` is green (NFR-Q1).

## Out of scope
Benchmark metric (Phase 1); redaction hardening (Phase 3); CLI polish (Phase 4).
