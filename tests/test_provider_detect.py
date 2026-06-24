"""Tests for AI summary provider auto-detection order."""
from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import provider_detect  # noqa: E402


class _FakeProvider:
    def __init__(self, ok: bool):
        self._ok = ok

    def preflight(self):
        return (self._ok, "ok" if self._ok else "not ready")


def _factory(available: set[str]):
    def make(name, **_kw):
        return _FakeProvider(name in available)
    return make


class ProviderDetectTest(unittest.TestCase):
    def test_prefers_codex_when_all_available(self):
        with patch.object(provider_detect, "get_provider",
                          _factory({"codex", "ollama", "claude"})):
            name, _ = provider_detect.detect_provider()
            self.assertEqual(name, "codex")

    def test_falls_back_to_ollama(self):
        with patch.object(provider_detect, "get_provider",
                          _factory({"ollama", "claude"})):
            name, _ = provider_detect.detect_provider()
            self.assertEqual(name, "ollama")

    def test_falls_back_to_claude(self):
        with patch.object(provider_detect, "get_provider",
                          _factory({"claude"})):
            name, _ = provider_detect.detect_provider()
            self.assertEqual(name, "claude")

    def test_none_available(self):
        with patch.object(provider_detect, "get_provider", _factory(set())):
            name, notes = provider_detect.detect_provider()
            self.assertIsNone(name)
            self.assertEqual(len(notes), 3)

    def test_preflight_exception_is_skipped(self):
        def boom(name, **_kw):
            if name == "codex":
                raise RuntimeError("cli missing")
            return _FakeProvider(name == "ollama")
        with patch.object(provider_detect, "get_provider", boom):
            name, _ = provider_detect.detect_provider()
            self.assertEqual(name, "ollama")


if __name__ == "__main__":
    unittest.main()
