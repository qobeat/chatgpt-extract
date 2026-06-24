"""Repo hygiene checks — committed files must not leak personal paths."""
from __future__ import annotations

import json
import os
import re
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")

PERSONAL_PATH_RE = re.compile(r"/mnt/c/Users/|/Users/[A-Za-z]+/")
FORBIDDEN_IN_COMMITTED_CONFIG = ("default_zips",)


class RepoHygieneTest(unittest.TestCase):
    def test_committed_config_has_no_personal_paths(self):
        path = os.path.join(ROOT, "config", "reconstruct.config.json")
        with open(path, encoding="utf-8") as f:
            raw = f.read()
        self.assertIsNone(PERSONAL_PATH_RE.search(raw), "personal path in committed config")
        cfg = json.loads(raw)
        for key in FORBIDDEN_IN_COMMITTED_CONFIG:
            self.assertNotIn(key, cfg, f"{key} should live in local config only")

    def test_public_schema_omits_conversation_ids(self):
        path = os.path.join(ROOT, "schema", "extracted_item_public_schema.json")
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        props = schema["properties"]["items"]["items"]["properties"]
        self.assertNotIn("source_conversation_ids", props)

    def test_gitignore_blocks_sensitive_paths(self):
        path = os.path.join(ROOT, ".gitignore")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        for needle in (
            ".env",
            "output/",
            "**/transcripts/",
            "reconstructed_projects.json",
            "config/reconstruct.config.local.json",
        ):
            self.assertIn(needle, content, f".gitignore missing {needle}")

    def test_published_placeholder_is_empty(self):
        path = os.path.join(ROOT, "published", "projects.json")
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        self.assertEqual(doc.get("n_items"), 0)
        self.assertEqual(doc.get("items"), [])

    def test_skills_have_no_personal_paths(self):
        for rel in (
            "skills/project-reconstruction/SKILL.md",
            "skills/chatgpt-export-triage/SKILL.md",
            "README.md",
        ):
            path = os.path.join(ROOT, rel)
            with open(path, encoding="utf-8") as f:
                raw = f.read()
            self.assertIsNone(
                PERSONAL_PATH_RE.search(raw),
                f"personal path in {rel}",
            )
            self.assertNotIn("kirae", raw.lower(), f"username in {rel}")


if __name__ == "__main__":
    unittest.main()
