"""Semantic search (gpt index / gpt ask): chunking, recency-weighted ranking,
incremental index round-trip, and prompt/citation assembly.

All tests inject a deterministic fake embedder, so they run fully offline — no
Ollama host, no network, no $DATA_ROOT.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest

import numpy as np

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import embeddings as emb  # noqa: E402
import index as ix  # noqa: E402
import ask  # noqa: E402

NOW = dt.datetime(2026, 6, 28, tzinfo=dt.timezone.utc)


def fake_embed(texts):
    """Deterministic toy embedder: bag-of-keywords -> small fixed-dim vector.

    Maps a handful of marker words to axes so similarity is meaningful and
    repeatable without a model. Length-normalization happens in the ranker.
    """
    keys = ["ados", "geometry", "readme", "cooking", "pytest"]
    out = []
    for t in texts:
        low = (t or "").lower()
        out.append([float(low.count(k)) for k in keys] + [1.0])
    return out


class ChunkTest(unittest.TestCase):
    def test_overlap_and_spans(self):
        text = "x" * 2500
        chunks = emb.chunk_transcript(text, size=1200, overlap=200)
        self.assertEqual([(s, e) for s, e, _ in chunks],
                         [(0, 1200), (1000, 2200), (2000, 2500)])
        # full coverage, every char reachable
        self.assertEqual(chunks[0][0], 0)
        self.assertEqual(chunks[-1][1], len(text))

    def test_short_and_empty(self):
        self.assertEqual(emb.chunk_transcript("hello"), [(0, 5, "hello")])
        self.assertEqual(emb.chunk_transcript("   "), [])
        self.assertEqual(emb.chunk_transcript(""), [])

    def test_deterministic(self):
        t = "abc " * 1000
        self.assertEqual(emb.chunk_transcript(t), emb.chunk_transcript(t))

    def test_invalid_overlap(self):
        with self.assertRaises(ValueError):
            emb.chunk_transcript("x" * 100, size=100, overlap=100)


class RecencyTest(unittest.TestCase):
    def test_today_full_weight(self):
        self.assertAlmostEqual(
            emb.recency_weight("2026-06-28", now=NOW), 1.0, places=3)

    def test_half_life(self):
        old = (NOW - dt.timedelta(days=180)).date().isoformat()
        self.assertAlmostEqual(
            emb.recency_weight(old, half_life_days=180, now=NOW), 0.5, places=2)

    def test_unknown_is_neutral(self):
        self.assertEqual(emb.recency_weight(None, now=NOW), 1.0)
        self.assertEqual(emb.recency_weight("not-a-date", now=NOW), 1.0)

    def test_disable_decay(self):
        self.assertEqual(
            emb.recency_weight("2000-01-01", half_life_days=0, now=NOW), 1.0)


class CosineRankTest(unittest.TestCase):
    def test_sims_and_topk(self):
        M = np.array([[1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype="float32")
        q = np.array([1, 0, 0], dtype="float32")
        sims = emb.cosine_sims(q, M)
        self.assertAlmostEqual(float(sims[0]), 1.0, places=4)
        self.assertAlmostEqual(float(sims[1]), 0.0, places=4)
        self.assertEqual(emb.top_indices(sims, 2)[0], 0)

    def test_topk_stable_on_ties(self):
        scores = np.array([0.5, 0.5, 0.5], dtype="float32")
        self.assertEqual(emb.top_indices(scores, 3), [0, 1, 2])

    def test_topk_bounds(self):
        self.assertEqual(emb.top_indices(np.array([1.0]), 5), [0])
        self.assertEqual(emb.top_indices(np.array([]), 3), [])


class BuildIndexTest(unittest.TestCase):
    def _recs(self):
        return [
            {"id": "a", "title": "ADOS geometry", "update_date": "2026-06-01",
             "text": "ados geometry " * 80},
            {"id": "b", "title": "cooking", "update_date": "2025-01-01",
             "text": "cooking recipe " * 80},
        ]

    def test_build_orders_by_chat_and_fills_manifest(self):
        r = ix.build_index(self._recs(), fake_embed, embed_model="fake",
                           chunk_size=400, chunk_overlap=50)
        self.assertEqual(r["stats"]["n_embedded"], 2)
        self.assertEqual(r["stats"]["n_reused"], 0)
        # chats are emitted sorted by id; row offsets are contiguous/consistent
        chats = r["manifest"]["chats"]
        self.assertEqual(chats["a"]["row_start"], 0)
        self.assertEqual(chats["a"]["row_end"], chats["b"]["row_start"])
        self.assertEqual(r["vectors"].shape[0], r["manifest"]["n_chunks"])
        self.assertEqual(r["manifest"]["dim"], r["vectors"].shape[1])

    def test_roundtrip_write_load(self):
        r = ix.build_index(self._recs(), fake_embed, embed_model="fake")
        d = tempfile.mkdtemp()
        ix.write_index(d, r)
        self.assertTrue(os.path.isfile(os.path.join(d, "vectors.npy")))
        self.assertTrue(os.path.isfile(os.path.join(d, "chunks.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(d, "manifest.json")))
        loaded = ix.load_existing(d)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["vectors"].shape, r["vectors"].shape)
        self.assertEqual(len(loaded["chunks"]), r["manifest"]["n_chunks"])

    def test_incremental_reuse_and_reembed(self):
        recs = self._recs()
        r = ix.build_index(recs, fake_embed, embed_model="fake")
        d = tempfile.mkdtemp()
        ix.write_index(d, r)
        existing = ix.load_existing(d)

        # Unchanged input -> everything reused, nothing re-embedded.
        calls = {"n": 0}

        def counting_embed(texts):
            calls["n"] += len(texts)
            return fake_embed(texts)

        r2 = ix.build_index(recs, counting_embed, embed_model="fake",
                            existing=existing)
        self.assertEqual(calls["n"], 0)
        self.assertEqual(r2["stats"]["n_reused"], 2)
        self.assertEqual(r2["stats"]["n_embedded"], 0)

        # Change one chat -> only that chat is re-embedded.
        recs[0]["text"] = "totally different content " * 30
        calls["n"] = 0
        r3 = ix.build_index(recs, counting_embed, embed_model="fake",
                            existing=existing)
        self.assertGreater(calls["n"], 0)
        self.assertEqual(r3["stats"]["n_embedded"], 1)
        self.assertEqual(r3["stats"]["n_reused"], 1)

    def test_rebuild_ignores_cache(self):
        recs = self._recs()
        r = ix.build_index(recs, fake_embed, embed_model="fake")
        d = tempfile.mkdtemp()
        ix.write_index(d, r)
        existing = ix.load_existing(d)
        calls = {"n": 0}

        def counting_embed(texts):
            calls["n"] += len(texts)
            return fake_embed(texts)

        ix.build_index(recs, counting_embed, embed_model="fake",
                       existing=existing, rebuild=True)
        self.assertGreater(calls["n"], 0)  # rebuild re-embeds despite cache


class RetrieveTest(unittest.TestCase):
    def _index(self):
        vecs = np.array([[1, 0, 0], [1, 0, 0], [0, 1, 0]], dtype="float32")
        chunks = [
            {"row": 0, "chat_id": "old", "title": "Old", "update_date": "2024-01-01", "text": "ados old"},
            {"row": 1, "chat_id": "new", "title": "New", "update_date": "2026-06-01", "text": "ados new"},
            {"row": 2, "chat_id": "other", "title": "Other", "update_date": "2026-06-01", "text": "cooking"},
        ]
        return vecs, chunks

    def test_recency_tiebreak(self):
        vecs, chunks = self._index()
        q = np.array([1, 0, 0], dtype="float32")
        hits = ask.retrieve(q, vecs, chunks, k=3, half_life_days=180, now=NOW)
        # identical cosine on old/new -> newer must come first; 'other' (sim 0) dropped
        self.assertEqual([h["chat_id"] for h in hits], ["new", "old"])

    def test_since_filter(self):
        vecs, chunks = self._index()
        q = np.array([1, 0, 0], dtype="float32")
        hits = ask.retrieve(q, vecs, chunks, k=3, since="2026-01-01", now=NOW)
        self.assertEqual([h["chat_id"] for h in hits], ["new"])

    def test_empty_index(self):
        self.assertEqual(ask.retrieve(np.array([1.0]), np.zeros((0, 1)), [], k=5), [])


class PromptTest(unittest.TestCase):
    def test_build_prompt_numbers_and_dedupes(self):
        hits = [
            {"chat_id": "x", "title": "Chat X", "update_date": "2026-01-01", "text": "alpha"},
            {"chat_id": "x", "title": "Chat X", "update_date": "2026-01-01", "text": "beta"},
            {"chat_id": "y", "title": "Chat Y", "update_date": "2025-01-01", "text": "gamma"},
        ]
        system, prompt, sources = ask.build_prompt("what?", hits)
        # two distinct chats -> two sources, numbered in first-seen order
        self.assertEqual([(s["n"], s["chat_id"]) for s in sources], [(1, "x"), (2, "y")])
        self.assertIn("[1]", prompt)
        self.assertIn("[2]", prompt)
        self.assertIn("alpha", prompt)
        self.assertIn("gamma", prompt)
        self.assertIn("[n]", system)  # cite instruction present

    def test_format_sources(self):
        out = ask.format_sources([
            {"n": 1, "chat_id": "abc", "title": "T", "update_date": "2026-06-01"}])
        self.assertIn("[1]", out)
        self.assertIn("id=abc", out)
        self.assertIn("2026-06-01", out)


if __name__ == "__main__":
    unittest.main()
