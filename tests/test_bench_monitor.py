"""Unit tests for the GPU/Ollama benchmark health monitor (no GPU required)."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import bench_monitor as bm  # noqa: E402


class ProcessorLabelTest(unittest.TestCase):
    def test_full_gpu(self):
        self.assertEqual(bm._processor_label(1.0), "100% GPU")
        self.assertTrue(bm.processor_is_gpu(bm._processor_label(1.0)))

    def test_full_cpu(self):
        self.assertEqual(bm._processor_label(0.0), "100% CPU")
        self.assertFalse(bm.processor_is_gpu(bm._processor_label(0.0)))

    def test_split_is_not_gpu(self):
        # A partial CPU spill must NOT count as on-GPU (benchmark invalidating).
        label = bm._processor_label(0.5)
        self.assertIn("CPU", label)
        self.assertFalse(bm.processor_is_gpu(label))


class ModelMatchTest(unittest.TestCase):
    def test_matches_tagged_and_base(self):
        rows = [{"name": "qwen3:8b", "processor": "100% GPU"}]
        self.assertIsNotNone(bm.model_loaded_row(rows, "qwen3:8b"))
        self.assertIsNotNone(bm.model_loaded_row(rows, "qwen3"))
        self.assertIsNone(bm.model_loaded_row(rows, "llama3.1:8b"))


class ClassifyTest(unittest.TestCase):
    GPU = {"available": True, "util_pct": 40.0, "mem_used_mib": 8000.0,
           "mem_total_mib": 24576.0, "mem_frac": 0.33, "power_w": 200.0}

    def setUp(self):
        # Avoid a real network probe; pretend the host is up so HOST_DOWN does
        # not mask the code under test.
        self._orig = bm.host_up
        bm.host_up = lambda *a, **k: True

    def tearDown(self):
        bm.host_up = self._orig

    def test_cpu_spill_is_fatal(self):
        rows = [{"name": "qwen3:8b", "processor": "100% CPU", "gpu_frac": 0.0}]
        h = bm.classify("qwen3:8b", "http://x", self.GPU, rows, [], running=True)
        self.assertEqual(h["status"], "FATAL")
        self.assertIn("CPU_SPILL", h["codes"])
        self.assertTrue(any("restart ollama" in f for f in h["fixes"]))

    def test_on_gpu_is_ok(self):
        rows = [{"name": "qwen3:8b", "processor": "100% GPU", "gpu_frac": 1.0}]
        h = bm.classify("qwen3:8b", "http://x", self.GPU, rows, [], running=True)
        self.assertEqual(h["status"], "OK")
        self.assertEqual(h["codes"], [])

    def test_log_errors_flagged(self):
        rows = [{"name": "qwen3:8b", "processor": "100% GPU", "gpu_frac": 1.0}]
        h = bm.classify("qwen3:8b", "http://x", self.GPU, rows,
                        ["llm call: timed out after 300s"], running=True)
        self.assertIn("LOG_ERRORS", h["codes"])

    def test_vram_full_warns(self):
        gpu = dict(self.GPU, mem_frac=0.99, mem_used_mib=24300.0)
        rows = [{"name": "qwen3:8b", "processor": "100% GPU", "gpu_frac": 1.0}]
        h = bm.classify("qwen3:8b", "http://x", gpu, rows, [], running=True)
        self.assertIn("VRAM_FULL", h["codes"])


if __name__ == "__main__":
    unittest.main()
