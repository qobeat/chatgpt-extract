"""Validate export_public output matches the public item schema shape."""
from __future__ import annotations

import importlib.util
import json
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

PUBLIC_REQUIRED = frozenset({"slug", "title", "primary_archetype", "primary_domain_pair", "goal"})
PUBLIC_FORBIDDEN = frozenset({"source_conversation_ids", "member_ids", "signal_summary"})


def validate_public_item(p: dict) -> list[str]:
    errors = []
    for key in PUBLIC_REQUIRED:
        if key not in p:
            errors.append(f"missing required field: {key}")
    for key in PUBLIC_FORBIDDEN:
        if key in p:
            errors.append(f"forbidden field present: {key}")
    for z in p.get("version_zip_files") or []:
        fn = z.get("filename", "") if isinstance(z, dict) else str(z)
        if "/" in fn or "\\" in fn:
            errors.append(f"zip filename not basename-only: {fn}")
    return errors


class SchemaRoundtripTest(unittest.TestCase):
    def test_sanitize_matches_public_schema_shape(self):
        sample = {
            "items": [{
                "item_id": "demo", "slug": "demo", "title": "Demo",
                "is_durable_project": False,
                "primary_archetype": {"id": "knowledge_qa"},
                "primary_domain_pair": {"domain": "general_knowledge"},
                "goal": "g",
                "source_conversation_ids": ["x"],
                "signal_summary": {"a": 1},
                "version_zip_files": [{"filename": "/a/b.zip"}],
                "file_artifacts": [],
                "archetype_fields": {"question": "q", "answer_summary": "a"},
            }]
        }
        public = ep.sanitize_document(sample)
        for p in public["items"]:
            self.assertEqual(validate_public_item(p), [])

    def test_public_schema_file_is_valid_jsonschema(self):
        path = os.path.join(ROOT, "schema", "extracted_item_public_schema.json")
        with open(path, encoding="utf-8") as f:
            schema = json.load(f)
        self.assertIn("items", schema["properties"])
        props = schema["properties"]["items"]["items"]["properties"]
        self.assertIn("primary_archetype", props)
        self.assertNotIn("source_conversation_ids", props)


if __name__ == "__main__":
    unittest.main()
