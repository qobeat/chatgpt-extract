"""
Catalog feature, CLI level — `gpt list / search / show` (README feature 1).

`test_store_query.py` covers the query layer; this drives the actual gpt_cli
command handlers end-to-end (argv parsing -> stdout) over a seeded data root,
so the user-facing Catalog commands and their flags (-i/-w/-a/-f, --chats,
globs, SLUG lookup, --json) are regression-locked.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
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
        {"slug": "lonely", "titles": ["Lonely"], "n_conversations": 1,
         "n_versions": 0, "start_date": "2025-01-01", "end_date": "2025-01-01"},
    ]
    with open(os.path.join(store, "clusters.json"), "w") as f:
        json.dump(clusters, f)
    cards = [
        {"id": "a1", "title": "ADOS Profile chat", "update_date": "2026-06-19",
         "n_turns": 10, "attachments": ["usage_events.csv"],
         "file_artifacts": ["usage_events.csv", "run.py"],
         "signals": {"n_turns": 10, "content_types": {"text": 10}}},
        {"id": "b2", "title": "Skip the meeting", "update_date": "2023-09-22",
         "n_turns": 4, "attachments": [], "file_artifacts": [],
         "signals": {"n_turns": 4, "content_types": {"text": 4}}},
    ]
    with open(os.path.join(store, "cards.jsonl"), "w") as f:
        for c in cards:
            f.write(json.dumps(c) + "\n")
    tdir = os.path.join(store, "transcripts")
    os.makedirs(tdir)
    with open(os.path.join(tdir, "a1.txt"), "w") as f:
        f.write("[user] Please analyze the USAGE_EVENTS trends\n\n"
                "[assistant] Here is the breakdown of usage patterns.")
    with open(os.path.join(tdir, "b2.txt"), "w") as f:
        f.write("[user] How do I skip a meeting politely?\n\n"
                "[assistant] The usaged metric is unrelated here.")


def _run(fn, argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = fn(argv)
    return code, buf.getvalue()


def _json(fn, argv: list[str]) -> tuple[int, object]:
    code, out = _run(fn, argv)
    return code, json.loads(out)


class CatalogListTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _seed(self.tmp.name)
        self.env = patch.dict(os.environ,
                              {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_list_projects_default_hides_singletons(self):
        code, rows = _json(gpt_cli.cmd_list, ["--json"])
        self.assertEqual(code, 0)
        slugs = [r["slug"] for r in rows]
        self.assertIn("ados-profile", slugs)
        self.assertIn("skip-meeting", slugs)
        self.assertNotIn("lonely", slugs)

    def test_list_projects_glob(self):
        code, rows = _json(gpt_cli.cmd_list, ["ados", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([r["slug"] for r in rows], ["ados-profile"])

    def test_list_chats_glob(self):
        code, rows = _json(gpt_cli.cmd_list, ["--chats", "*ADOS*", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in rows], ["a1"])

    def test_list_text_output_renders(self):
        code, out = _run(gpt_cli.cmd_list, [])
        self.assertEqual(code, 0)
        self.assertIn("ados-profile", out)
        self.assertIn("projects)", out)


class CatalogSearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _seed(self.tmp.name)
        self.env = patch.dict(os.environ,
                              {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_search_case_sensitive_default_misses(self):
        code, rows = _json(gpt_cli.cmd_search, ["usage_events", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(rows, [])

    def test_search_ignore_case_i(self):
        code, rows = _json(gpt_cli.cmd_search, ["-i", "usage_events", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in rows], ["a1"])

    def test_search_whole_word_w(self):
        code, rows = _json(gpt_cli.cmd_search, ["-w", "-i", "usage", "--json"])
        self.assertEqual(code, 0)
        # whole-word "usage" matches a1 ("usage patterns"), not b2's "usaged".
        self.assertEqual([r["id"] for r in rows], ["a1"])

    def test_search_attachments_f(self):
        code, rows = _json(gpt_cli.cmd_search, ["-f", "*.csv", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in rows], ["a1"])

    def test_search_scope_all_a_matches_filename(self):
        # run.py is in a1's file_artifacts but not its transcript text.
        _, text_only = _json(gpt_cli.cmd_search, ["run.py", "--json"])
        self.assertEqual(text_only, [])
        code, rows = _json(gpt_cli.cmd_search, ["-a", "run.py", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual([r["id"] for r in rows], ["a1"])


class CatalogShowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _seed(self.tmp.name)
        self.env = patch.dict(os.environ,
                              {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_show_slug_found(self):
        code, rec = _json(gpt_cli.cmd_show, ["ados-profile", "--json"])
        self.assertEqual(code, 0)
        self.assertEqual(rec["slug"], "ados-profile")
        self.assertEqual(rec["n_versions"], 1275)

    def test_show_missing_slug_returns_error(self):
        code, rec = _json(gpt_cli.cmd_show, ["does-not-exist", "--json"])
        self.assertEqual(code, 1)
        self.assertFalse(rec["found"])


if __name__ == "__main__":
    unittest.main()
