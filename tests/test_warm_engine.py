"""
Warm engine wrapper — lifecycle logic, offline (no codex/claude subprocess).

A FakeEngine overrides spawn/exchange so we can assert the base-class contract
that the daemon relies on: single-flight complete(), recycle-after-N restarts,
and timeout -> poison (kill so the next call restarts) + WarmEngineError.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import warm_engine as we  # noqa: E402


class FakeEngine(we.WarmEngine):
    name = "fake"

    def __init__(self, **kw):
        super().__init__(**kw)
        self.started = 0
        self.closed = 0
        self._alive = False
        self.behavior = "ok"

    def _spawn_cmd(self):  # never actually used (start is overridden)
        return ["true"]

    def start(self):
        self.started += 1
        self._alive = True
        self._turns = 0

    def alive(self):
        return self._alive

    def close(self):
        self.closed += 1
        self._alive = False

    def _exchange(self, system, prompt, deadline):
        if self.behavior == "timeout":
            raise we.WarmEngineError("fake: timed out")
        return f"echo:{prompt}"


class WarmEngineTest(unittest.TestCase):
    def test_complete_returns_text_and_info(self):
        eng = FakeEngine()
        text, info = eng.complete("sys", "hello", timeout=5)
        self.assertEqual(text, "echo:hello")
        self.assertEqual(info["engine"], "fake")
        self.assertIn("elapsed_ms", info)
        self.assertEqual(eng.started, 1)

    def test_recycle_after_restarts_process(self):
        eng = FakeEngine(recycle_after=2)
        eng.complete("s", "a")
        eng.complete("s", "b")
        eng.complete("s", "c")  # turn count hit threshold -> restart before this
        self.assertEqual(eng.started, 2)
        self.assertEqual(eng.closed, 1)

    def test_timeout_poisons_engine_and_raises(self):
        eng = FakeEngine()
        eng.behavior = "timeout"
        with self.assertRaises(we.WarmEngineError):
            eng.complete("s", "q", timeout=1)
        self.assertFalse(eng.alive())   # killed
        self.assertEqual(eng.closed, 1)
        # next call restarts a fresh process
        eng.behavior = "ok"
        eng.complete("s", "q2")
        self.assertEqual(eng.started, 2)


class GetEngineTest(unittest.TestCase):
    def test_known_engines(self):
        self.assertIsInstance(we.get_engine("claude"), we.ClaudeWarmEngine)
        self.assertIsInstance(we.get_engine("codex"), we.CodexWarmEngine)

    def test_unknown_engine_raises(self):
        with self.assertRaises(we.WarmEngineError):
            we.get_engine("nope")


if __name__ == "__main__":
    unittest.main()
