"""Unit tests for scripts/export_public.py sanitization (ADOS item schema)."""
from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")


def _load_export_public():
    spec = importlib.util.spec_from_file_location(
        "export_public",
        os.path.join(SCRIPTS, "export_public.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ep = _load_export_public()

SAMPLE = {
    "generated_by": "test",
    "provider": "ollama",
    "model": "gpt-oss:20b",
    "ontology_version": "1.0.0",
    "n_items": 1,
    "items": [
        {
            "item_id": "demo",
            "slug": "demo",
            "title": "Demo App",
            "is_durable_project": True,
            "primary_archetype": {"id": "software_app", "label": "App", "rationale": "r"},
            "primary_domain_pair": {"domain": "software_engineering", "subdomain": None},
            "start_date": "2026-01-01",
            "end_date": "2026-06-01",
            "n_conversations": 2,
            "n_passes": 1,
            "version_zip_files": [
                {"filename": "/mnt/c/Users/alice/Downloads/demo-v1.zip",
                 "slug": "demo", "version": "1"}
            ],
            "file_artifacts": ["app.py"],
            "source_conversation_ids": ["conv-secret-abc"],
            "member_ids": ["also-stripped"],
            "signal_summary": {"has_code": True},
            "bundle_sha": "deadbeef",
            "cost_usd": 0.0,
            "goal": "Build a demo app",
            "objectives": [{"text": "Ship MVP", "role": "forming"}],
            "archetype_fields": {"quickstart": "run it", "how_to_use": "click",
                                 "how_to_update": "bump v"},
        }
    ],
}


class ExportPublicTest(unittest.TestCase):
    def test_strips_provenance_and_internal_fields(self):
        out = ep.sanitize_item(SAMPLE["items"][0])
        for forbidden in ("source_conversation_ids", "member_ids",
                          "signal_summary", "bundle_sha", "cost_usd"):
            self.assertNotIn(forbidden, out)

    def test_keeps_classification(self):
        out = ep.sanitize_item(SAMPLE["items"][0])
        self.assertEqual(out["primary_archetype"]["id"], "software_app")
        self.assertEqual(out["primary_domain_pair"]["domain"], "software_engineering")

    def test_normalizes_zip_to_basename(self):
        out = ep.sanitize_item(SAMPLE["items"][0])
        self.assertEqual(out["version_zip_files"][0]["filename"], "demo-v1.zip")

    def test_windows_backslash_basename(self):
        self.assertEqual(
            ep.basename_only(r"C:\Users\alice\Downloads\proj-v2.zip"),
            "proj-v2.zip",
        )

    def test_sanitize_document_count(self):
        doc = ep.sanitize_document(SAMPLE)
        self.assertEqual(doc["n_items"], 1)
        self.assertEqual(len(doc["items"]), 1)

    def test_review_clean_document(self):
        doc = ep.sanitize_document(SAMPLE)
        self.assertEqual(ep.review_document(doc), [])

    def test_review_detects_email(self):
        dirty = ep.sanitize_document(SAMPLE)
        dirty["items"][0]["goal"] = "Contact me at alice@example.com"
        findings = ep.review_document(dirty)
        self.assertTrue(any("email" in f for f in findings))

    def test_review_detects_user_path_in_archetype_field(self):
        dirty = ep.sanitize_document(SAMPLE)
        dirty["items"][0]["archetype_fields"]["how_to_use"] = \
            "Open /mnt/c/Users/alice/Downloads/foo"
        findings = ep.review_document(dirty)
        self.assertTrue(any("Windows user path" in f for f in findings))

    def test_markdown_includes_slug_archetype_goal(self):
        item = ep.sanitize_item(SAMPLE["items"][0])
        md = ep.item_to_markdown(item)
        self.assertIn("# Demo App", md)
        self.assertIn("`demo`", md)
        self.assertIn("software_app", md)
        self.assertIn("Build a demo app", md)
        self.assertNotIn("conv-secret", md)


if __name__ == "__main__":
    unittest.main()
