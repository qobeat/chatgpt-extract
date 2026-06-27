# Redesign proposal — measurable GOAL, IQ questions, and a faceted classification

> Status: **draft for review** (2026-06-26). Covers (2) GOAL/OBJECTIVES rewrite,
> (3) numeric decision questions, (4) classification redesign for both real-life
> catalog use and in-depth model-IQ measurement, and (5) the alignment contract the
> `models_json_redesign` plan must satisfy. Changing the GOAL/OBJECTIVES is a
> governed action (NFR-Q5) — this file is the explicit decision record; merge into
> `README.md` + `PLANNED-WORKS.md` once approved.

---

## 2. Revised GOAL and OBJECTIVES (keeps the ideas, made measurable)

**GOAL.** Decide, with reproducible evidence, whether a solo AI-founder should
**keep a purchased RTX 3090 (24 GB, ~$1,400, still returnable)** for local LLM
inference — by benchmarking local Ollama models against flagship, plan-covered
cloud models on the founder's *own* real ChatGPT history, which serves at once as
(a) a private, queryable knowledge **catalog** and (b) the benchmark **workload**.
"Better" is decided on **separated, measured axes — reliability, depth, correctness
("IQ"), speed, energy, and privacy — that are never blended**, where a model's
**IQ = its difficulty-weighted correctness** at classifying chats and answering
them, scored against an **etalon** (the consensus of strong reference models, or
the single strongest reference model where consensus is unavailable).

The GPU question is the *first* decision the instrument settles; the harness
generalises to the next hardware/model choice.

**OBJECTIVES (each SMART — specific, measured, verifiable):**

| # | Pillar | Objective (measurable) | Done when |
|---|---|---|---|
| **O1** | **Catalog** | Losslessly extract + classify 100% of items from each export into the faceted ADOS schema, with **zero silent content-type drops** and deterministic facts copied verbatim. | coverage report shows every `content_type` handled/flagged; schema round-trip passes; provenance auditable (FR-C1..C5). |
| **O2** | **Benchmark** | Run every model on the **same** bundles and report **6 separated axes** (completion, depth-on-success, IQ/accuracy, schema-valid, s/item & Wh/item) with no blended rank key. | `gpt metrics` emits all axes as distinct columns; runs isolated per `--run-label` (FR-B1..B6). |
| **O3** | **IQ / correctness** *(was implicit; now explicit)* | Score each model's **difficulty-weighted accuracy vs the etalon**, decomposed by cognitive skill and difficulty tier, on items that have a **reliable** ground truth (inter-judge agreement above threshold). | accuracy reported per skill×difficulty; etalon agreement (κ) reported; unreliable cells excluded (FR-B3 + new facets). |
| **O4** | **Decision** | Convert the axes into an explicit keep-vs-return / local-vs-cloud / which-model verdict with the economics (capex vs $0-marginal plan and vs paid API break-even). | `AI_MODEL_TESTS.md` verdict regenerable from `$DATA_ROOT` by documented read-only commands; conditions stated numerically (FR-D1/D2). |

**Non-goals (unchanged):** not a database, not a hosted service, not a synthetic
benchmark, no raw personal data in git.

---

## 3. The decision questions — every answer is a number

The test is "objective" only if it ends in numbers that force a verdict. These are
the questions the run must answer; each cell in the result table is one answer.
(Q-IDs are stable and referenced by the metrics code and `AI_MODEL_TESTS.md`.)

**Reliability & output**
- **Q1 — Completion.** For each model, `LLM_OK / N`? *(%)*
- **Q2 — Depth-on-success.** Mean schema-fill over completed items? *(%)*
- **Q3 — Schema-valid JSON.** Clean-JSON rate? *(%)*

**IQ / correctness (the new core)**
- **Q4 — Overall IQ.** Difficulty-weighted accuracy vs etalon over reliably-keyed
  items? *(0–100)*
- **Q5 — Local-vs-cloud IQ gap.** `best_cloud_IQ − best_local_IQ`? *(percentage points)*
- **Q6 — IQ by difficulty.** Accuracy at each tier T1–T4 — where does local fall
  off? *(% per tier)*
- **Q7 — IQ by cognitive skill.** Accuracy per skill (retrieve / explain /
  extract / classify / reason / generate / plan / advise)? *(% per skill)*
- **Q8 — Etalon reliability.** Inter-judge agreement of the consensus key? *(Fleiss'/Cohen's κ, 0–1)*
- **Q9 — Stability.** Across 3 repeats, per-model accuracy spread? *(± pp)* — so a
  2–3 pt gap can be called noise or signal.

**Speed, energy, fit**
- **Q10 — Speed.** Warm s/item and generation tok/s per model? *(s, tok/s)*
- **Q11 — Energy.** Measured Wh/item and $/1,000 items at $0.20/kWh? *($, Wh)*
- **Q12 — VRAM fit.** Largest model that fits at 16k ctx, and headroom on 24 GB? *(GB)*

**Economics & privacy (drive the keep/return call)**
- **Q13 — Break-even volume.** Items at which the $1,400 capex is repaid vs the
  cheapest *paid* cloud alternative (vs the $0 plan it is never repaid — state
  that explicitly)? *(items, or ∞)*
- **Q14 — Privacy cost.** Accuracy/depth delta when the cloud pre-send scrubber
  (`--scrub-cloud`, NFR-P3) is on vs off? *(pp)*

**Verdict rule (numeric, not vibe):** *Return the card unless at least one holds —*
(a) privacy is mandatory **and** Q14 shows cloud redaction costs ≥ X pp accuracy;
(b) sustained volume ≥ Q13 break-even against the relevant paid tier;
(c) the best local IQ (Q4) is within Y pp of best cloud **and** Q11 energy and
Q10 speed are acceptable; (d) the GPU is already amortised by other work. Set
X and Y before the run so the conclusion is pre-committed.

---

## 4. Classification redesign — faceted, for *both* catalog use and IQ

### 4.1 The core problem with today's scheme

The catalog uses **one** classification — `(Primary Archetype, Primary
Domain/Subdomain)` — and the benchmark reuses *that same pair* as its correctness
signal (`accuracy = pair matches codex`). One label is being asked to do two
unrelated jobs:

1. **Real-life cataloguing** — "what did I build, in what area?" (browse, search, recall).
2. **Model-IQ measurement** — "how hard was this task, what cognitive skill did it
   test, is there even a checkable answer, and did the model get it right?"

A `(archetype, domain)` exact-match is a *coarse, single, binary* correctness
signal. It cannot tell you **where** a model is weak (skill? difficulty?), it
scores items that have **no objective answer** (creative work) the same as ones
that do, and it inherits the "codex is the key, not ground truth" problem. The
redesign **keeps the two existing facets** and adds **orthogonal eval facets**, so
the catalog gets richer and the IQ metric becomes decomposable and defensible.

### 4.2 Faceted taxonomy (orthogonal, not a deeper tree)

Each item carries independent facets. **Catalog facets** answer "what is it";
**eval facets** answer "what does it test."

| Facet | Purpose | Values | New? |
|---|---|---|---|
| **A. Archetype** — what is delivered | catalog | the 13 current archetypes (refined, §4.6) | keep |
| **B. Domain/Subdomain** — what knowledge governs correctness | catalog + eval | the 14 current domains | keep |
| **C. Cognitive type** — what mental operation is demanded | **eval (core)** | retrieve · explain · extract_transform · classify_judge · reason_analyze · generate_create · plan_strategize · converse_advise | **new** |
| **D. Difficulty tier** — how hard | **eval (core)** | T1 trivial · T2 moderate · T3 hard · T4 expert | **new** |
| **E. Verifiability class** — can it even be scored objectively | **eval (core)** | objective · rubric · subjective | **new** |
| **F. Durability** — Project vs single Intent | catalog | `is_durable_project` (kept) | keep |
| **G. Modality** — in/out medium | catalog | text · code · image · data · mixed | new, mostly derivable |

Why orthogonal facets beat a deeper archetype tree: a single chat can be an
`automation_script` (A) in `information_security` (B) that demands
`reason_analyze` (C) at `T3` (D) with an `objective` answer (E). Collapsing those
into one label loses exactly the structure the IQ metric needs.

### 4.3 Facet C — cognitive type (the IQ backbone)

Task-oriented (not Bloom verbatim), 8 mutually-distinguishable operations:

| id | tests | typical etalon |
|---|---|---|
| `retrieve` | factual recall / lookup | objective |
| `explain` | conceptual clarity | rubric |
| `extract_transform` | pulling structure from unstructured input | objective |
| `classify_judge` | categorisation / evaluation (the meta-skill the benchmark itself uses) | objective/rubric |
| `reason_analyze` | multi-step reasoning, math, debugging, causal analysis | objective |
| `generate_create` | open-ended creation (writing, code, media, naming) | subjective/rubric |
| `plan_strategize` | producing a goal-directed sequence | rubric |
| `converse_advise` | interactive diagnosis / advice | rubric |

This is what turns "16% accuracy" into "fails `reason_analyze` at T3 but fine on
`extract_transform` at T1" — actionable, and the answer to **Q7**.

### 4.4 Facet D — difficulty tier (anchored, not vibes)

Score each item 1–4 on four 0–3 sub-axes, sum → tier; the rubric is published so
two annotators (or models) agree:

- **Steps** — reasoning hops to a correct answer (0: one; 3: many interdependent).
- **Specialisation** — depth of domain expertise required (0: general; 3: expert).
- **Ambiguity** — how under-specified the task is (0: closed; 3: open).
- **Context load** — how much of the bundle must be integrated (0: local; 3: whole).

T1 = sum 0–2, T2 = 3–5, T3 = 6–8, T4 = 9–12. Enables **difficulty-weighted IQ**
(tier weight = 1/2/3/4) and **stratified sampling** so the gold set isn't all easy
items. Answers **Q6**.

### 4.5 Facet E — verifiability class (protects the metric)

Not everything has a right answer. Tag each item:

- **objective** — one checkable answer (math, extraction, a fact). Etalon is
  deterministic or high-agreement consensus. *Counts fully toward IQ.*
- **rubric** — gradeable against explicit criteria (classification, summary
  fidelity, plan quality). Etalon = rubric-scored consensus. *Counts, weighted by κ.*
- **subjective** — taste/style (creative writing, branding). No defensible single
  key. *Reported as a preference rate, **excluded from the IQ/accuracy number.***

This is the single most important addition: it stops the benchmark from pretending
a creative-writing chat has a "correct" archetype the way an extraction task does,
and it makes **Q8** (etalon reliability) meaningful per class.

### 4.6 Etalon protocol — the "IQ key", three tiers of evidence

Formalises the goal's "consensus answer **or** strongest model":

1. **Tier-0 gold (anchor).** A human-adjudicated **stratified** sample (≥30 items,
   spread across D×C×E) labelled by hand. The ground truth the others are checked
   against. Addresses the standing "codex is not ground truth" open question.
2. **Tier-1 consensus.** For `objective`/`rubric` items, etalon = the
   **majority/consensus of K strong reference models** (e.g. codex, composer-2.5,
   claude, + one paid frontier). Compute **inter-judge agreement (Fleiss' κ)** and
   **only trust cells with κ ≥ 0.6**; low-κ cells fall back to Tier-0 or are flagged.
3. **Tier-2 single-key.** Where no consensus exists, use the single strongest model
   as a provisional key, **explicitly flagged as weaker evidence**.

Report the etalon's own reliability (Q8) next to model scores — a model can't be
meaningfully "62% accurate" against a key whose judges only agree 55% of the time.

### 4.7 IQ scoring — still separated, never blended

Per model, reported as **distinct** columns + a `skill × difficulty` heatmap:

- `completion%` (reliability) — unchanged.
- `depth%` (fill) — unchanged, still "did it populate the schema," not correctness.
- **`IQ`** = Σ(tier_weight × correct) / Σ(tier_weight) over `objective`+`rubric`
  items in reliable (high-κ) cells — difficulty-weighted accuracy.
- **per-skill accuracy vector** (the radar) and **per-tier accuracy** — Q6/Q7.
- `pref%` for `subjective` items — reported apart, **not** folded into IQ.
- `±` spread from 3 repeats (Q9).

Consistent with the project's existing discipline (AI_MODEL_TESTS §3.5): reliability,
depth, and correctness stay in separate columns; this just makes correctness
**multi-dimensional and reliability-gated** instead of a single binary match.

### 4.8 Implementation impact (do it properly, not minimally)

- **Schema** (`schema/extracted_item_schema.json` + public): add `cognitive_type`,
  `difficulty_tier` (+ the four sub-scores), `verifiability_class`, `modality`.
  Bump `ontology_version` → **2.0.0**; carry it into every output (NFR-Q3) with a
  `port_legacy.py` migration for existing runs.
- **Ontology**: add `ontology/cognitive_types.json`, `ontology/difficulty.json`,
  `ontology/verifiability.json` (each a governed Reference Model Bank record with
  `concept_ref`, `when_to_use`, signals, version).
- **Classifier** (`classify.py`): emit deterministic *priors* for C/D/E from signals
  (e.g. presence of math → `reason_analyze`; whole-bundle integration → high context
  load); LLM confirms/overrides under drift guards, as today.
- **Metrics** (`metrics.py`): `gpt metrics quality` gains `--by-skill`,
  `--by-difficulty`, difficulty-weighted `IQ`, the κ report, and excludes
  `subjective` from accuracy.
- **New commands**: `gpt goldset` (build/adjudicate the stratified Tier-0 set),
  `gpt etalon` (compute Tier-1 consensus + κ).
- **Drift guards (added)**: difficulty is not length; cognitive type is not
  archetype; `objective` requires a genuinely checkable answer or it is `rubric`.
- **Tests**: fixtures asserting facet round-trip, difficulty rubric arithmetic,
  κ computation, and that `subjective` items never enter the IQ number.

### 4.9 What real-life use gains

Beyond IQ, the new facets make the catalog far more useful to browse: "show my
**T3+ reasoning** projects in `information_security`", "everything `generate_create`
I did in `arts_creative`", "all `objective` `extract_transform` tasks" — queries
the flat `(archetype, domain)` pair cannot express today.

---

## 5. Alignment contract for the `models_json_redesign` plan (parts 1 & 5)

> I could not read `~/.cursor/plans/models_json_redesign_14ead9a9.plan.md` (outside
> the mounted folder; workspace mount erroring). Below is the **checklist the plan
> must satisfy** to be aligned with the revised goal — apply it once the file is
> readable (copy it into the repo or paste it). I will give a line-by-line review then.

The plan **must**:

1. **Serve the 6 separated axes (O2) — never a blended rank.** If it adds a single
   "score" to `models.json`, that violates AI_MODEL_TESTS §3.5 / FR-B2. Notes must
   carry completion · depth · json · **IQ** · s/item · Wh/item as distinct fields.
2. **Make notes data-derived (FR-D2).** Every per-model verdict regenerated by
   `gen_model_notes.py` from a defined sweep + reference; never hand-edited (we just
   saw a hand-added suffix get correctly stripped).
3. **Carry the new IQ signal.** Once §4 lands, the note's `acc%` becomes the
   difficulty-weighted, reliability-gated IQ; the metadata block must record the
   etalon reference and κ threshold used.
4. **Keep the model bank's job narrow.** `models.json` maps *name → provider →
   options + verdict note*. It is **not** the place for the gold set, the ontology,
   or per-item results — those live in `$DATA_ROOT`/ontology. Guard against the
   redesign over-loading it.
5. **Preserve provider/auth and cost semantics** (plan vs api vs local; subscription
   "covered by plan" vs token-billed) and the `skip`/`num_ctx` fields.
6. **Not touch GOAL/OBJECTIVES** except via this decision record (NFR-Q5).
7. **Map each change to an FR-/NFR- ID** and state a verification, per
   `REQUIREMENTS.md` conventions.

If the plan is mostly cosmetic (field renames, ordering), it is low-risk but should
still be checked against items 1–4. If it introduces a scoring/aggregation field,
that is the highest-risk part and item 1 governs it.
