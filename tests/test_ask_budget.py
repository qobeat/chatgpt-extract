"""
Ask feature, latency contract — `gpt ask` budget + entity route (README feature 2).

Covers the interactive-latency hard requirement without a live model:
  - a synthesis that exceeds the budget is reported UNUSABLE (exit 3), not hung;
  - a deterministic entity route answers with NO model call at all;
  - retrieval overhead stays bounded on a tiny index.

The provider and embedder are mocked, so this runs offline in CI.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import ask  # noqa: E402
import providers  # noqa: E402


def _seed_index(root: str, *, with_entities: bool = False) -> str:
    index_dir = os.path.join(root, "index")
    os.makedirs(index_dir)
    with open(os.path.join(index_dir, "manifest.json"), "w") as f:
        json.dump({"embed_model": "test-embed", "n_chats": 1}, f)
    vectors = np.array([[1.0, 0.0, 0.0, 0.0],
                        [0.0, 1.0, 0.0, 0.0]], dtype="float32")
    np.save(os.path.join(index_dir, "vectors.npy"), vectors)
    chunks = [
        {"chat_id": "c1", "title": "ADOS notes", "update_date": "2026-06-19",
         "start": 0, "end": 100, "text": "ADOS profile discussion and goals."},
        {"chat_id": "c2", "title": "Other", "update_date": "2026-06-18",
         "start": 0, "end": 100, "text": "Unrelated content about cooking."},
    ]
    with open(os.path.join(index_dir, "chunks.jsonl"), "w") as f:
        for c in chunks:
            f.write(json.dumps(c) + "\n")
    if with_entities:
        with open(os.path.join(index_dir, "entities.json"), "w") as f:
            json.dump({
                "schema": "ados-entities/1", "product": "ados-profile",
                "versions": {},
                "summary": {"newest_overall": None, "latest_stable": None,
                            "acronym": {"term": "ADOS",
                                        "expansion": "Agentic Digital Operating System",
                                        "mentions": 7, "n_chats": 3,
                                        "chat_id": "c1"}}}, f)
    return index_dir


class _Recorder:
    """Records whether get_provider was invoked (to prove the route bypasses it)."""

    def __init__(self):
        self.called = False

    def __call__(self, *a, **k):
        self.called = True
        raise AssertionError("get_provider must not be called on a routed answer")


class AskBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ,
                              {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_over_budget_synthesis_is_unusable(self):
        _seed_index(self.tmp.name, with_entities=False)

        class TimeoutProvider:
            def __init__(self, *a, **k):
                pass

            def complete(self, system, prompt, json_mode=False):
                raise providers.ProviderError(
                    "ollama: timed out after 1s (no retry; likely VRAM spill)")

        with patch("embeddings.embed_one", return_value=[1.0, 0.0, 0.0, 0.0]), \
             patch("providers.get_provider", return_value=TimeoutProvider()):
            buf, err = io.StringIO(), io.StringIO()
            with redirect_stdout(buf), redirect_stderr(err):
                code = ask.main(["tell", "me", "about", "ados", "--no-daemon",
                                 "--budget", "1", "--allow-cpu", "--no-route"])
        self.assertEqual(code, ask.EXIT_UNUSABLE)
        self.assertIn("unusable", err.getvalue().lower())

    def test_entity_route_answers_without_model(self):
        _seed_index(self.tmp.name, with_entities=True)
        rec = _Recorder()
        with patch("providers.get_provider", rec), \
             patch("embeddings.embed_one",
                   side_effect=AssertionError("embed must not run on a route")):
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                code = ask.main(["what", "does", "ados", "stand", "for",
                                 "--no-daemon", "--json"])
        self.assertEqual(code, 0)
        self.assertFalse(rec.called)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["route"], "entity")
        self.assertIn("Agentic Digital Operating System", payload["answer"])

    def test_retrieve_overhead_bounded(self):
        # Pure retrieval over a tiny index should be effectively instant.
        import time
        idx = ask.load_index(_seed_index(self.tmp.name))
        qvec = [1.0, 0.0, 0.0, 0.0]
        t0 = time.monotonic()
        hits = ask.retrieve(qvec, idx["vectors"], idx["chunks"], k=2)
        dt = time.monotonic() - t0
        self.assertEqual(hits[0]["chat_id"], "c1")  # most similar wins
        self.assertLess(dt, 1.0)


if __name__ == "__main__":
    unittest.main()
