"""Tests for gpt zips-verify / zip_verify."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import paths  # noqa: E402
import zip_verify  # noqa: E402
import zip_scan_cache  # noqa: E402


class ZipVerifyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "store")
        os.makedirs(self.store)

    tearDown = lambda self: self.tmp.cleanup()

    def _write_ledger_and_index(self):
        ledger = {
            "zips": {
                "new": {
                    "basename": "hash-2026-06-01-12-00-00-abc.zip",
                    "size": 1000,
                    "seen": 3, "added": 3, "updated": 0,
                    "skipped": 0, "written": 3,
                    "first_processed": "2026-06-01T00:00:00+00:00",
                    "last_processed": "2026-06-01T00:00:00+00:00",
                    "runs": 1,
                },
                "old": {
                    "basename": "hash-2025-10-01-12-00-00-xyz.zip",
                    "size": 500,
                    "seen": 1, "added": 1, "updated": 0,
                    "skipped": 0, "written": 1,
                    "first_processed": "2025-10-01T00:00:00+00:00",
                    "last_processed": "2025-10-01T00:00:00+00:00",
                    "runs": 1,
                },
            }
        }
        with open(os.path.join(self.store, "zip_ledger.json"), "w") as f:
            json.dump(ledger, f)
        index = {
            "c1": {"title": "A", "source_zip": "hash-2026-06-01-12-00-00-abc.zip", "update_date": "2026-06-01"},
            "c2": {"title": "B", "source_zip": "hash-2026-06-01-12-00-00-abc.zip", "update_date": "2026-06-02"},
            "c3": {"title": "C", "source_zip": "hash-2026-06-01-12-00-00-abc.zip", "update_date": "2026-06-03"},
            "c9": {"title": "Only old", "source_zip": "hash-2025-10-01-12-00-00-xyz.zip", "update_date": "2025-10-01"},
        }
        with open(os.path.join(self.store, "index.json"), "w") as f:
            json.dump(index, f)

    def test_verdict_ok_when_catalog_covers_exports(self):
        self._write_ledger_and_index()
        new_path = os.path.join(self.tmp.name, "hash-2026-06-01-12-00-00-abc.zip")
        old_path = os.path.join(self.tmp.name, "hash-2025-10-01-12-00-00-xyz.zip")
        open(new_path, "wb").close()
        open(old_path, "wb").close()

        def fake_ids(path: str):
            if path == new_path:
                return {"c1", "c2", "c3"}, 3, None
            if path == old_path:
                return {"c9"}, 1, None
            return set(), 0, "unknown"

        cfg = {
            "default_zips": [new_path, old_path],
            "export_search_dirs": [],
        }
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name}):
            with patch.object(zip_verify, "discover_zip_paths",
                              side_effect=lambda basenames, c=None: {
                                  "hash-2026-06-01-12-00-00-abc.zip": new_path,
                                  "hash-2025-10-01-12-00-00-xyz.zip": old_path,
                              }):
                with patch.object(zip_verify, "conversation_ids_in_zip", side_effect=fake_ids):
                    with patch.object(paths, "load_config", return_value=cfg):
                        rep = zip_verify.zip_verify()
        self.assertEqual(rep["verdict"], "ok")
        self.assertEqual(rep["n_catalog"], 4)
        self.assertEqual(rep["n_older_only"], 1)
        self.assertTrue(all(c["ok"] for c in rep["checks"]
                            if c["id"] != "ownership_balance"))

    def test_cached_ids_avoid_reopening_zip(self):
        """When the hash cache has ids for a zip, conversation_ids_in_zip is
        never called (no archive open)."""
        self._write_ledger_and_index()
        new_path = os.path.join(self.tmp.name, "hash-2026-06-01-12-00-00-abc.zip")
        old_path = os.path.join(self.tmp.name, "hash-2025-10-01-12-00-00-xyz.zip")
        with open(new_path, "wb") as f:
            f.write(b"new-export-bytes")
        with open(old_path, "wb") as f:
            f.write(b"old-export-different-bytes")

        # Pre-populate the scan cache for both exports.
        zip_scan_cache.put_ids(self.store, new_path, {"c1", "c2", "c3"})
        zip_scan_cache.put_ids(self.store, old_path, {"c9"})

        cfg = {"default_zips": [new_path, old_path], "export_search_dirs": []}
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name}):
            with patch.object(zip_verify, "discover_zip_paths",
                              side_effect=lambda basenames, c=None: {
                                  "hash-2026-06-01-12-00-00-abc.zip": new_path,
                                  "hash-2025-10-01-12-00-00-xyz.zip": old_path,
                              }):
                with patch.object(zip_verify, "conversation_ids_in_zip") as scan:
                    with patch.object(paths, "load_config", return_value=cfg):
                        rep = zip_verify.zip_verify()
        scan.assert_not_called()
        self.assertEqual(rep["verdict"], "ok")
        self.assertEqual(rep["n_zips_from_cache"], 2)
        self.assertEqual(rep["n_zips_scanned"], 0)

    def test_force_zip_read_bypasses_cache(self):
        """--force-zip-read re-opens every export even when cached."""
        self._write_ledger_and_index()
        new_path = os.path.join(self.tmp.name, "hash-2026-06-01-12-00-00-abc.zip")
        old_path = os.path.join(self.tmp.name, "hash-2025-10-01-12-00-00-xyz.zip")
        with open(new_path, "wb") as f:
            f.write(b"new-export-bytes")
        with open(old_path, "wb") as f:
            f.write(b"old-export-different-bytes")
        zip_scan_cache.put_ids(self.store, new_path, {"c1", "c2", "c3"})
        zip_scan_cache.put_ids(self.store, old_path, {"c9"})

        def fake_ids(path: str):
            if path == new_path:
                return {"c1", "c2", "c3"}, 3, None
            return {"c9"}, 1, None

        cfg = {"default_zips": [new_path, old_path], "export_search_dirs": []}
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name}):
            with patch.object(zip_verify, "discover_zip_paths",
                              side_effect=lambda basenames, c=None: {
                                  "hash-2026-06-01-12-00-00-abc.zip": new_path,
                                  "hash-2025-10-01-12-00-00-xyz.zip": old_path,
                              }):
                with patch.object(zip_verify, "conversation_ids_in_zip",
                                  side_effect=fake_ids) as scan:
                    with patch.object(paths, "load_config", return_value=cfg):
                        rep = zip_verify.zip_verify(force_zip_read=True)
        self.assertEqual(scan.call_count, 2)
        self.assertEqual(rep["n_zips_scanned"], 2)
        self.assertEqual(rep["n_zips_from_cache"], 0)
        self.assertTrue(rep["forced_zip_read"])

    def test_verdict_issues_when_newest_missing_from_catalog(self):
        self._write_ledger_and_index()
        new_path = os.path.join(self.tmp.name, "export-new.zip")
        open(new_path, "wb").close()

        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name}):
            with patch.object(zip_verify, "discover_zip_paths",
                              return_value={"hash-2026-06-01-12-00-00-abc.zip": new_path,
                                            "hash-2025-10-01-12-00-00-xyz.zip": None}):
                with patch.object(zip_verify, "conversation_ids_in_zip",
                                  return_value=({"c1", "c2", "c3", "cX"}, 4, None)):
                    rep = zip_verify.zip_verify()
        self.assertEqual(rep["verdict"], "issues")
        newest_check = next(c for c in rep["checks"] if c["id"] == "newest_in_catalog")
        self.assertFalse(newest_check["ok"])


if __name__ == "__main__":
    unittest.main()
