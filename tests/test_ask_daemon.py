"""
Ask feature, warm router-aware daemon — socket round-trip + model switching.

Drives the real `ask_daemon.serve()` loop in a worker thread with the router and
providers FAKED (no codex/claude subprocess, no Ollama, no network), proving:
  - ping / stats / entity-route / synthesis / shutdown over the unix socket;
  - the entity route answers with no provider call at all;
  - a synthesis route runs through the resolved provider and is recorded in
    stats + history;
  - the not-found contract (no hits -> the fixed sentinel);
  - warm-engine model switching (one resident engine, swapped on change).
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ask  # noqa: E402
import ask_daemon  # noqa: E402
import ask_ipc  # noqa: E402
import embeddings as emb  # noqa: E402


class FakeProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def complete(self, system, prompt, json_mode=False):
        from providers import Usage
        return ("FAKE ANSWER grounded in [1].", Usage(output_tokens=7))


class FakeWarmEngine:
    """Stands in for a claude/codex warm engine (no subprocess)."""

    def __init__(self, name="claude", model=None):
        self.name = name
        self.model = model
        self.closed = False

    def alive(self):
        return not self.closed

    def preflight(self):
        return True, "ok"

    def start(self):
        self.closed = False

    def complete(self, system, prompt, timeout=15.0):
        return (f"WARM[{self.name}] [1]", {"engine": self.name, "elapsed_ms": 1.0})

    def close(self):
        self.closed = True


def _idx():
    vectors = np.array([[1.0, 0.0], [0.0, 1.0]], dtype="float32")
    chunks = [
        {"chat_id": "c1", "title": "ADOS", "update_date": "2026-06-19",
         "start": 0, "end": 50, "text": "ADOS profile goals."},
        {"chat_id": "c2", "title": "Other", "update_date": "2026-06-18",
         "start": 0, "end": 50, "text": "Cooking."},
    ]
    return {"manifest": {"embed_model": "test"}, "vectors": vectors, "chunks": chunks}


def _entities():
    return {"schema": "ados-entities/1", "product": "ados-profile", "versions": {},
            "summary": {"newest_overall": None, "latest_stable": None,
                        "acronym": {"term": "ADOS",
                                    "expansion": "Agentic Digital Operating System",
                                    "mentions": 7, "n_chats": 3, "chat_id": "c1"}}}


def _state():
    defaults = {"k": 8, "per_chat": 3, "half_life": emb.DEFAULT_HALF_LIFE_DAYS,
                "rerank": False, "budget": 15}
    return ask_daemon.DaemonState(_idx(), _entities(), "test", None, defaults,
                                  cfg={"ask": {}}, default_engine="claude")


class AskDaemonTest(unittest.TestCase):
    def test_socket_round_trip(self):
        tmp = tempfile.mkdtemp()
        sock = os.path.join(tmp, "ask.sock")
        state = _state()
        th = threading.Thread(target=ask_daemon.serve, args=(state, sock, 5),
                              daemon=True)
        # Synthesis routes to local Ollama (is_local) via a fake provider.
        local_route = ("ok", "ollama", None, True, "local Ollama (test)")
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=local_route), \
             patch("ask_daemon.get_provider",
                   side_effect=lambda name, **kw: FakeProvider(**kw)):
            th.start()
            try:
                for _ in range(50):
                    if ask_ipc.ping(sock) is not None:
                        break
                    time.sleep(0.1)

                pong = ask_ipc.ping(sock)
                self.assertIsNotNone(pong)
                self.assertEqual(pong["engine"], "claude")  # default warm engine

                # entity route -> no provider call
                r = ask_ipc.send_request(sock, {"op": "ask",
                                                "question": "what does ados stand for"})
                self.assertTrue(r["ok"])
                self.assertEqual(r["route"], "entity")
                self.assertIn("Agentic Digital Operating System", r["answer"])

                # synthesis route -> fake provider answer, recorded
                r2 = ask_ipc.send_request(sock, {"op": "ask",
                                                 "question": "tell me about ados"})
                self.assertTrue(r2["ok"])
                self.assertEqual(r2["route"], "synthesis")
                self.assertIn("FAKE ANSWER", r2["answer"])
                self.assertFalse(r2["not_found"])
                self.assertEqual(r2["provider"], "ollama")
                self.assertIn("embed_ms", r2["timings"])
                # FR-Q19/FR-Q16: the daemon reports output tokens and the
                # interactive num_predict cap it applied (not the 8k context).
                self.assertEqual(r2["tokens"], 7)
                self.assertEqual(r2["num_predict"], ask.DEFAULT_ASK_NUM_PREDICT)

                # stats op reflects the two served requests + history
                stats = ask_ipc.send_request(sock, {"op": "stats"})
                self.assertTrue(stats["ok"])
                self.assertEqual(stats["served"], 2)
                self.assertGreaterEqual(len(stats["history"]), 2)
                self.assertIn("pid", stats)
            finally:
                try:
                    ask_ipc.send_request(sock, {"op": "shutdown"}, timeout=2)
                except OSError:
                    pass
                th.join(timeout=5)
        self.assertFalse(os.path.exists(sock))

    def test_no_hits_returns_not_found(self):
        state = _state()
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.retrieve", return_value=[]):
            resp = ask_daemon.handle_ask(
                {"op": "ask", "question": "nonsense xyzzy",
                 "no_entity_route": True}, state)
        self.assertTrue(resp["ok"])
        self.assertTrue(resp["not_found"])
        self.assertEqual(resp["answer"], ask.NOT_FOUND_MSG)
        self.assertEqual(resp["sources"], [])

    def test_gate_error_carries_rc(self):
        state = _state()
        gate = ("error", 2, "provider 'openai' sends data off-box.", None, None)
        with patch("embeddings.embed_one", return_value=[1.0, 0.0]), \
             patch("ask.resolve_route", return_value=gate):
            resp = ask_daemon.handle_ask(
                {"op": "ask", "question": "tell me about ados",
                 "no_entity_route": True, "provider": "openai"}, state)
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["rc"], 2)

    def test_warm_engine_switches_on_model_change(self):
        state = _state()
        made: list[tuple[str, str | None]] = []

        def fake_get_engine(name, model=None, **kw):
            made.append((name, model))
            return FakeWarmEngine(name=name, model=model)

        with patch("ask_daemon.get_engine", side_effect=fake_get_engine):
            e1 = state.warm_engine_for("claude", None)
            e1b = state.warm_engine_for("claude", None)  # same key -> reused
            self.assertIs(e1, e1b)
            e2 = state.warm_engine_for("codex", None)    # change -> switch
            self.assertIsNot(e1, e2)
            self.assertTrue(e1.closed)                   # old one stopped
        self.assertEqual(made, [("claude", None), ("codex", None)])


class AskIpcTest(unittest.TestCase):
    def test_read_write_line_round_trip(self):
        a, b = socket.socketpair()
        try:
            ask_ipc.write_line(a, {"op": "ask", "question": "hi"})
            msg = ask_ipc.read_line(b)
            import json
            self.assertEqual(json.loads(msg), {"op": "ask", "question": "hi"})
        finally:
            a.close()
            b.close()

    def test_read_line_eof_returns_none(self):
        a, b = socket.socketpair()
        a.close()
        try:
            self.assertIsNone(ask_ipc.read_line(b))
        finally:
            b.close()

    def test_ping_none_when_no_daemon(self):
        tmp = tempfile.mkdtemp()
        sock = os.path.join(tmp, "ask.sock")
        self.assertIsNone(ask_ipc.ping(sock, timeout=0.5))


if __name__ == "__main__":
    unittest.main()
