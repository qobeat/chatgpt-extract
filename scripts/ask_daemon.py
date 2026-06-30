#!/usr/bin/env python3
"""
gpt ask-serve — one warm, router-aware `ask` daemon for interactive latency.

Every `gpt ask` is otherwise a cold process: ~1.5s just to boot Python, load the
~160MB index, embed, and retrieve — *before* the model is even called, and the
CLI models pay another 2-12s of their own cold-start on top. This single shared
daemon pays all of that once and keeps it resident:

  - the semantic index (vectors + chunks) in RAM,
  - a warmed embedder (the first query model-load is amortised),
  - the entity index for deterministic version answers,
  - the capability ROUTER ([scripts/lib/ask_route.py](scripts/lib/ask_route.py)),
    so it serves BOTH the local Ollama model and the cloud engines
    (codex/claude/cursor) and switches the active model on demand,
  - at most ONE warm CLI engine ([scripts/lib/warm_engine.py](scripts/lib/warm_engine.py))
    at a time (started/stopped when the routed engine changes).

`gpt ask` then becomes a thin client over a unix socket
([scripts/lib/ask_ipc.py](scripts/lib/ask_ipc.py)); the daemon is the default
execution surface. It is single-instance (refuses to start twice on one index),
self-exits after an idle period, never generates in the background (no idle token
cost), and keeps each request self-contained (no cross-question token bleed).

  gpt ask-serve                      # foreground, default engine, default index
  gpt ask-serve --engine codex       # warm CLI engine used for cloud routes
  gpt ask-serve --idle-timeout 0     # never auto-exit
  gpt ask --stats                    # client: print this daemon's status
  gpt ask --no-daemon                # client: bypass the daemon (in-process)

Security: a warm CLI engine is locked to text-only / read-only (no file edits, no
shell), and the socket is a local file in the index dir (no network surface).
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time
from collections import deque

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))

import ask  # noqa: E402  (reuse retrieval/prompt/route/not-found helpers)
import ask_ipc  # noqa: E402
import ask_route  # noqa: E402
import embeddings as emb  # noqa: E402
import entities as ent  # noqa: E402
import paths  # noqa: E402
import redact  # noqa: E402
from providers import ProviderError, get_provider  # noqa: E402
from warm_engine import WarmEngineError, get_engine  # noqa: E402

# Engines that benefit from a persistent warm subprocess (CLI cold-start). All
# other routes (local Ollama, cursor/openai/anthropic) call the provider
# directly — Ollama keeps the model resident itself.
WARM_ENGINES = frozenset({"claude", "codex"})


class DaemonState:
    """Everything held warm for the lifetime of the daemon + live stats."""

    def __init__(self, idx, entities, embed_model, host, defaults,
                 cfg=None, default_engine=None):
        self.idx = idx
        self.entities = entities
        self.embed_model = embed_model
        self.host = host
        self.defaults = defaults
        self.cfg = cfg or {}
        self.default_engine = (default_engine or "").lower() or None
        self.lock = threading.Lock()  # single-flight synthesis
        self.rec_lock = threading.Lock()  # guards stats writes (FR-Q18 threads)
        # At most one warm CLI engine resident at a time; switched on demand.
        self.active = None            # WarmEngine instance or None
        self.active_key = None        # (engine_name, model)
        # Live stats (REQ-Daemon1).
        self.started = time.time()
        self.served = 0
        self.answer_s = 0.0
        self.last_route = None
        self.last_model = None
        self.history: deque = deque(maxlen=50)

    # --- warm-engine lifecycle (model switching) ---------------------------
    def warm_engine_for(self, name: str, model: str | None):
        """Return a warm engine for (name, model), switching if it changed.

        Only one warm CLI engine is resident; routing to a different engine or
        model stops the previous one first (so "one daemon for all models").
        """
        key = (name, model)
        if self.active is not None and self.active_key == key and self.active.alive():
            return self.active
        if self.active is not None:
            try:
                self.active.close()
            except Exception:
                pass
            self.active = None
            self.active_key = None
        eng = get_engine(name, model=model)
        ok, msg = eng.preflight()
        if not ok:
            raise WarmEngineError(f"engine '{name}' unavailable: {msg}")
        eng.start()
        self.active = eng
        self.active_key = key
        return eng

    def active_name(self) -> str | None:
        if self.active is not None:
            return self.active.name
        return self.default_engine

    def cpu_seconds(self) -> float:
        t = os.times()
        return float(t.user + t.system + t.children_user + t.children_system)

    def close_engines(self) -> None:
        if self.active is not None:
            try:
                self.active.close()
            except Exception:
                pass
            self.active = None
            self.active_key = None


def _now_ms(t0: float) -> float:
    return round((time.monotonic() - t0) * 1000, 1)


def _route_args(req: dict):
    """A minimal argparse-like namespace so we can reuse ask.resolve_route."""
    import types
    return types.SimpleNamespace(
        provider=req.get("provider"),
        model=req.get("model"),
        host=req.get("host"),
        route=bool(req.get("route", True)),
        require_gpu=bool(req.get("require_gpu", True)),
        prefer=req.get("prefer"),
        scrub_cloud=bool(req.get("scrub_cloud", False)),
    )


def _synthesize(state: DaemonState, provider_name: str, model: str | None,
                is_local: bool, system: str, prompt: str, budget: float,
                num_ctx: int | None) -> tuple[str, str]:
    """Run one synthesis and return (text, engine_label). Raises on failure.

    Warm CLI engines (claude/codex) go through the resident warm engine (and are
    switched on demand); everything else uses a direct provider call.
    """
    no_abort = budget is not None and budget <= 0
    if provider_name in WARM_ENGINES:
        eng = state.warm_engine_for(provider_name, model)
        timeout = 86400.0 if no_abort else float(budget)
        text, _info = eng.complete(system, prompt, timeout=timeout)
        return (text or "").strip(), eng.name
    # Direct provider (local Ollama, or cursor/openai/anthropic).
    import math
    timeout = 86400 if no_abort else max(1, math.ceil(budget))
    kwargs: dict = {"model": model or "", "timeout": timeout, "max_retries": 1}
    if is_local:
        kwargs["model"] = model or "gpt-oss:20b"
        kwargs["host"] = state.host
        kwargs["num_ctx"] = num_ctx or ask.DEFAULT_ASK_NUM_CTX
    provider = get_provider(provider_name, **kwargs)
    text, _usage = provider.complete(system, prompt, json_mode=False)
    return (text or "").strip(), provider_name


def handle_ask(req: dict, state: DaemonState) -> dict:
    """Run retrieval + (route|synthesise) for one question, with the not-found
    contract and the privacy/GPU gate enforced server-side (warm)."""
    question = (req.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "empty question"}
    d = state.defaults
    k = int(req.get("k") or d["k"])
    per_chat = int(req.get("per_chat", d["per_chat"]))
    half_life = float(req.get("half_life", d["half_life"]))
    since = req.get("since") or None
    rerank = bool(req.get("rerank", d["rerank"]))
    budget = float(req.get("budget") if req.get("budget") is not None
                   else d["budget"])
    route_ok = not req.get("no_entity_route")

    t_all = time.monotonic()
    timings: dict[str, float] = {}

    # 1) Deterministic answer (version superlative or acronym) — no model, no
    # route decision (so an entity question never needs a GPU or cloud engine).
    if route_ok:
        routed = ent.route_answer(question, state.entities)
        if routed:
            sources = ask.source_for_chat(state.idx, routed.get("chat_id"))
            return {"ok": True, "answer": routed["answer"], "route": "entity",
                    "intent": routed.get("intent"),
                    "version": routed.get("version"),
                    "expansion": routed.get("expansion"),
                    "mentions": routed.get("mentions"),
                    "n_chats": routed.get("n_chats"),
                    "sources": sources, "engine": "entity",
                    "provider": "entity", "model": None, "not_found": False,
                    "elapsed_ms": _now_ms(t_all), "timings": timings}

    # 2) Embed + retrieve.
    t0 = time.monotonic()
    try:
        qvec = emb.embed_one(question, model=state.embed_model, host=state.host)
    except emb.EmbeddingError as e:
        return {"ok": False, "error": f"embed failed: {e}"}
    timings["embed_ms"] = _now_ms(t0)

    t0 = time.monotonic()
    hits = ask.retrieve(qvec, state.idx["vectors"], state.idx["chunks"], k=k,
                        half_life_days=half_life, since=since, per_chat=per_chat)
    if rerank:
        hits = ask.lexical_rerank(question, hits)
    timings["retrieve_ms"] = _now_ms(t0)
    if not hits:
        # REQ-Output2: nothing retrieved → the fixed sentinel, no guessing.
        return {"ok": True, "answer": ask.NOT_FOUND_MSG, "not_found": True,
                "route": "synthesis", "sources": [], "engine": None,
                "provider": None, "model": None, "elapsed_ms": _now_ms(t_all),
                "timings": timings}

    # 3) Resolve the route (privacy/GPU gate, warm). Errors carry an rc the
    # client mirrors, so a daemon answer behaves exactly like in-process.
    status, a, b, c, route_note = ask.resolve_route(_route_args(req), state.cfg)
    if status == "error":
        return {"ok": False, "rc": int(a), "error": b}
    provider_name, model_override, is_local = a, b, c

    system, prompt, sources = ask.build_prompt(question, hits)
    n_findings = 0
    if not is_local:
        system, sf = redact.scrub(system)
        prompt, pf = redact.scrub(prompt)
        n_findings = len(sf) + len(pf)

    ask_cfg = state.cfg.get("ask") or {}
    oll = state.cfg.get("ollama") or {}
    model_name = (model_override or req.get("model")
                  or (ask_cfg.get("model") or oll.get("model") if is_local
                      else None)
                  or ("gpt-oss:20b" if is_local else None))
    num_ctx = (req.get("num_ctx") or ask_cfg.get("num_ctx")
               or ask.DEFAULT_ASK_NUM_CTX)

    # 4) Synthesis (single-flight) under the budget.
    t0 = time.monotonic()
    with state.lock:
        try:
            text, engine_label = _synthesize(
                state, provider_name, model_name, is_local, system, prompt,
                budget, num_ctx)
        except (WarmEngineError, ProviderError) as e:
            timings["synth_ms"] = _now_ms(t0)
            elapsed = (time.monotonic() - t0)
            unusable = (budget and budget > 0
                        and ask._looks_like_timeout(e, elapsed, budget))
            return {"ok": True, "unusable": bool(unusable),
                    "answer": None, "not_found": False, "route": "synthesis",
                    "sources": sources, "provider": provider_name,
                    "model": model_name, "engine": provider_name,
                    "error": str(e), "route_note": route_note,
                    "elapsed_ms": _now_ms(t_all), "timings": timings,
                    "budget_s": budget}
    timings["synth_ms"] = _now_ms(t0)

    not_found = ask.is_not_found(text)
    return {"ok": True, "answer": ask.NOT_FOUND_MSG if not_found else text,
            "not_found": not_found, "route": "synthesis",
            "sources": [] if not_found else sources,
            "provider": provider_name, "model": model_name,
            "engine": engine_label, "route_note": route_note,
            "scrubbed_pii": n_findings, "elapsed_ms": _now_ms(t_all),
            "timings": timings}


def _ping_payload(state: DaemonState) -> dict:
    return {"ok": True, "pid": os.getpid(), "engine": state.active_name(),
            "model": state.last_model,
            "n_chunks": len(state.idx["chunks"]),
            "served": state.served,
            "uptime_s": round(time.time() - state.started, 1)}


def _stats_payload(state: DaemonState) -> dict:
    return {"ok": True, "pid": os.getpid(), "started": state.started,
            "uptime_s": round(time.time() - state.started, 1),
            "engine": state.active_name(), "model": state.last_model,
            "num_ctx": (state.cfg.get("ask") or {}).get("num_ctx")
            or ask.DEFAULT_ASK_NUM_CTX,
            "served": state.served, "answer_s": round(state.answer_s, 2),
            "cpu_s": round(state.cpu_seconds(), 2),
            "n_chunks": len(state.idx["chunks"]),
            "history": list(state.history)}


def _record(state: DaemonState, question: str, resp: dict) -> None:
    # FR-Q18: connections are now handled on worker threads, so the stats writes
    # are serialised under a dedicated lock (cheap, never held during synthesis).
    with state.rec_lock:
        state.served += 1
        state.answer_s += (resp.get("elapsed_ms") or 0.0) / 1000.0
        state.last_route = resp.get("route")
        if resp.get("model"):
            state.last_model = resp.get("model")
        state.history.append({
            "ts": time.time(), "route": resp.get("route") or "?",
            "engine": resp.get("engine") or resp.get("provider") or "?",
            "elapsed_ms": resp.get("elapsed_ms") or 0.0,
            # Truncated, non-sensitive label only (no full prompt/answer stored).
            "q": (question[:60] + "…") if len(question) > 60 else question,
        })


def _handle_conn(conn: socket.socket, state: DaemonState,
                 stop: dict) -> None:
    """Serve ONE connection (on its own thread). Cheap ops (ping/stats/shutdown)
    answer immediately even while a synthesis holds the single-flight lock on
    another thread — no head-of-line blocking (FR-Q18)."""
    import json
    with conn:
        conn.settimeout(120)
        try:
            line = ask_ipc.read_line(conn)
            if line is None:
                return
            req = json.loads(line)
        except (ValueError, OSError):
            return
        op = req.get("op", "ask")
        try:
            if op == "ping":
                ask_ipc.write_line(conn, _ping_payload(state))
            elif op == "stats":
                ask_ipc.write_line(conn, _stats_payload(state))
            elif op == "shutdown":
                stop["flag"] = True
                ask_ipc.write_line(conn, {"ok": True, "shutting_down": True})
            else:
                try:
                    resp = handle_ask(req, state)
                except Exception as e:  # never let one bad request kill us
                    resp = {"ok": False, "error": f"{type(e).__name__}: {e}"}
                if resp.get("ok"):
                    _record(state, (req.get("question") or ""), resp)
                ask_ipc.write_line(conn, resp)
        except OSError:
            # Client hung up before we replied — nothing to do.
            return


def serve(state: DaemonState, sock_path: str, idle_timeout: float) -> int:
    """Accept loop on a unix socket; each connection is handled on its own
    thread so synthesis (single-flight via `state.lock`) never blocks ping/stats/
    shutdown (FR-Q18). Returns an exit code."""
    if os.path.exists(sock_path):
        os.unlink(sock_path)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path)
    srv.listen(32)
    os.chmod(sock_path, 0o600)  # owner-only (defense in depth)
    # Always poll at ≤1s so the stop flag and idle timeout stay responsive
    # regardless of the configured idle window.
    srv.settimeout(1.0)

    stop = {"flag": False}

    def _sig(_signum, _frame):
        stop["flag"] = True
    try:
        signal.signal(signal.SIGTERM, _sig)
        signal.signal(signal.SIGINT, _sig)
    except ValueError:
        # signal.signal only works on the main thread; tests drive serve() from
        # a worker thread and rely on the {op:shutdown} message instead.
        pass

    print(f"gpt ask-serve · engine={state.active_name()} · "
          f"{len(state.idx['chunks'])} chunks · socket {sock_path}",
          file=sys.stderr, flush=True)

    last_active = time.monotonic()
    workers: list[threading.Thread] = []
    try:
        while not stop["flag"]:
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                if idle_timeout and (time.monotonic() - last_active) > idle_timeout:
                    print("gpt ask-serve · idle timeout, exiting", file=sys.stderr)
                    break
                continue
            except OSError:
                break
            last_active = time.monotonic()
            t = threading.Thread(target=_handle_conn, args=(conn, state, stop),
                                 daemon=True)
            t.start()
            workers.append(t)
            workers = [w for w in workers if w.is_alive()]
    finally:
        try:
            srv.close()
            if os.path.exists(sock_path):
                os.unlink(sock_path)
        except OSError:
            pass
        for w in workers:  # let in-flight answers drain briefly
            w.join(timeout=2)
        state.close_engines()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt ask-serve",
        description="Warm, router-aware `ask` daemon: holds index + embedder + "
                    "entities + a warm CLI engine, and routes per question.")
    ap.add_argument("--engine", default=None,
                    help="Warm CLI engine for cloud routes: claude (~2s) or "
                         "codex (~5s). Default: config ask.engine or claude.")
    ap.add_argument("--model", default=None, help="Engine model override.")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--per-chat", type=int, default=3)
    ap.add_argument("--half-life", type=float, default=emb.DEFAULT_HALF_LIFE_DAYS)
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--budget", type=float, default=None,
                    help="Per-question synthesis budget (s). Default config "
                         "ask.budget_s or 60.")
    ap.add_argument("--idle-timeout", type=float, default=900.0,
                    help="Self-exit after N idle seconds (0 = never).")
    ap.add_argument("--host", default=None, help="Ollama host for embedding.")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(argv)

    cfg = paths.load_config()
    ask_cfg = cfg.get("ask") or {}
    # The warm CLI engine the daemon will use for cloud routes (default claude).
    default_engine = (args.engine or ask_cfg.get("engine") or "claude").lower()
    budget = args.budget or ask_cfg.get("budget_s") or ask.DEFAULT_BUDGET_S

    run_label = paths.resolve_run_label(args.run_label)
    index_dir = paths.index_dir(run_label=run_label)
    idx = ask.load_index(index_dir)
    if idx is None:
        print(f"[error] no semantic index at {index_dir}. Run: gpt index",
              file=sys.stderr)
        return 1

    sock_path = ask_ipc.socket_path(index_dir)
    if ask_ipc.ping(sock_path) is not None:
        # Single-instance: never start twice on one index.
        print(f"[error] a daemon is already serving {sock_path}", file=sys.stderr)
        return 1

    embed_model = idx["manifest"].get("embed_model")
    host = args.host or (cfg.get("ollama") or {}).get("host")
    entities = ent.load_entities(index_dir)

    defaults = {"k": args.k, "per_chat": args.per_chat,
                "half_life": args.half_life, "rerank": args.rerank,
                "budget": budget}
    state = DaemonState(idx, entities, embed_model, host, defaults,
                        cfg=cfg, default_engine=default_engine)

    # Pre-warm the embedder so the first real query doesn't pay its load.
    try:
        emb.embed_one("warmup", model=embed_model, host=host)
    except emb.EmbeddingError as e:
        print(f"[warn] embedder warmup failed (continuing): {e}", file=sys.stderr)
    # Pre-warm the default CLI engine (pay its cold-start now) so a cloud route's
    # first question is already warm. Best-effort: a missing CLI is fine — local
    # routes don't need it, and cloud routes will surface the error on use.
    if default_engine in WARM_ENGINES:
        try:
            eng = state.warm_engine_for(default_engine, args.model)
            eng.complete("Reply with exactly: ok", "ok", timeout=30)
        except Exception as e:  # noqa: BLE001 - warmup is best-effort
            print(f"[warn] engine warmup failed (continuing): {e}",
                  file=sys.stderr)

    return serve(state, sock_path, args.idle_timeout)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
