"""Unit tests for run-scoped path isolation in scripts/lib/paths.py."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import paths  # noqa: E402


class RunLabelPathsTest(unittest.TestCase):
    def test_run_root_under_output(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RECONSTRUCTOR_DATA_ROOT", None)
            root = paths.run_root("modeltest")
            self.assertTrue(root.endswith(os.path.join("output", "runs", "modeltest")))

    def test_run_label_isolates_store_bundles_json(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RECONSTRUCTOR_DATA_ROOT", None)
            store = paths.store_dir(run_label="modeltest")
            bundles = paths.bundles_dir(run_label="modeltest")
            out_json = paths.reconstructed_json(run_label="modeltest")
            self.assertTrue(store.endswith(os.path.join("runs", "modeltest", "store")))
            self.assertTrue(bundles.endswith(os.path.join("runs", "modeltest", "bundles")))
            self.assertTrue(
                out_json.endswith(
                    os.path.join("runs", "modeltest", "reconstructed_projects.json")
                )
            )

    def test_explicit_overrides_run_label(self):
        self.assertEqual(
            paths.store_dir("/custom/store", run_label="ignored"),
            "/custom/store",
        )

    def test_run_data_root_with_label(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RECONSTRUCTOR_DATA_ROOT", None)
            root = paths.run_data_root(run_label="abc")
            self.assertTrue(root.endswith(os.path.join("output", "runs", "abc")))

    def test_update_latest_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": tmp}):
                ptr = paths.update_latest_pointer("myrun")
                self.assertTrue(os.path.exists(ptr))
                if os.path.islink(ptr):
                    self.assertTrue(os.readlink(ptr).endswith(
                        os.path.join("runs", "myrun")
                    ))
                else:
                    with open(ptr, encoding="utf-8") as f:
                        self.assertEqual(f.read().strip(), "myrun")

    def test_run_label_with_env_data_root(self):
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": "/tmp/cgpt-data"}):
            store = paths.store_dir(run_label="t1")
            self.assertEqual(store, "/tmp/cgpt-data/runs/t1/store")


if __name__ == "__main__":
    unittest.main()
