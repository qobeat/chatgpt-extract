"""NFR-Q8 — documentation & MANIFEST governance integrity.

Closes audit findings F-003 (broken internal links) and F-004 (incomplete
MANIFEST coverage) and keeps them closed:

  - every internal *relative* markdown link in the committed tree resolves;
  - every governed source subtree carries a `MANIFEST.md` per the documented
    scope in the root `MANIFEST.md` (skill leaf dirs are governed by `SKILL.md`).
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SKIP_DIRS = {"output", "__pycache__", ".git", "node_modules", ".pytest_cache"}
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _iter_markdown():
    for d, dirs, files in os.walk(ROOT):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for f in files:
            if f.endswith(".md"):
                yield os.path.join(d, f)


class DocLinkIntegrityTest(unittest.TestCase):
    def test_internal_relative_links_resolve(self):
        broken = []
        for path in _iter_markdown():
            base = os.path.dirname(path)
            with open(path, encoding="utf-8", errors="replace") as fh:
                for ln, line in enumerate(fh, 1):
                    for m in LINK_RE.finditer(line):
                        target = m.group(1).split()[0].split("#")[0].strip()
                        if not target or target.startswith(
                                ("http://", "https://", "mailto:", "#")):
                            continue
                        if target.startswith("/"):
                            resolved = os.path.join(ROOT, target.lstrip("/"))
                        else:
                            resolved = os.path.normpath(os.path.join(base, target))
                        if not os.path.exists(resolved):
                            rel = os.path.relpath(path, ROOT)
                            broken.append(f"{rel}:{ln} -> {target}")
        self.assertEqual(broken, [], "broken internal markdown links:\n" +
                         "\n".join(broken))


class ManifestCoverageTest(unittest.TestCase):
    # Governed source subtrees that MUST carry a MANIFEST.md (documented in the
    # root MANIFEST.md "MANIFEST COVERAGE" section).
    GOVERNED = [
        "config", "config/generated", "docs", "geometry", "ontology",
        "schema", "schema/ados", "scripts", "scripts/lib",
        "scripts/lib/providers", "published", "ados-vocabulary",
        ".github/workflows", "tests", "tests/fixtures", "skills",
    ]

    def test_governed_subtrees_have_a_manifest(self):
        missing = [d for d in self.GOVERNED
                   if not os.path.isfile(os.path.join(ROOT, d, "MANIFEST.md"))]
        self.assertEqual(missing, [], f"governed dirs missing MANIFEST.md: {missing}")

    def test_skill_leaf_dirs_are_governed_by_skill_md(self):
        skills = os.path.join(ROOT, "skills")
        leaves = [n for n in os.listdir(skills)
                  if os.path.isdir(os.path.join(skills, n))]
        self.assertTrue(leaves, "expected at least one skill")
        for name in leaves:
            self.assertTrue(
                os.path.isfile(os.path.join(skills, name, "SKILL.md")),
                f"skills/{name} must carry a SKILL.md (its manifest)")


if __name__ == "__main__":
    unittest.main()
