"""Unit tests for scripts/lib/ollama_probe.py fallback behavior."""
from __future__ import annotations

import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import ollama_probe  # noqa: E402


class OllamaProbeFallbackTest(unittest.TestCase):
    def test_normalize_host_adds_scheme(self):
        self.assertEqual(
            ollama_probe.normalize_host("127.0.0.1:11434"),
            "http://127.0.0.1:11434",
        )

    def test_host_available_uses_http_fallback(self):
        fake = (200, {"version": "0.0.1"}, None)
        with patch.object(ollama_probe, "_ensure_ollama_test", return_value=False):
            with patch.object(ollama_probe, "_http_json", return_value=fake):
                self.assertTrue(ollama_probe.host_available("http://localhost:11434"))

    def test_host_unavailable(self):
        with patch.object(ollama_probe, "_ensure_ollama_test", return_value=False):
            with patch.object(ollama_probe, "_http_json", return_value=(0, None, "conn refused")):
                self.assertFalse(ollama_probe.host_available())

    def test_installed_models_fallback(self):
        payload = {"models": [{"name": "gpt-oss:20b"}, {"name": "qwen2.5-coder:14b"}]}
        with patch.object(ollama_probe, "_ensure_ollama_test", return_value=False):
            with patch.object(ollama_probe, "_http_json", return_value=(200, payload, None)):
                names = ollama_probe.installed_models()
        self.assertEqual(names, ["gpt-oss:20b", "qwen2.5-coder:14b"])

    def test_model_present(self):
        with patch.object(ollama_probe, "installed_models", return_value=["gpt-oss:20b"]):
            self.assertTrue(ollama_probe.model_present("gpt-oss:20b"))
            self.assertFalse(ollama_probe.model_present("missing:7b"))

    def test_preflight_unreachable(self):
        with patch.object(ollama_probe, "host_available", return_value=False):
            ok, msg = ollama_probe.preflight("gpt-oss:20b")
        self.assertFalse(ok)
        self.assertIn("unreachable", msg.lower())

    def test_preflight_missing_model(self):
        with patch.object(ollama_probe, "host_available", return_value=True):
            with patch.object(ollama_probe, "model_present", return_value=False):
                with patch.object(ollama_probe, "installed_models", return_value=["other:7b"]):
                    ok, msg = ollama_probe.preflight("gpt-oss:20b")
        self.assertFalse(ok)
        self.assertIn("not found", msg.lower())

    def test_load_config_via_paths(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
        import paths  # noqa: E402
        cfg = paths.load_config()
        self.assertIn("ollama", cfg)
        self.assertIn("ollama_test_home", cfg)


if __name__ == "__main__":
    unittest.main()
