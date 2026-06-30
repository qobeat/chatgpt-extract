"""Stress tests for the Ask feature + warm daemon — concurrency, abuse, latency.

Complements the functional `test_ask_daemon.py` / `test_ask_route.py` by hammering
the surfaces under load and with hostile input. Each case names the requirement
it exercises so a regression maps back to a contract.

Matrix (→ REQUIREMENTS.md):
  - FR-Q14  warm daemon: single-flight synthesis, request isolation (no cross-
            question bleed), survives malformed input, stats/history under load,
            and (FR-Q18) STAYS RESPONSIVE to ping/stats while a synthesis runs.
  - FR-Q8   not-found contract holds under concurrent no-hit questions.
  - FR-Q9   over-budget synthesis is reported unusable, never hangs.
  - FR-Q16  streaming guard is correct for arbitrary chunk boundaries.

All providers / engines are FAKED (no Ollama, no codex/claude, no network).
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ask  # noqa: E402
import ask_daemon  # noqa: E402
import ask_ipc  # noqa: E402
import embeddings as emb  # noqa: E402
from providers import ProviderError  # noqa: E402

LOCAL_ROUTE = ("ok", "ollama", None, True, "local Ollama (test)")


class EchoProvider:
    """Returns the question line from the prompt, so a response can be traced
    back to the request that produced it (bleed detector). Reports a token
    count so FR-Q19 accounting can be asserted under load."""

    def __init__(self, **kw):
        self.kw = kw

    def complete(self, system, prompt, json_mode=False):
        from providers import Usage
        first = prompt.splitlines()[0] if prompt else ""
        return (f"{first} — answer [1]", Usage(output_tokens=11))


class TimeoutProvider:
    def __init__(self, **kw):
        pass

    def complete(self, system, prompt, json_mode=False):
        raise ProviderError("ollama: timed out after 1s (no retry; VRAM spill)")


class SlowProvider:
    def __init__(self, **kw):
        pass

    def complete(self, system, prompt, json_mode=False):
        time.sleep(1.5)
        return ("slow but grounded [1]", None)


def _idx():
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    chunks = [
        {"chat_id": "c1", "title": "ADOS", "update_date": "2026-06-19",
         "start": 0, "end": 50, "text": "ADOS profile goals."},
        {"chat_id": "c2", "title": "Other", "update_date": "2026-06-18",
         "start": 0, "end": 50, "text": "Cooking notes."},
    ]
    return {"manifest": {"embed_model": "test"}, "vectors": vectors,
            "chunks": chunks}


def _state():
    defaults = {"k": 8, "per_chat": 3, "half_life": emb.DEFAULT_HALF_LIFE_DAYS,
                "rerank": False, "budget": 15}
    return ask_daemon.DaemonState(_idx(), {}, "test", None, defaults,
                                  cfg={"ask": {}}, default_engine="claude")


class _DaemonHarness:
    """Start `serve()` in a worker thread on a temp socket; tidy shutdown."""

    def __init__(self, state):
        self.tmp = tempfile.mkdtemp()
        self.sock = os.path.join(self.tmp, "ask.sock")
        self.state = state
        self.th = threading.Thread(target=ask_daemon.serve,
                                   args=(self.state, self.sock, 30), daemon=True)

    def __enter__(self):
        self.th.start()
        for _ in range(100):
            if ask_ipc.ping(self.sock) is not None:
                break
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        try:
            ask_ipc.send_request(self.sock, {"op": "shutdown"}, timeout=2)
        except OSError:
            pass
        self.th.join(timeout=5)


def _retry_request(sock, req, timeout=10.0, tries=20):
    """Client that retries connect (unix-socket backlog can refuse bursts)."""
    last = None
    for _ in range(tries):
        try:
            return ask_ipc.send_request(sock, req, timeout=timeout)
        except OSError as e:  # ECONNREFUSED under a connect burst
            last = e
            time.sleep(0.02)
    raise last  # pragma: no cover


class RequestIsolationTest(unittest.TestCase):
    """FR-Q14 — concurrent distinct questions never bleed into each other."""

    def test_concurrent_no_cross_question_bleed(self):
        state = _state()
        n = 48

        def one(i):
            return ask_daemon.handle_ask(
                {"question": f"MARKER{i:04d} tell me about ados",
                 "no_entity_route": True}, state)

        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=LOCAL_ROUTE), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: EchoProvider(**kw)):
            with ThreadPoolExecutor(max_workers=16) as ex:
                results = list(ex.map(one, range(n)))

        for i, r in enumerate(results):
            self.assertTrue(r["ok"], r)
            self.assertFalse(r["not_found"])
            self.assertIn(f"MARKER{i:04d}", r["answer"],
                          f"request {i} got another request's answer: {r['answer']!r}")
            # FR-Q19: accurate token accounting holds under concurrency — every
            # synthesis reports its output tokens and the interactive cap.
            self.assertEqual(r["tokens"], 11)
            self.assertEqual(r["num_predict"], ask.DEFAULT_ASK_NUM_PREDICT)


class NotFoundUnderLoadTest(unittest.TestCase):
    """FR-Q8 — every concurrent no-hit question collapses to the sentinel."""

    def test_concurrent_no_hits_all_not_found(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.retrieve", return_value=[]):
            def one(i):
                return ask_daemon.handle_ask(
                    {"question": f"xyzzy nonsense {i}", "no_entity_route": True},
                    state)
            with ThreadPoolExecutor(max_workers=12) as ex:
                results = list(ex.map(one, range(36)))
        self.assertTrue(all(r["not_found"] for r in results))
        self.assertTrue(all(r["answer"] == ask.NOT_FOUND_MSG for r in results))
        self.assertTrue(all(r["sources"] == [] for r in results))


class BudgetUnusableTest(unittest.TestCase):
    """FR-Q9 — a timed-out synthesis is flagged unusable, not hung."""

    def test_timeout_is_unusable(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=LOCAL_ROUTE), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: TimeoutProvider(**kw)):
            resp = ask_daemon.handle_ask(
                {"question": "tell me about ados", "no_entity_route": True}, state)
        self.assertTrue(resp["ok"])
        self.assertTrue(resp["unusable"])
        self.assertIsNone(resp["answer"])


class MalformedInputTest(unittest.TestCase):
    """FR-Q14 — a bad request must never take the daemon down."""

    def test_garbage_then_normal_request_survives(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=LOCAL_ROUTE), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: EchoProvider(**kw)), \
             _DaemonHarness(state) as h:
            import socket as _s
            # 1) non-JSON line
            c = _s.socket(_s.AF_UNIX, _s.SOCK_STREAM)
            c.connect(h.sock)
            c.sendall(b"this is not json\n")
            c.close()
            # 2) empty question
            r0 = _retry_request(h.sock, {"op": "ask", "question": "   "})
            self.assertFalse(r0["ok"])
            # 3) unknown op falls through to ask handler with no question
            r1 = _retry_request(h.sock, {"op": "frobnicate"})
            self.assertFalse(r1["ok"])
            # daemon is still alive and answers a real request
            r2 = _retry_request(h.sock, {"op": "ask", "question": "MARKER about ados",
                                         "no_entity_route": True})
            self.assertTrue(r2["ok"])
            self.assertIn("MARKER", r2["answer"])
            self.assertIsNotNone(ask_ipc.ping(h.sock))

    def test_oversized_line_raises_cleanly(self):
        import socket as _s
        a, b = _s.socketpair()
        try:
            a.sendall(b"x" * 100)  # no newline, ever
            with self.assertRaises(ValueError):
                ask_ipc.read_line(b, max_bytes=50)
        finally:
            a.close()
            b.close()


class StatsUnderLoadTest(unittest.TestCase):
    """FR-Q14 — served count is exact and history is bounded under load."""

    def test_served_count_and_history_cap(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=LOCAL_ROUTE), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: EchoProvider(**kw)), \
             _DaemonHarness(state) as h:
            n = 60

            def fire(i):
                return _retry_request(
                    h.sock, {"op": "ask", "question": f"MARKER{i} ados",
                             "no_entity_route": True})

            with ThreadPoolExecutor(max_workers=8) as ex:
                list(ex.map(fire, range(n)))
            stats = _retry_request(h.sock, {"op": "stats"})
            self.assertEqual(stats["served"], n)
            self.assertLessEqual(len(stats["history"]), 50)  # deque maxlen
            self.assertGreater(stats["answer_s"], -1)


class DaemonResponsivenessTest(unittest.TestCase):
    """FR-Q18 — a long synthesis must not block ping/stats (no HOL blocking)."""

    def test_ping_is_fast_during_slow_synthesis(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=LOCAL_ROUTE), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: SlowProvider(**kw)), \
             _DaemonHarness(state) as h:
            # Fire a 1.5s synthesis in the background.
            slow = threading.Thread(
                target=lambda: _retry_request(
                    h.sock, {"op": "ask", "question": "slow ados",
                             "no_entity_route": True}, timeout=10),
                daemon=True)
            slow.start()
            time.sleep(0.2)  # let the synthesis get going
            t0 = time.monotonic()
            pong = _retry_request(h.sock, {"op": "ping"}, timeout=5)
            elapsed = time.monotonic() - t0
            self.assertIsNotNone(pong)
            self.assertLess(elapsed, 0.8,
                            f"ping blocked {elapsed:.2f}s behind a slow synthesis "
                            "(head-of-line blocking; FR-Q18)")
            slow.join(timeout=5)


class SingleInstanceRaceTest(unittest.TestCase):
    """FR-Q20 — a second daemon on a live socket refuses; it never steals it."""

    def test_second_serve_refuses_and_first_survives(self):
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             _DaemonHarness(_state()) as h:
            # First daemon is live (harness already pinged it). A second serve()
            # on the same socket must refuse (exit 1), not unlink + rebind.
            rc = ask_daemon.serve(_state(), h.sock, 1)
            self.assertEqual(rc, 1)
            # The original daemon is still answering on the same socket.
            self.assertIsNotNone(ask_ipc.ping(h.sock))

    def test_stale_socket_is_reclaimed(self):
        # A socket file with no live owner (crashed daemon) must not block a
        # fresh start — serve() pings, finds nobody, and reclaims it.
        tmp = tempfile.mkdtemp()
        sock = os.path.join(tmp, "ask.sock")
        open(sock, "w").close()  # leftover file, nothing listening
        th = threading.Thread(target=ask_daemon.serve,
                              args=(_state(), sock, 30), daemon=True)
        th.start()
        try:
            ok = any(ask_ipc.ping(sock) is not None or time.sleep(0.05)
                     for _ in range(100))
            self.assertIsNotNone(ask_ipc.ping(sock))
        finally:
            try:
                ask_ipc.send_request(sock, {"op": "shutdown"}, timeout=2)
            except OSError:
                pass
            th.join(timeout=5)


class StreamGuardStressTest(unittest.TestCase):
    """FR-Q16 — the streaming not-found guard is correct for any chunking."""

    def _provider(self, chunks):
        from providers import Usage

        class _P:
            def stream(self, system, prompt, json_mode=False):
                for c in chunks:
                    yield c
                yield Usage()
        return _P()

    def test_randomized_chunk_boundaries(self):
        import io
        rng = random.Random(1234)
        bodies = [
            "I couldn't find that in your chats.",                 # refusal
            "ADOS = Agentic Digital Operating System. [1]",        # short real
            "ADOS is a framework. [1] " + ("detail " * 60),        # long real
            "The chats do not contain information about that.",    # refusal
        ]
        for body in bodies:
            for _ in range(25):
                # random chunking
                chunks, i = [], 0
                while i < len(body):
                    step = rng.randint(1, 7)
                    chunks.append(body[i:i + step])
                    i += step
                buf = io.StringIO()
                text, nf, _tok = ask.stream_local_answer(
                    self._provider(chunks), "s", "p", budget=60.0,
                    no_abort=True, t0=time.monotonic(), out=buf)
                self.assertEqual(text, body)
                # classification must match the buffered-equivalent contract
                self.assertEqual(nf, ask.is_not_found(body))
                # a real answer is printed; a refusal is held back for the sentinel
                self.assertEqual(bool(buf.getvalue().strip()), not nf)


if __name__ == "__main__":
    unittest.main()
