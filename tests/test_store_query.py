"""Tests for the read-only store queries behind `gpt list/search/info`."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import store_query as sq  # noqa: E402
import gpt_cli  # noqa: E402


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
         "n_turns": 10, "attachments": ["usage_events.csv"],
         "file_artifacts": ["usage_events.csv", "run.py"],
         "signals": {"n_turns": 10, "n_user_turns": 4,
                     "n_assistant_turns": 6, "content_types": {"text": 10},
                     "file_ext_classes": {"code": 2}}},
        {"id": "b2", "title": "Skip the meeting", "update_date": "2023-09-22",
         "n_turns": 4, "attachments": [], "file_artifacts": [],
         "signals": {"n_turns": 4, "n_user_turns": 2,
                     "n_assistant_turns": 2, "content_types": {"text": 4},
                     "file_ext_classes": {}}},
    ]
    with open(os.path.join(store, "cards.jsonl"), "w") as f:
        for c in cards:
            f.write(json.dumps(c) + "\n")
    tdir = os.path.join(store, "transcripts")
    os.makedirs(tdir)
    # a1 mentions usage_events in prose; b2 has unrelated text + a near-miss word.
    with open(os.path.join(tdir, "a1.txt"), "w") as f:
        f.write("[user] Please analyze the USAGE_EVENTS trends\n\n"
                "[assistant] Here is the breakdown of usage patterns.")
    with open(os.path.join(tdir, "b2.txt"), "w") as f:
        f.write("[user] How do I skip a meeting politely?\n\n"
                "[assistant] The usaged metric is unrelated here.")
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

    def test_search_transcripts_contains_case_sensitive(self):
        # Default is case-sensitive substring: lowercase pattern misses uppercase.
        self.assertEqual(sq.search_transcripts("usage_events"), [])
        # The pattern as it appears in b2 ("usaged") still matches as substring.
        rows = sq.search_transcripts("usaged")
        self.assertEqual([r["id"] for r in rows], ["b2"])

    def test_search_transcripts_ignore_case(self):
        rows = sq.search_transcripts("usage_events", ignore_case=True)
        self.assertEqual([r["id"] for r in rows], ["a1"])
        self.assertEqual(rows[0]["matched_in"], "text")
        self.assertIn("USAGE_EVENTS", rows[0]["snippet"])

    def test_search_transcripts_whole_word(self):
        # Whole-word "usaged" matches b2's standalone token; case-insensitive.
        rows = sq.search_transcripts("usaged", word=True, ignore_case=True)
        self.assertEqual([r["id"] for r in rows], ["b2"])
        # Whole-word "usage" matches a1 ("usage patterns") but NOT b2's "usaged"
        # nor a1's "USAGE_EVENTS" token (_ is a word char).
        rows = sq.search_transcripts("usage", word=True, ignore_case=True)
        self.assertEqual([r["id"] for r in rows], ["a1"])
        # Contains mode instead matches "usage" inside "usaged" and "usage…".
        rows = sq.search_transcripts("usage", ignore_case=True)
        self.assertEqual({r["id"] for r in rows}, {"a1", "b2"})

    def test_search_transcripts_scope_all_matches_filename(self):
        # "run.py" is in a1's file_artifacts but not its transcript text.
        self.assertEqual(sq.search_transcripts("run.py"), [])
        rows = sq.search_transcripts("run.py", scope_all=True)
        self.assertEqual([r["id"] for r in rows], ["a1"])
        self.assertEqual(rows[0]["matched_in"], "file")

    def test_search_attachments(self):
        rows = sq.search_attachments("usage_events.csv")
        self.assertEqual([r["id"] for r in rows], ["a1"])
        self.assertIn("usage_events.csv", rows[0]["matched_files"])
        # Glob over attachment/file names.
        rows = sq.search_attachments("*.csv")
        self.assertEqual([r["id"] for r in rows], ["a1"])

    def test_transcript_path(self):
        p = sq.transcript_path("a1")
        self.assertTrue(p.endswith(os.path.join("store", "transcripts", "a1.txt")))

    def test_read_transcript_and_chat_meta(self):
        self.assertIn("USAGE_EVENTS", sq.read_transcript("a1"))
        self.assertEqual(sq.read_transcript("missing"), "")
        meta = sq.chat_meta("a1")
        self.assertEqual(meta["title"], "ADOS Profile chat")
        self.assertEqual(meta["update_date"], "2026-06-19")
        self.assertEqual(meta["n_turns"], 10)
        self.assertIsNone(sq.chat_meta("nope"))

    def test_build_highlight_regex(self):
        # Case sensitivity.
        self.assertIsNone(sq.build_highlight_regex("usage_events").search(
            "the USAGE_EVENTS file"))
        self.assertTrue(sq.build_highlight_regex(
            "usage_events", ignore_case=True).search("the USAGE_EVENTS file"))
        # Whole-word excludes longer tokens.
        rx = sq.build_highlight_regex("usage", word=True, ignore_case=True)
        self.assertTrue(rx.search("plain usage here"))
        self.assertIsNone(rx.search("the usaged metric"))
        # Glob '?' spans a single char (matches both '-' and '_').
        rx = sq.build_highlight_regex("usage?events")
        self.assertTrue(rx.search("usage-events-2026.csv"))
        self.assertTrue(rx.search("usage_events.csv"))
        self.assertIsNone(sq.build_highlight_regex(""))

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


class ParseSearchStreamTest(unittest.TestCase):
    def test_extracts_ids_pattern_and_flags(self):
        stream = (
            '3 chat(s) matching "usage_events" in transcript text [-i -w]:\n'
            "UPDATED     TURNS  TITLE\n"
            "2026-05-03     44  Pokemon\n"
            "  id=aaa\n"
            "  [text] something\n"
            "2026-04-16     13  Cursor\n"
            "  id=bbb\n"
            "  id=aaa\n"  # duplicate should be dropped
        )
        out = gpt_cli._parse_search_stream(stream)
        self.assertEqual(out["ids"], ["aaa", "bbb"])
        self.assertEqual(out["pattern"], "usage_events")
        self.assertTrue(out["ignore_case"])
        self.assertTrue(out["word"])

    def test_no_flags_header(self):
        stream = ('1 chat(s) matching "meeting" in transcript text:\n'
                  "  id=zzz\n")
        out = gpt_cli._parse_search_stream(stream)
        self.assertEqual(out["ids"], ["zzz"])
        self.assertEqual(out["pattern"], "meeting")
        self.assertFalse(out["ignore_case"])
        self.assertFalse(out["word"])


class CatPlanTest(unittest.TestCase):
    def test_defaults_and_edges(self):
        plan = gpt_cli._plan_cat_parts([20], 50)
        self.assertFalse(plan["grep_mode"])
        p = plan["parts"][0]
        self.assertEqual((p["start"], p["end"], p["matched_line"], p["p"]),
                         (12, 23, 20, 1))
        self.assertEqual(p["end"] - p["start"], 11)  # Context: 11 lines
        # Edge match clamps to the file bounds.
        edge = gpt_cli._plan_cat_parts([2], 50)["parts"][0]
        self.assertEqual((edge["start"], edge["end"]), (1, 5))

    def test_multiple_parts_renumbered(self):
        parts = gpt_cli._plan_cat_parts([10, 30], 50)["parts"]
        self.assertEqual([(p["p"], p["start"], p["end"]) for p in parts],
                         [(1, 2, 13), (2, 22, 33)])

    def test_context_no_1_is_grep(self):
        plan = gpt_cli._plan_cat_parts([10, 30], 50, context_no=1)
        self.assertTrue(plan["grep_mode"])
        for p in plan["parts"]:
            self.assertEqual(p["start"], p["matched_line"])
            self.assertEqual(p["end"], p["matched_line"])

    def test_context_no_centered(self):
        p = gpt_cli._plan_cat_parts([20], 50, context_no=12)["parts"][0]
        # extra=11 -> above=5, below=6
        self.assertEqual((p["start"], p["end"]), (15, 26))

    def test_max_parts_and_reverse(self):
        fwd = gpt_cli._plan_cat_parts([10, 20, 30], 50, max_parts=1)["parts"]
        self.assertEqual([p["matched_line"] for p in fwd], [10])
        rev = gpt_cli._plan_cat_parts([10, 20, 30], 50, max_parts=1,
                                      reverse=True)["parts"]
        self.assertEqual([p["matched_line"] for p in rev], [30])

    def test_max_lines_forward_and_reverse(self):
        # Two 5-line blocks (before=after=2): 8..12 and 28..32.
        fwd = gpt_cli._plan_cat_parts([10, 30], 100, before=2, after=2,
                                      max_lines=7)["parts"]
        self.assertEqual([(p["start"], p["end"]) for p in fwd],
                         [(8, 12), (28, 29)])
        rev = gpt_cli._plan_cat_parts([10, 30], 100, before=2, after=2,
                                      max_lines=7, reverse=True)["parts"]
        self.assertEqual([(p["start"], p["end"]) for p in rev],
                         [(11, 12), (28, 32)])

    def test_grep_mode_max_lines(self):
        plan = gpt_cli._plan_cat_parts([10, 20, 30], 50, context_no=1,
                                       max_lines=2, reverse=True)
        self.assertEqual([p["matched_line"] for p in plan["parts"]], [20, 30])
        self.assertEqual(plan["total_found"], 3)


if __name__ == "__main__":
    unittest.main()
