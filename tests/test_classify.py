"""Unit tests for the deterministic classify prior."""
from __future__ import annotations

import importlib.util
import os
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")


def _load_classify():
    spec = importlib.util.spec_from_file_location(
        "classify", os.path.join(SCRIPTS, "classify.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cl = _load_classify()


class ClassifyTest(unittest.TestCase):
    def test_ontology_loads(self):
        onto = cl.load_ontology()
        ids = {a["id"] for a in onto["archetypes"]["archetypes"]}
        self.assertIn("software_app", ids)
        self.assertIn("media_generation", ids)
        doms = {d["id"] for d in onto["domains"]["domains"]}
        self.assertIn("education", doms)

    def test_versioned_software_app(self):
        cluster = {
            "slug": "my-app", "n_conversations": 5, "n_versions": 3,
            "file_artifacts": ["app.py", "index.html"],
            "signal_summary": {"n_version_zips": 3, "has_code": True,
                               "file_ext_classes": {"code": 2},
                               "top_title_keywords": ["my", "app"]},
            "titles": ["My App v1", "My App v2"],
        }
        out = cl.classify_cluster(cluster)
        self.assertEqual(out["primary_archetype"]["id"], "software_app")

    def test_media_generation_no_code(self):
        cluster = {
            "slug": "holiday-portrait", "n_conversations": 1, "n_versions": 0,
            "file_artifacts": [],
            "signal_summary": {"n_version_zips": 0, "has_code": False,
                               "has_image_asset": True,
                               "top_title_keywords": ["holiday", "portrait"]},
            "titles": ["Holiday portrait transformation"],
        }
        out = cl.classify_cluster(cluster)
        self.assertEqual(out["primary_archetype"]["id"], "media_generation")

    def test_education_domain_for_sat(self):
        cluster = {
            "slug": "sat-practice", "n_conversations": 4, "n_versions": 0,
            "file_artifacts": [],
            "signal_summary": {"top_title_keywords": ["sat", "practice", "test"]},
            "titles": ["SAT practice test"],
        }
        out = cl.classify_cluster(cluster)
        self.assertEqual(out["primary_archetype"]["id"], "study_education_resource")
        self.assertEqual(out["primary_domain_pair"]["domain"], "education")

    def test_returns_valid_archetype_id(self):
        onto = cl.load_ontology()
        ids = {a["id"] for a in onto["archetypes"]["archetypes"]}
        out = cl.classify_cluster({"slug": "x", "titles": ["random thing"]})
        self.assertIn(out["primary_archetype"]["id"], ids)


if __name__ == "__main__":
    unittest.main()
