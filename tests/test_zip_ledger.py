"""Tests for the per-zip already-handled ledger."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import zip_ledger  # noqa: E402


def _write_zip(path: str, size: int, fill: bytes = b"x") -> None:
    with open(path, "wb") as f:
        f.write(fill * size)


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 4096)
            fp1 = zip_ledger.fingerprint(z)
            fp2 = zip_ledger.fingerprint(z)
            self.assertEqual(fp1["content_hash"], fp2["content_hash"])
            self.assertEqual(fp1["size"], 4096)

    def test_rename_keeps_same_content_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.zip")
            b = os.path.join(tmp, "renamed.zip")
            _write_zip(a, 8192)
            _write_zip(b, 8192)
            self.assertEqual(
                zip_ledger.fingerprint(a)["content_hash"],
                zip_ledger.fingerprint(b)["content_hash"])

    def test_different_content_differs(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.zip")
            b = os.path.join(tmp, "b.zip")
            _write_zip(a, 4096, fill=b"x")
            _write_zip(b, 4096, fill=b"y")
            self.assertNotEqual(
                zip_ledger.fingerprint(a)["content_hash"],
                zip_ledger.fingerprint(b)["content_hash"])

    def test_large_file_hashes_head_and_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            z = os.path.join(tmp, "big.zip")
            # Larger than 2 * _CHUNK so head and tail both contribute.
            size = zip_ledger._CHUNK * 2 + 100
            with open(z, "wb") as f:
                f.write(b"H" * zip_ledger._CHUNK)
                f.write(b"M" * 100)
                f.write(b"T" * zip_ledger._CHUNK)
            h1 = zip_ledger.fingerprint(z)["content_hash"]
            # Change only the tail; hash must change.
            with open(z, "r+b") as f:
                f.seek(size - 10)
                f.write(b"Z" * 10)
            h2 = zip_ledger.fingerprint(z)["content_hash"]
            self.assertNotEqual(h1, h2)


class LedgerRoundTripTest(unittest.TestCase):
    def test_lookup_none_before_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 2048)
            self.assertIsNone(zip_ledger.lookup(store, z))

    def test_record_then_lookup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 2048)
            zip_ledger.record(store, z, {
                "seen": 10, "added": 7, "updated": 1, "skipped": 2, "written": 8,
            })
            entry = zip_ledger.lookup(store, z)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["seen"], 10)
            self.assertEqual(entry["added"], 7)
            self.assertEqual(entry["runs"], 1)
            self.assertTrue(os.path.exists(zip_ledger.ledger_path(store)))

    def test_record_persists_shard_accounting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 2048)
            zip_ledger.record(store, z, {
                "seen": 10, "written": 8,
                "shards_total": 3, "shards_parsed": 2,
            })
            entry = zip_ledger.lookup(store, z)
            self.assertEqual(entry["shards_total"], 3)
            self.assertEqual(entry["shards_parsed"], 2)

    def test_shard_keys_default_to_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 2048)
            entry = zip_ledger.record(store, z, {"seen": 5})
            self.assertEqual(entry["shards_total"], 0)
            self.assertEqual(entry["shards_parsed"], 0)

    def test_second_record_increments_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            z = os.path.join(tmp, "a.zip")
            _write_zip(z, 2048)
            first = zip_ledger.record(store, z, {"seen": 5})
            second = zip_ledger.record(store, z, {"seen": 5})
            self.assertEqual(first["runs"], 1)
            self.assertEqual(second["runs"], 2)
            self.assertEqual(first["first_processed"], second["first_processed"])

    def test_lookup_matches_renamed_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = os.path.join(tmp, "store")
            os.makedirs(store)
            a = os.path.join(tmp, "a.zip")
            b = os.path.join(tmp, "renamed.zip")
            _write_zip(a, 4096)
            _write_zip(b, 4096)
            zip_ledger.record(store, a, {"seen": 3})
            self.assertIsNotNone(zip_ledger.lookup(store, b))


if __name__ == "__main__":
    unittest.main()
