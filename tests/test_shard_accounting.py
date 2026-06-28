"""Shard-level accounting (FR-C1/C2): a multi-shard export must never lose a
shard silently (F1) nor let one bad shard abort the whole run (F2).

`iter_conversations` isolates each shard: a valid-but-unrecognized shard yields
0, a corrupt shard raises-and-is-skipped, and both lower `shards_parsed` below
`shards_total` so the caller can flag a visible coverage miss. These tests use
the dependency-light stdlib path (no ijson required) but the outcomes hold for
both backends.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import chatgpt_parse as cp  # noqa: E402


def _conv(cid: str) -> dict:
    return {"id": cid, "title": cid.upper(), "mapping": {}}


def _make_zip(path: str, shards: dict[str, str]) -> None:
    """Write a zip whose members are the given {name: raw_json_text} shards."""
    with zipfile.ZipFile(path, "w") as zf:
        for name, raw in shards.items():
            zf.writestr(name, raw)


class ShardAccountingTest(unittest.TestCase):
    def test_silent_loss_becomes_visible_miss(self):
        # 3 shards: good (2 chats), valid-but-unrecognized (0), corrupt (raises).
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "export.zip")
            _make_zip(zp, {
                "conversations-000.json": json.dumps([_conv("a"), _conv("b")]),
                # Recognizable-JSON but not a conversation container -> 0 yield.
                "conversations-001.json": json.dumps({"data": [_conv("c")]}),
                # Truncated/garbage JSON -> parse raises mid-shard.
                "conversations-002.json": '{ "mapping": ',
            })
            stats: dict = {}
            ids = [c["id"] for c in cp.iter_conversations(zp, shard_stats=stats)]

        # The good shard's chats survive; the lost shard does NOT vanish silently.
        self.assertEqual(sorted(ids), ["a", "b"])
        self.assertEqual(stats["shards_total"], 3)
        self.assertEqual(stats["shards_parsed"], 1)
        self.assertLess(stats["shards_parsed"], stats["shards_total"])

    def test_corrupt_shard_does_not_abort_run(self):
        # A corrupt shard in the middle must be skipped, not raise to the caller,
        # so a later good shard is still yielded (no all-or-nothing abort).
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "export.zip")
            _make_zip(zp, {
                "conversations-000.json": "{ not valid json",
                "conversations-001.json": json.dumps([_conv("z")]),
            })
            stats: dict = {}
            ids = [c["id"] for c in cp.iter_conversations(zp, shard_stats=stats)]
        self.assertEqual(ids, ["z"])
        self.assertEqual((stats["shards_total"], stats["shards_parsed"]), (2, 1))

    def test_all_shards_good_parsed_equals_total(self):
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "export.zip")
            _make_zip(zp, {
                "conversations-000.json": json.dumps([_conv("a")]),
                "conversations-001.json": json.dumps([_conv("b"), _conv("c")]),
            })
            stats: dict = {}
            ids = [c["id"] for c in cp.iter_conversations(zp, shard_stats=stats)]
        self.assertEqual(sorted(ids), ["a", "b", "c"])
        self.assertEqual((stats["shards_total"], stats["shards_parsed"]), (2, 2))

    def test_all_shards_fail_raises_runtimeerror(self):
        # When nothing parses anywhere, the loud global failure is preserved.
        with tempfile.TemporaryDirectory() as tmp:
            zp = os.path.join(tmp, "export.zip")
            _make_zip(zp, {
                "conversations-000.json": "{ broken",
                "conversations-001.json": json.dumps({"data": [_conv("x")]}),
            })
            stats: dict = {}
            with self.assertRaises(RuntimeError):
                list(cp.iter_conversations(zp, shard_stats=stats))
            self.assertEqual((stats["shards_total"], stats["shards_parsed"]), (2, 0))


if __name__ == "__main__":
    unittest.main()
