"""Tests for the per-zip conversation-id hash cache (zip_scan_cache)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import zip_scan_cache  # noqa: E402


class ZipScanCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = os.path.join(self.tmp.name, "store")
        os.makedirs(self.store)

    tearDown = lambda self: self.tmp.cleanup()

    def _write(self, name: str, content: bytes) -> str:
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_round_trip(self):
        zp = self._write("export.zip", b"some zip-ish bytes")
        self.assertIsNone(zip_scan_cache.get_ids(self.store, zp))
        zip_scan_cache.put_ids(self.store, zp, {"c1", "c2", "c3"})
        self.assertEqual(zip_scan_cache.get_ids(self.store, zp), {"c1", "c2", "c3"})

    def test_hash_change_misses(self):
        zp = self._write("export.zip", b"original content")
        zip_scan_cache.put_ids(self.store, zp, {"c1"})
        self.assertEqual(zip_scan_cache.get_ids(self.store, zp), {"c1"})
        # Replace the file contents -> fingerprint changes -> cache miss.
        with open(zp, "wb") as f:
            f.write(b"totally different and longer content now")
        self.assertIsNone(zip_scan_cache.get_ids(self.store, zp))

    def test_basename_guard_blocks_collision(self):
        """Two files with identical content (same hash) but different names must
        not share a cache entry."""
        content = b"identical bytes here"
        a = self._write("a.zip", content)
        b = self._write("b.zip", content)
        zip_scan_cache.put_ids(self.store, a, {"only-a"})
        # Same content_hash, different basename -> guarded miss, not a false hit.
        self.assertIsNone(zip_scan_cache.get_ids(self.store, b))
        self.assertEqual(zip_scan_cache.get_ids(self.store, a), {"only-a"})

    def test_missing_file_returns_none(self):
        self.assertIsNone(
            zip_scan_cache.get_ids(self.store, os.path.join(self.tmp.name, "nope.zip")))
        self.assertIsNone(
            zip_scan_cache.put_ids(self.store, os.path.join(self.tmp.name, "nope.zip"),
                                   {"x"}))

    def test_corrupt_cache_file_tolerated(self):
        with open(zip_scan_cache.cache_path(self.store), "w") as f:
            f.write("{ not json")
        zp = self._write("export.zip", b"bytes")
        self.assertIsNone(zip_scan_cache.get_ids(self.store, zp))
        zip_scan_cache.put_ids(self.store, zp, {"c1"})
        self.assertEqual(zip_scan_cache.get_ids(self.store, zp), {"c1"})


if __name__ == "__main__":
    unittest.main()
