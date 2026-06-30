# `gpt ask` — requirements ledger

The single source of truth for what `gpt ask` (and its warm daemon) must do, why,
and the current status. IDs are stable so they can be cited in commits, tests,
and follow-up work.

Status legend: **DONE** (implemented + tested) · **DEFERRED** (next release) ·
**ON HOLD** (intentionally paused) · **OPEN**.

Key files: [scripts/ask.py](scripts/ask.py), [scripts/ask_daemon.py](scripts/ask_daemon.py),
[scripts/lib/ask_route.py](scripts/lib/ask_route.py),
[scripts/lib/ollama_probe.py](scripts/lib/ollama_probe.py),
[scripts/lib/models_bank.py](scripts/lib/models_bank.py), [run.py](run.py).

---

## Output / cosmetics

| ID | Requirement | Status |
|----|-------------|--------|
| REQ-1 | No blank line between the answer and the rest of the output. | DONE |
| REQ-2 | Bottom **status line** with key info: start time, duration (s), token budget, model name. | DONE |
| REQ-3 | Move `(N references across M chats)` out of the answer sentence and under the `Sources:` header. | DONE |
| REQ-4 | Sources hidden by default; shown only on request. | DONE (now via `--show-sources`, see REQ-Output1) |
| REQ-Output1 | `--show-sources` flag prints the cited Sources list (chat title + id + char span). `--details` kept as a hidden back-compat alias. | DONE |
| REQ-Output2 | **No guessing.** If the indexed chats don't contain the answer, output exactly `Not found in chat data.` and a status line (exit 0). Enforced for every engine: empty retrieval, the model's sentinel, or a short refusal phrase all normalise to the one message (`ask.is_not_found`). | DONE |

## Latency, budget, GPU, routing

| ID | Requirement | Status |
|----|-------------|--------|
| REQ-5 | Time budget is a wall-clock cap on synthesis, not a hard 15s kill for all models. Default `--budget 60`; `--budget 0` disables the abort; a live "working…" indicator shows a slow synthesis is alive, not hung. | DONE |
| REQ-6 | **GPU hard-block.** Refuse to run local Ollama on CPU (too slow); `--require-gpu` is the default, `--allow-cpu` opts out. Residency is detected via Ollama `/api/ps` VRAM share. | DONE |
| REQ-7 | **Capability router.** Auto-route to the most capable available engine: local GPU Ollama, else cloud `codex → claude → cursor`. `--route` default on, `--no-route` forces an explicit provider, `--prefer` sets the cloud order. | DONE |
| REQ-7a | A **table of models and how each must be called** (same business area for all questions, so no question-aware routing). The table is the model bank ([config/models.json](config/models.json) via `models_bank`); surfaced by `--list-models`. | DONE |
| REQ-Models1 | `--list-models` lists each bank model with a ready-to-paste `gpt ask "…"` command and the right per-model flags (local needs `--allow-cpu`; cloud needs `--scrub-cloud`). | DONE |
| MAIN-REQ-TIMEBUDGET | The most capable route should meet the **15s interactive target** — the architectural proof that the design is correct. (Formerly mislabelled "REQ-5a".) | ON HOLD — revisit after the rest land; track with `--budget 15` + `gpt ask-eval`. |

## Privacy

| ID | Requirement | Status |
|----|-------------|--------|
| REQ-Privacy1 | Local Ollama is the default and never leaves the box. A cloud/CLI provider requires `--scrub-cloud`, which redacts PII before anything is sent. | DONE |
| REQ-Doc2 | `--scrub-cloud` help rewritten in plain language: it lets your chat data leave THIS computer (blanks personal info, then a cloud/CLI model over the internet answers); off = data never leaves your machine. | DONE |

## Warm daemon (single, shared, router-aware)

| ID | Requirement | Status |
|----|-------------|--------|
| REQ-Daemon1 | **Default ON.** One shared daemon is auto-started and reused; `--no-daemon` opts out. | DONE |
| REQ-Daemon2 | Status reports whether the daemon was used and its **pid**. | DONE |
| REQ-Daemon3 | Daemon **startup excluded** from the answer's time budget (one-time cost; the answer clock resets after it is ready). | DONE |
| REQ-Daemon4 | **Single instance** — refuses to start twice on one index (socket ping guard). | DONE |
| REQ-Daemon5 | **No token leak**: no background generation when idle (no idle cost) **and** strict per-request isolation (self-contained prompts; the claude warm engine recycles to bound context bleed). | DONE |
| REQ-Daemon6 | **Detailed status** via `gpt ask --stats`: start time, uptime, CPU used, token budget, time spent in answers, requests served, and a recent-request history. | DONE |
| REQ-Daemon7 | **One daemon for all models**: holds the router; runs local Ollama and cloud engines; keeps at most one warm CLI engine resident and **switches it when the model/engine changes** (usually one default model). | DONE |

## Documentation

| ID | Requirement | Status |
|----|-------------|--------|
| REQ-Doc1 | Any big change updates the README and `--help`. Covered for: daemon-default, `--show-sources`, `--list-models`, `--scrub-cloud` wording, not-found behaviour, routing/GPU, no-stale-index. | DONE |
| REQ-Persist1 | All discussed/implemented requirements recorded in this file. | DONE (this file) |

---

## Follow-ups (the "F" items)

| ID | Item | Status |
|----|------|--------|
| F1 | Router integrated into the warm daemon (one daemon, all models). | DONE (REQ-Daemon7) |
| F2 | Persist the requirements ledger. | DONE (this file) |
| F3 | **Ollama GPU offload broken under WSL2** (llama-server GPU-discovery watchdog times out → silent CPU fallback, despite an RTX 3090 visible to `nvidia-smi`). Root cause: CUDA/Vulkan discovery for the systemd Ollama service in WSL2 (Ollama 0.30.x). For now REQ-6 hard-blocks CPU and REQ-7 routes to cloud, so `gpt ask` stays usable. | DEFERRED → becomes a **core requirement** next release (make local GPU offload actually work, not just route around it). |
| F4 | **"Stale index" must not exist by design.** Root cause: `gpt run` built Extract→Cluster→Bundle but never refreshed the semantic index, so the catalog could out-grow the index until a manual `gpt index`. Fix: `gpt run`/`gpt all` now run an **incremental, embedder-gated** index step after Bundle; `gpt ask` **self-heals** a small delta inline (incremental re-embed) and only defers a very large delta to `gpt index`. The alarming "run gpt index" nag is gone. | DONE |

---

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Answered (including the grounded `Not found in chat data.`). |
| 2 | Bad usage / privacy gate (cloud provider without `--scrub-cloud`). |
| 3 | `EXIT_UNUSABLE` — synthesis exceeded the budget (too slow for interactive ask). |
| 4 | `EXIT_NO_GPU` — local model not GPU-resident, CPU not permitted, and no cloud engine available. |

## Tests

- [tests/test_ask_route.py](tests/test_ask_route.py) — routing decision, GPU gate, budget default, not-found, `--show-sources`/`--details`, `--list-models`.
- [tests/test_ask_daemon.py](tests/test_ask_daemon.py) — socket round-trip, entity route, synthesis, stats/history, not-found, gate rc, warm-engine model switching.
- [tests/test_ask_privacy.py](tests/test_ask_privacy.py) — cloud privacy gate + PII scrubbing.
- [tests/test_ask_budget.py](tests/test_ask_budget.py) — over-budget → unusable; entity route with no model call.
- [tests/test_ask_live.py](tests/test_ask_live.py) — gated end-to-end answer with sources.
