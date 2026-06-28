"""Batched classification: pack many items per provider call, with a per-item
fallback so robustness is never below the per-item baseline.

Covers the prompt builder, the result splitter, the char-bounded chunker, and
the prefetch pass (token attribution + fallback for missing/malformed slugs).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))

from providers.base import Usage  # noqa: E402


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, relpath))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


S = _load("summarize", "summarize.py")
ONT = S.load_ontology()


def _cluster(slug: str) -> dict:
    return {
        "slug": slug, "n_versions": 1, "n_conversations": 2,
        "member_ids": ["c1"], "version_zip_files": [], "file_artifacts": [],
        "signal_summary": {},
        "classify_prior": {
            "primary_archetype": {"id": "knowledge_qa"},
            "primary_domain_pair": {"domain": "general_knowledge",
                                    "subdomain": None},
        },
    }


def _work(slugs, body="x" * 100):
    return [(_cluster(s), f"{body} {s}", f"hash-{s}") for s in slugs]


def _valid_obj(goal="g"):
    return {
        "primary_archetype": {"id": "knowledge_qa"},
        "primary_domain_pair": {"domain": "general_knowledge"},
        "goal": goal, "objectives": [], "requirements": [],
        "archetype_fields": {},
    }


class _Trace:
    def __init__(self):
        self.events = []

    def event(self, event_type, message, payload=None, severity="INFO"):
        self.events.append((event_type, message, payload or {}, severity))
        return {}


class _BatchProvider:
    """Returns a queued response per complete() call; counts calls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0
        self.prompts = []

    def complete(self, system, prompt, json_mode=True):
        self.calls += 1
        self.prompts.append(prompt)
        text = self._responses.pop(0) if self._responses else "{}"
        return text, Usage(input_tokens=120, output_tokens=40)


class BuildBatchPromptTest(unittest.TestCase):
    def test_lists_every_slug_and_shape(self):
        prompt = S.build_batch_prompt(_work(["a", "b", "c"]), ONT)
        for slug in ("a", "b", "c"):
            self.assertIn(slug, prompt)
        self.assertIn("JSON object", prompt)
        # OUTPUT_SHAPE markers
        self.assertIn("primary_archetype", prompt)


class SplitBatchResultTest(unittest.TestCase):
    def test_keeps_only_dict_values_for_known_slugs(self):
        parsed = {"a": _valid_obj(), "b": "not a dict", "z": _valid_obj()}
        out = S.split_batch_result(parsed, ["a", "b", "c"])
        self.assertEqual(set(out), {"a"})          # b malformed, c missing, z extra

    def test_non_dict_top_level_yields_empty(self):
        self.assertEqual(S.split_batch_result(["a"], ["a"]), {})
        self.assertEqual(S.split_batch_result(None, ["a"]), {})


class ChunkWorkTest(unittest.TestCase):
    def test_respects_batch_size(self):
        chunks = list(S.chunk_work(_work(list("abcde")), batch_size=2,
                                   batch_max_chars=10**9, sys_len=0))
        self.assertEqual([len(c) for c in chunks], [2, 2, 1])

    def test_respects_char_budget(self):
        # Each item ~ 100 body + overhead; cap forces 1 per chunk.
        chunks = list(S.chunk_work(_work(list("abcd"), body="y" * 300),
                                   batch_size=99, batch_max_chars=400,
                                   sys_len=0))
        self.assertTrue(all(len(c) == 1 for c in chunks))
        self.assertEqual(len(chunks), 4)

    def test_single_oversized_item_ships_alone(self):
        chunks = list(S.chunk_work(_work(["big"], body="z" * 5000),
                                   batch_size=10, batch_max_chars=100,
                                   sys_len=0))
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), 1)


class PrefetchBatchesTest(unittest.TestCase):
    def test_one_call_classifies_whole_chunk(self):
        work = _work(["a", "b", "c"])
        resp = json.dumps({"a": _valid_obj(), "b": _valid_obj(),
                           "c": _valid_obj()})
        prov = _BatchProvider([resp])
        out = S.prefetch_batches(
            prov, "SYS", work, ONT, batch_size=3, batch_max_chars=10**9,
            max_parse_retries=1, trace=_Trace(), skip=set())
        self.assertEqual(prov.calls, 1)            # all three in ONE call
        self.assertEqual(set(out), {"a", "b", "c"})
        # tokens attributed across the chunk sum to the batch total (120 in)
        self.assertEqual(sum(v[1] for v in out.values()), 120 - 120 % 1)
        # each entry is (parsed, in, out, timing, secs)
        parsed, in_tok, out_tok, timing, secs = out["a"]
        self.assertEqual(parsed["goal"], "g")
        self.assertIn("load_ms", timing)

    def test_missing_and_malformed_slugs_are_absent(self):
        work = _work(["a", "b", "c"])
        # b malformed, c missing entirely
        resp = json.dumps({"a": _valid_obj(), "b": "oops"})
        prov = _BatchProvider([resp])
        out = S.prefetch_batches(
            prov, "SYS", work, ONT, batch_size=3, batch_max_chars=10**9,
            max_parse_retries=0, trace=_Trace(), skip=set())
        self.assertEqual(set(out), {"a"})          # b, c fall back to per-item

    def test_skip_excludes_resume_done(self):
        work = _work(["a", "b"])
        resp = json.dumps({"b": _valid_obj()})
        prov = _BatchProvider([resp])
        out = S.prefetch_batches(
            prov, "SYS", work, ONT, batch_size=9, batch_max_chars=10**9,
            max_parse_retries=0, trace=_Trace(), skip={"a"})
        self.assertNotIn("a", out)
        self.assertIn("b", out)                    # b was sent and classified
        self.assertNotIn('slug="a"', prov.prompts[0])  # a skipped (resume-done)
        self.assertIn('slug="b"', prov.prompts[0])

    def test_whole_batch_unparseable_returns_empty(self):
        work = _work(["a", "b"])
        prov = _BatchProvider(["not json", "still not json"])
        trace = _Trace()
        out = S.prefetch_batches(
            prov, "SYS", work, ONT, batch_size=9, batch_max_chars=10**9,
            max_parse_retries=1, trace=trace, skip=set())
        self.assertEqual(out, {})                  # everything falls back
        self.assertTrue(any(e[0] == "BATCH_MISS" for e in trace.events))


if __name__ == "__main__":
    unittest.main()
