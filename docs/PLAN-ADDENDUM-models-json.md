# Addendum to the `models_json_redesign` plan — review, schemas, alignment

> Companion to `~/.cursor/plans/models_json_redesign_14ead9a9.plan.md` and to
> `docs/REDESIGN-PROPOSAL.md`. Adds: (1) a review of the plan, (5) its alignment
> with the revised GOAL, and the **JSON Schemas** (Draft 2020-12) for every data
> file the redesign touches — updated where a schema already existed, newly
> proposed where none did.

## 1. Review of the plan — verdict: **sound, approve with 3 additions**

The plan is well-targeted and *increases* alignment with the goal. Its core moves
are right:

- **Split machine-generated from hand-curated.** Moving the benchmark numbers out
  of `config/models.json` into `config/generated/model_benchmarks.json` is exactly
  the fix the fragile free-text `note` needed — we literally watched a hand-added
  note suffix get stripped by the regenerator last session. Machine-owned data in a
  machine-owned file. ✔ (directly serves FR-D2.)
- **Typed fields instead of a prose verdict.** `completion_pct`, `accuracy_pct`,
  `wh_per_item`, … as numbers, not a string to parse. ✔ (serves FR-B2/B3.)
- **Upsert, never delete; latest-snapshot.** Reasonable for a single-box bank. ✔
- **Structured `billing` object replacing `tier`+`free`.** Clearer and honest about
  subscription vs token vs local. ✔

**Strengths to keep:** the `provider:name` key, the generated-file marker, keeping
the file committed (offline resolve + reviewable verdicts), and preserving the
`gpt gen-model-notes` alias so docs/CI don't break.

### Three additions (the review's asks)

**A1 — Normalize plan prices; do not put `usd_per_month` on every model.**
The plan attaches `usd_per_month` to each subscription entry, but several models
share one plan (all Cursor models → Cursor Pro; codex → a ChatGPT plan). Duplicating
the price invites drift. Use a **plan registry** (`config/plans.json`, schema
provided) and have each model's `billing.plan_id` reference it. One price, one place,
dated and sourced.

**A2 — The monthly prices in the plan look wrong and are time-sensitive — verify
before hard-coding.** The plan lists *ChatGPT Pro $100/mo*, *Cursor Pro $60/mo*,
*Claude Pro $20/mo*. As of my knowledge these do not all match known tiers (ChatGPT
is typically Plus $20 / Pro $200 with no $100 tier; Cursor Pro has commonly been
$20/mo; Claude Pro $20/mo looks right). **I cannot confirm current prices** — they
change. The `plans.schema.json` therefore *requires* `verified_at` + `source_url`
per plan so each price is a checked, dated fact (matches the OSINT rule). Verify on
the official pricing pages before committing numbers.

**A3 — Leave room for the IQ redesign.** Once `docs/REDESIGN-PROPOSAL.md` §4 lands,
the headline correctness field is no longer a flat `accuracy_pct` but a
difficulty-weighted, reliability-gated **`iq`** plus `accuracy_by_skill` /
`accuracy_by_difficulty` / `pref_pct` / etalon `kappa`. `model_benchmarks.schema.json`
already includes these as optional fields so the generated file is forward-compatible
and you don't re-migrate later.

## 5. Alignment with the revised GOAL — **passes the §5 checklist**

Against the alignment contract in `docs/REDESIGN-PROPOSAL.md` §5:

| # | Requirement | Plan status |
|---|---|---|
| 1 | Serve the 6 separated axes; **never a blended rank** | ✔ typed fields, no single score. Schema forbids a blended key by construction. |
| 2 | Notes **data-derived** (FR-D2) | ✔ generator owns the file; hand-edits not the source of truth. |
| 3 | Carry the new **IQ** signal | ⚠ plan stores flat `accuracy_pct`; **A3** extends the schema to the IQ fields. |
| 4 | Keep the bank's job **narrow** | ✔ improved — split is exactly this. |
| 5 | Preserve provider/auth + cost semantics | ✔ via `billing` + `pricing.json`; **A1** normalizes plan prices. |
| 6 | Don't touch GOAL/OBJECTIVES except by decision record | ✔ unaffected; the README change is recorded here + in `REDESIGN-PROPOSAL.md`. |
| 7 | Map each change to an FR/NFR + verification | ⚠ partial — add the FR/NFR id + a one-line verify to each todo (see below). |

**Suggested per-todo verification (closes #7):** `schema-models` → validates against
`schema/models_bank.schema.json`; `gen-file` → validates against
`schema/model_benchmarks.schema.json`; `generator` → `test_gen_model_benchmarks.py`
asserts upsert-preserves-unseen / adds-new / idempotent `--check`; `bank` →
`format_bank()` renders billing groups from `plans.json`; `regen-verify` →
`pytest -q` green + a schema-validation step in CI.

## JSON Schemas — does the data format agree with "JSON as interim contract"?

**Yes — with one clarification.** Using **JSON Schema (Draft 2020-12) as the
canonical contract** for every structured data file is the right call and is
industry-standard, *even when the delivered/serialized form is not JSON*. The
schema is the **interface definition**; the storage/wire format can differ:

- A schema can describe **one record**, while the file stores many as **JSONL**
  (e.g. `store/cards.jsonl`) or even **CSV/Parquet** for bulk/tabular data — each
  row still validates against the record schema.
- The human-facing **output** (the `AI_MODEL_TESTS.md` tables, `gpt arena`) is
  rendered *from* schema-valid data; it is a view, not the contract.

Caveat: JSON Schema validates **shape, types, enums, ranges** — not cross-field
semantics (e.g. "`completed` ≤ `n_items`", "`score` equals the sum of the four
sub-axes"). Those stay as unit-test invariants / a `--check` step. So: JSON Schema
for the contract; targeted validators for the arithmetic. That is the standard split.

Standards applied in the schemas: Draft 2020-12 (`$schema`/`$id`/`$defs`/`$ref`),
`snake_case` keys (matching the repo), `additionalProperties:false` on closed
objects, ISO-8601 `format: date`/`date-time`, ISO-4217 currency, units in field
names (`usd_per_1m_input`, `wh_per_item`, `*_pct` constrained 0–100), conditional
requireds via `if/then/allOf`, and foreign keys by `pattern`ed id tokens.

## Schema catalog — what validates what

| Data file | Schema | Status |
|---|---|---|
| `schema/extracted_item_schema.json` (the catalog records) | itself | **updated** — added eval facets `cognitive_type`, `difficulty{}`, `verifiability_class`, `modality` (Draft-07 retained; 2020-12 upgrade recommended). |
| `config/models.json` (redesigned, hand-curated) | `schema/models_bank.schema.json` | **new** — `billing` object, `plan_id` FK, conditional requireds, no benchmark fields. |
| `config/plans.json` (normalized plan registry) | `schema/plans.schema.json` | **new** — addition A1; dated, sourced prices. |
| `config/generated/model_benchmarks.json` (generated) | `schema/model_benchmarks.schema.json` | **new** — typed axes kept separate; optional IQ/etalon fields (A3). |
| `config/pricing.json` (token rates) | `schema/pricing.schema.json` | **new** — formalizes the existing file, non-breaking. |
| `ontology/archetypes.json`, `domains.json`, + new `cognitive_types.json` / `difficulty.json` / `verifiability.json` | `schema/ontology_banks.schema.json` | **new** — one envelope, per-record `$defs`. |

### Still undefined (proposed as follow-up, not yet written)
`store/index.json`, `store/cards.jsonl`, `store/clusters.json`, `bundles/INDEX.json`,
and `summarize_trace.jsonl` / `power_trace.jsonl` have no schema. Recommend defining
record schemas for these in a later pass (Phase 2/4) so the whole pipeline is
contract-checked end-to-end; they are out of scope for the models-json redesign.

## Apply order
1. Land `config/plans.json` + `models.json` (validate against their schemas).
2. Rename generator → `gen_model_benchmarks.py`; emit `config/generated/model_benchmarks.json` (validate).
3. `models_bank.py` merges generated + plans at load; render billing groups.
4. Add a CI step: validate each data file against its schema + run `pytest -q`.
5. When §4 IQ lands: extend the generator to fill `iq`/`accuracy_by_*`/`kappa` (already in the schema).
