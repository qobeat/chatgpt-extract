"""Tests for the AI summary confirmation gate and estimates."""
from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import confirm  # noqa: E402


class EstimateTest(unittest.TestCase):
    def test_eta_scales_with_items(self):
        self.assertEqual(confirm.eta_seconds("codex", 0), 0)
        self.assertGreater(confirm.eta_seconds("codex", 10),
                           confirm.eta_seconds("codex", 1))

    def test_format_duration(self):
        self.assertTrue(confirm.format_duration(30).endswith("s"))
        self.assertIn("min", confirm.format_duration(600))
        self.assertIn("hr", confirm.format_duration(3 * 3600))

    def test_format_size(self):
        self.assertEqual(confirm.format_size(512), "512 B")
        self.assertIn("KB", confirm.format_size(2048))


class GateTest(unittest.TestCase):
    def test_noask_proceeds(self):
        out = io.StringIO()
        self.assertTrue(confirm.gate("codex", "", 5, noask=True, stream=out))
        self.assertIn("Proceeding", out.getvalue())

    def test_non_tty_refuses(self):
        out = io.StringIO()
        with patch.object(sys.stdin, "isatty", return_value=False):
            self.assertFalse(confirm.gate("codex", "", 5, stream=out))
        self.assertIn("Refusing", out.getvalue())

    def test_tty_yes(self):
        out = io.StringIO()
        with patch.object(sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value="y"):
            self.assertTrue(confirm.gate("ollama", "gpt-oss:20b", 3, stream=out))

    def test_tty_default_no(self):
        out = io.StringIO()
        with patch.object(sys.stdin, "isatty", return_value=True), \
                patch("builtins.input", return_value=""):
            self.assertFalse(confirm.gate("ollama", "gpt-oss:20b", 3, stream=out))

    def test_cost_shown_for_api(self):
        out = io.StringIO()
        confirm.gate("openai", "gpt-5-mini", 10, est_usd=0.8,
                     subscription=False, noask=True, stream=out)
        self.assertIn("$0.80", out.getvalue())

    def test_subscription_shows_plan_line(self):
        out = io.StringIO()
        confirm.gate("codex", "", 10, est_usd=0.0, subscription=True,
                     noask=True, stream=out)
        self.assertIn("plan/quota", out.getvalue())


if __name__ == "__main__":
    unittest.main()
