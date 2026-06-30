#!/usr/bin/env python3
"""
gpt ask — answer a question from your own chats (semantic, local, cited).

Embeds the question with the same local model that built the index, retrieves
the most relevant transcript chunks (similarity x recency, so the *latest*
chats win on near-ties), and asks a generation model to answer using only that
retrieved context — printing the answer plus a cited Sources list.

Local by default (Ollama, $0, no data egress). Using a cloud/CLI provider
requires --scrub-cloud, which redacts PII (emails, paths, tokens, phones) from
the question and context before anything leaves the machine (NFR-P2).

  gpt ask "what is the latest ADOS README.md format?"
  gpt ask "what is the ados-geometry concept?" --k 10 --rerank
  gpt ask "what are the ADOS requirements?" --since 2026-01-01
  gpt ask "..." --provider openai --model gpt-5-mini --scrub-cloud
  gpt ask "..." --json                 # machine-readable answer + sources

Run `gpt index` first to build the index. Without one, `gpt ask` degrades to a
keyword scan over transcripts (warns, still returns the most relevant chats)
rather than erroring. Sources carry chunk char-offsets so a citation points at
an exact transcript region.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import ask_ipc  # noqa: E402
import ask_route  # noqa: E402
import embeddings as emb  # noqa: E402
import entities as ent  # noqa: E402
import paths  # noqa: E402
import redact  # noqa: E402
import uio  # noqa: E402
from providers import CLOUD_PROVIDERS  # noqa: E402

# Providers other than local Ollama send data off-box (API or signed-in CLI),
# so they are gated behind --scrub-cloud.
LOCAL_PROVIDERS = {"ollama"}

# Interactive latency target (REQ-5). This is the architecture's DESIGN DRIVER:
# the most capable available route should answer within this budget. It is no
# longer the default runtime kill — the default `--budget` is 60s so a slower
# model still answers — but `--budget 15` proves the target on the best route,
# and `--budget 0` disables the abort entirely (indicator only).
LATENCY_TARGET_S = 15.0
DEFAULT_BUDGET_S = 60.0
# A smaller context than the summariser's 32k: `ask` feeds only the retrieved
# excerpts, so 8k fits k=8 chunks while cutting prefill (and avoiding the slow
# 32k cold-load that made the default `gpt ask` look hung).
DEFAULT_ASK_NUM_CTX = 8192
# FR-Q16: cap the interactive answer length. Ask answers are short and cited, so
# a tight generation budget keeps a warm local answer inside the 15s target —
# unlike the summarizer's 1500-token records. At ~100 tok/s on the RTX 3090,
# ~384 tokens generate in ~4s, leaving headroom for prompt-eval under 15s.
DEFAULT_ASK_NUM_PREDICT = 384
# Distinct exit code so scripts/benchmarks can tell "too slow / unusable" apart
# from a generic failure.
EXIT_UNUSABLE = 3
# REQ-6: local model is not GPU-resident (and CPU not permitted) and no cloud
# engine was available — a hard block distinct from a generic failure.
EXIT_NO_GPU = 4

# REQ-Output2: the exact, only thing `gpt ask` may say when the indexed chats do
# not contain the answer. No model (local or cloud) is allowed to guess: the
# answer must be grounded in the user's own exports or it is this sentinel.
NOT_FOUND_MSG = "Not found in chat data."

SYSTEM_PROMPT = (
    "You answer questions using ONLY the provided excerpts from the user's own "
    "ChatGPT history. Each excerpt is tagged [n] with its chat title and date. "
    "Rules:\n"
    "- Use ONLY facts stated in the excerpts. Never use outside/general "
    "knowledge, and never guess or infer beyond what the excerpts say.\n"
    "- Cite the excerpts you use inline as [n].\n"
    "- If several excerpts conflict, prefer the most recent date and say so.\n"
    "- If the excerpts do not contain the answer, reply with EXACTLY this line "
    "and nothing else:\n"
    f"{NOT_FOUND_MSG}\n"
    "- Be concise and concrete."
)

# Phrases a model emits when it cannot answer from the excerpts. We normalise any
# of these (across local + cloud providers) to the single NOT_FOUND_MSG so the
# "no guessing" contract reads identically regardless of which engine answered.
_NOT_FOUND_PATTERNS = (
    "not found in chat data",
    "couldn't find", "could not find", "can't find", "cannot find",
    "no relevant", "do not contain", "don't contain", "does not contain",
    "doesn't contain", "no information", "not contained in", "not mentioned",
    "no mention of", "isn't in the", "is not in the", "not in the indexed",
    "not in the provided", "not present in",
)


def is_not_found(answer: str | None) -> bool:
    """True when an answer is empty or a (non-grounded) 'couldn't find' reply.

    Centralises REQ-Output2 detection so the in-process and daemon paths agree:
    an empty/blank answer, the exact sentinel, or a short refusal phrase all
    collapse to NOT_FOUND_MSG rather than leaking a model's freelance guess.
    """
    text = (answer or "").strip()
    if not text:
        return True
    low = text.lower()
    if low.rstrip(".") == NOT_FOUND_MSG.lower().rstrip("."):
        return True
    # Only treat a refusal phrase as not-found for a SHORT answer: a long answer
    # that happens to contain "does not contain X" is still a real answer.
    if len(text) <= 240 and any(p in low for p in _NOT_FOUND_PATTERNS):
        return True
    return False


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------
def load_index(index_dir: str):
    """Return {manifest, vectors(np.ndarray), chunks(list)} or None if absent."""
    man_path = os.path.join(index_dir, "manifest.json")
    vec_path = os.path.join(index_dir, "vectors.npy")
    chunk_path = os.path.join(index_dir, "chunks.jsonl")
    if not (os.path.isfile(man_path) and os.path.isfile(vec_path)
            and os.path.isfile(chunk_path)):
        return None
    import numpy as np
    with open(man_path, encoding="utf-8") as f:
        manifest = json.load(f)
    vectors = np.load(vec_path)
    chunks = []
    with open(chunk_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return {"manifest": manifest, "vectors": vectors, "chunks": chunks}


# ---------------------------------------------------------------------------
# Retrieval + prompt assembly (pure; numpy via embeddings helpers)
# ---------------------------------------------------------------------------
def retrieve(qvec, vectors, chunks, *, k: int = 8,
             half_life_days: float = emb.DEFAULT_HALF_LIFE_DAYS,
             since: str | None = None, now=None,
             per_chat: int = 3, pool_factor: int = 4) -> list[dict]:
    """Rank chunks by similarity x recency; return the top `k` as dicts.

    R3 per-chat diversity cap: with `per_chat > 0`, scan a larger candidate pool
    (`k * pool_factor`) but admit at most `per_chat` chunks from any single
    `chat_id`, so one long version-enumeration chat can't flood the top-k and
    crowd out the chat that actually answers the question. `per_chat=0` disables
    the cap (legacy behaviour: pure top-k).

    Each result is the chunk dict plus `sim` (cosine) and `score` (final). A
    `since` (YYYY-MM-DD) date drops older chunks entirely. Deterministic on
    ties (lower row index first).
    """
    import numpy as np
    if vectors is None or getattr(vectors, "shape", (0,))[0] == 0 or not chunks:
        return []
    sims = emb.cosine_sims(qvec, vectors)
    weights = np.asarray(
        [emb.recency_weight(c.get("update_date"), half_life_days=half_life_days,
                            now=now) for c in chunks], dtype="float32")
    final = sims * weights
    if since:
        keep = np.asarray(
            [1.0 if (c.get("update_date") or "")[:10] >= since else 0.0
             for c in chunks], dtype="float32")
        final = final * keep
    pool = k if per_chat <= 0 else min(len(chunks), max(k * pool_factor, k))
    order = emb.top_indices(final, pool)
    out: list[dict] = []
    seen: dict[str, int] = {}
    for i in order:
        if float(final[i]) <= 0.0:
            continue
        if per_chat > 0:
            cid = chunks[i].get("chat_id")
            if seen.get(cid, 0) >= per_chat:
                continue
            seen[cid] = seen.get(cid, 0) + 1
        hit = dict(chunks[i])
        hit["sim"] = float(sims[i])
        hit["score"] = float(final[i])
        out.append(hit)
        if len(out) >= k:
            break
    return out


def lexical_rerank(question: str, hits: list[dict]) -> list[dict]:
    """Re-order `hits` by blending the semantic score with lexical overlap.

    A lightweight, dependency-free re-rank: each hit's final score is its
    retrieval `score` nudged by the fraction of distinct question words that
    appear in the excerpt. This sharpens precision when several chunks are
    semantically close but only some actually mention the asked-about terms.
    Deterministic; a full cross-encoder re-rank remains a future option.
    """
    qwords = {w for w in re_words(question) if len(w) > 2}
    if not qwords or not hits:
        return list(hits)
    ranked = []
    for i, hit in enumerate(hits):
        words = set(re_words(hit.get("text") or ""))
        overlap = len(qwords & words) / len(qwords)
        base = float(hit.get("score") or 0.0)
        ranked.append((-(base * (1.0 + overlap)), i, hit))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [h for _s, _i, h in ranked]


def re_words(text: str) -> list[str]:
    """Lowercased alphanumeric word tokens (helper for lexical scoring)."""
    import re
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def build_prompt(question: str, hits: list[dict]) -> tuple[str, str, list[dict]]:
    """Assemble (system, user_prompt, sources) from retrieved chunks.

    Sources are de-duplicated by chat in first-seen order and numbered [1..N];
    every excerpt in the prompt is tagged with its source number so the model
    can cite it. Each source also carries the char span of its first matching
    chunk (`start`/`end`) so a citation points at an exact transcript region.
    Returns the sources list as ordered dicts for printing.
    """
    sources: list[dict] = []
    num_by_chat: dict[str, int] = {}
    blocks: list[str] = []
    for hit in hits:
        cid = hit.get("chat_id", "")
        if cid not in num_by_chat:
            num_by_chat[cid] = len(sources) + 1
            sources.append({
                "n": num_by_chat[cid],
                "chat_id": cid,
                "title": hit.get("title") or "(untitled)",
                "update_date": hit.get("update_date") or "",
                "start": hit.get("start"),
                "end": hit.get("end"),
            })
        n = num_by_chat[cid]
        title = hit.get("title") or "(untitled)"
        date = hit.get("update_date") or "?"
        span = ""
        if isinstance(hit.get("start"), int) and isinstance(hit.get("end"), int):
            span = f" chars {hit['start']}-{hit['end']}"
        text = (hit.get("text") or "").strip()
        blocks.append(f"[{n}] {title} ({date}){span}\n{text}")
    context = "\n\n".join(blocks)
    user_prompt = (
        f"Question: {question}\n\n"
        f"Excerpts from your chats (newest-weighted):\n\n{context}\n\n"
        f"Answer the question using only these excerpts, citing [n]."
    )
    return SYSTEM_PROMPT, user_prompt, sources


def source_for_chat(idx: dict, chat_id: str | None) -> list[dict]:
    """Build a single-entry sources list (citation) for a routed answer."""
    if not chat_id:
        return []
    for c in idx.get("chunks", []):
        if c.get("chat_id") == chat_id:
            return [{"n": 1, "chat_id": chat_id,
                     "title": c.get("title") or "(untitled)",
                     "update_date": c.get("update_date") or "",
                     "start": c.get("start"), "end": c.get("end")}]
    return [{"n": 1, "chat_id": chat_id, "title": "(untitled)",
             "update_date": "", "start": None, "end": None}]


def reference_note(routed: dict | None) -> str | None:
    """``"7 references across 3 chats"`` for a routed answer, else None.

    Surfaced in the `Sources:` header rather than inline in the answer, so the
    answer line stays a clean sentence.
    """
    if not routed:
        return None
    m, n = routed.get("mentions"), routed.get("n_chats")
    if m and n:
        return f"{m} references across {n} chats"
    return None


def format_sources(sources: list[dict], note: str | None = None) -> str:
    header = "Sources:" + (f" ({note})" if note else "")
    lines = [header]
    for s in sources:
        date = s.get("update_date") or "—"
        span = ""
        if isinstance(s.get("start"), int) and isinstance(s.get("end"), int):
            span = f" · chars {s['start']}-{s['end']}"
        lines.append(f"  [{s['n']}] {s.get('title', '(untitled)')} · {date} · "
                     f"id={s.get('chat_id', '')}{span}")
    return "\n".join(lines)


def fmt_duration(seconds: float) -> str:
    """Compact, never-zero duration: ``3ms`` / ``0.9s`` / ``14s``.

    The old ``{:.1f}s`` rendered a deterministic entity answer (~3ms) as a
    confusing ``0.0s``; this keeps sub-second answers honest (FR-Q19)."""
    if seconds >= 10:
        return f"{seconds:.0f}s"
    if seconds >= 0.1:
        return f"{seconds:.1f}s"
    if seconds >= 0.0005:
        return f"{seconds * 1000:.0f}ms"
    return "<1ms"


def fmt_token_budget(used: int | None, budget: int | None) -> str | None:
    """The bracket's token figure: ``34/384 tok`` (used/budget), ``34 tok``
    (no known cap), or ``0 tok`` (deterministic route). ``None`` hides it when
    the engine reports no count (e.g. a warm CLI engine)."""
    if used is None:
        return None
    if budget:
        return f"{used:,}/{budget:,} tok"
    return f"{used:,} tok"


def status_line(t_start: float, *, model: str | None,
                used_tokens: int | None = None,
                token_budget: int | None = None,
                where: str | None = None) -> str:
    """One compact, accurate run-summary line (FR-Q19):

        ``gpt ask · <model|route> · [ <elapsed> · <used>/<budget> tok ] · <where>``

    All the run facts on a single line: which model/route answered, how long it
    took (sub-second precise), how many output tokens it spent against the
    interactive budget (``num_predict`` — NOT the context window), and whether a
    warm daemon or an in-process call served it. `used_tokens=0` marks a
    deterministic route (no model ran); `None` hides the token figure."""
    import time as _time
    dur = _time.monotonic() - t_start
    inner = [fmt_duration(dur)]
    tok = fmt_token_budget(used_tokens, token_budget)
    if tok:
        inner.append(tok)
    bracket = "[ " + " · ".join(inner) + " ]"
    return uio.context_line("gpt ask", model or "?", bracket, where or "")


def keyword_fallback(question: str, run_label: str | None,
                     k: int) -> list[dict]:
    """Sources-shaped keyword hits when no semantic index exists.

    Scans transcripts for the question's salient words (longest first) so
    `gpt ask` still returns the most relevant chats — degraded, but useful —
    instead of erroring out. No embeddings, no LLM.
    """
    import store_query as sq
    words = sorted({w for w in re_words(question) if len(w) > 3},
                   key=len, reverse=True)
    rows: list[dict] = []
    seen: set[str] = set()
    for w in words or [question]:
        for r in sq.search_transcripts(w, ignore_case=True, scope_all=True,
                                       limit=k, run_label=run_label):
            cid = r.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            rows.append({
                "n": len(rows) + 1,
                "chat_id": cid,
                "title": r.get("title") or "(untitled)",
                "update_date": r.get("update_date") or "",
                "snippet": r.get("snippet") or "",
            })
            if len(rows) >= k:
                return rows
    return rows


def index_delta(idx: dict, run_label: str | None) -> int:
    """How many catalog chats the index has NOT captured yet (0 = current).

    After `gpt run` adds chats, an index built before it under-covers the
    catalog by this many chats until it is refreshed.
    """
    try:
        import store_query as sq
        st = sq.catalog_state(run_label)
        return max(0, int(st.get("n_chats") or 0)
                   - int((idx.get("manifest") or {}).get("n_chats") or 0))
    except Exception:
        return 0


def index_is_stale(idx: dict, run_label: str | None) -> bool:
    """True when the catalog holds more chats than the index captured."""
    return index_delta(idx, run_label) > 0


# How big a delta `gpt ask` will self-heal inline before it would rather defer
# to an explicit `gpt index` (keeps the interactive path from a surprise stall).
AUTO_REFRESH_MAX_DELTA = 200


def auto_refresh_index(index_dir: str, run_label: str | None,
                       embed_model: str, host: str | None) -> dict | None:
    """Incrementally embed the new chats and return the reloaded index.

    F4 "no stale index by design": the index is incremental, so refreshing only
    re-embeds chats that changed/were added. Returns the fresh index on success,
    or None if it could not refresh (caller keeps using the old index).
    """
    try:
        import index as index_mod
        records = list(index_mod.iter_chat_records(run_label))
        existing = index_mod.load_existing(index_dir)

        def _embed(texts: list[str]) -> list[list[float]]:
            return emb.embed_texts(texts, model=embed_model, host=host)

        result = index_mod.build_index(records, _embed, embed_model=embed_model,
                                       existing=existing)
        index_mod.write_index(index_dir, result)
        return load_index(index_dir)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Warm-daemon client (thin path)
# ---------------------------------------------------------------------------
def ensure_daemon(index_dir: str, *, engine: str | None = None,
                  run_label: str | None = None,
                  wait_s: float = 60.0) -> tuple[bool, float]:
    """Ensure one warm daemon is serving; start it (detached) if needed.

    Returns (serving, startup_seconds). Single-instance: if a daemon already
    answers the socket we return immediately (startup 0.0). Otherwise we spawn
    one detached and poll until it pings, fast-failing if the child process
    exits (e.g. a missing index) instead of blocking for the whole `wait_s`.
    """
    import subprocess
    import time
    sock = ask_ipc.socket_path(index_dir)
    if ask_ipc.ping(sock) is not None:
        return True, 0.0
    cmd = [sys.executable, os.path.join(HERE, "ask_daemon.py")]
    if engine:
        cmd += ["--engine", engine]
    if run_label:
        cmd += ["--run-label", run_label]
    log_path = os.path.join(index_dir, "ask_daemon.log")
    t0 = time.time()
    try:
        log = open(log_path, "ab")
        proc = subprocess.Popen(cmd, stdout=log, stderr=log,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True, env=os.environ.copy())
    except OSError as e:
        print(f"[warn] could not spawn daemon: {e}", file=sys.stderr)
        return False, time.time() - t0
    while time.time() - t0 < wait_s:
        if ask_ipc.ping(sock, 1.0) is not None:
            return True, time.time() - t0
        if proc.poll() is not None:  # child exited before serving — give up now
            return False, time.time() - t0
        time.sleep(0.4)
    return False, time.time() - t0


def answer_via_daemon(sock: str, question: str, args, start_dt=None,
                      t_start: float | None = None,
                      token_budget: int | None = None) -> int:
    """Send the question to the warm daemon and print its reply.

    The daemon owns routing, so we forward the full routing intent (provider,
    GPU policy, preference, scrub flag); it resolves local-GPU vs cloud, enforces
    the same privacy/GPU gate, synthesises, and applies the not-found contract.
    """
    import socket as _socket
    import time as _time
    if t_start is None:
        t_start = _time.monotonic()
    budget = (args.budget if args.budget is not None else DEFAULT_BUDGET_S)
    pong = ask_ipc.ping(sock)
    pid = pong.get("pid") if pong else None

    def _status(model: str | None, resp: dict) -> None:
        if start_dt is None:
            return
        sys.stdout.flush()
        where = f"daemon pid {pid}" if pid else "daemon"
        # Prefer the daemon-reported output tokens + cap; fall back to the
        # client's configured budget so the bracket is never blank.
        used = resp.get("tokens")
        cap = resp.get("num_predict") or token_budget
        print(status_line(t_start, model=model, used_tokens=used,
                          token_budget=cap, where=where), file=sys.stderr)

    req = {"op": "ask", "question": question, "k": args.k,
           "per_chat": args.per_chat, "half_life": args.half_life,
           "since": args.since, "rerank": args.rerank,
           "no_entity_route": args.no_entity_route, "budget": budget,
           # routing intent (resolved server-side, warm):
           "provider": args.provider, "model": args.model, "host": args.host,
           "route": args.route, "require_gpu": args.require_gpu,
           "prefer": args.prefer, "scrub_cloud": args.scrub_cloud,
           "num_ctx": args.num_ctx, "num_predict": args.num_predict}
    try:
        timeout = (budget + 30) if budget and budget > 0 else 86400
        resp = ask_ipc.send_request(sock, req, timeout=timeout)
    except (OSError, _socket.timeout, ValueError) as e:
        print(f"[error] daemon request failed: {e}", file=sys.stderr)
        return 1
    if not resp.get("ok"):
        # Gate failures (privacy / GPU) carry a return code to mirror in-process.
        if resp.get("rc"):
            print(f"[error] {resp.get('error')}", file=sys.stderr)
            return int(resp["rc"])
        print(f"[error] daemon: {resp.get('error')}", file=sys.stderr)
        return 1
    model = resp.get("model") or resp.get("engine")
    sources = resp.get("sources") or []
    if resp.get("route_note"):
        print(uio.context_line("gpt ask", resp["route_note"]), file=sys.stderr)
    if resp.get("unusable"):
        print(f"[unusable] {model} exceeded the "
              f"{resp.get('budget_s', budget)}s budget for this question",
              file=sys.stderr)
        if args.show_sources and sources:
            print(format_sources(sources), file=sys.stderr)
        _status(model, resp)
        return EXIT_UNUSABLE
    answer = resp.get("answer")
    not_found = bool(resp.get("not_found")) or is_not_found(answer)
    answer_out = NOT_FOUND_MSG if not_found else (answer or "").strip()
    if args.json:
        print(json.dumps({"question": question, "answer": answer_out,
                          "not_found": not_found, "route": resp.get("route"),
                          "provider": resp.get("provider") or resp.get("engine"),
                          "model": resp.get("model"),
                          "elapsed_ms": resp.get("elapsed_ms"),
                          "sources": [] if not_found else sources},
                         ensure_ascii=False, indent=2))
        return 0
    print(answer_out)
    if args.show_sources and sources and not not_found:
        note = reference_note(resp)
        print(format_sources(sources, note))
    _status(model, resp)
    return 0


def _looks_like_timeout(err: Exception, elapsed: float, budget: float) -> bool:
    """True when a provider failure is (almost certainly) the budget firing."""
    msg = str(err).lower()
    if budget <= 0:  # no abort configured → never classify as a timeout
        return "timed out" in msg or "timeout" in msg
    return "timed out" in msg or "timeout" in msg or elapsed >= budget * 0.9


# Hold back this many characters before committing streamed output to stdout, so
# a short "couldn't find it" refusal (is_not_found caps at 240 chars) can still
# collapse to the NOT_FOUND_MSG sentinel (FR-Q8) instead of leaking to screen.
_STREAM_GUARD_CHARS = 240


def stream_local_answer(provider, system: str, prompt: str, *, budget: float,
                        no_abort: bool, t0: float, out=None
                        ) -> tuple[str, bool, int | None]:
    """Stream a local answer to `out` (stdout) with a not-found guard + budget.

    Returns `(full_text, not_found, output_tokens)`. Buffers the first
    `_STREAM_GUARD_CHARS` so a refusal can collapse to the sentinel (FR-Q8); once
    past the guard it prints tokens live for low perceived latency (FR-Q16).
    `output_tokens` comes from the stream's final `Usage` (None if the stream
    reported none) so the status line can show the real cost (FR-Q19). Raises
    ProviderError if the budget is exceeded mid-stream (so the caller's UNUSABLE
    path fires) or the stream fails. The sentinel itself is printed by the caller.
    """
    import time as _t
    from providers import ProviderError, Usage

    out = out or sys.stdout
    buf: list[str] = []
    full: list[str] = []
    decided = False
    printed = False
    out_tokens: int | None = None
    for chunk in provider.stream(system, prompt, json_mode=False):
        if isinstance(chunk, Usage):
            out_tokens = chunk.output_tokens or None
            break
        full.append(chunk)
        if not no_abort and (_t.monotonic() - t0) >= budget:
            if printed:
                out.write("\n")
                out.flush()
            raise ProviderError("ollama stream: timed out (budget)")
        if decided:
            out.write(chunk)
            out.flush()
            printed = True
            continue
        buf.append(chunk)
        joined = "".join(buf)
        if len(joined) > _STREAM_GUARD_CHARS:
            out.write(joined)
            out.flush()
            printed = True
            decided = True
            buf = []
    full_text = "".join(full)
    not_found = is_not_found(full_text)
    if not decided and not not_found:
        out.write(full_text)
        out.flush()
        printed = True
    if printed and not full_text.endswith("\n"):
        out.write("\n")
        out.flush()
    return full_text, not_found, out_tokens


# ---------------------------------------------------------------------------
# REQ-5: live "working" indicator so a slow synthesis is visibly not hung
# ---------------------------------------------------------------------------
class working_indicator:
    """Context manager that animates a `working…` spinner on a TTY stderr.

    Disabled automatically when stderr is not a TTY (pipes, tests, logs) so it
    never pollutes captured output. The elapsed seconds make a long-but-alive
    synthesis obviously distinct from a hang.
    """

    def __init__(self, label: str, stream=None):
        self.label = label
        self.stream = stream or sys.stderr
        self.enabled = bool(getattr(self.stream, "isatty", lambda: False)())
        self._stop = None
        self._t = None

    def __enter__(self):
        if not self.enabled:
            return self
        import threading
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def _run(self):
        import itertools
        import time as _time
        frames = itertools.cycle("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")
        t0 = _time.monotonic()
        while not self._stop.wait(0.1):
            el = _time.monotonic() - t0
            self.stream.write(f"\r{next(frames)} {self.label} {el:0.0f}s ")
            self.stream.flush()

    def __exit__(self, *exc):
        if self.enabled and self._stop is not None:
            self._stop.set()
            if self._t is not None:
                self._t.join(timeout=0.5)
            self.stream.write("\r" + " " * (len(self.label) + 18) + "\r")
            self.stream.flush()
        return False


# ---------------------------------------------------------------------------
# REQ-6 / REQ-7: GPU residency gate + capability router
# ---------------------------------------------------------------------------
def gpu_residency(model: str, host: str | None, load_timeout: int = 120) -> dict:
    """Whether `model` is GPU-resident on the Ollama host (patchable in tests)."""
    import ollama_probe
    return ollama_probe.model_gpu_state(model, host, load_timeout=load_timeout)


def _gpu_detail(state: dict) -> str:
    if state.get("on_gpu") is None:
        return state.get("note") or "placement unknown / host unreachable"
    return f"{int(round(state.get('gpu_frac', 0.0) * 100))}% on GPU"


def engine_available(engine: str, cfg: dict) -> tuple[bool, str]:
    """Preflight one routing engine via provider_detect (patchable in tests)."""
    import provider_detect
    name, notes = provider_detect.detect_provider(order=(engine,), cfg=cfg)
    return (name == engine), (notes[-1] if notes else "unknown")


def resolve_route(args, cfg: dict):
    """Pick the provider/model for this question (REQ-6/REQ-7).

    Returns ("ok", provider_name, model_override, is_local, note) on success, or
    ("error", rc, errmsg, None, None) on a gate failure (the caller prints
    errmsg). Pure of stdout/stderr so the warm daemon can reuse it and return a
    structured error. The cloud privacy gate (forced cloud needs --scrub-cloud)
    is enforced here so it trips before any embedding or network egress.
    """
    oll = cfg.get("ollama") or {}
    ask_cfg = cfg.get("ask") or {}
    ollama_model = (args.model or ask_cfg.get("model") or oll.get("model")
                    or "gpt-oss:20b")
    host = args.host or ask_cfg.get("host") or oll.get("host")
    prefer = ([p.strip() for p in args.prefer.split(",") if p.strip()]
              if args.prefer else None)

    plan = ask_route.plan_route(route_enabled=args.route,
                                forced_provider=args.provider,
                                local_usable=False, prefer=prefer)

    # 1) Forced provider: honor it, keep the cloud privacy gate.
    if plan["action"] == "forced":
        name = plan["provider"]
        if name in CLOUD_PROVIDERS and not args.scrub_cloud:
            return ("error", 2,
                    f"provider '{name}' sends data off-box. Re-run with "
                    f"--scrub-cloud to redact PII first, or use --provider "
                    f"ollama (local).", None, None)
        if name == "ollama":
            ok, msg = _ollama_gpu_ok(ollama_model, host, args)
            if not ok:
                return ("error", EXIT_NO_GPU, msg, None, None)
        model = ask_route.model_for_engine(name, args.model)
        return ("ok", name, model, name == "ollama", f"forced provider {name}")

    # 2) Routing disabled (--no-route): local Ollama, GPU gate applies.
    if plan["action"] == "local_only":
        ok, msg = _ollama_gpu_ok(ollama_model, host, args)
        if not ok:
            return ("error", EXIT_NO_GPU, msg, None, None)
        return ("ok", "ollama", args.model, True, "routing disabled; local Ollama")

    # 3) Routing on: prefer the local GPU, else the most capable cloud engine.
    if args.require_gpu:
        state = gpu_residency(ollama_model, host)
        local_ok = state.get("on_gpu") is True
        gpu_note = _gpu_detail(state)
    else:
        local_ok, gpu_note = True, "cpu allowed (--allow-cpu)"
    if local_ok:
        return ("ok", "ollama", args.model, True, f"local Ollama ({gpu_note})")

    tried: list[str] = []
    for eng in ask_route.cloud_order(prefer):
        ok, _msg = engine_available(eng, cfg)
        tried.append(f"{eng}={'ok' if ok else 'no'}")
        if ok:
            model = ask_route.model_for_engine(eng, args.model)
            return ("ok", eng, model, False,
                    f"no local GPU ({gpu_note}) → {eng}")
    return ("error", EXIT_NO_GPU,
            f"'{ollama_model}' is not GPU-resident ({gpu_note}) and no cloud "
            f"engine is available ({', '.join(tried)}). Fixes: make Ollama "
            f"offload to the GPU, pass --allow-cpu to permit slow CPU, or sign "
            f"in to codex/claude/cursor.", None, None)


def _ollama_gpu_ok(model: str, host: str | None, args) -> tuple[bool, str]:
    """REQ-6 gate for an Ollama target.

    Returns (True, "ok") if GPU-resident or CPU permitted, else
    (False, <hard-block message>) for the caller to surface.
    """
    if not args.require_gpu:
        return True, "cpu allowed (--allow-cpu)"
    state = gpu_residency(model, host)
    if state.get("on_gpu") is True:
        return True, _gpu_detail(state)
    detail = _gpu_detail(state)
    return False, (
        f"Ollama model '{model}' is not GPU-resident ({detail}). Refusing to "
        f"run on CPU (too slow for interactive ask). Fixes: make Ollama offload "
        f"to the GPU, pass --allow-cpu to permit it, or enable routing (drop "
        f"--no-route) to use a cloud engine.")


# ---------------------------------------------------------------------------
# REQ-Models1 / REQ-7a: the model table — how each model must be CALLED by ask
# ---------------------------------------------------------------------------
def ask_command_for(entry: dict, question: str = "your question") -> str:
    """The full, copy-pasteable `gpt ask` command to run one bank model.

    The flags differ per model: a local Ollama model needs `--allow-cpu` if it
    is not GPU-resident; a cloud/CLI model needs `--scrub-cloud` (data leaves the
    box). `cursor` routes to its composer model.
    """
    provider = entry.get("provider", "")
    name = entry.get("name", "")
    if provider == "ollama":
        return (f'gpt ask "{question}" --provider ollama --model {name} '
                f'[--allow-cpu]')
    model = name or (ask_route.CURSOR_MODEL if provider == "cursor" else "")
    model_flag = f" --model {model}" if model else ""
    return f'gpt ask "{question}" --provider {provider}{model_flag} --scrub-cloud'


def format_model_commands(cfg: dict, question: str = "your question") -> str:
    """List the model bank with the exact `gpt ask` command for each (REQ-7a).

    Same business area for every question, so there is no question-aware
    routing: this is simply the table of models and how each must be called.
    """
    import models_bank
    entries = models_bank.load_bank(cfg=cfg)
    lines = ["Models `gpt ask` can use — copy a line to force that model:",
             "  (Default: `gpt ask \"…\"` auto-routes to local GPU Ollama, else "
             "the best available cloud engine.)", ""]
    last = None
    for e in entries:
        if e.get("skip"):
            continue
        prov = e.get("provider")
        if prov != last:
            lines.append(f"  [{prov}]")
            last = prov
        bits = [models_bank.billing_label(e),
                "installed" if e.get("_discovered") else "",
                models_bank.benchmark_summary(e)]
        comment = " · ".join(b for b in bits if b)
        cmd = "    " + ask_command_for(e, question)
        lines.append(f"{cmd}  # {comment}" if comment else cmd)
    lines += ["",
              "  Local Ollama = $0, stays on your machine. Cloud/CLI engines "
              "(codex/claude/cursor) need --scrub-cloud (data leaves the box "
              "after PII is blanked)."]
    return "\n".join(lines)


def daemon_stats_report(index_dir: str) -> str:
    """Human-readable warm-daemon status (REQ-Daemon1): pid, uptime, CPU, etc."""
    sock = ask_ipc.socket_path(index_dir)
    try:
        resp = ask_ipc.send_request(sock, {"op": "stats"}, timeout=3.0)
    except (OSError, ValueError) as exc:  # no socket / no daemon
        return (f"gpt ask · no warm daemon running for {index_dir} "
                f"({type(exc).__name__}). Start one: gpt ask-serve")
    if not resp.get("ok"):
        return f"gpt ask · daemon error: {resp.get('error')}"
    import datetime as _dt

    def _fmt_ts(ts):
        if not ts:
            return "?"
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    lines = ["gpt ask · warm daemon status",
             f"  pid             {resp.get('pid')}",
             f"  started         {_fmt_ts(resp.get('started'))}",
             f"  uptime          {resp.get('uptime_s', 0):.0f}s",
             f"  active engine   {resp.get('engine') or '(none yet)'}",
             f"  active model    {resp.get('model') or '(none)'}",
             f"  token budget    {resp.get('num_ctx') or '?'} ctx",
             f"  requests served {resp.get('served', 0)}",
             f"  time in answers {resp.get('answer_s', 0.0):.1f}s",
             f"  CPU used        {resp.get('cpu_s', 0.0):.1f}s",
             f"  index chunks    {resp.get('n_chunks', 0):,}"]
    history = resp.get("history") or []
    if history:
        lines.append("  recent requests (newest last):")
        for h in history[-10:]:
            lines.append(f"    {_fmt_ts(h.get('ts'))} · {h.get('route', '?'):9} "
                         f"· {h.get('engine', '?'):8} · "
                         f"{h.get('elapsed_ms', 0):.0f}ms · {h.get('q', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt ask",
        description="Answer a question from your chats (semantic, local, cited).")
    ap.add_argument("question", nargs="*",
                    help="The question to answer (omit for --list-models / "
                         "--stats).")
    ap.add_argument("--k", type=int, default=8,
                    help="Number of transcript chunks to retrieve (default 8).")
    ap.add_argument("--provider", default=None,
                    help="Force a synthesis provider (default: auto-route). A "
                         "cloud provider still needs --scrub-cloud.")
    ap.add_argument("--model", default=None,
                    help="Synthesis model (default: config ollama.model).")
    ap.add_argument("--host", default=None, help="Ollama host override.")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window for local synthesis (default: config).")
    ap.add_argument("--num-predict", type=int, default=None,
                    help="Max tokens to generate for the answer (local synthesis; "
                         "default: config ask.num_predict or 384). A tight cap "
                         "keeps a warm answer inside the 15s target (FR-Q16).")
    ap.add_argument("--no-stream", dest="stream", action="store_false",
                    default=True,
                    help="Disable token streaming for local synthesis. Streaming "
                         "(default, on a TTY) shows the answer as it is generated "
                         "for lower perceived latency; --json is always buffered.")
    ap.add_argument("--budget", type=float, default=None,
                    help="Wall-clock budget in seconds for synthesis (default: "
                         "config ask.budget_s or 60). Exceeding it aborts and "
                         "reports unusable; --budget 15 proves the interactive "
                         "target on the best route; --budget 0 disables the "
                         "abort (indicator only).")
    # REQ-6 — GPU hard-block for local Ollama (default on; --allow-cpu opts out).
    gpu = ap.add_mutually_exclusive_group()
    gpu.add_argument("--require-gpu", dest="require_gpu", action="store_true",
                     default=True,
                     help="Refuse local Ollama unless it is GPU-resident "
                          "(default).")
    gpu.add_argument("--allow-cpu", dest="require_gpu", action="store_false",
                     help="Permit local Ollama on CPU (slow; disables the GPU "
                          "hard-block).")
    # REQ-7 — capability router (default on; --no-route forces explicit provider).
    route = ap.add_mutually_exclusive_group()
    route.add_argument("--route", dest="route", action="store_true", default=True,
                       help="Auto-route to the most capable available engine "
                            "(default).")
    route.add_argument("--no-route", dest="route", action="store_false",
                       help="Disable routing; use only --provider/--model.")
    ap.add_argument("--prefer", default=None,
                    help="Preferred cloud engine order when no local GPU, "
                         "comma-separated (e.g. claude,codex,cursor).")
    ap.add_argument("--half-life", type=float, default=emb.DEFAULT_HALF_LIFE_DAYS,
                    help="Recency half-life in days (0 disables decay).")
    ap.add_argument("--per-chat", type=int, default=3,
                    help="Max chunks admitted per chat (diversity cap; 0 = off). "
                         "Stops one long chat from flooding the top-K.")
    ap.add_argument("--no-entity-route", action="store_true",
                    help="Disable deterministic version-superlative answers from "
                         "the entity index (force retrieval + synthesis).")
    ap.add_argument("--since", default=None,
                    help="Only consider chats updated on/after YYYY-MM-DD.")
    ap.add_argument("--show-context", action="store_true",
                    help="Print the retrieved excerpts before the answer.")
    ap.add_argument("--show-sources", dest="show_sources", action="store_true",
                    help="Show the cited Sources list (chat title + id + char "
                         "span) that back the answer. Hidden by default.")
    # Back-compat alias for the former flag name; hidden from help.
    ap.add_argument("--details", dest="show_sources", action="store_true",
                    help=argparse.SUPPRESS)
    ap.add_argument("--rerank", action="store_true",
                    help="Blend a lexical-overlap re-rank into retrieval for "
                         "sharper precision on the top-K.")
    ap.add_argument("--json", action="store_true",
                    help="Emit a JSON object (answer + sources) for scripting.")
    ap.add_argument("--scrub-cloud", action="store_true",
                    help="Let your chat data leave THIS computer to get an "
                         "answer: it blanks out personal info (names, emails, "
                         "file paths, keys) and then lets a cloud/CLI model "
                         "(Claude/Codex/Cursor, over the internet) answer. "
                         "Off (default) = your data never leaves your machine "
                         "(local Ollama only).")
    ap.add_argument("--list-models", action="store_true",
                    help="List the model bank with a ready-to-paste `gpt ask` "
                         "command for each, then exit.")
    ap.add_argument("--stats", action="store_true",
                    help="Show the warm daemon's status (pid, uptime, CPU, "
                         "requests, history), then exit.")
    # Warm daemon (gpt ask-serve) controls. DEFAULT: ON. One shared daemon holds
    # the index/embedder/entities warm (and a warm CLI engine when a cloud route
    # is used), so the heavy ~1.5s+ cold-start is paid ONCE, not per question.
    # `gpt ask` auto-starts it if missing and reuses it thereafter; its one-time
    # startup is EXCLUDED from the answer's time budget. Use --no-daemon to
    # answer fully in-process instead.
    ap.add_argument("--no-daemon", action="store_true",
                    help="Do not use the warm daemon; answer in-process "
                         "(slower cold-start, but self-contained).")
    ap.add_argument("--daemon", action="store_true",
                    help="Require an ALREADY-running daemon; error if none is "
                         "serving (do not auto-start).")
    ap.add_argument("--auto-serve", action="store_true",
                    help="(Deprecated; now the default.) Start the warm daemon "
                         "if none is running, then use it.")
    ap.add_argument("--engine", default=None,
                    help="Warm CLI engine the daemon uses for cloud routes "
                         "(claude|codex; default: config ask.engine).")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(argv)

    cfg = paths.load_config()

    # --list-models: print the bank + a ready-to-paste command per model, exit.
    if args.list_models:
        print(format_model_commands(cfg))
        return 0

    run_label = paths.resolve_run_label(args.run_label)
    index_dir = paths.index_dir(run_label=run_label)

    # --stats: report the warm daemon's status (pid, uptime, CPU, history), exit.
    if args.stats:
        print(daemon_stats_report(index_dir))
        return 0

    question = " ".join(args.question).strip()
    if not question:
        print("[error] empty question", file=sys.stderr)
        return 2

    import datetime as _datetime
    import time as _time
    start_dt = _datetime.datetime.now()
    t_start = _time.monotonic()

    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[error] numpy is required for `gpt ask`. Run: bash setup.sh",
              file=sys.stderr)
        return 1

    # Display defaults for the bottom status line: the synthesis model and the
    # interactive token budget (`num_predict`, NOT the context window) `ask` is
    # configured to use. Shown on every path — a deterministic route reports
    # `0 tok` so it is obvious no model was called (FR-Q19).
    _oll = cfg.get("ollama") or {}
    _ask_cfg = cfg.get("ask") or {}
    disp_model = (args.model or _ask_cfg.get("model") or _oll.get("model")
                  or "gpt-oss:20b")
    token_budget = (args.num_predict or _ask_cfg.get("num_predict")
                    or DEFAULT_ASK_NUM_PREDICT)

    def emit_status(model: str | None = disp_model,
                    used_tokens: int | None = None,
                    budget: int | None = None) -> None:
        sys.stdout.flush()
        print(status_line(t_start, model=model, used_tokens=used_tokens,
                          token_budget=budget, where="in-process"),
              file=sys.stderr)

    # Warm-daemon routing (thin client). DEFAULT: ON — one shared daemon is
    # auto-started if missing and reused thereafter. Its one-time startup is
    # EXCLUDED from the answer budget (we reset the clock after it is ready).
    # --no-daemon answers in-process; --daemon requires an already-running one.
    sock = ask_ipc.socket_path(index_dir)
    ping = None
    started_note: str | None = None
    if not args.no_daemon:
        ping = ask_ipc.ping(sock)
        if ping is None and args.daemon:
            print(f"[error] --daemon requested but none is serving {sock}. "
                  f"Start one with `gpt ask-serve`.", file=sys.stderr)
            return 2
        if ping is None and load_index(index_dir) is not None:
            # Auto-start (default). Fast-fail if there is no index to serve.
            engine = args.engine or (cfg.get("ask") or {}).get("engine")
            # Notify (the model that will serve) + animate a spinner so the
            # ~10-15s one-time cold start reads as "working", not "hung" (FR-Q19).
            print(uio.context_line(
                "gpt ask", f"starting warm daemon… model {disp_model}"
                + (f", engine {engine}" if engine else "")), file=sys.stderr)
            with working_indicator(f"starting warm daemon (model {disp_model})…"):
                ok, startup_s = ensure_daemon(index_dir, engine=engine,
                                              run_label=run_label)
            if ok:
                ping = ask_ipc.ping(sock)
                started_note = (f"warm daemon ready in {startup_s:.1f}s · "
                                f"model {disp_model} "
                                f"(one-time; excluded from budget)")
            else:
                print("[warn] could not start the warm daemon; answering "
                      "in-process", file=sys.stderr)
    if ping is not None:
        if started_note:
            print(uio.context_line("gpt ask", started_note), file=sys.stderr)
        # Exclude daemon startup from the answer clock: reset just before send.
        return answer_via_daemon(sock, question, args, start_dt,
                                 _time.monotonic(), token_budget)

    idx = load_index(index_dir)
    if idx is None:
        # No embeddings yet: degrade to a keyword scan rather than error out, so
        # `gpt ask` still surfaces the most relevant chats (FR-Q follow-up).
        fb = keyword_fallback(question, run_label, args.k)
        note = (f"No semantic index at {index_dir}; answered by keyword scan. "
                f"Build the index for grounded answers:  gpt index")
        if args.json:
            print(json.dumps({"question": question, "answer": None,
                              "mode": "keyword_fallback", "note": note,
                              "sources": fb}, ensure_ascii=False, indent=2))
            return 0
        print(f"[warn] {note}", file=sys.stderr)
        if not fb:
            print("No chats matched those keywords either. Run: gpt index",
                  file=sys.stderr)
            return 1
        for s in fb:
            snip = (s.get("snippet") or "").strip()
            print(f"  [{s['n']}] {s['title']} · {s.get('update_date') or '—'} · "
                  f"id={s['chat_id']}")
            if snip:
                print(f"      … {snip[:160]}")
        return 0

    # R6 intent routing: a version-superlative question ("newest / latest stable
    # version?") is a fact about the whole catalog, not a passage — answer it
    # deterministically from the entity index with a citation, before involving
    # the language model. Local, no data egress, repeatable.
    if not args.no_entity_route:
        routed = ent.route_answer(question, ent.load_entities(index_dir))
        if routed:
            sources = source_for_chat(idx, routed.get("chat_id"))
            if args.json:
                print(json.dumps({
                    "question": question, "answer": routed["answer"],
                    "route": "entity", "intent": routed.get("intent"),
                    "version": routed.get("version"),
                    "expansion": routed.get("expansion"), "sources": sources,
                }, ensure_ascii=False, indent=2))
                return 0
            print(routed["answer"])
            if args.show_sources and sources:
                print(format_sources(sources, reference_note(routed)))
            emit_status(model="entity", used_tokens=0)
            return 0

    # REQ-6/REQ-7: decide provider/model (forced → local GPU → cloud → fail).
    # Done before embedding so the cloud privacy gate trips before any egress.
    status, a, b, c, route_note = resolve_route(args, cfg)
    if status == "error":
        if b:  # b is the user-facing error message on the error path
            print(f"[error] {b}", file=sys.stderr)
        return a  # rc
    provider_name, model_override, is_local = a, b, c
    if route_note:
        print(uio.context_line("gpt ask", route_note), file=sys.stderr)

    embed_model = idx["manifest"].get("embed_model")
    try:
        qvec = emb.embed_one(question, model=embed_model, host=args.host)
    except emb.EmbeddingError as e:
        print(f"[error] could not embed the question: {e}", file=sys.stderr)
        return 1

    # F4: keep the index current by design rather than nagging the user. A small
    # delta is healed inline (incremental: only the new chats are embedded); a
    # large one is deferred to an explicit `gpt index` so we never stall the
    # interactive path. `gpt run`/`gpt all` already index after each build, so
    # this rarely fires.
    delta = index_delta(idx, run_label)
    if delta > 0:
        if delta <= AUTO_REFRESH_MAX_DELTA:
            with working_indicator(f"refreshing index (+{delta} chats)…"):
                fresh = auto_refresh_index(index_dir, run_label, embed_model,
                                           args.host)
            if fresh is not None:
                idx = fresh
                print(uio.context_line("gpt ask",
                                       f"refreshed index (+{delta} new chats)"),
                      file=sys.stderr)
        else:
            print(uio.context_line("gpt ask",
                                   f"index covers {delta} fewer chats than the "
                                   f"catalog; run `gpt index` to include them"),
                  file=sys.stderr)

    hits = retrieve(qvec, idx["vectors"], idx["chunks"], k=args.k,
                    half_life_days=args.half_life, since=args.since,
                    per_chat=args.per_chat)
    if args.rerank:
        hits = lexical_rerank(question, hits)
    if not hits:
        # REQ-Output2: nothing retrieved → no guessing, the fixed sentinel.
        if args.json:
            print(json.dumps({"question": question, "answer": NOT_FOUND_MSG,
                              "not_found": True, "sources": []},
                             ensure_ascii=False, indent=2))
            return 0
        print(NOT_FOUND_MSG)
        emit_status(model="not found", used_tokens=0)
        return 0

    system, prompt, sources = build_prompt(question, hits)

    if args.show_context:
        print(uio.context_line("gpt ask", f"{len(hits)} excerpts",
                               f"{len(sources)} chats"))
        for h in hits:
            print(f"\n--- score {h['score']:.3f} (sim {h['sim']:.3f}) · "
                  f"{h.get('title')} · {h.get('update_date')} · "
                  f"id={h.get('chat_id')}")
            print((h.get("text") or "")[:500])
        print()

    n_findings = 0
    if not is_local:
        system, sf = redact.scrub(system)
        prompt, pf = redact.scrub(prompt)
        n_findings = len(sf) + len(pf)

    import math
    import time as _time
    from providers import get_provider, ProviderError

    # REQ-5: the budget no longer hard-defaults to 15s. The default (60s) lets a
    # slower model finish; `--budget 15` proves the interactive target on the
    # best route; `--budget 0` disables the abort entirely (indicator only). We
    # fail fast (max_retries=1) so an over-budget model is reported UNUSABLE.
    oll = cfg.get("ollama") or {}
    ask_cfg = cfg.get("ask") or {}
    budget = (args.budget if args.budget is not None
              else (ask_cfg.get("budget_s") or DEFAULT_BUDGET_S))
    no_abort = budget is not None and budget <= 0
    timeout = 86400 if no_abort else max(1, math.ceil(budget))
    model_name = (model_override or args.model
                  or (ask_cfg.get("model") or oll.get("model") if is_local else None)
                  or ("gpt-oss:20b" if is_local else ""))
    prov_kwargs: dict = {"model": model_name, "timeout": timeout, "max_retries": 1}
    if is_local:
        prov_kwargs["host"] = args.host or ask_cfg.get("host") or oll.get("host")
        prov_kwargs["num_ctx"] = (args.num_ctx or ask_cfg.get("num_ctx")
                                  or DEFAULT_ASK_NUM_CTX)
        prov_kwargs["num_predict"] = (args.num_predict or ask_cfg.get("num_predict")
                                      or DEFAULT_ASK_NUM_PREDICT)
    num_predict_disp = prov_kwargs.get("num_predict")
    disp = (model_name if is_local else
            (f"{provider_name}:{model_name}" if model_name else provider_name))
    budget_label = "∞" if no_abort else f"{budget:g}s"

    print(uio.context_line("gpt ask", f"synthesizing with {disp}",
                           f"budget {budget_label}",
                           f"target {LATENCY_TARGET_S:g}s"), file=sys.stderr)
    # FR-Q16: stream local synthesis to the terminal for lower perceived latency.
    # Only on an interactive TTY and never for --json (machine output stays a
    # single buffered object, byte-identical to before).
    use_stream = (is_local and getattr(args, "stream", True) and not args.json
                  and sys.stdout.isatty())
    streamed = False
    out_tokens: int | None = None
    t_synth = _time.monotonic()
    try:
        provider = get_provider(provider_name, **prov_kwargs)
        if use_stream:
            print(uio.context_line("gpt ask", "streaming answer…"),
                  file=sys.stderr)
            text, _stream_nf, out_tokens = stream_local_answer(
                provider, system, prompt, budget=budget, no_abort=no_abort,
                t0=t_synth)
            streamed = True
        else:
            with working_indicator(f"synthesizing with {disp}…"):
                text, _usage = provider.complete(system, prompt, json_mode=False)
            out_tokens = _usage.output_tokens if _usage is not None else None
    except ProviderError as e:
        elapsed = _time.monotonic() - t_synth
        if not no_abort and _looks_like_timeout(e, elapsed, budget):
            print(f"[unusable] {disp} exceeded the {budget:g}s budget "
                  f"({elapsed:.1f}s) — too slow for interactive ask. Try "
                  f"--budget N, a faster route (--prefer), or the warm daemon "
                  f"(gpt ask-serve).", file=sys.stderr)
            if args.show_sources:
                print(format_sources(sources), file=sys.stderr)
            emit_status(model=disp, used_tokens=None, budget=num_predict_disp)
            return EXIT_UNUSABLE
        print(f"[error] synthesis failed: {e}", file=sys.stderr)
        # Sources are the useful fallback so the user can read the chats; show
        # them with --show-sources (consistent with the normal output).
        if args.show_sources:
            print(format_sources(sources), file=sys.stderr)
        emit_status(model=disp, used_tokens=None, budget=num_predict_disp)
        return 1

    # REQ-Output2: a non-grounded "couldn't find it" reply (from any provider)
    # collapses to the fixed sentinel with no sources — never a freelance guess.
    not_found = is_not_found(text)
    answer_out = NOT_FOUND_MSG if not_found else text.strip()

    if args.json:
        print(json.dumps({
            "question": question,
            "answer": answer_out,
            "not_found": not_found,
            "provider": provider_name,
            "model": model_name or None,
            "route": route_note,
            "scrubbed_pii": n_findings if not is_local else 0,
            "output_tokens": out_tokens,
            "num_predict": num_predict_disp,
            "sources": [] if not_found else sources,
        }, ensure_ascii=False, indent=2))
        return 0

    if not is_local and n_findings:
        print(uio.context_line("gpt ask",
                               f"scrubbed {n_findings} PII match(es) before "
                               f"{provider_name}"))
    if streamed:
        # The real answer was already streamed to stdout; only a not-found
        # collapse still needs the sentinel printed here (FR-Q8).
        if not_found:
            print(answer_out)
    else:
        print(answer_out)
    if args.show_sources and not not_found:
        print(format_sources(sources))
    emit_status(model=disp, used_tokens=out_tokens, budget=num_predict_disp)
    return 0


if __name__ == "__main__":
    import interrupt
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt ask"))
