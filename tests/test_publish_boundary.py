"""NFR-P1 / NFR-P2: the publish boundary actively scrubs PII and a boundary
test fails on any leak into the published surface."""
from __future__ import annotations

import importlib.util
import json
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")


def _load_export_public():
    spec = importlib.util.spec_from_file_location(
        "export_public", os.path.join(SCRIPTS, "export_public.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


ep = _load_export_public()

DIRTY = {
    "generated_by": "test", "provider": "ollama", "model": "qwen3:8b",
    "ontology_version": "1.0.0", "n_items": 1,
    "items": [{
        "item_id": "demo", "slug": "demo", "title": "Demo",
        "is_durable_project": True,
        "primary_archetype": {"id": "software_app"},
        "primary_domain_pair": {"domain": "software_engineering"},
        "goal": "Contact alice@example.com about the build",
        "objectives": [{"text": "Open /home/alex/secret/notes.md"}],
        "requirements": ["call 415-555-1234 for access"],
        "archetype_fields": {
            "quickstart": "export TOKEN=sk-abcdefABCDEF0123456789",
            "how_to_use": "see /mnt/c/Users/alex/Downloads/x.zip",
            "how_to_update": "bump version",
        },
        "version_zip_files": [{"filename": "/mnt/c/Users/alex/Downloads/demo-v1.zip",
                               "version": "1"}],
        "source_conversation_ids": ["conv-secret-abc"],
        "llm_ok": True, "classification_source": "llm", "schema_valid": True,
    }],
}

LEAKS = ("alice@example.com", "/home/alex", "/Users/alex", "415-555-1234",
         "sk-abcdefABCDEF0123456789", "conv-secret-abc")


class PublishScrubTest(unittest.TestCase):
    def test_detect_only_finds_planted_pii(self):
        # Without --scrub, the detector must flag the leaks (so the commit fails).
        public = ep.sanitize_document(DIRTY, scrub=False)
        findings = ep.review_document(public)
        self.assertTrue(findings)

    def test_scrub_removes_all_planted_pii(self):
        public = ep.sanitize_document(DIRTY, scrub=True)
        blob = json.dumps(public, ensure_ascii=False)
        for leak in LEAKS:
            self.assertNotIn(leak, blob, f"leak survived scrub: {leak}")

    def test_scrubbed_document_passes_review(self):
        public = ep.sanitize_document(DIRTY, scrub=True)
        self.assertEqual(ep.review_document(public), [])

    def test_audit_flags_never_published(self):
        public = ep.sanitize_document(DIRTY, scrub=True)
        item = public["items"][0]
        for forbidden in ("llm_ok", "classification_source", "schema_valid",
                          "source_conversation_ids", "model_slug_votes"):
            self.assertNotIn(forbidden, item)

    def test_zip_path_reduced_to_basename(self):
        public = ep.sanitize_document(DIRTY, scrub=True)
        fn = public["items"][0]["version_zip_files"][0]["filename"]
        self.assertEqual(fn, "demo-v1.zip")
        self.assertNotIn("/", fn)

    def test_markdown_surface_is_clean_after_scrub(self):
        public = ep.sanitize_document(DIRTY, scrub=True)
        md = ep.item_to_markdown(public["items"][0])
        for leak in LEAKS:
            self.assertNotIn(leak, md)


if __name__ == "__main__":
    unittest.main()
