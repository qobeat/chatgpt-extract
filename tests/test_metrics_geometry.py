"""Geometry-aware metrics guard (Task 6): every column `gpt metrics` renders must
be bound to a Project Coordinate declared in the Geometry, so a new column can't
be added without declaring its measures / does_not_measure — the durable guard
against silently re-blending the separated quality axes.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import metrics  # noqa: E402


class MetricsGeometryGuardTest(unittest.TestCase):
    def test_every_column_maps_to_a_declared_coordinate(self):
        declared = metrics.declared_coordinate_ids()
        self.assertTrue(declared, "geometry must declare coordinates")
        for col, cid in metrics.COLUMN_COORDINATES.items():
            self.assertIn(cid, declared,
                          f"column {col} -> undeclared coordinate {cid}")

    def test_guard_passes_for_current_columns(self):
        # Should not raise against the committed geometry.
        metrics.assert_columns_declared()

    def test_undeclared_column_is_rejected(self):
        with self.assertRaises(ValueError):
            metrics.assert_columns_declared(
                {"some_new_pct": "COORD-DOES-NOT-EXIST"})

    def test_guard_degrades_when_geometry_missing(self):
        # A missing geometry file must not crash a read-only metrics print.
        metrics.assert_columns_declared(
            {"some_new_pct": "COORD-DOES-NOT-EXIST"},
            geometry_path="/nonexistent/project-geometry.json")


if __name__ == "__main__":
    unittest.main()
