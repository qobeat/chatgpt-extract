"""Tests for the shared redaction module (NFR-P2 / NFR-P3).

Covers detect-only `find`, the active `scrub` transform with typed
placeholders, recursive `scrub_obj`, and the broadened pattern set (email,
home paths across OSes, phone, tokens). Negative cases ensure normal prose and
version strings are not mangled.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import redact  # noqa: E402


class FindTest(unittest.TestCase):
    def _kinds(self, text):
        return {k for k, _ in redact.find(text)}

    def test_detects_email(self):
        self.assertIn("email", self._kinds("write me at alice@example.com please"))

    def test_detects_linux_home_path(self):
        self.assertIn("linux home path", self._kinds("see /home/alex/secret.txt"))

    def test_detects_wsl_windows_path(self):
        self.assertIn("WSL windows path",
                      self._kinds("at /mnt/c/Users/alex/Downloads/x.zip"))

    def test_detects_macos_path(self):
        self.assertIn("macOS home path", self._kinds("/Users/alex/Documents/a"))

    def test_detects_phone(self):
        self.assertIn("phone", self._kinds("call +1 415 555 1234 now"))
        self.assertIn("phone", self._kinds("call 415-555-1234 now"))

    def test_detects_openai_key(self):
        self.assertIn("openai key",
                      self._kinds("key sk-abcdefABCDEF0123456789 ok"))

    def test_detects_github_token(self):
        self.assertIn("github token",
                      self._kinds("ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"))

    def test_clean_prose_has_no_findings(self):
        self.assertEqual(redact.find("Version 1.2.3 shipped on the 3rd pass."), [])


class ScrubTransformTest(unittest.TestCase):
    def test_scrub_replaces_email_with_placeholder(self):
        out, findings = redact.scrub("reach alice@example.com today")
        self.assertNotIn("alice@example.com", out)
        self.assertIn(redact.PH_EMAIL, out)
        self.assertTrue(findings)

    def test_scrub_replaces_home_path(self):
        out, _ = redact.scrub("open /mnt/c/Users/alex/Downloads/export.zip")
        self.assertNotIn("/alex/", out)
        self.assertIn(redact.PH_PATH, out)

    def test_scrub_replaces_token(self):
        out, _ = redact.scrub("export OPENAI_API_KEY=sk-abcdefABCDEF0123456789")
        self.assertNotIn("sk-abcdefABCDEF0123456789", out)
        self.assertIn(redact.PH_TOKEN, out)

    def test_scrub_is_idempotent_on_clean_text(self):
        text = "A normal sentence with v2.0 and no secrets."
        out, findings = redact.scrub(text)
        self.assertEqual(out, text)
        self.assertEqual(findings, [])

    def test_scrub_obj_recurses(self):
        payload = {
            "goal": "email alice@example.com",
            "objectives": ["see /home/alex/notes"],
            "nested": {"phone": "call 415-555-1234"},
            "count": 3,
        }
        out = redact.scrub_obj(payload)
        self.assertNotIn("alice@example.com", out["goal"])
        self.assertNotIn("/home/alex", out["objectives"][0])
        self.assertNotIn("415-555-1234", out["nested"]["phone"])
        self.assertEqual(out["count"], 3)


class CloudPreSendIntentTest(unittest.TestCase):
    def test_bundle_with_pii_is_clean_after_scrub(self):
        # This is exactly the transform summarize.py applies to a bundle before
        # any cloud provider call (NFR-P3): planted PII must be absent after.
        bundle = (
            "DETERMINISTIC FACTS\n"
            "user: alex; contact alice@example.com\n"
            "path: /mnt/c/Users/alex/Downloads/ados-profile.zip\n"
            "token: sk-abcdefABCDEF0123456789\n"
        )
        scrubbed, findings = redact.scrub(bundle)
        for leak in ("alice@example.com", "/Users/alex", "sk-abcdefABCDEF"):
            self.assertNotIn(leak, scrubbed)
        self.assertGreaterEqual(len(findings), 3)


if __name__ == "__main__":
    unittest.main()
