# chatgpt-extract ↔ ADOS vocabulary mapping

This project is an ADOS **Project** (it ships scripts, so it is not an ADOS
runtime *module* — modules forbid executable scripts). It is governed by ADOS
**Project Geometry** and the **Pillars**, and it reuses ADOS concepts/terms so the
code, schema, and docs share one controlled vocabulary.

## Concept reuse (from `ados-concepts`, 60 concept records)

| ADOS concept | chatgpt-extract usage |
|---|---|
| Project / Goal / Objective | the project's Goal + 3 Objectives; Objective roles use the ADOS **Forming / Speeding / Governance** triad already present in `schema/extracted_item_schema.json`. |
| Primary/Secondary Archetype | reused from `ontology/archetypes.json` (classification target). |
| Domain/Subdomain Pair | reused from `ontology/domains.json`. |
| Project Delivery (Boundary Ladder) | Catalog / Benchmark instrument / Decision verdict. |
| Project Coordinate + Measurement Contract | each benchmark axis (completion, depth-on-success, accuracy, schema-validity, speed, energy) with explicit measures / does_not_measure / anchors. |
| Guard vs scoring vs diagnostic coordinate; mandatory gate | schema-validity and coverage are **guards/gates**; energy is **diagnostic**. |
| Project State (append-only) | per-sweep observations against coordinates. |

## Pillar alignment (from `ados-pillars`, 17 active: PILLAR-01..14,17,18,20)

- **PILLAR-01 Project Determination:** the project keeps one durable identity
  (`project_slug` stable, not inferred from a filename).
- **PILLAR-02 / -03 (classification / Goal-Objectives):** archetype+domain pairs;
  one Goal, governed Objectives by role.
- **PILLAR-04 (material Deliveries):** the three Deliveries above.
- **PILLAR-17 (document metadata field contract):** the `ESSAY.md` metadata header
  follows this contract.
- **PILLAR-20 (version/identity provenance):** version appears only in authorized
  identity/release/provenance surfaces.

## Method reuse (from `ados-geometry`)

The benchmark *is* an application of `ADOS-PROJECT-GEOMETRY-METHOD.md`: Procedures
D (Deliveries), E–F (Coordinates + Measurement Contracts), G (anchors), H
(vectors), K (rubric), and the fail-closed rules. The
`statistical/adaptive observation contract` (method §10.4) is used for the
accuracy and verdict coordinates (named sweep, sample size, no durable claim from
one run).

## Lifecycle naming (from `ados-architecture` 0.8.20)

ADOS renamed `CHANGE-LOGS.md`→`CHANGELOG.md` and `PLANNED-WORKS.md`→`TODO.md`, and
**forbids `PLANNED-WORKS.md`** in a strict package. This project keeps
`CHANGELOG.md` + `TODO.md` as the governed lifecycle surfaces.
