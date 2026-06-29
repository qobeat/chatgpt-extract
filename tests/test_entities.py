#!/usr/bin/env python3
"""Offline tests for the catalog entity index (scripts/lib/entities.py).

All pure: version extraction, instability attribution, semver ordering,
newest/latest-stable selection, intent routing, and deterministic answers.
No numpy, no network, no live index.
"""
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))

import entities as ent  # noqa: E402


class TestVersionParsing(unittest.TestCase):
    def test_major_minor(self):
        self.assertEqual(ent.major_minor("1.23.0"), "1.23")
        self.assertEqual(ent.major_minor("2.0"), "2.0")

    def test_version_key_orders_numerically(self):
        # 1.23 > 1.4 (not string order) and 2.0 > 1.23
        self.assertGreater(ent.version_key("1.23"), ent.version_key("1.4"))
        self.assertGreater(ent.version_key("2.0"), ent.version_key("1.23"))

    def test_only_product_qualified_versions(self):
        text = ("ados-profile-v2.0.zip vs ados-profile-v1.23.zip; "
                "package_version=1.23.0")
        self.assertEqual(set(ent.extract_qualified_versions(text)), {"2.0", "1.23"})

    def test_unqualified_numbers_ignored(self):
        # numpy/gemini/section numbers must not pollute the table
        text = "numpy 2.1.3 is unexpected; see section 1.2 and gemini 1.5 pro"
        self.assertEqual(ent.extract_qualified_versions(text), [])


class TestInstability(unittest.TestCase):
    def test_attributes_neg_to_governed_version_only(self):
        # The classic sentence flags 2.0, NOT 1.23, even though both appear.
        text = ("ados-profile review: My current recommendation: do not approve "
                "v2.0 as a clean successor to v1.23 yet.")
        self.assertEqual(ent.find_unstable_versions(text), {"2.0"})

    def test_requires_product_context(self):
        text = "do not approve v2.0"  # no ados-profile anchor nearby
        self.assertEqual(ent.find_unstable_versions(text), set())


class TestSelection(unittest.TestCase):
    def _records(self):
        recs = []
        # 1.23: the dominant stable release (many mentions, 2 chats)
        recs.append({"chat_id": "A", "title": "ados-profile-v1.23.zip vs ados-profile-v2.0.zip",
                     "text": ("ados-profile-v1.23 " * 18 + "ados-profile-v2.0 " * 8
                              + "ados-profile: do not approve v2.0 as a clean successor to v1.23 yet.")})
        recs.append({"chat_id": "B", "title": "ADOS Profile v1.23 release",
                     "text": "ados-profile-v1.23 " * 6})
        # 2.0: newest but unstable; second chat to satisfy min_chats
        recs.append({"chat_id": "C", "title": "ados-profile-v2.0 drift",
                     "text": "ados-profile-v2.0 " * 3})
        # 1.24: a higher-numbered *attempt* with little support -> not stable.
        # Titles intentionally unqualified so the attempt stays well under the
        # support floor (mirrors the real catalog: ~7 mentions vs a 117 mode).
        recs.append({"chat_id": "D", "title": "upgrade attempt notes",
                     "text": "ados-profile-v1.24 "})
        recs.append({"chat_id": "E", "title": "more upgrade notes",
                     "text": "ados-profile-v1.24 "})
        return recs

    def test_build_verdicts(self):
        doc = ent.build_entities(self._records())
        self.assertEqual(doc["summary"]["newest_overall"]["version"], "2.0")
        self.assertFalse(doc["summary"]["newest_overall"]["stable"])
        self.assertEqual(doc["summary"]["latest_stable"]["version"], "1.23")

    def test_support_floor_excludes_attempt(self):
        # 1.24 is numerically > 1.23 but under-supported -> never latest_stable
        versions = ent.build_entities(self._records())["versions"]
        stable = ent.select_latest_stable(versions)
        self.assertEqual(stable["version"], "1.23")

    def test_newest_chat_citation_present(self):
        doc = ent.build_entities(self._records())
        self.assertIn(doc["summary"]["newest_overall"]["chat_id"], {"A", "C"})


class TestIntentRouting(unittest.TestCase):
    def test_latest_stable_intent(self):
        self.assertEqual(
            ent.version_superlative_intent("What is the latest stable ados-profile version?"),
            "latest_stable")

    def test_newest_intent_even_with_stable_clause(self):
        self.assertEqual(
            ent.version_superlative_intent("What is the newest ados-profile version overall, and is it stable?"),
            "newest")

    def test_why_question_not_routed(self):
        # explanation request must reach normal synthesis
        self.assertIsNone(ent.version_superlative_intent(
            "Why is ados-profile v2.0 not stable or approved as a clean successor to v1.23?"))

    def test_non_superlative_not_routed(self):
        self.assertIsNone(ent.version_superlative_intent(
            "Were there attempts to move from 1.23 to 1.24 and to 2.0?"))
        self.assertIsNone(ent.version_superlative_intent(
            "What is the rule for README.md vs CHANGELOG.md regarding version numbers?"))
        self.assertIsNone(ent.version_superlative_intent(
            "What is the ados-geometry concept?"))


class TestAnswer(unittest.TestCase):
    def setUp(self):
        self.doc = ent.build_entities([
            {"chat_id": "A", "title": "ados-profile-v1.23.zip vs ados-profile-v2.0.zip",
             "text": ("ados-profile-v1.23 " * 18 + "ados-profile-v2.0 " * 8
                      + "ados-profile: do not approve v2.0 as a clean successor to v1.23 yet.")},
            {"chat_id": "B", "title": "ADOS Profile v1.23 release", "text": "ados-profile-v1.23 " * 6},
            {"chat_id": "C", "title": "ados-profile-v2.0 drift", "text": "ados-profile-v2.0 " * 3},
        ])

    def test_latest_stable_answer_leads_with_version(self):
        r = ent.answer_version_query("What is the latest stable ados-profile version?", self.doc)
        self.assertEqual(r["version"], "1.23")
        self.assertTrue(r["answer"].strip().startswith("1.23"))

    def test_newest_answer_leads_with_version_and_notes_unstable(self):
        r = ent.answer_version_query("What is the newest ados-profile version overall?", self.doc)
        self.assertEqual(r["version"], "2.0")
        self.assertTrue(r["answer"].strip().startswith("2.0"))
        self.assertIn("not stable", r["answer"].lower())

    def test_none_for_non_version_question(self):
        self.assertIsNone(ent.answer_version_query("What is my favorite pizza topping?", self.doc))

    def test_none_without_entities(self):
        self.assertIsNone(ent.answer_version_query("What is the newest version?", None))


class TestPersistenceAndSchema(unittest.TestCase):
    def test_roundtrip_and_schema(self):
        import tempfile
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        doc = ent.build_entities([
            {"chat_id": "A", "title": "ados-profile-v1.23.zip", "text": "ados-profile-v1.23 " * 4},
        ])
        schema = json.load(open(os.path.join(ROOT, "schema", "entities.schema.json")))
        jsonschema.validate(doc, schema)
        with tempfile.TemporaryDirectory() as d:
            path = ent.write_entities(d, doc)
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(ent.load_entities(d)["product"], "ados-profile")
        self.assertIsNone(ent.load_entities("/nonexistent/index/dir"))


if __name__ == "__main__":
    unittest.main()
