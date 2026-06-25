"""Sanitization of LLM output in summarize.build_item.

Smaller models (e.g. llama3.1:8b) emit "" or null for OPTIONAL enum/string
fields. The schema only accepts an enum member or the field's absence, so the
summarizer must drop those before writing — otherwise the run ends in schema
validation errors like:
    objectives/0/role: '' is not one of ['forming', 'speeding', 'governance']
    deliveries/0/kind: None is not of type 'string'
    deliveries/0/materiality: '' is not one of ['material', 'supporting']
"""
from __future__ import annotations

import importlib.util
import os
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
SCHEMA = os.path.join(ROOT, "schema", "extracted_item_schema.json")


def _load_summarize():
    spec = importlib.util.spec_from_file_location(
        "summarize", os.path.join(SCRIPTS, "summarize.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


S = _load_summarize()

CLUSTER = {
    "slug": "demo", "n_versions": 1, "n_conversations": 2,
    "start_date": "2025-01-01", "end_date": "2025-02-01",
    "member_ids": ["c1"], "version_zip_files": [], "file_artifacts": [],
    "signal_summary": {},
    "classify_prior": {
        "primary_archetype": {"id": "knowledge_qa"},
        "primary_domain_pair": {"domain": "general_knowledge", "subdomain": None},
    },
}


class CleanHelpersTest(unittest.TestCase):
    def test_objectives_drop_blank_role_and_textless(self):
        out = S._clean_objectives(
            [{"text": "a", "role": ""}, {"text": "", "role": "forming"},
             {"text": "b", "role": "GOVERNANCE"}, {"text": "c", "role": "bogus"}])
        self.assertEqual(out, [{"text": "a"},
                               {"text": "b", "role": "governance"},
                               {"text": "c"}])

    def test_deliveries_drop_null_kind_and_blank_materiality(self):
        out = S._clean_deliveries(
            [{"name": "x", "kind": None, "materiality": ""},
             {"name": "y", "kind": "md", "materiality": "material"},
             {"name": "", "kind": "z"}])
        self.assertEqual(out, [{"name": "x"},
                               {"name": "y", "materiality": "material", "kind": "md"}])

    def test_requirements_evolution_requires_change(self):
        out = S._clean_requirements_evolution(
            [{"date": "", "change": "c"}, {"date": None, "change": ""}])
        self.assertEqual(out, [{"date": None, "change": "c"}])

    def test_confidence_is_clamped(self):
        self.assertEqual(S._clamp_confidence(1.7), 1.0)
        self.assertEqual(S._clamp_confidence(-2), 0.0)
        self.assertEqual(S._clamp_confidence("nan-ish"), 0.0)
        self.assertEqual(S._clamp_confidence(0.5), 0.5)

    def test_secondary_lists_require_keys(self):
        self.assertEqual(
            S._clean_secondary_archetypes([{"id": ""}, {"id": "software_app"}]),
            [{"id": "software_app"}])
        self.assertEqual(
            S._clean_domain_pairs([{"domain": ""}, {"domain": "education",
                                                    "subdomain": ""}]),
            [{"domain": "education", "subdomain": None}])


class MalformedTypeTest(unittest.TestCase):
    """Weak models (e.g. gemma3:1b) sometimes emit a bare string/list where the
    schema expects an object/array. build_item must coerce these to the
    deterministic prior instead of raising AttributeError/ValueError."""

    def test_coercion_helpers(self):
        self.assertEqual(S._as_obj("software_app"), {})
        self.assertEqual(S._as_obj(["x"]), {})
        self.assertEqual(S._as_obj({"id": "x"}), {"id": "x"})
        self.assertEqual(S._as_list("abc"), [])
        self.assertEqual(S._as_list({"a": 1}), [])
        self.assertEqual(S._as_list(["a"]), ["a"])
        self.assertEqual(S._as_text(" hi "), "hi")
        self.assertEqual(S._as_text(["not", "a", "string"]), "")

    def test_string_typed_fields_fall_back_to_prior(self):
        ontology = S.load_ontology()
        # Everything the schema expects as object/array arrives as a bare string.
        parsed = {
            "primary_archetype": "software_app",
            "primary_domain_pair": "education",
            "goal": ["should", "be", "a", "string"],
            "objectives": "just a sentence, not a list",
            "requirements": 5,
            "archetype_fields": "scope here",
            "confidence": "high",
        }
        item = S.build_item(CLUSTER, parsed, ontology, "ollama", "gemma3:1b",
                            "abc", 0.0)
        # Falls back to the deterministic prior rather than crashing.
        self.assertEqual(item["primary_archetype"]["id"], "knowledge_qa")
        self.assertEqual(item["primary_domain_pair"]["domain"], "general_knowledge")
        self.assertEqual(item["goal"], "")
        self.assertEqual(item["objectives"], [])
        self.assertEqual(item["requirements"], [])
        self.assertEqual(item["confidence"], 0.0)

    def test_string_typed_fields_validate(self):
        from trace import validate_with_jsonschema  # noqa: E402
        ontology = S.load_ontology()
        parsed = {"primary_archetype": "software_app",
                  "primary_domain_pair": "education",
                  "archetype_fields": ["nope"], "goal": 42}
        item = S.build_item(CLUSTER, parsed, ontology, "ollama", "gemma3:1b",
                            "abc", 0.0)
        ok, errors = validate_with_jsonschema({"items": [item]}, SCHEMA)
        self.assertTrue(ok, msg=f"schema errors: {errors}")


class BuildItemSchemaTest(unittest.TestCase):
    def test_dirty_llm_output_validates(self):
        from trace import validate_with_jsonschema  # noqa: E402
        ontology = S.load_ontology()
        parsed = {
            "primary_archetype": {"id": "knowledge_qa", "label": "QA"},
            "primary_domain_pair": {"domain": "general_knowledge", "subdomain": ""},
            "goal": "g", "confidence": 1.7,
            "objectives": [{"text": "do thing", "role": ""}],
            "deliveries": [{"name": "out", "kind": None, "materiality": ""}],
            "requirements_evolution": [{"date": "", "change": "c"}],
            "secondary_archetypes": [{"id": ""}],
            "secondary_domain_pairs": [{"domain": "", "subdomain": ""}],
            "archetype_fields": {"question": "q", "answer_summary": "a"},
        }
        item = S.build_item(CLUSTER, parsed, ontology, "ollama", "llama3.1:8b",
                            "abc", 0.0)
        ok, errors = validate_with_jsonschema({"items": [item]}, SCHEMA)
        self.assertTrue(ok, msg=f"schema errors: {errors}")


if __name__ == "__main__":
    unittest.main()
