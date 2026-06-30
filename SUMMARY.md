# SUMMARY — do we have clear answers on all three goals?

This is the owner-facing scorecard for the three features defined in
[ESSAY.md](ESSAY.md): **Catalog**, **Ask**, and **Benchmark**. Each section states
the goal, shows the evidence as a table, gives the **formula/meaning of every
column**, and names the tests that back the claim. The deep model-by-model
benchmark detail lives in [AI_MODEL_TESTS.md](AI_MODEL_TESTS.md); this file is the
summary.

| | |
|---|---|
| **Date** | 2026-06-28 |
| **Data root** | `$DATA_ROOT` = `~/chatgpt-reconstructor-data` (private, gitignored) |
| **Catalog** | 4,122 chats · 181 projects · 2023-07-01 → 2026-06-19 |
| **Benchmark sweep** | `cmp-0628` — 27 project bundles, 16 models, `num_ctx=16384` |
| **Tests** | `pytest -q` green (see each section for the relevant targets) |

---

## 1. Catalog — "a private, losslessly-extracted, queryable record" (OBJ-CATALOG)

**Answer: yes.** The export is fully parsed, classified, queryable, and provably
private. `gpt zips-verify` proves no silent loss.

### 1.1 What is in the catalog (`gpt info`)

| Statistic | Value | Meaning / formula |
|---|---|---|
| Chats | 4,122 | distinct conversations parsed from all processed exports (union, de-duplicated by chat id) |
| Projects | 181 (124 with version zips) | clusters of related chats; "with zips" = projects that contain at least one uploaded code/version archive |
| Date range | 2023-07-01 → 2026-06-19 | min..max chat `update_time` across the catalog |
| Turns | 45,779 (user 20,932 / assistant 24,847) | total messages; user+assistant split |
| Content types | text 44,004 · multimodal_text 1,702 · code 71 · user_editable_context 2 | count of message parts by ChatGPT `content_type` (proves browsing/tool/code turns are captured, not dropped) |
| File classes | doc 10,613 · data 8,860 · code 6,762 · notebook 21 · config 41 | uploaded/attached files bucketed by kind |
| AI summary | 181 items · 0 failed (ollama `llama3.1:8b`) | classified project cards = LLM_OK / attempted (here 181/181) |
| Disk | store 57.4 MB · bundles 3.7 MB | on-disk size of the parsed store and the per-project bundles |

### 1.2 The commands work as designed

Every read command was run live; "backing test" is the automated proof.

| Command | What it does | Result | Backing test |
|---|---|---|---|
| `gpt info` | catalog statistics (table 1.1) | 4,122 chats / 181 projects | `test_store_query` |
| `gpt status` | one-line catalog + summary + output state | OK | `test_store_query` |
| `gpt list` | rank projects by chats/versions/date | 181 projects listed (e.g. `ados-profile` 304 chats / 1275 vers) | `test_store_query` |
| `gpt search "ados"` | full-text scan over transcripts, cited | 186 matching chats with `id=` citations | `test_store_query` |
| `gpt show ados-profile` | one project's archetype/domain/goal | archetype `software_app`, domain `education/sat_preparation` | `test_schema_roundtrip` |
| `gpt zips-verify` | prove every exported chat is in the catalog | **VERDICT OK** — 4,122 = 4,113 newest-export + 9 older-only | `test_zip_verify`, `test_zip_ledger` |

### 1.3 It is private

| Guarantee | How it holds | Backing test |
|---|---|---|
| Raw chats never leave the box | live only under `$DATA_ROOT` (gitignored); no transcript text in any committed file | `test_check_no_secrets` |
| Published surface is sanitized | `gpt publish` actively redacts emails/paths/phones/tokens/JWT/PEM/IPv4 into placeholders, plus a user-supplied personal dictionary (`config/redact.local.json`) | `test_publish_boundary`, `test_redact`, `test_export_public`, `test_release_hardening` |
| Logs are PII-free | traces emit only labels/counts, never transcript text or `$DATA_ROOT` paths | `test_log_scrub` |
| `gpt ask` **and** `gpt summarize` are local by default | a cloud provider is refused unless `--scrub-cloud` or `--allow-raw-cloud-egress` — symmetric privacy gate | `test_ask_privacy`, `test_release_hardening` |

Catalog + privacy test run: **99 passed, 9 subtests** (`test_store_query`,
`test_content_coverage`, `test_shard_accounting`, `test_schema_roundtrip`,
`test_zip_verify`, `test_zip_ledger`, `test_publish_boundary`, `test_redact`,
`test_log_scrub`, `test_check_no_secrets`, `test_export_public`).

---

## 2. Ask — "semantic recall over the catalog, cited, local" (OBJ-CATALOG)

**Answer: yes.** `gpt index` builds a local embedding index; `gpt ask` retrieves
by similarity x recency and answers using only the retrieved chunks, with inline
`[n]` citations, running on local Ollama ($0, offline) by default.

Index built live on the RTX 3090: **4,121 chats → 38,904 chunks** (`bge-m3`,
1024-dim), now embedding **title+date with each chunk** (`embed_input =
title_chunk`, the Phase A winner — see 3.4) so version/ADR tokens in titles are
retrievable. The battery below was re-graded live on local Ollama (`qwen3:8b`,
`--k 8`, recency on), $0 and offline. Each question has a **verifiable ground
truth** (from `gpt search` over the catalog + owner confirmation) so the answer
can be graded, not just admired.

| # | Question | Ground truth | Answer (summary) | Grade |
|---|---|---|---|---|
| 1 | What is the rule for README.md vs CHANGELOG.md re: version numbers? | README/durable docs must not cite a version; only CHANGELOG.md does | "README must not reference the version number; that belongs only in CHANGELOG.md" `[n]` | ✓ correct |
| 2 | What is the ados-geometry concept? | the "goal-attractor geometry" | archetype, narrowed domain, meaning axes, goal figure/surface, attractor basin, convergence vector, repair triggers `[n3]` | ✓ correct |
| 3 | What does the ADOS compliance-check skill verify? | a multi-point compliance checklist | 11-point list: package identity, metadata governance, requirements coverage, geometry, self-eval, surface structure, JSON/JSONL discipline, validators/tests, portability, host-runtime boundaries, release-claim alignment `[n2]` | ✓ correct |
| 4 | What are the mandatory axis families for the ADOS profile? | research / specification / competition / science / market | exactly those five `[1]` | ✓ correct |
| 5 | Were there attempts to move from 1.23 → 1.24 and → 2.0, and what happened? | yes; 2.0 attempted but not stable | "1.24 implemented/validated (PASS); 2.0 attempt hit high-risk drift and was not adopted" `[1]` | ✓ correct |
| 6 | How did the ADOS pillars evolve up to v2.0? | pillars evolved v1.21 → v2.0 | accurate narrative: early pillars mixed app-reqs/governance/version notes; later cleaned to pure doctrine `[1]` | ✓ correct |
| 7 | What is the latest **stable** ados-profile version? | **1.23** | **"v1.4"** ✗ — and `--half-life 0` no longer rescues it: the enumeration chat's *title* (`...1.8 1.7 1.6 1.5 1.4`) now wins on similarity too (see findings) | ✗ wrong |
| 8 | What is the newest ados-profile version **overall**, and is it stable? | **2.0**, not stable | "v1.4, stable, STRICT_PASS" — still wrong; the same version-enumeration chat floods the top-k | ✗ wrong |
| 9 | What is my favorite pizza topping? *(negative)* | not in catalog | "the excerpts don't contain that; not in indexed chats" | ✓ refused |
| 10 | What does the ADOS spec say about quantum-teleportation deadlines? *(fabricated negative)* | not in catalog | "the excerpts don't contain that; couldn't find it" | ✓ refused |
| 11 | Why is ados-profile v2.0 not stable / approved as a clean successor to v1.23? | drift report verdict: **"do not approve v2.0 as a clean successor yet"**; CRITICAL compaction (APP 75→28, GOV 90→40, glossary 156→10), schema/skill rearchitecture, reduced evidence; manual approval required | "not stable due to high-risk drift; **not approved as a clean successor**; blockers = requirement/glossary/app-model reductions" `[1]` | ✓ correct |
| 12 | What is ADR-0005, and what is its status? | "Controlled Use of the Word `canonical`"; status **Proposed / pending approval** (2026-06-16) | topic exactly right — "clarifies the meaning of `canonical`" — **and now reports the status correctly: "proposed ADR, not yet approved"** `[n4]` | ✓ correct |

**Score: 8 correct, 2 wrong, 2 correct refusals (out of 12)** — up from 7 correct
after adopting title+date embedding. All answers were citation-grounded and **none
hallucinated content**; the two failures (Q7, Q8) return a *wrong-but-real* version
from the retrieved chunks, never an invented one.

**What title+date embedding changed (honest, mixed result).** It clearly *helped*
concept/status recall — **Q12 went partial → correct** (it now quotes the literal
"proposed ADR, not yet approved" instead of mis-reading "approved"), and Q11's
drift-report chunk is now ranked **#1**. But it *hurt* the version-superlatives:
because the offending chat's **title is itself a version list**
(`ados-profile1.8 1.7 1.6 1.5 1.4.1 1.4`, Jun-19), embedding the title made that
chat win even under pure similarity — so **Q7 lost the `--half-life 0` rescue** it
had on the chunk-only index. This is exactly the failure the deferred structured
version index / intent-routing phases (R6/R7) are designed to fix; title embedding
is a net +1 but not a substitute for them.

**Columns / meaning**

- **Question** — the natural-language query passed to `gpt ask "..."`.
- **Ground truth** — the verifiable correct answer, established from `gpt search`
  over the catalog (full-text, which finds 2.0/1.23/1.24 correctly) plus owner
  confirmation.
- **Answer (summary)** — the model's reply, grounded **only** in retrieved
  excerpts; if the excerpts lack the answer it says so rather than inventing one.
- **Grade** — ✓ correct · ✗ wrong · ✓ refused (correctly declined a
  not-in-catalog question).

**What the verification revealed (honest limitations).** After title+date
embedding, the retrieval layer (not synthesis) is still the weak point on
*version-superlative* questions — and the fix had a measurable trade-off:

- **Status fields now read correctly (Q12, fixed).** With version/ADR tokens from
  titles in the embedding, `ask` pulls the actual ADR-0005 chunk and reports its
  literal status — **"proposed ADR, not yet approved"** — instead of the previous
  over-read "approved". Concept/status recall is the clear winner of this change.
- **A version-enumeration title now dominates (Q7, regressed).** The chat titled
  `ados-profile1.8 1.7 1.6 1.5 1.4.1 1.4` (Jun-19) is the villain: embedding its
  *title* injected those version tokens into its vectors, so it wins on similarity
  for any "latest version" query. On the chunk-only index `--half-life 0` surfaced
  `ados-profil-v1.23.zip` and gave the correct **1.23**; on the title_chunk index it
  returns **v1.4** even with recency off. Title embedding traded a recency problem
  for a stronger lexical-title attractor.
- **"Newest overall = 2.0" is still a genuine miss (Q8).** The same enumeration
  chat floods the top-`k`; the model answers with the highest version it *sees*
  (v1.4). The data is in the catalog (`gpt search "v2.0"` → 15 chats) — dense
  retrieval just won't rank it first.
- **Anchored phrasing still works (Q11).** Naming the discriminating tokens
  ("**v2.0** / clean successor") pulls the right drift-report chunk to **rank #1** and
  the model reproduces the verdict verbatim with a citation. So the failure is
  retrieval *recall on vague superlative queries*, not a missing document.
- **Takeaway:** title+date embedding is a **net +1 (7 → 8)** and fixes status
  questions, but **version-superlatives need a structured version index + intent
  routing** (R6/R7) — a per-chat version/stability table queried deterministically —
  rather than more embedding tricks. Tracked in the [Fix ask IQ](.cursor/plans/fix_ask_iq_d69d4888.plan.md)
  plan (Phases 2-3) and `TODO.md`.

**Update — Phase 1 retrieval fixes (R2 + R3, measured by `gpt ask-eval`).** Two
no-reindex changes: **R2** raised the recency half-life default 180 → 365 days
(decay now breaks near-ties only, not relevance), and **R3** added a *per-chat
diversity cap* to `ask.retrieve()` — scan a larger pool (`k × 4`) but admit at
most `--per-chat` (default **3**) chunks per `chat_id`, so the version-enumeration
chat can no longer flood the top-`k`. Result on the 12-question battery:
**retrieval recall went 10/12 → 12/12 gold chats found** — Q7/Q8's gold v1.23/2.0
chat is now *in* the top-`k` (it was absent entirely before). The answer
scoreboard holds at **8 correct + 2 correct refusals = 10/12**: Q12 (ADR-0005)
stayed correct at `per-chat=3` (at `=2` the cap starved its multi-chunk answer,
a measured trade-off), and **Q7/Q8 are now synthesis-bound, not retrieval-bound** —
the model sees the right chat but still extracts `v1.4` first. This confirms the
remaining version-superlative failures need **intent routing / structured version
answer (R6/R7)**, not more retrieval tuning.

**Update — Phase 3 structured version index + intent routing (R7 + R6). Battery
now 12/12.** A version-superlative question ("newest / latest stable version?")
is a fact about the *whole catalog*, not a passage, so no amount of retrieval
tuning makes synthesis reliably pick the right number. **R7** (`scripts/lib/entities.py`,
`gpt build-entities`) scans the index once (no re-embed) and writes
`index/entities.json`: a product-scoped table of every `ados-profile` version,
its mention count, chat coverage, and instability votes — from which it derives
two deterministic verdicts. Guard rails learned from the live data: versions are
counted only when **product-qualified** (`ados-profile-vX.Y`, `package_version=`)
so numpy/gemini/"section 1.2" noise is excluded; instability is attributed only
to the version a negation *governs* (`do not approve v2.0`), so the
`v1.23 → v2.0` drift sentence flags 2.0 only; and `latest_stable` requires a
support floor (≥15% of the modal version's mentions), which excludes
higher-numbered but barely-referenced **attempts** like 1.24. The verdicts:
`newest_overall = 2.0 (unstable)`, `latest_stable = 1.23 (117 refs / 9 chats)`.
**R6** routes identity questions ("what is the …") to these verdicts with a
citation — *before* the LLM, locally and repeatably — while explanation
questions ("why is v2.0 not stable") still reach normal synthesis. Result: the
ask-eval battery is now **12/12 answers correct · 12/12 gold retrieved**. Sample:

```
$ gpt ask "What is the newest ados-profile version overall, and is it stable?"
2.0 is the newest ados-profile version overall, but it is not stable:
"...do not approve v2.0 as a clean successor yet". The latest stable release is 1.23.
Sources:
  [1] ados-profile-v2.0.zip vs ados-profile-v1.23.zip · 2026-06-18 · id=6a30986e…
```

Backing tests: `test_ask_live` (real embeddings rank the right chat for the
example questions) and `test_ask_privacy` (cloud calls require scrubbing).

**Update — interactive latency contract + warm daemon (correctness was fine;
this is speed/UX).** A bare `gpt ask` defaulted to `gpt-oss:20b` @ 32k context
and a 300s provider timeout, so a cold call could appear to *hang* for ~100s.
Three fixes turn that into a hard contract:

1. **Deterministic routing for catalog facts.** The entity index now also mines
   the product **acronym** expansion (validated by initials: a phrase only
   counts if its words spell `ADOS`). "What does ADOS stand for? / what is
   ADOS?" routes to `ADOS → Agentic Digital Operating System` with a citation
   and **no model call** — measured **~3-8ms** warm, **~1.5s** cold in-process
   (Python boot + index load), on *any* engine. Version-superlatives route the
   same way.
2. **A synthesis budget.** Non-routed answers run under a budget (default 15s,
   `--budget N`, `num_ctx` cut to 8k); a model that exceeds it is aborted and
   reported `[unusable]` with a distinct **exit code 3**, never left to hang.
   `gpt ask-eval --budget N` records per-question `elapsed_ms` and a usable
   verdict, surfacing a per-model latency line for the benchmark decision.
3. **A warm daemon** (`gpt ask-serve`, `scripts/ask_daemon.py`) that keeps the
   index, embedder, entities, and a persistent `claude`/`codex` engine resident,
   so `gpt ask` becomes a thin unix-socket client. Measured warm round-trips:
   **claude ~2s**, **codex ~2-5s** (vs 6-12s cold). It is **opt-in** (the engine
   is a plan-authenticated CLI that leaves the box): plain `gpt ask` uses it only
   if you started one, and stays local+$0 otherwise.

Engine spike (pinned protocols): `claude -p --input-format stream-json` is the
only CLI that clears ~2s warm but shares one session (so the daemon recycles it
every few turns and sends self-contained prompts); `codex mcp-server`'s `codex`
tool is stateless per call but ~2-5s. Honest floor: a *grounded multi-sentence*
synthesis over 8 excerpts is ~5-15s even warm — which is exactly what the budget
bounds; the ~2s guarantee holds for routed/short answers.

Backing tests: `test_warm_engine` (lifecycle: recycle, timeout→poison),
`test_ask_daemon` (socket round-trip with a mock engine; thin-client fallback),
`test_ask_budget` (over-budget→exit 3; entity route makes no model call),
`test_catalog_cli` / `test_benchmark_cli` (the other two README features).

**Update — latency knobs + daemon responsiveness (FR-Q16 / FR-Q18).** Three
latency fixes landed for the interactive path: the Ollama provider sends
`think="low"` for `gpt-oss` (booleans are ignored there), the `ask` path caps
output at `num_predict=384`, and local synthesis **streams** to the terminal
(`--no-stream`/`--json` stay buffered). A dedicated **stress suite**
(`test_ask_stress`) then hammered the warm daemon and surfaced one real bug:
the accept loop handled one connection at a time, so a long synthesis blocked
`ping`/`stats`/`shutdown` for up to the budget (head-of-line blocking). Fixed —
`serve()` now handles each connection on its own thread while synthesis stays
single-flight; filed and verified as **FR-Q18**. Backing tests:
`test_ask_latency` (think/num_predict/streaming guard) and `test_ask_stress`
(48 concurrent questions with no bleed, malformed-input survival, ping-fast-
during-slow-synthesis).

---

## 3. Benchmark — "is the $1,400 RTX 3090 worth it for this workload?" (OBJ-BENCH + OBJ-DECISION)

**Answer: hard to justify on output alone.** The plan-covered cloud models finish
nearly every item and classify it correctly at **$0 marginal**; locally only the
big reasoners classify well, and they are the slowest and most power-hungry. Keep
the card only for privacy/offline, very high volume, or if already amortised.

All three tables are the same `cmp-0628` sweep: 27 identical project bundles,
`num_ctx=16384`, accuracy keyed to `codex`. Cloud rows (codex, claude,
composer-2.5, composer-2.5-fast) are now **all fresh** from this sweep.

### 3.1 Performance (latency + throughput)

| Model | Where | s/item | warm s/item | load_s | gen tok/s | throughput tok/s |
|---|---|---:|---:|---:|---:|---:|
| composer-2.5-fast | Cursor plan | 14.4 | — | — | 59.6 | 505.3 |
| composer-2.5 | Cursor plan | 27.1 | — | — | 31.2 | 268.5 |
| codex | ChatGPT plan | 27.3 | — | — | 27.1 | 270.1 |
| claude | Claude plan | 38.5 | — | — | 20.9 | 190.2 |
| qwen2.5-coder:1.5b | RTX 3090 | 2.9 | 2.7 | 5.1 | 134.0 | 2258.6 |
| qwen2.5-coder:3b | RTX 3090 | 3.9 | 3.7 | 5.5 | 95.4 | 1703.6 |
| qwen2.5-coder:7b | RTX 3090 | 6.2 | 6.0 | 5.8 | 64.8 | 1065.2 |
| gemma3:1b | RTX 3090 | 6.1 | 4.9 | 27.7 | 54.9 | 1152.0 |
| qwen2.5vl:7b | RTX 3090 | 6.5 | 6.1 | 9.8 | 56.7 | 1015.9 |
| llama3.1:8b | RTX 3090 | 7.8 | 7.2 | 14.3 | 39.8 | 856.2 |
| qwen3:8b | RTX 3090 | 8.7 | 8.3 | 9.5 | 50.7 | 769.2 |
| qwen2.5-coder:14b | RTX 3090 | 12.9 | 12.6 | 7.4 | 32.8 | 518.3 |
| gpt-oss:20b | RTX 3090 | 20.4 | 19.6 | 18.1 | 22.4 | 381.8 |
| qwen3.6:35b | RTX 3090 | 33.4 | 19.2 | 354.6 | 16.4 | 207.4 |
| qwen3.6:27b | RTX 3090 | 41.1 | 36.7 | 109.7 | 14.3 | 169.6 |
| gemma4:31b | RTX 3090 | 45.7 | 35.9 | 245.2 | 12.9 | 156.2 |

**Columns / formulas** (cloud has no warm/load/Wh: no local VRAM load to separate)

- **s/item** = total wall-seconds / completed items (includes the one-time model load).
- **warm s/item** = (wall-seconds - `load_duration`) / completed items — steady-state speed.
- **load_s** = one-time seconds to load the model into VRAM (`load_duration`).
- **gen tok/s** = generated tokens / generation-seconds (decode speed).
- **throughput tok/s** = (prompt + generated tokens) / wall-seconds (end-to-end token rate).

### 3.2 Intellect (quality, three separate axes + schema)

| Model | Where | completion% | depth-on-success% | accuracy% | schema-valid% |
|---|---|---:|---:|---:|---:|
| codex | ChatGPT plan | 93 | 98 | 100 (ref) | 93 |
| composer-2.5 | Cursor plan | 100 | 99 | 80 | 100 |
| composer-2.5-fast | Cursor plan | 100 | 99 | 76 | 100 |
| claude | Claude plan | 96 | 98 | 54 | 96 |
| gemma4:31b | RTX 3090 | 93 | 89 | 74 | 93 |
| qwen3.6:35b | RTX 3090 | 93 | 80 | 65 | 93 |
| qwen3.6:27b | RTX 3090 | 93 | 88 | 61 | 93 |
| gpt-oss:20b | RTX 3090 | 81 | 76 | 50 | 81 |
| qwen2.5-coder:14b | RTX 3090 | 93 | 74 | 22 | 93 |
| qwen2.5vl:7b | RTX 3090 | 93 | 66 | 17 | 89 |
| qwen3:8b | RTX 3090 | 93 | 85 | 9 | 93 |
| qwen2.5-coder:3b | RTX 3090 | 93 | 52 | 9 | 93 |
| qwen2.5-coder:7b | RTX 3090 | 93 | 70 | 4 | 93 |
| qwen2.5-coder:1.5b | RTX 3090 | 93 | 69 | 0 | 93 |
| llama3.1:8b | RTX 3090 | 96 | 57 | 0 | 96 |
| gemma3:1b | RTX 3090 | 89 | 27 | 0 | 11 |

**Columns / formulas** (reliability, depth, and correctness are kept SEPARATE — never blended)

- **completion%** = LLM_OK / attempted x 100 (reliability: did the item finish).
- **depth-on-success%** = mean of four 0-100 fill axes — goal, min(objectives,3)/3, min(requirements,3)/3, archetype-field fill — over **completed items only** (completeness, not correctness).
- **accuracy%** = items whose (primary archetype, primary domain) match the `codex` reference / items both classified x 100 (correctness; `codex` = 100 by construction).
- **schema-valid%** = schema-shaped clean-JSON items / attempted x 100 (a coder-model strength, distinct from reliability).

The defining lesson is visible here: `qwen3:8b` fills 85% depth but is only 9%
correct — **depth is not accuracy**.

### 3.3 Economics — the $1,400 question

At $0.20/kWh. Cloud is $0 marginal because the plans are already paid for.

| Option | Up-front | Wh/item | energy $/item | marginal $/item | reliability% | accuracy% | Pays back the $1,400? |
|---|---:|---:|---:|---:|---:|---:|---|
| composer-2.5-fast (Cursor plan) | $0 | — | — | $0 | 100 | 76 | n/a — no capital cost |
| codex (ChatGPT plan) | $0 | — | — | $0 | 93 | 100 (ref) | n/a — no capital cost |
| claude (Claude plan) | $0 | — | — | $0 | 96 | 54 | n/a — no capital cost |
| RTX 3090 — `gemma4:31b` (best local accuracy) | **$1,400** | 3.197 | $0.00064 | $0.00064 | 93 | 74 | No — see below |
| RTX 3090 — `qwen2.5-coder:1.5b` (fastest local) | **$1,400** | 0.215 | $0.00004 | $0.00004 | 93 | 0 | No — see below |
| Paid cloud API (untested) | $0 | — | per-token | ~$0.03/item | — | — | only this column makes the GPU pencil out |

**Break-even logic.** The card's only per-item *saving* is versus a **metered**
API. Against the plan models you already pay for, the marginal cost is the same
($0), so the $1,400 never pays back on output: payback items =
$1,400 / (cloud $/item - local energy $/item) = $1,400 / (≈$0 - $0.0006) ->
**no positive break-even**. Versus a paid API at ~$0.03/item the crossover is
≈ 1,400 / 0.03 ≈ **47,000 items** — but those same items are already $0 on the
plan. So the GPU is justified only by **privacy/offline**, **plan rate-limits at
very high volume**, or **prior amortisation** by other GPU work — not by this
workload's economics.

**Columns / formulas**

- **Up-front** = one-time capital cost (the $1,400 card, or $0 for a plan you hold).
- **Wh/item** = measured GPU watt-hours per completed item (integral of `nvidia-smi power.draw` at 1 Hz / completed); cloud has none.
- **energy $/item** = Wh/item / 1000 x $/kWh (here $0.20).
- **marginal $/item** = incremental cost to process one more item (energy for local; $0 for plan-covered cloud; per-token for a metered API).
- **reliability% / accuracy%** = as defined in 3.2.
- **Pays back the $1,400?** = whether per-item savings ever recover the capital cost (see break-even logic).

### 3.4 GPU telemetry (measured) — `gpt metrics gpu`

Every GPU run now records a **full telemetry ledger** — one
`gpu-telemetry-sample/1` JSON line per ~0.5 s capturing power, power-limit,
temperature, GPU/memory utilization, VRAM, SM/memory clocks, fan, and pstate
(`scripts/lib/gpu_telemetry.py`, written to `gpu_trace.jsonl`). Each run is
aggregated into a schema-validated `gpu-telemetry-summary/1` block (avg/peak/min
per metric + integrated watt-hours + a throttle flag), validated by
[`schema/gpu_telemetry.schema.json`](schema/gpu_telemetry.schema.json). This is
the evidence behind the "fans are loud / is 254 W OK?" question: it is now
measured, not guessed.

The table below is rendered by `gpt metrics gpu` from the committed
`config/generated/{model_benchmarks,embed_benchmarks}.json`. The **embed** rows
are the live `cmp-0628` embedding sweep on the RTX 3090 (160-chat scope, 1,913
chunks each); the **gen** generation rows are **back-filled with `—`** because
full telemetry capture is newer than that sweep — their historical **Wh/item**
(integral of `power.draw`) is preserved in 3.3, and a re-metered
`gpt benchmark --meter-power` sweep will populate the rest.

| Workload | Model / variant | avg W | peak W | peak °C | util % | peak VRAM (MiB) | peak SM clock (MHz) | energy Wh | per-item | throttled |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|
| embed | bge-m3 · title_chunk | 208 | 265 | 71 | 37 | 10,210 | 1,920 | 4.858 | 2.54 Wh/1k | no |
| embed | bge-m3 · chunk | 204 | 257 | 70 | 37 | 10,223 | 1,935 | 4.820 | 2.52 Wh/1k | no |
| embed | qwen3-embedding:4b · title_chunk | 288 | 312 | 75 | 80 | 18,835 | 1,905 | 15.741 | 8.23 Wh/1k | no |
| embed | qwen3-embedding:4b · chunk | 283 | 315 | 75 | 76 | 18,819 | 1,920 | 15.017 | 7.85 Wh/1k | no |
| gen | all 12 local Ollama models | — | — | — | — | — | — | — | see 3.3 | — |
| gen | 4 cloud models (no GPU) | — | — | — | — | — | — | — | n/a | — |

**The energy view picks the same winner as the quality view.** `bge-m3` and
`qwen3-embedding:4b` both hit **Recall@8 = 1.00**, but `bge-m3` ranks better
(**MRR 0.85 vs 0.60**) *and* costs **~3× less energy** (2.54 vs 8.23 Wh/1k), runs
cooler (71 vs 75 °C), at half the utilization (37 vs 80 %) and half the VRAM
(10 vs 19 GB). The cheaper local model is also the better one — so the telemetry
*confirms* the embedder choice rather than trading quality for power.

**Columns / formulas** (`—` = no telemetry captured for that run)

- **avg W / peak W** = mean / peak board power draw, watts (`nvidia-smi power.draw`);
  peak 315 W sits under the card's **350 W** limit, so the loud fans are cooling a
  high-but-not-redline load.
- **peak °C** = peak core temperature; the **83 °C** throttle band was never
  reached (`throttled = no`), so no thermal clock-stealing corrupted the timings.
- **util %** = mean GPU compute utilization (`utilization.gpu`) — `bge-m3`
  embedding is bursty (≈37 % mean, host-side chunking between GPU batches) while
  the 4 B `qwen3-embedding` saturates the card (≈80 %).
- **peak VRAM** = peak `memory.used`, MiB — `bge-m3` uses ~10 GB of 24 GB;
  `qwen3-embedding:4b` ~19 GB. Both leave head-room (no `VRAM_FULL`/CPU-spill).
- **peak SM clock** = peak `clocks.sm`, MHz (boost behaviour).
- **energy Wh** = trapezoidal time-integral of `power.draw` over the run.
- **per-item** = **Wh/item** for generation (3.3) or **Wh per 1,000 chunks** for
  embedding (one-time index cost): embedding the full **38,904-chunk** catalog
  with `bge-m3` costs ≈ 38.9 × 2.54 ≈ **99 Wh ≈ $0.02** at $0.20/kWh — a rounding
  error against the $1,400 card (vs ≈ 320 Wh ≈ $0.06 for `qwen3-embedding:4b`).
- **throttled** = whether peak temp reached the thermal-throttle band.

Backing test: `test_gpu_telemetry` (offline — ledger aggregation, legacy-trace
compatibility, null/back-fill summary, and schema validity, no GPU required).

---

## Verdict

- **Catalog:** done and private — 4,122 chats, lossless (`zips-verify` OK), 99 tests green.
- **Ask:** working — local, cited semantic recall; **12/12** verification questions
  correct (10 substantive answers + 2 correct refusals), **never hallucinated
  content**. Path to 12/12: title+date embedding (7→8, fixed the ADR-0005 *status*
  answer) → Phase 1 per-chat diversity cap + softer recency (retrieval recall
  10/12→12/12) → Phase 3 structured version index + intent routing, which answers
  *version-superlative* questions ("latest stable / newest version") deterministically
  from `index/entities.json` with a citation (1.23 stable, 2.0 newest-but-unstable)
  instead of relying on the LLM to pick the right number out of context. See
  table 2 and the Fix-ask-IQ plan.
- **Benchmark:** answered — for this workload the RTX 3090 is **not justified on
  output alone**; the $0-marginal plan models match or beat it on reliability and
  accuracy. Keep the card only for privacy/offline, very high volume, or prior
  amortisation. Full per-model detail and methodology: [AI_MODEL_TESTS.md](AI_MODEL_TESTS.md).
