# PLANNED-WORKS — chatgpt-extract roadmap

> **Note (ADOS 0.8.20):** this file is now an **informal planning note**, not a
> governed lifecycle surface. ADOS renamed `PLANNED-WORKS.md` → `TODO.md` and
> forbids `PLANNED-WORKS.md` in a strict package, so the governed roadmap lives
> in [`TODO.md`](TODO.md) and success is defined by
> [`geometry/project-geometry.json`](geometry/project-geometry.json). Keep this
> file only for background/rationale; make roadmap changes in `TODO.md`.

High-level roadmap for evolving `chatgpt-extract` into a best-in-class,
lightweight, command-line-only personal toolkit for WSL. This document is
**stable**: the phase plans in `plans/PLAN_PHASE1..4.md` implement it and must not
change the GOAL or OBJECTIVES without an explicit request.

The GOAL and the three OBJECTIVES are defined in `README.md` and are repeated here
only by reference: **O1 Catalog**, **O2 Benchmark**, **O3 Decision**.

---

## Repository topology (decision)

**Keep the two repositories you already have. Do not add a third.**

| Repo | Role | Visibility | Owns |
|---|---|---|---|
| `chatgpt-extract` | The **tool** | public | extract / cluster / classify / summarize, the `gpt` CLI, ontology + schema, the benchmark harness, sanitized `published/` |
| `chatgpt-extract-catalog` | **Observability** | private | reads runs the tool wrote; writes catalogs, run summaries, cross-run stats; keeps the fuller *unsanitized* catalog |

**Why this axis and not "export vs logic":** the only durable reason to separate
two repos here is the **PII / visibility boundary**. The tool can be public
because it commits only sanitized output; the observability repo must be private
because it deliberately retains chat-derived titles, `source_conversation_ids`,
and LLM-written summaries. Splitting instead on "data export vs processing logic"
would cut a tightly-coupled pipeline (extract → cluster → bundle → summarize) in
half and force a fragile internal API for no benefit.

**Two refinements (carried into the phases):**
1. The catalog repo **vendors copies** of `paths.py`, `ulog.py`, `run_log.py`.
   Record the upstream commit each copy came from (a `VENDORED_FROM` line) so the
   two repos cannot silently drift. *(Phase 4.)*
2. **Raw chat data lives in neither repo** — it stays in `$DATA_ROOT`, already
   gitignored. No phase changes this.

---

## Roadmap at a glance

| Phase | Theme | Primary objective | Why this order |
|---|---|---|---|
| **1** | Benchmark validity → settle the GPU question | O2, O3 (+ NFR-P3) | The keep-vs-return verdict rests on a metric that conflates depth + reliability and omits correctness. Highest value, time-sensitive (the card is still returnable). The cloud pre-send scrubber lands here, **before** any cloud re-run, so re-benchmarking does not re-leak. |
| **2** | Catalog completeness & fidelity | O1 | "All data extracted" is not yet true — browsing/tool/reasoning content-types, per-message `model_slug`, and attachments are dropped. The benchmark workload is only as representative as the catalog. |
| **3** | Publish / redaction hardening + observability | NFR-P, O1 | Today redaction is detect-only with narrow patterns. Make it an active transform; broaden patterns; wire the catalog repo's run-stats into the loop. |
| **4** | CLI / UX polish + packaging | cross-cutting | Make it best-in-class for daily WSL use: consistent verbs, fast feedback, `--json` everywhere, vendored-lib pinning, install ergonomics. |

Each phase is independently shippable and leaves the tool in a working state. A
phase's exit criteria are the acceptance checks in its `PLAN_PHASEX.md`, which map
to specific `FR-*` / `NFR-*` IDs in `REQUIREMENTS.md`.

---

## Phase 1 — Benchmark validity and the keep-vs-return re-decision

**Outcome:** a benchmark you can defend, and a final, evidence-grounded answer to
"is the RTX 3090 worth $1,400 for this workload?"

Covers `FR-B2` (report completion and depth-on-success as **separate columns**,
never one blended rank key), `FR-B3` (a **correctness** check adjudicated against a
reference — `codex` or a held answer key — not just depth), `FR-B4`
(**structured-output enforcement**: Ollama `format=json` / GBNF grammar +
retry-on-parse-failure, so failures stop injecting zeros), `FR-B6` (power/cost
model with measured watt-hours), and `NFR-P3` (the **cloud pre-send scrubber**,
gating any cloud re-run). Ends by re-running the suite and rewriting the
`AI_MODEL_TESTS.md` verdict from the corrected numbers.

---

## Phase 2 — Catalog completeness and fidelity

**Outcome:** the catalog losslessly represents what is actually in the export.

Covers `FR-C2` (capture the content-types currently dropped: `tether_quote`,
`tether_browsing_display`, `execution_output`, o1/o3 reasoning), `FR-C3`
(per-message `model_slug` and `metadata.attachments`), and `FR-C5`
(round-trip/coverage tests proving no silent loss). The deterministic-first,
LLM-last pipeline and the ADOS ontology/schema are unchanged in shape — this
widens what feeds them.

---

## Phase 3 — Publish / redaction hardening and observability

**Outcome:** the published surface is provably safe by construction, and runs are
observable across the two repos.

Covers `NFR-P2` (redaction becomes an active **transform**, not detect-only;
broaden beyond emails + paths to names, phones, tokens), `NFR-P1`
(publish-boundary tests that fail the commit on any leak), and the
`chatgpt-extract-catalog` integration (run registry + `RUN_SUMMARY` + cross-run
stats consumed by `gpt`). Reconciles the vendored-lib copies (sets up Phase 4's
pinning).

---

## Phase 4 — CLI / UX polish and packaging

**Outcome:** best-in-class lightweight CLI for daily WSL use.

Covers `FR-U1..U3` (consistent verb grammar, `--json` on every read command, fast
first-byte feedback and progress on long runs), the `catalog-query` ergonomics
(`gpt list/search/show/info`), `VENDORED_FROM` pinning for the catalog repo, and
install/setup ergonomics (`setup.sh`, `.env.example`, doctor command). No new data
semantics — this is the fit-and-finish pass.

---

## What is explicitly **out of scope** (non-goals, restated)

A hosted service or web UI; a database backend; a synthetic-benchmark suite;
storing raw personal data in any git repo; and any change to the GOAL or the three
OBJECTIVES. Raising any of these requires an explicit decision, not a phase.
