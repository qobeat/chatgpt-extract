"""Unit tests for scripts/lib/paths.py."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import paths  # noqa: E402


class PathsTest(unittest.TestCase):
    def test_defaults_without_env(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("RECONSTRUCTOR_DATA_ROOT", None)
            self.assertIsNone(paths.data_root())
            self.assertTrue(paths.store_dir().endswith(os.path.join("output", "store")))
            self.assertTrue(paths.bundles_dir().endswith(os.path.join("output", "bundles")))
            self.assertTrue(
                paths.reconstructed_json().endswith(
                    os.path.join("output", "reconstructed_projects.json")
                )
            )

    def test_env_data_root(self):
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": "/tmp/cgpt-data"}):
            self.assertEqual(paths.data_root(), "/tmp/cgpt-data")
            self.assertEqual(paths.store_dir(), "/tmp/cgpt-data/store")
            self.assertEqual(paths.bundles_dir(), "/tmp/cgpt-data/bundles")
            self.assertEqual(
                paths.reconstructed_json(),
                "/tmp/cgpt-data/reconstructed_projects.json",
            )

    def test_tilde_expansion(self):
        with patch.dict(os.environ, {"RECONSTRUCTOR_DATA_ROOT": "~/my-data"}):
            self.assertEqual(paths.data_root(), os.path.expanduser("~/my-data"))

    def test_explicit_overrides(self):
        self.assertEqual(paths.store_dir("/custom/store"), "/custom/store")
        self.assertEqual(paths.bundles_dir("/custom/bundles"), "/custom/bundles")
        self.assertEqual(paths.reconstructed_json("/custom/out.json"), "/custom/out.json")
        self.assertEqual(paths.published_json("/custom/pub.json"), "/custom/pub.json")

    def test_published_json_default_under_repo(self):
        pub = paths.published_json()
        self.assertTrue(pub.endswith(os.path.join("published", "projects.json")))


if __name__ == "__main__":
    unittest.main()
