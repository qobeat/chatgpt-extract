"""FR-Q16 — interactive latency knobs: think, num_predict, and streaming.

Offline, pure tests (no network, no numpy):

- `think_for_model` requests `"low"` for gpt-oss (booleans are ignored there) and
  keeps `False` elsewhere, with an explicit override always winning.
- The Ollama payload carries the model's `think` value and the per-instance
  `num_predict` (so the interactive `ask` cap and the summarizer's larger budget
  stay distinct).
- `OllamaProvider.stream` parses NDJSON deltas and yields a final `Usage`.
- `ask.stream_local_answer` streams a real answer to its output but holds a short
  refusal back so it still collapses to the not-found sentinel (FR-Q8).
"""
from __future__ import annotations

import io
import os
import sys
import time
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

from providers import Usage  # noqa: E402
from providers.ollama_provider import (  # noqa: E402
    DEFAULT_NUM_PREDICT, OllamaProvider, think_for_model,
)
import ask  # noqa: E402


class ThinkForModelTest(unittest.TestCase):
    def test_gpt_oss_gets_low_not_boolean(self):
        self.assertEqual(think_for_model("gpt-oss:20b"), "low")
        self.assertEqual(think_for_model("gpt-oss:120b"), "low")

    def test_other_models_keep_boolean_false(self):
        self.assertIs(think_for_model("qwen3:8b"), False)
        self.assertIs(think_for_model("llama3.1:8b"), False)

    def test_explicit_override_wins(self):
        self.assertEqual(think_for_model("gpt-oss:20b", "high"), "high")
        self.assertIs(think_for_model("qwen3:8b", False), False)
        self.assertEqual(think_for_model("anything", "medium"), "medium")


class PayloadKnobsTest(unittest.TestCase):
    def _capture(self, model, **kw):
        captured = {}
        prov = OllamaProvider(model=model, **kw)

        def fake_post(url, payload, headers, **_kw):
            captured["payload"] = payload
            return {"message": {"content": "{}"}, "prompt_eval_count": 1,
                    "eval_count": 1}

        prov._post_json = fake_post  # type: ignore[assignment]
        prov.complete("sys", "user", json_mode=False)
        return captured["payload"]

    def test_gpt_oss_payload_thinks_low(self):
        payload = self._capture("gpt-oss:20b")
        self.assertEqual(payload["think"], "low")

    def test_non_gpt_oss_payload_thinks_false(self):
        payload = self._capture("qwen3:8b")
        self.assertIs(payload["think"], False)

    def test_num_predict_defaults_and_overrides(self):
        self.assertEqual(self._capture("qwen3:8b")["options"]["num_predict"],
                         DEFAULT_NUM_PREDICT)
        self.assertEqual(
            self._capture("qwen3:8b", num_predict=384)["options"]["num_predict"],
            384)


class _FakeResp:
    def __init__(self, lines):
        self._lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._lines)


class StreamParseTest(unittest.TestCase):
    def test_stream_yields_chunks_then_usage(self):
        lines = [
            b'{"message":{"content":"Hello "}}\n',
            b'{"message":{"content":"world"}}\n',
            b'{"message":{"content":""},"done":true,'
            b'"prompt_eval_count":7,"eval_count":2,"eval_duration":2000000}\n',
        ]
        prov = OllamaProvider(model="gpt-oss:20b")
        with mock.patch("urllib.request.urlopen",
                        return_value=_FakeResp(lines)):
            out = list(prov.stream("sys", "user", json_mode=False))
        chunks = [c for c in out if isinstance(c, str)]
        usage = [u for u in out if isinstance(u, Usage)]
        self.assertEqual("".join(chunks), "Hello world")
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0].output_tokens, 2)
        self.assertEqual(usage[0].input_tokens, 7)


class _FakeStreamProvider:
    def __init__(self, chunks):
        self._chunks = chunks

    def stream(self, system, prompt, json_mode=False):
        for c in self._chunks:
            yield c
        yield Usage()


class StreamLocalAnswerTest(unittest.TestCase):
    def _run(self, chunks):
        buf = io.StringIO()
        prov = _FakeStreamProvider(chunks)
        text, nf = ask.stream_local_answer(
            prov, "sys", "prompt", budget=60.0, no_abort=True,
            t0=time.monotonic(), out=buf)
        return text, nf, buf.getvalue()

    def test_long_real_answer_streams_to_output(self):
        body = "ADOS is a framework. [1] " + ("x" * 300)
        text, nf, printed = self._run([body])
        self.assertFalse(nf)
        self.assertEqual(text, body)
        self.assertIn("ADOS is a framework.", printed)

    def test_short_refusal_collapses_and_is_not_printed(self):
        text, nf, printed = self._run(["I couldn't find that in your chats."])
        self.assertTrue(nf)
        self.assertEqual(printed, "")  # caller prints the sentinel, not us

    def test_short_real_answer_is_printed(self):
        text, nf, printed = self._run(["ADOS = A Document Ontology System. [1]"])
        self.assertFalse(nf)
        self.assertIn("ADOS = A Document Ontology System.", printed)

    def test_budget_overrun_raises(self):
        from providers import ProviderError

        # Budget already blown (t0 far in the past); the first chunk trips it.
        prov = _FakeStreamProvider(["partial answer that is long " * 20])
        with self.assertRaises(ProviderError):
            ask.stream_local_answer(
                prov, "s", "p", budget=1.0, no_abort=False,
                t0=time.monotonic() - 100, out=io.StringIO())


if __name__ == "__main__":
    unittest.main()
