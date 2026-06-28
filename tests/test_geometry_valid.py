"""ADOS Project Geometry is the governed, drift-proof contract for this project's
evaluation. These tests make the separation of reliability / depth / correctness
a thing a validator checks, not a convention a future edit can erode.

They validate the committed Geometry and Evaluation Rubric against the ADOS
schemas (Draft 2020-12) and assert referential integrity that JSON Schema alone
cannot express (every ref resolves, scoring axes match scoring coordinates).
"""
from __future__ import annotations

import json
import os
import pathlib
import unittest

import jsonschema

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADOS_SCHEMA = ROOT / "schema" / "ados"
GEOMETRY = ROOT / "geometry" / "project-geometry.json"
RUBRIC = ROOT / "geometry" / "evaluation-rubric.json"


def _load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class GeometrySchemaTest(unittest.TestCase):
    def test_project_geometry_valid(self):
        schema = _load(ADOS_SCHEMA / "project-geometry.schema.json")
        inst = _load(GEOMETRY)
        jsonschema.Draft202012Validator(schema).validate(inst)  # raises on drift

    def test_evaluation_rubric_valid(self):
        schema = _load(ADOS_SCHEMA / "evaluation-rubric.schema.json")
        inst = _load(RUBRIC)
        jsonschema.Draft202012Validator(schema).validate(inst)


class GeometryReferentialIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.geom = _load(GEOMETRY)
        self.coords = {c["coordinate_id"]: c
                       for c in self.geom["project_coordinates"]}
        self.deliveries = {d["delivery_id"]: d for d in self.geom["deliveries"]}
        self.vectors = {v["vector_id"]: v for v in self.geom["vectors"]}

    def test_delivery_coordinate_refs_resolve(self):
        for d in self.geom["deliveries"]:
            for cref in d["coordinate_refs"]:
                self.assertIn(cref, self.coords,
                              f"{d['delivery_id']} -> unknown coordinate {cref}")

    def test_coordinate_owner_refs_resolve(self):
        for cid, c in self.coords.items():
            self.assertIn(c["owner_delivery_ref"], self.deliveries,
                          f"{cid} owner_delivery_ref")
            self.assertIn(c["owner_vector_ref"], self.vectors,
                          f"{cid} owner_vector_ref")
            self.assertIn(c["vector_ref"], self.vectors, f"{cid} vector_ref")
            for ref in c.get("distinct_from", []):
                # distinct_from may reference a coordinate or the literal "total".
                if ref != "total":
                    self.assertIn(ref, self.coords, f"{cid} distinct_from {ref}")

    def test_vector_coordinate_order_resolves(self):
        for vid, v in self.vectors.items():
            for cref in v["coordinate_order"]:
                self.assertIn(cref, self.coords, f"{vid} coordinate_order {cref}")

    def test_completion_anchors_are_a_fuller_ladder(self):
        anchors = self.coords["COORD-B-COMPLETION"]["measurement_contract"]["anchors"]
        values = [a["value"] for a in anchors]
        self.assertEqual(values, sorted(values))
        self.assertTrue(set(values) >= {0, 50, 100},
                        "completion ladder should span 0..100 with intermediate states")
        for v in values:
            self.assertEqual(v % 10, 0, "anchor values must be multiples of 10")


class RubricCoherenceTest(unittest.TestCase):
    def setUp(self):
        self.geom = _load(GEOMETRY)
        self.rubric = _load(RUBRIC)
        self.coords = {c["coordinate_id"]: c
                       for c in self.geom["project_coordinates"]}

    def test_rubric_targets_this_geometry(self):
        self.assertEqual(self.rubric["geometry_id"], self.geom["geometry_id"])
        self.assertEqual(self.rubric["geometry_version"],
                         self.geom["geometry_version"])

    def test_axis_coordinate_refs_resolve(self):
        for ax in self.rubric["axes"]:
            self.assertIn(ax["coordinate_ref"], self.coords,
                          f"{ax['axis_id']} -> unknown coordinate")

    def test_axes_cover_exactly_the_scoring_coordinates(self):
        scored_by_axes = {ax["coordinate_ref"] for ax in self.rubric["axes"]}
        scoring_coords = {cid for cid, c in self.coords.items()
                          if c["coordinate_kind"] == "scoring"}
        self.assertEqual(scored_by_axes, scoring_coords,
                         "every scoring coordinate maps to exactly one axis and "
                         "no guard/diagnostic coordinate is scored")

    def test_weights_sum_to_100(self):
        self.assertEqual(sum(ax["weight"] for ax in self.rubric["axes"]), 100)

    def test_axis_gate_refs_resolve(self):
        gate_ids = {g["gate_id"] for g in self.rubric["mandatory_gates"]}
        for ax in self.rubric["axes"]:
            for gref in ax.get("gate_refs", []):
                self.assertIn(gref, gate_ids, f"{ax['axis_id']} gate_ref {gref}")


if __name__ == "__main__":
    unittest.main()
