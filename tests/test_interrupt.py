"""Tests for uniform Ctrl+C handling (scripts/lib/interrupt.py)."""
from __future__ import annotations

import io
import os
import signal
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import interrupt  # noqa: E402


class RunCliTest(unittest.TestCase):
    def setUp(self):
        interrupt.reset()

    def test_returns_main_exit_code(self):
        self.assertEqual(interrupt.run_cli(lambda: 0, "gpt x"), 0)
        self.assertEqual(interrupt.run_cli(lambda: 7, "gpt x"), 7)

    def test_none_is_treated_as_success(self):
        self.assertEqual(interrupt.run_cli(lambda: None, "gpt x"), 0)

    def test_keyboard_interrupt_yields_130(self):
        def boom():
            raise KeyboardInterrupt
        err = io.StringIO()
        old = sys.stderr
        sys.stderr = err
        try:
            rc = interrupt.run_cli(boom, "gpt search")
        finally:
            sys.stderr = old
        self.assertEqual(rc, interrupt.SIGINT_EXIT)
        self.assertEqual(interrupt.SIGINT_EXIT, 130)
        self.assertIn("interrupted", err.getvalue())
        self.assertIn("gpt search", err.getvalue())


class ReportTest(unittest.TestCase):
    def setUp(self):
        interrupt.reset()

    def test_report_without_state(self):
        out = io.StringIO()
        interrupt.report("gpt info", stream=out)
        line = out.getvalue()
        self.assertIn("[interrupted] ^C · gpt info", line)
        # No progress published -> no trailing state separator.
        self.assertNotIn("/", line)

    def test_report_with_progress(self):
        interrupt.set_total(4122, unit="chats")
        for _ in range(1234):
            interrupt.advance()
        out = io.StringIO()
        interrupt.report("gpt search", stream=out)
        line = out.getvalue()
        self.assertIn("gpt search", line)
        self.assertIn("1,234 / 4,122 chats", line)

    def test_report_with_label_only(self):
        interrupt.note("summarizing my-slug")
        out = io.StringIO()
        interrupt.report("gpt summarize", stream=out)
        self.assertIn("summarizing my-slug", out.getvalue())


class PropagateChildTest(unittest.TestCase):
    def test_maps_sigint_exit_codes_to_130(self):
        self.assertEqual(interrupt.propagate_child(130), 130)
        self.assertEqual(interrupt.propagate_child(-signal.SIGINT), 130)

    def test_passes_other_codes_through(self):
        self.assertEqual(interrupt.propagate_child(0), 0)
        self.assertEqual(interrupt.propagate_child(2), 2)
        self.assertEqual(interrupt.propagate_child(1), 1)


if __name__ == "__main__":
    unittest.main()
