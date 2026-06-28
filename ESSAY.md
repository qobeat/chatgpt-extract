## Metadata

| Attribute | Value |
|---|---|
| DOCUMENT_TYPE | normative |
| DOCUMENT_STATUS | draft |
| UPDATED_AT | 2026-06-28 |
| DOCUMENT_ROLE | model_document |
| GOVERNANCE_AREA | project_essay |
| CONSUMERS | owner; planner; worker; evaluator |
| WHEN_TO_USE | Read before forming or changing the Goal, Objectives, Deliveries, or evaluation of chatgpt-extract. |
| HOW_TO_USE | Treat as the durable statement of what this Project is and how its success is judged. Do not override it with a single benchmark run or a model-bank note. |
| DOCUMENT_CONTENT | The thesis, Goal/Objective framing, and the depth-vs-correctness lesson that defines the evaluation instrument. |
| AUTHORITY_REF | project-geometry.json |

# chatgpt-extract — using your own AI history as a grounded decision instrument

## Purpose

`chatgpt-extract` turns a personal ChatGPT export into two things at once: a
private, queryable catalog of everything you have built with an AI, and a
**benchmark workload made of that same real work**. Its reason to exist is a
decision a solo founder actually faces — *is this $1,400 GPU worth keeping, and
should this work run local or in the cloud?* — answered not by synthetic
benchmarks but by how providers perform on the tasks you really do.

## Thesis

A model-selection or hardware decision is only as trustworthy as the measurement
behind it. The project's defining lesson is that **depth is not correctness**. An
early version's quality column rewarded richly-filled records and quietly scored
failures as zero; under it, small models looked like giant-killers. Once
correctness was adjudicated against a reference, the illusion collapsed — a model
can emit clean, fully-populated JSON with the wrong archetype (one local model:
85% fill, 16% correct). The instrument's job is to keep reliability, depth, and
correctness as **separate axes**, exclude failures from depth, gate
non-compensable faults, and measure cost and energy for real — so the verdict is
defensible and reproducible, not a story told by one conflated number.

## Goal and Objectives

**Goal:** make grounded build-vs-buy and model-selection decisions for a home lab,
using real ChatGPT history as both knowledge base and benchmark workload.

- **OBJ-CATALOG (Forming):** losslessly extract and classify the export into a
  private, queryable ADOS catalog.
- **OBJ-BENCH (Speeding):** evaluate providers on that real workload with
  reliability, depth-on-success, correctness, schema-validity, latency, energy,
  and cost reported separately.
- **OBJ-DECISION (Governance):** convert the benchmark into an explicit,
  reproducible keep-vs-return / local-vs-cloud / which-model verdict with the
  economics.

## Evaluation stance

Success is defined by the Project Geometry (`project-geometry.json`), not by prose
here: each material Delivery has Project Coordinates with explicit `measures`,
`does_not_measure`, 0–100 anchors, and gates. The RTX 3090 question is simply the
first decision the instrument answers; the same machinery generalizes to the next
card or model. A favorable one-off run never establishes a durable verdict — a
claim of `100` is scoped to a named sweep, window, and Geometry version.

## Blue-ocean note

The defensible niche is not "another LLM benchmark." It is a **personal,
privacy-respecting decision instrument**: your own corpus as the test set, run
locally, with a governance layer (ADOS Geometry) that makes the measurement itself
auditable. That combination — real personal workload + offline-by-default + a
checked separation of quality axes — is what general benchmarks cannot offer.
