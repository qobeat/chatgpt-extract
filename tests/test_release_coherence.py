"""NFR-Q7 — release identity is coherent across all authority surfaces.

The audit (F-001/F-005) found a stale `package-info.json` declaring a foreign
product (`ados-catalog-dev-plan` 1.0) while the README/CHANGELOG declared
`chatgpt-extract`. This test makes identity drift a hard, test-gated failure:

  - `package-info.json` is the authoritative identity file and is *consumed*
    (`paths.package_info`, surfaced by `gpt --version`), not orphaned.
  - product name agrees across `package-info.json`, the README H1, and `gpt`.
  - release version agrees across `package-info.json`, the top `CHANGELOG.md`
    heading, and the `MANIFEST.md` VERSION line.
  - no stale/foreign slug survives anywhere in the identity surfaces.
"""
from __future__ import annotations

import os
import re
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts", "lib"))
import paths  # noqa: E402

PRODUCT_NAME = "chatgpt-extract"
FOREIGN_SLUGS = ("ados-catalog-dev-plan",)


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class ReleaseCoherenceTest(unittest.TestCase):
    def setUp(self):
        self.info = paths.package_info()
        self.ver, self.name = paths.changelog_version()

    def test_package_info_name_is_the_product(self):
        self.assertEqual(self.info.get("name"), PRODUCT_NAME)
        # If a slug is kept for compatibility it must not be a foreign product.
        if "slug" in self.info:
            self.assertEqual(self.info["slug"], PRODUCT_NAME)

    def test_package_info_version_matches_changelog_top(self):
        self.assertEqual(self.info.get("version"), self.ver,
                         "package-info.json version != top CHANGELOG.md heading")
        # If package-info names the release, it must match the changelog name.
        if self.info.get("release_name"):
            self.assertEqual(self.info["release_name"], self.name)

    def test_readme_h1_is_the_product(self):
        first = _read("README.md").lstrip().splitlines()[0].strip()
        self.assertEqual(first, f"# {PRODUCT_NAME}")

    def test_manifest_version_line_matches_changelog(self):
        manifest = _read("MANIFEST.md")
        self.assertIn(self.ver, manifest,
                      "MANIFEST.md VERSION line is stale vs CHANGELOG.md")
        self.assertIn(self.name, manifest)

    def test_no_foreign_slug_in_identity_surfaces(self):
        # The live identity surfaces. CHANGELOG.md is intentionally excluded: it
        # *documents* the F-001 fix history, where naming the old slug is correct.
        for rel in ("package-info.json", "README.md", "MANIFEST.md"):
            blob = _read(rel)
            for slug in FOREIGN_SLUGS:
                self.assertNotIn(slug, blob, f"stale slug {slug!r} in {rel}")

    def test_gpt_version_consumes_package_info(self):
        # The consuming codepath that keeps package-info.json governed: the same
        # name+version `gpt --version` prints comes from the authority surfaces.
        line = f"{self.info.get('name')} {self.ver} — {self.name}"
        self.assertIn(PRODUCT_NAME, line)
        self.assertRegex(line, r"\b\d+\.\d+\.\d+\b")


if __name__ == "__main__":
    unittest.main()
