"""Tests for GPU power metering math (FR-B6)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import power as power_lib  # noqa: E402


class EnergyIntegralTest(unittest.TestCase):
    def _write_trace(self, samples):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for t, w in samples:
                f.write(json.dumps({"t": t, "w": w}) + "\n")
        self.addCleanup(os.remove, path)
        return path

    def test_constant_power_integral(self):
        # 360 W held for 10 s = 3600 J = exactly 1 Wh.
        path = self._write_trace([(0.0, 360.0), (10.0, 360.0)])
        wh, dur, n = power_lib.energy_wh_from_trace(path)
        self.assertAlmostEqual(wh, 1.0, places=4)
        self.assertAlmostEqual(dur, 10.0, places=4)
        self.assertEqual(n, 2)

    def test_trapezoidal_ramp(self):
        # Ramp 0 -> 100 W over 3600 s: mean 50 W * 1 h = 50 Wh.
        path = self._write_trace([(0.0, 0.0), (3600.0, 100.0)])
        wh, _dur, _n = power_lib.energy_wh_from_trace(path)
        self.assertAlmostEqual(wh, 50.0, places=2)

    def test_single_sample_is_zero_energy(self):
        path = self._write_trace([(0.0, 300.0)])
        wh, _dur, n = power_lib.energy_wh_from_trace(path)
        self.assertEqual(wh, 0.0)
        self.assertEqual(n, 1)

    def test_missing_trace_is_safe(self):
        wh, dur, n = power_lib.energy_wh_from_trace("/nonexistent/path.jsonl")
        self.assertEqual((wh, dur, n), (0.0, 0.0, 0))


class MeterAvailabilityTest(unittest.TestCase):
    def test_unavailable_meter_is_noop(self):
        # Force the unavailable branch regardless of host nvidia-smi.
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.addCleanup(os.remove, path)
        meter = power_lib.PowerMeter(path)
        meter.available = False
        with meter:
            pass
        self.assertFalse(meter.summary()["available"])


if __name__ == "__main__":
    unittest.main()
