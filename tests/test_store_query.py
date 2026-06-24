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
         "n_versions": 1275, "start_date": "2024-12-06", "end_date": "2026-06-19",
         "member_ids": ["a1"]},
        {"slug": "skip-meeting", "titles": ["Skip Meeting"], "n_conversations": 6,
         "n_versions": 0, "start_date": "2023-09-22", "end_date": "2023-09-22",
         "member_ids": ["b2"]},
        {"slug": "sat-app", "titles": ["SAT App"], "n_conversations": 3,
         "n_versions": 5, "start_date": "2025-01-01", "end_date": "2026-01-01",
         "member_ids": []},
        {"slug": "startup-ideas", "titles": ["Startup Ideas"], "n_conversations": 2,
         "n_versions": 0, "start_date": "2025-06-01", "end_date": "2025-06-02",
         "member_ids": []},
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
    recon = {
        "items": [
            {
                "slug": "ados-profile",
                "title": "ADOS Profile",
                "is_durable_project": True,
                "primary_archetype": {"id": "controlled_spec_or_schema"},
                "goal": "Govern ADOS",
                "n_passes": 1275,
            },
            {
                "slug": "skip-meeting",
                "title": "Skip Meeting",
                "is_durable_project": False,
                "primary_archetype": {"id": "personal_admin"},
                "goal": "Skip a meeting",
            },
            {
                "slug": "sat-app",
                "title": "SAT App",
                "is_durable_project": True,
                "primary_archetype": {"id": "software_app"},
                "goal": "Build SAT app",
                "n_passes": 5,
            },
            {
                "slug": "startup-ideas",
                "title": "Startup Ideas",
                "is_durable_project": False,
                "primary_archetype": {"id": "knowledge_qa"},
                "goal": "Brainstorm startups",
            },
        ]
    }
    with open(os.path.join(root, "reconstructed_projects.json"), "w") as f:
        json.dump(recon, f)


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

    def test_zip_status_ledger_and_source(self):
        store = os.path.join(self.tmp.name, "store")
        ledger = {
            "zips": {
                "abc": {
                    "basename": "export-a.zip",
                    "seen": 10, "added": 10, "updated": 0,
                    "skipped": 0, "written": 10,
                    "first_processed": "2026-01-01T00:00:00+00:00",
                    "last_processed": "2026-01-01T00:00:00+00:00",
                    "runs": 1,
                }
            }
        }
        with open(os.path.join(store, "zip_ledger.json"), "w") as f:
            json.dump(ledger, f)
        index = {
            "id1": {"title": "t", "source_zip": "export-a.zip"},
            "id2": {"title": "u", "source_zip": "export-a.zip"},
            "id3": {"title": "v", "source_zip": "export-b.zip"},
        }
        with open(os.path.join(store, "index.json"), "w") as f:
            json.dump(index, f)

        st = sq.zip_status(check_paths=["/tmp/export-c.zip"])
        self.assertTrue(st["has_ledger"])
        self.assertEqual(st["n_chats_in_store"], 3)
        by_name = {e["basename"]: e for e in st["entries"]}
        self.assertEqual(by_name["export-a.zip"]["status"], "full")
        self.assertEqual(by_name["export-a.zip"]["chats_in_store"], 2)
        self.assertEqual(by_name["export-b.zip"]["status"], "indexed")
        self.assertEqual(by_name["export-c.zip"]["status"], "missing")

    def test_item_categories(self):
        items = sq.load_summary_items()
        self.assertEqual(sq.item_categories(items["sat-app"]), ["app", "project"])
        self.assertEqual(sq.item_categories(items["startup-ideas"]), ["idea"])
        self.assertEqual(sq.item_categories(items["ados-profile"]), ["project"])

    def test_list_projects_enriched_glob_and_chats(self):
        rows = sq.list_projects_enriched("ados")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["slug"], "ados-profile")
        self.assertEqual(rows[0]["categories"], ["project"])
        self.assertEqual(len(rows[0]["chats"]), 1)
        self.assertEqual(rows[0]["chats"][0]["id"], "a1")

    def test_list_category_tree(self):
        tree = sq.list_category_tree(categories=["app", "idea"])
        self.assertEqual([p["slug"] for p in tree["categories"]["app"]], ["sat-app"])
        self.assertEqual([p["slug"] for p in tree["categories"]["idea"]],
                         ["startup-ideas"])
        full = sq.list_category_tree(include_uncategorized=True)
        self.assertIn("uncategorized_chats", full)
        self.assertEqual(full["n_total_chats"], 2)


if __name__ == "__main__":
    unittest.main()
