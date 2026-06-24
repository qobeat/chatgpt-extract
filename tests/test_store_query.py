"""Tests for the read-only store queries behind `gpt list/search/info`."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import store_query as sq  # noqa: E402


def _seed(root: str) -> None:
    store = os.path.join(root, "store")
    os.makedirs(store)
    clusters = [
        {"slug": "ados-profile", "titles": ["ADOS Profile"], "n_conversations": 304,
         "n_versions": 1275, "start_date": "2024-12-06", "end_date": "2026-06-19"},
        {"slug": "skip-meeting", "titles": ["Skip Meeting"], "n_conversations": 6,
         "n_versions": 0, "start_date": "2023-09-22", "end_date": "2023-09-22"},
        {"slug": "lonely", "titles": ["Lonely"], "n_conversations": 1,
         "n_versions": 0, "start_date": "2025-01-01", "end_date": "2025-01-01"},
    ]
    with open(os.path.join(store, "clusters.json"), "w") as f:
        json.dump(clusters, f)
    cards = [
        {"id": "a1", "title": "ADOS Profile chat", "update_date": "2026-06-19",
         "n_turns": 10, "signals": {"n_turns": 10, "n_user_turns": 4,
                                    "n_assistant_turns": 6, "content_types": {"text": 10},
                                    "file_ext_classes": {"code": 2}}},
        {"id": "b2", "title": "Skip the meeting", "update_date": "2023-09-22",
         "n_turns": 4, "signals": {"n_turns": 4, "n_user_turns": 2,
                                   "n_assistant_turns": 2, "content_types": {"text": 4},
                                   "file_ext_classes": {}}},
    ]
    with open(os.path.join(store, "cards.jsonl"), "w") as f:
        for c in cards:
            f.write(json.dumps(c) + "\n")


class StoreQueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _seed(self.tmp.name)
        self.env = patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_list_projects_filters_singletons(self):
        rows = sq.list_projects()
        slugs = [r["slug"] for r in rows]
        self.assertIn("ados-profile", slugs)
        self.assertIn("skip-meeting", slugs)
        self.assertNotIn("lonely", slugs)  # 1 conv, 0 versions

    def test_list_projects_sorted_by_versions(self):
        rows = sq.list_projects()
        self.assertEqual(rows[0]["slug"], "ados-profile")

    def test_glob_substring_and_wildcard(self):
        self.assertEqual([r["slug"] for r in sq.list_projects("ados")],
                         ["ados-profile"])
        self.assertEqual([r["slug"] for r in sq.list_projects("*meeting")],
                         ["skip-meeting"])

    def test_search_mixes_projects_and_chats(self):
        rows = sq.search("meeting", limit=10)
        kinds = {r["kind"] for r in rows}
        self.assertIn("project", kinds)
        self.assertIn("chat", kinds)

    def test_info_aggregates_signals(self):
        s = sq.info_stats()
        self.assertEqual(s["n_chats"], 2)
        self.assertEqual(s["n_turns"], 14)
        self.assertEqual(s["content_types"]["text"], 14)
        self.assertEqual(s["date_min"], "2023-09-22")
        self.assertEqual(s["date_max"], "2026-06-19")

    def test_catalog_state_no_store(self):
        with tempfile.TemporaryDirectory() as empty:
            with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": empty}):
                st = sq.catalog_state()
                self.assertFalse(st["has_store"])
                self.assertEqual(st["n_chats"], 0)


if __name__ == "__main__":
    unittest.main()
