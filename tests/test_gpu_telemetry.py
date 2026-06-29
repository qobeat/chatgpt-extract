"""GPU telemetry: schema-valid summaries from a JSONL ledger, legacy-trace
compatibility, and a null summary for cloud/back-filled runs. All offline — no
nvidia-smi, no GPU required."""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
LIB = os.path.join(ROOT, "scripts", "lib")
SCHEMA = os.path.join(ROOT, "schema", "gpu_telemetry.schema.json")


def _load():
    spec = importlib.util.spec_from_file_location(
        "gpu_telemetry", os.path.join(LIB, "gpu_telemetry.py"))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


tele = _load()


def _write(lines: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for o in lines:
            f.write(json.dumps(o) + "\n")
    return path


class SummaryTest(unittest.TestCase):
    def test_full_ledger_aggregates(self):
        # Two samples 10s apart at 200W -> 200W * 10s = 2000 J = 0.5556 Wh.
        path = _write([
            {"t": 1000.0, "power_w": 200.0, "temp_c": 70.0, "util_gpu_pct": 90.0,
             "util_mem_pct": 40.0, "mem_used_mib": 8000.0, "fan_pct": 55.0,
             "clock_sm_mhz": 1800.0, "power_limit_w": 350.0},
            {"t": 1010.0, "power_w": 200.0, "temp_c": 84.0, "util_gpu_pct": 100.0,
             "util_mem_pct": 50.0, "mem_used_mib": 9000.0, "fan_pct": 80.0,
             "clock_sm_mhz": 1900.0, "power_limit_w": 350.0},
        ])
        try:
            s = tele.summarize_trace(path, interval_s=0.5)
        finally:
            os.unlink(path)
        self.assertTrue(s["available"])
        self.assertEqual(s["n_samples"], 2)
        self.assertAlmostEqual(s["energy_wh"], 0.5556, places=3)
        self.assertEqual(s["duration_s"], 10.0)
        self.assertEqual(s["power_w"]["avg"], 200.0)
        self.assertEqual(s["temp_c"]["peak"], 84.0)
        self.assertEqual(s["util_gpu_pct"]["peak"], 100.0)
        self.assertEqual(s["power_limit_w"], 350.0)
        self.assertTrue(s["throttled"])  # peak 84C >= 83C

    def test_legacy_power_trace_compat(self):
        # Old {t, w} power trace still integrates energy; health stats stay null.
        path = _write([{"t": 0.0, "w": 100.0}, {"t": 3600.0, "w": 100.0}])
        try:
            s = tele.summarize_trace(path)
        finally:
            os.unlink(path)
        self.assertTrue(s["available"])
        self.assertAlmostEqual(s["energy_wh"], 100.0, places=1)  # 100W for 1h
        self.assertIsNone(s["temp_c"]["peak"])
        self.assertIsNone(s["throttled"])

    def test_empty_trace_is_null_summary(self):
        path = _write([])
        try:
            s = tele.summarize_trace(path)
        finally:
            os.unlink(path)
        self.assertEqual(s, tele.null_summary())
        self.assertFalse(s["available"])

    def test_null_summary_shape(self):
        s = tele.null_summary()
        self.assertEqual(s["schema"], tele.SCHEMA_SUMMARY)
        self.assertFalse(s["available"])
        for f in tele.STAT_FIELDS:
            self.assertEqual(s[f], {"avg": None, "peak": None, "min": None})


class SchemaTest(unittest.TestCase):
    def test_summaries_validate(self):
        import jsonschema
        with open(SCHEMA, encoding="utf-8") as f:
            schema = json.load(f)
        path = _write([
            {"t": 1.0, "power_w": 150.0, "temp_c": 60.0},
            {"t": 2.0, "power_w": 250.0, "temp_c": 62.0},
        ])
        try:
            full = tele.summarize_trace(path)
        finally:
            os.unlink(path)
        jsonschema.validate(full, schema)
        jsonschema.validate(tele.null_summary(), schema)


if __name__ == "__main__":
    unittest.main()
