"""Offline tests for the `gpt ask` privacy gate (FR-Q4).

No Ollama, no network: the embedder, the index loader, and the synthesis
provider are all faked. These pin the privacy-critical behaviour the thesis
rests on — a cloud/CLI provider is refused unless `--scrub-cloud`, and when it
is allowed the question + retrieved context are PII-scrubbed (`redact.scrub`)
before they ever reach the provider, while the local Ollama path sends the raw
prompt and needs no flag. Also covers the no-index guidance path (FR-Q2).
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import ask  # noqa: E402
import embeddings as emb  # noqa: E402
import providers  # noqa: E402
import redact  # noqa: E402

# A chunk carrying planted PII so we can prove scrubbing happened (or did not).
PII_EMAIL = "alex@example.com"
PII_PATH = "/home/alex/secrets/notes.txt"
PII_TEXT = f"My email is {PII_EMAIL} and my notes live at {PII_PATH}."

FAKE_INDEX = {
    "manifest": {"embed_model": "fake-embed"},
    "vectors": np.array([[1.0, 0.0]], dtype="float32"),
    "chunks": [{
        "row": 0, "chat_id": "c1", "title": "Secrets",
        "update_date": "2026-06-20", "start": 0, "end": len(PII_TEXT),
        "text": PII_TEXT,
    }],
}


class _SpyProvider:
    """Stands in for a real provider; records what it is asked to complete."""
    last: dict | None = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def complete(self, system, prompt, json_mode=False):
        _SpyProvider.last = {"system": system, "prompt": prompt,
                             "kwargs": self.kwargs}
        return "answer [1]", None


class AskPrivacyGateTest(unittest.TestCase):
    def setUp(self):
        _SpyProvider.last = None
        self.calls = {"get_provider": 0, "embed_one": 0}

        def fake_embed_one(_text, **_kw):
            self.calls["embed_one"] += 1
            return np.array([1.0, 0.0], dtype="float32")

        def fake_get_provider(_name, **kwargs):
            self.calls["get_provider"] += 1
            return _SpyProvider(**kwargs)

        self._orig = {
            "load_index": ask.load_index,
            "embed_one": emb.embed_one,
            "get_provider": providers.get_provider,
        }
        ask.load_index = lambda _d: dict(FAKE_INDEX)
        emb.embed_one = fake_embed_one
        providers.get_provider = fake_get_provider

    def tearDown(self):
        ask.load_index = self._orig["load_index"]
        emb.embed_one = self._orig["embed_one"]
        providers.get_provider = self._orig["get_provider"]

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ask.main(argv)
        return rc, out.getvalue(), err.getvalue()

    def test_cloud_refused_without_scrub_flag(self):
        rc, _out, err = self._run(
            ["secret question", "--provider", "openai", "--no-daemon"])
        self.assertEqual(rc, 2)
        self.assertIn("--scrub-cloud", err)
        # Nothing left the box: the gate trips before embedding or any provider.
        self.assertEqual(self.calls["embed_one"], 0)
        self.assertEqual(self.calls["get_provider"], 0)
        self.assertIsNone(_SpyProvider.last)

    def test_cloud_allowed_with_scrub_redacts_before_send(self):
        rc, _out, _err = self._run(
            ["secret question", "--provider", "openai", "--scrub-cloud",
             "--no-daemon"])
        self.assertEqual(rc, 0)
        sent = _SpyProvider.last
        self.assertIsNotNone(sent)
        # Raw PII must NOT reach the provider; typed placeholders must be there.
        self.assertNotIn(PII_EMAIL, sent["prompt"])
        self.assertNotIn(PII_PATH, sent["prompt"])
        self.assertIn(redact.PH_EMAIL, sent["prompt"])
        self.assertIn(redact.PH_PATH, sent["prompt"])

    def test_local_provider_allowed_without_flag_and_unscrubbed(self):
        # Force the local Ollama path (REQ-6/7: default now routes + GPU-gates).
        rc, _out, _err = self._run(
            ["secret question", "--allow-cpu", "--no-route", "--no-daemon"])
        self.assertEqual(rc, 0)
        sent = _SpyProvider.last
        self.assertIsNotNone(sent)
        # Local path never leaves the box, so it passes the raw context through.
        self.assertIn(PII_EMAIL, sent["prompt"])
        self.assertIn(PII_PATH, sent["prompt"])
        self.assertEqual(self.calls["get_provider"], 1)

    def test_json_output_carries_answer_and_sources(self):
        rc, out, _err = self._run(
            ["secret question", "--json", "--allow-cpu", "--no-route",
             "--no-daemon"])
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["question"], "secret question")
        self.assertEqual(doc["answer"], "answer [1]")
        self.assertEqual(doc["sources"][0]["chat_id"], "c1")


class AskKeywordFallbackTest(unittest.TestCase):
    """No index -> keyword scan instead of erroring (FR-Q follow-up)."""

    def test_json_fallback_uses_keyword_hits(self):
        import store_query as sq
        orig_load, orig_search = ask.load_index, sq.search_transcripts
        ask.load_index = lambda _d: None
        sq.search_transcripts = lambda *a, **k: [
            {"id": "kw1", "title": "Keyword hit", "update_date": "2026-05-01",
             "snippet": "matched line"}]
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    contextlib.redirect_stderr(io.StringIO()):
                rc = ask.main(["geometry rubric", "--json"])
        finally:
            ask.load_index, sq.search_transcripts = orig_load, orig_search
        self.assertEqual(rc, 0)
        doc = json.loads(out.getvalue())
        self.assertEqual(doc["mode"], "keyword_fallback")
        self.assertEqual(doc["sources"][0]["chat_id"], "kw1")


class AskNoIndexTest(unittest.TestCase):
    def test_missing_index_tells_user_to_build(self):
        orig = ask.load_index
        ask.load_index = lambda _d: None
        try:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = ask.main(["anything"])
        finally:
            ask.load_index = orig
        self.assertEqual(rc, 1)
        self.assertIn("gpt index", err.getvalue())


if __name__ == "__main__":
    unittest.main()
