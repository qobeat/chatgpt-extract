"""Unit tests for --limit and skip-before-build in extract_cards.py."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))

import extract_cards  # noqa: E402


def _conv(cid: str, ut: float, title: str = "t") -> dict:
    return {
        "id": cid,
        "title": title,
        "update_time": ut,
        "create_time": ut - 100,
        "mapping": {},
        "current_node": None,
    }


class ExtractLimitTest(unittest.TestCase):
    def test_limit_stops_after_n_writes(self):
        convs = [_conv(f"id{i}", float(i)) for i in range(10)]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "store")
            os.makedirs(out, exist_ok=True)
            argv = [
                "extract_cards.py",
                "--zip", "/fake.zip",
                "--out", out,
                "--limit", "3",
            ]
            real_exists = os.path.exists

            def exists(path):
                if path == "/fake.zip":
                    return True
                return real_exists(path)

            with patch.object(extract_cards, "iter_conversations", return_value=iter(convs)):
                with patch.object(extract_cards, "build_card", side_effect=lambda c: {
                    "id": c["id"],
                    "title": c["title"],
                    "create_time": c["create_time"],
                    "update_time": c["update_time"],
                    "transcript": f"body {c['id']}",
                    "zip_files": [],
                    "file_artifacts": [],
                    "slug_votes": {},
                    "n_turns": 1,
                }):
                    with patch("extract_cards.os.path.exists", side_effect=exists):
                        with patch("sys.argv", argv):
                            rc = extract_cards.main()
            self.assertEqual(rc, 0)
            index_path = os.path.join(out, "index.json")
            self.assertTrue(os.path.exists(index_path))
            import json
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
            self.assertEqual(len(index), 3)

    def test_skip_before_build_skips_unchanged(self):
        """Unchanged conversations should not call build_card."""
        conv = _conv("same-id", 100.0)
        build_calls = []

        def fake_build(c):
            build_calls.append(c["id"])
            return {
                "id": c["id"],
                "title": "t",
                "create_time": 0,
                "update_time": c.get("update_time", 100.0),
                "transcript": "x",
                "zip_files": [],
                "file_artifacts": [],
                "slug_votes": {},
                "n_turns": 1,
            }

        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "store")
            os.makedirs(out, exist_ok=True)
            import json
            with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
                json.dump({"same-id": {"update_time": 100.0}}, f)
            argv = ["extract_cards.py", "--zip", "/fake.zip", "--out", out]
            real_exists = os.path.exists

            def exists(path):
                if path == "/fake.zip":
                    return True
                return real_exists(path)

            with patch.object(extract_cards, "iter_conversations", return_value=iter([conv])):
                with patch.object(extract_cards, "build_card", side_effect=fake_build):
                    with patch("extract_cards.os.path.exists", side_effect=exists):
                        with patch("sys.argv", argv):
                            extract_cards.main()
            self.assertEqual(build_calls, [])


if __name__ == "__main__":
    unittest.main()
