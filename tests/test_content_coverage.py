"""FR-C2 / FR-C3 / FR-C5: content-type coverage, per-message provenance, and a
round-trip proof that no message node is silently dropped.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))

import chatgpt_parse as cp  # noqa: E402


def _load_extract_cards():
    spec = importlib.util.spec_from_file_location(
        "extract_cards", os.path.join(SCRIPTS, "extract_cards.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ec = _load_extract_cards()


def _msg(role, content, metadata=None):
    return {"author": {"role": role}, "content": content,
            "metadata": metadata or {}}


class ContentTypeCoverageTest(unittest.TestCase):
    def _text(self, content, role="assistant"):
        _r, text, _c = cp.message_text(_msg(role, content))
        return text

    def test_tether_quote_captured(self):
        t = self._text({"content_type": "tether_quote",
                        "title": "Example", "text": "a quoted snippet",
                        "url": "https://example.com"})
        self.assertIn("[web quote]", t)
        self.assertIn("quoted snippet", t)

    def test_tether_browsing_display_captured(self):
        t = self._text({"content_type": "tether_browsing_display",
                        "result": "search results body"})
        self.assertIn("[browsing]", t)
        self.assertIn("search results body", t)

    def test_execution_output_captured(self):
        t = self._text({"content_type": "execution_output",
                        "text": "stdout: 42"})
        self.assertIn("[execution output]", t)
        self.assertIn("42", t)

    def test_reasoning_thoughts_captured(self):
        t = self._text({"content_type": "thoughts",
                        "thoughts": [{"summary": "plan", "content": "step one"}]})
        self.assertIn("[reasoning]", t)
        self.assertTrue(t.strip())

    def test_unknown_content_type_degrades_to_placeholder(self):
        # Never an empty drop, never a crash.
        t = self._text({"content_type": "some_future_type", "payload": {"x": 1}})
        self.assertEqual(t, "[some_future_type]")

    def test_every_known_content_type_yields_nonempty(self):
        samples = {
            "text": {"content_type": "text", "parts": ["hello"]},
            "multimodal_text": {"content_type": "multimodal_text",
                                "parts": ["hi", {"content_type": "image_asset"}]},
            "code": {"content_type": "code", "text": "print(1)"},
            "user_editable_context": {"content_type": "user_editable_context",
                                      "user_profile": "p", "user_instructions": "i"},
            "tether_quote": {"content_type": "tether_quote", "text": "q"},
            "tether_browsing_display": {"content_type": "tether_browsing_display",
                                        "result": "r"},
            "execution_output": {"content_type": "execution_output", "text": "o"},
            "thoughts": {"content_type": "thoughts",
                         "thoughts": [{"content": "c"}]},
            "reasoning_recap": {"content_type": "reasoning_recap", "content": "c"},
        }
        for name, content in samples.items():
            with self.subTest(content_type=name):
                _r, text, ctype = cp.message_text(_msg("assistant", content))
                self.assertTrue(text.strip(), f"{name} produced empty text")
                self.assertEqual(ctype, name)


class ProvenanceTest(unittest.TestCase):
    def test_model_slug_captured(self):
        self.assertEqual(
            cp.message_model_slug(_msg("assistant", {"content_type": "text",
                                                     "parts": ["x"]},
                                       metadata={"model_slug": "o3-mini"})),
            "o3-mini")

    def test_attachments_captured(self):
        atts = cp.message_attachments(
            _msg("user", {"content_type": "text", "parts": ["see file"]},
                 metadata={"attachments": [{"name": "report.pdf"}, "raw.csv"]}))
        self.assertEqual(atts, ["report.pdf", "raw.csv"])

    def test_no_user_json_pii_leaks_into_attachments(self):
        # Only declared filenames; an email in metadata is not an attachment.
        atts = cp.message_attachments(
            _msg("user", {"content_type": "text", "parts": ["x"]},
                 metadata={"author_email": "alice@example.com"}))
        self.assertEqual(atts, [])


def _node(role, content, parent, metadata=None):
    return {"message": _msg(role, content, metadata), "parent": parent,
            "children": []}


class BuildCardIntegrationTest(unittest.TestCase):
    def _conv(self):
        mapping = {
            "root": {"message": None, "parent": None, "children": ["u"]},
            "u": _node("user", {"content_type": "text", "parts": ["build X"]},
                       "root", {"attachments": [{"name": "spec.md"}]}),
            "a": _node("assistant", {"content_type": "text", "parts": ["ok"]},
                       "u", {"model_slug": "gpt-4o"}),
            "t": _node("tool", {"content_type": "tether_browsing_display",
                                "result": "fetched docs"}, "a"),
            "r": _node("assistant", {"content_type": "thoughts",
                                     "thoughts": [{"content": "reasoned"}]}, "t",
                       {"model_slug": "o3"}),
        }
        mapping["u"]["children"] = ["a"]
        mapping["a"]["children"] = ["t"]
        mapping["t"]["children"] = ["r"]
        return {"id": "c1", "title": "demo", "current_node": "r",
                "create_time": 1.0, "update_time": 2.0, "mapping": mapping}

    def test_browsing_reasoning_and_provenance_on_card(self):
        card = ec.build_card(self._conv())
        self.assertIn("[browsing]", card["transcript"])
        self.assertIn("[tool]", card["transcript"])
        self.assertIn("[reasoning]", card["transcript"])
        self.assertEqual(card["attachments"], ["spec.md"])
        self.assertIn("gpt-4o", card["model_slug_votes"])
        self.assertIn("o3", card["model_slug_votes"])
        self.assertTrue(card["signals"]["has_browsing"])
        self.assertTrue(card["signals"]["has_reasoning"])

    def test_round_trip_no_silent_drop(self):
        # Every message-bearing node maps to captured content (or a [tag]); the
        # transcript turn count equals the number of content-bearing nodes.
        card = ec.build_card(self._conv())
        # 4 message nodes (u, a, t, r) all carry text -> 4 transcript turns.
        self.assertEqual(card["n_turns"], 4)


if __name__ == "__main__":
    unittest.main()
