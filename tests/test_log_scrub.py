"""NFR-P4: persisted traces must carry only labels/counts — no transcript text,
home paths, emails, or tokens."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
from trace import TraceWriter  # noqa: E402


class TraceScrubTest(unittest.TestCase):
    def _read(self, path):
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

    def test_error_payload_is_scrubbed(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.addCleanup(os.remove, path)
        tw = TraceWriter(path, run_id="ollama:qwen3:8b")
        tw.event("LLM_FAIL", "demo-slug",
                 {"error": "failed reading /home/alex/secret and "
                           "emailing alice@example.com"}, severity="ERROR")
        events = self._read(path)
        blob = json.dumps(events)
        self.assertNotIn("/home/alex", blob)
        self.assertNotIn("alice@example.com", blob)

    def test_counts_survive_scrub(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.addCleanup(os.remove, path)
        tw = TraceWriter(path, run_id="r")
        tw.event("LLM_OK", "slug", {"secs": 9.8, "in_tok": 1200, "out_tok": 300,
                                    "usd": 0.0})
        e = self._read(path)[0]
        self.assertEqual(e["payload"]["in_tok"], 1200)
        self.assertEqual(e["payload"]["secs"], 9.8)

    def test_scrub_can_be_disabled(self):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        self.addCleanup(os.remove, path)
        tw = TraceWriter(path, run_id="r", scrub=False)
        tw.event("NOTE", "x", {"error": "alice@example.com"})
        self.assertIn("alice@example.com", json.dumps(self._read(path)))


if __name__ == "__main__":
    unittest.main()
