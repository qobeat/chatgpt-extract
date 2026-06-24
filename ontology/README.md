# Ontology — ADOS Reference Model Bank

This folder is the project's **Reference Model Bank** (`ADOS-EVAL-REFERENCE-MODEL-BANK`):
a versioned, controlled set of reusable models used to classify every extracted item.
It is grounded in the ADOS Evaluation Glossary
(`ados-rag/ADOS-EVALUATION-GLOSSARY.md`).

## Files

- **`archetypes.json`** — controlled **Archetype** set (`ADOS-EVAL-ARCHETYPE`).
  Answers *"what reusable KIND of thing is being delivered?"* Each record has an
  `id`, `label`, ADOS `concept_ref`, `when_to_use`, deterministic `signals`, and a
  per-archetype **`field_contract`** (the archetype-conditioned keys the summarizer
  must fill).
- **`domains.json`** — controlled **Domain / Subdomain** set
  (`ADOS-EVAL-DOMAIN`, `ADOS-EVAL-DOMAIN-PAIR`). Answers *"what body of knowledge
  governs correctness and evidence?"*

## How every item is classified

Each extracted item carries (mirroring `ADOS-EVAL-PROJECT` / `ADOS-EVAL-INTENT`):

- **Primary Archetype [1]** (`ADOS-EVAL-PRIMARY-ARCHETYPE`) + Secondary Archetypes [0..n].
- **Primary Domain/Subdomain Pair [1]** (`ADOS-EVAL-PRIMARY-DOMAIN-PAIR`) + Secondary Pairs [0..n].

A durable, multi-Pass item is a **Project** (`ADOS-EVAL-PROJECT`); a single-Pass
interaction maps to one **Intent** (`ADOS-EVAL-INTENT`), which the glossary says
"is assigned exactly one Archetype and one Domain/Subdomain Pair." We capture this
with the `is_durable_project` flag.

## Drift guards (must change observable behavior)

These are enforced in the classifier prompt and reviewed in evaluation:

1. **Archetype ≠ Domain ≠ file extension ≠ tool stack** (`ADOS-EVAL-ARCHETYPE`).
   Incidental code in a chat does not make the item `software_app`; ask what is
   *delivered*.
2. **Primary Archetype is not the most visible file** (`ADOS-EVAL-PRIMARY-ARCHETYPE`).
3. **Primary Domain is not "software engineering" just because software implements
   the product** (`ADOS-EVAL-PRIMARY-DOMAIN-PAIR`). The canonical example: an SAT
   practice app is Primary Domain `education/sat_preparation`, Primary Archetype
   `software_app`, with `software_engineering` and `ai_ml/llm_tutoring` only Secondary.
4. **Materiality test for any Domain/Subdomain** (`ADOS-EVAL-DOMAIN`): if changing
   the label changes no correctness, evidence, risk, vocabulary, or reference class,
   it is not material — drop it.
5. **Secondary classifications must earn their place** through distinct material
   contribution (`ADOS-EVAL-SECONDARY-ARCHETYPE`, `ADOS-EVAL-SECONDARY-DOMAIN-PAIR`),
   not decoration.

## Versioning

Both files carry `version` + `updated_at`. Treat them as governed records: extend
deliberately (seed new archetypes/domains from labeled real clusters), bump the
version, and keep `concept_ref`s pointing at the owning glossary terms.
