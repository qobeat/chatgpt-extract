# ESSAY — Your own AI history as a grounded decision instrument

> **Format note.** The "ADOS essay standard" is your internal convention and was
> not in the materials provided, so this follows an inferred ADOS shape — thesis
> → context → argument → evidence → counter-argument → decision → so-what —
> consistent with the ADOS pipeline (idea → research → design/BRD → spec/SRS →
> implement → deploy) and your OSINT-grade evidence rule. Adjust the section
> order to your real standard if it differs.

---

## Thesis

A solo AI founder's scarcest input is not compute or capital — it is **grounded
judgement about where to spend them.** `chatgpt-extract` is best understood not
as an export parser but as a **decision instrument**: it converts the founder's
own accumulated ChatGPT work into two assets at once — a private, queryable
**catalog** of what they have built, and a **benchmark** whose test workload *is*
that real work. Because the benchmark runs on the founder's actual tasks rather
than synthetic prompts, the build-vs-buy and model-selection calls it produces
are grounded in reality, not in a leaderboard that may not resemble the job.

## Context — the solo founder's home lab

The setting is specific and it matters: one person, a Dell 5820 with 120 GB RAM
and a used RTX 3090, building AI startups on home hardware, hunting blue-ocean
niches. Every dollar of capital (a $1,400 GPU) and every dollar of marginal cost
(per-token API spend) competes directly with runway. The founder already pays for
Cursor and ChatGPT plans, so the true alternative to local inference is often not
"nothing" but "$0 marginal on a plan I already have." A decision instrument for
this person must therefore price **capital against an existing zero-marginal
option**, and must weigh **privacy** — because the raw material is the founder's
own thinking — as a first-class axis, not a footnote.

## Argument — why "your own history" is the right corpus

Three properties make the founder's ChatGPT export the ideal corpus for both
pillars. First, it is **representative by construction**: the tasks in it are the
tasks the founder will keep doing, so a model that does well on it will do well on
the work. Second, it is **already structured enough to be deterministic-first**:
project versions arrive as `slug-vX.Y.zip`, conversations form a DAG with a
canonical branch, and dates/files/ids are facts — so the heavy lifting can be done
with no LLM and no cost, leaving the model only the fuzzy prose. This
deterministic-first, LLM-last design is what makes the catalog **auditable**: the
facts are copied verbatim and merged over the model, so the model can never
silently rewrite history. Third, it is **private**, which forces the architecture
to put the privacy boundary in the right place — raw and complete locally,
redacted only at the publish edge.

## Evidence — and a caution about measuring the right thing

The instrument's first verdict is concrete: on this workload the free,
plan-covered cloud models finish every item at $0 marginal, every local model
fits on the 24 GB card, and the GPU's value reduces to *the ability to run
locally at all* — so the card is hard to justify on output alone, and is worth
keeping mainly for privacy, very high volume, or if it is already amortised.

But the evidence also teaches a lesson about **measurement discipline** that is
the intellectual core of this project. The first cut of the benchmark ranked
models by a single "quality" number — and that number made *larger* local models
look *worse*, with a 1.5-billion-parameter model beating a 35-billion one. Under
the OSINT-grade rule (split into atomic claims, primary sources first, separate
fact from inference), that result does not survive inspection. The number was the
mean of four **fill** axes — does each field have content, are there at least
three list items — and **none of them measured whether the content was right.**
Worse, failed items were scored as zero rather than excluded, so a model that
failed more often was penalised twice. Recomputing on successful items only
**inverts** the ordering: the large models move to the top. The honest conclusion
is not "big models win" — survivorship bias and a sample of ten forbid that — but
something more useful: **completion and depth-on-success are different things and
must never be blended, and the real weakness of large local models on this box is
reliability, which is largely a fixable harness problem** (enforce structured
output; retry on parse failure) rather than a deficit of intelligence.

## Counter-argument — "just use the cloud and skip all this"

The strongest objection is that a solo founder should not build a decision
instrument at all: use the free plan models, ship, move on. For pure throughput
on non-sensitive work, that objection is correct and the instrument agrees — it
recommends the cloud. But it ignores the two axes the cloud cannot serve: when
the corpus is the founder's own unfiled thinking, sending it to Cursor, OpenAI or
Anthropic is a **privacy cost the dollar table does not show**; and a leaderboard
trained on someone else's prompts cannot tell this founder which model is best on
*their* tasks. The instrument's value is precisely in the cases where the cloud's
"just ship" advice is incomplete — and in turning the GPU question from a vibe
into a reproducible verdict that the next hardware decision can reuse.

## Decision

Keep the RTX 3090 only if privacy/offline is non-negotiable, volume exceeds the
plan, or the card is already amortised; otherwise return it, because the
alternative is both higher-reliability and $0. Standardise on `composer-2.5-fast`
or `codex` for plan-covered quality, and `qwen3:8b` / `qwen2.5-coder:1.5b`
locally — but treat the *local quality ordering as provisional* until the metric
is corrected (separate completion from correctness) and structured output is
enforced. This is a decision with a built-in expiry: re-run it when the metric is
fixed, when a paid frontier model is in scope, or when the next GPU is on the
table.

## So what — the reusable pattern

The transferable idea, beyond this repo, is a discipline for solo AI builders:
**measure tools on your own work, separate the things you are tempted to blend,
and put the privacy boundary at the publish edge.** A blue-ocean niche hides in
that last clause — most benchmarking tooling assumes a team, a cloud, and a
synthetic corpus; almost none is built for one person deciding, on private data,
on home hardware, whether the next dollar buys a GPU or a token. That is the niche
this instrument occupies, and the reason it is worth more than the export parser
it appears to be.
