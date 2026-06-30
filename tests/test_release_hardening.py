"""Release-hardening unit tests for the GPT-5.5 review fixes.

  - Cloud `summarize` privacy symmetry with `gpt ask` (FR-Q4 / NFR-P3):
    a cloud provider is refused unless scrubbed or explicitly opted into raw.
  - `build_bundles.select_clusters`: the CLI contract now matches behaviour
    (--min-versions / --include-multi-chat / --include-singletons), and the
    `gpt bundle` command is wired at the entrypoint with those flags (FR-U5).
  - `redact` custom local dictionary (gitignored personal literals).
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import build_bundles  # noqa: E402
import gpt_cli  # noqa: E402
import redact  # noqa: E402
import summarize  # noqa: E402
from providers import CLOUD_PROVIDERS  # noqa: E402


class BundleCliContractTest(unittest.TestCase):
    """FR-U5 — the `gpt bundle` claim must be true at the entrypoint, not only
    as a library function (audit F-002)."""

    def test_bundle_is_wired_at_the_gpt_entrypoint(self):
        self.assertIn("bundle", gpt_cli.DELEGATED)
        script_rel, _prefix = gpt_cli.DELEGATED["bundle"]
        self.assertTrue(script_rel.endswith("build_bundles.py"), script_rel)

    def test_bundle_help_lists_the_documented_flags(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["gpt bundle", "--help"]), \
                redirect_stdout(buf), self.assertRaises(SystemExit):
            build_bundles.main()
        out = buf.getvalue()
        for flag in ("--min-versions", "--include-multi-chat",
                     "--include-singletons"):
            self.assertIn(flag, out, f"{flag} missing from `gpt bundle --help`")
        self.assertIn("gpt bundle", out)  # prog reads as the entrypoint command


class CloudEgressGateTest(unittest.TestCase):
    def test_cloud_without_scrub_or_optin_is_blocked(self):
        for prov in CLOUD_PROVIDERS:
            msg = summarize.cloud_egress_block_reason(prov, False, False)
            self.assertIsNotNone(msg, f"{prov} should be blocked")
            self.assertIn(prov, msg)

    def test_scrub_or_optin_unblocks_cloud(self):
        prov = next(iter(CLOUD_PROVIDERS))
        self.assertIsNone(summarize.cloud_egress_block_reason(prov, True, False))
        self.assertIsNone(summarize.cloud_egress_block_reason(prov, False, True))

    def test_local_provider_never_blocked(self):
        self.assertIsNone(summarize.cloud_egress_block_reason("ollama", False, False))


class SelectClustersTest(unittest.TestCase):
    def _clusters(self):
        return [
            {"slug": "proj-v", "n_versions": 3, "n_conversations": 1},
            {"slug": "multi", "n_versions": 0, "n_conversations": 4},
            {"slug": "singleton", "n_versions": 0, "n_conversations": 1},
        ]

    def test_default_keeps_versions_or_multichat(self):
        kept = build_bundles.select_clusters(
            self._clusters(), min_versions=1, include_multi_chat=True,
            include_singletons=False)
        slugs = {c["slug"] for c in kept}
        self.assertEqual(slugs, {"proj-v", "multi"})  # singleton dropped

    def test_no_multichat_drops_versionless_multichat(self):
        kept = build_bundles.select_clusters(
            self._clusters(), min_versions=1, include_multi_chat=False,
            include_singletons=False)
        self.assertEqual({c["slug"] for c in kept}, {"proj-v"})

    def test_include_singletons_keeps_all(self):
        kept = build_bundles.select_clusters(
            self._clusters(), min_versions=1, include_multi_chat=True,
            include_singletons=True)
        self.assertEqual(len(kept), 3)

    def test_higher_min_versions_is_stricter(self):
        kept = build_bundles.select_clusters(
            self._clusters(), min_versions=5, include_multi_chat=False,
            include_singletons=False)
        self.assertEqual(kept, [])


class RedactCustomDictTest(unittest.TestCase):
    def test_local_terms_and_patterns_are_scrubbed(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "redact.local.json")
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump({"terms": ["Jane Roe", "Maple HOA"],
                           "patterns": [r"ACME-\d{4}"]}, f)
            with mock.patch.dict(os.environ, {"REDACT_LOCAL_JSON": cfg}):
                redact._custom_cache["key"] = None  # force reload for this path
                text = "Contact Jane Roe at the Maple HOA about ACME-1234."
                out, findings = redact.scrub(text)
                self.assertNotIn("Jane Roe", out)
                self.assertNotIn("Maple HOA", out)
                self.assertNotIn("ACME-1234", out)
                self.assertIn(redact.PH_CUSTOM, out)
                self.assertTrue(any(k == "custom" for k, _ in findings))
        # Cache reset so other tests see no custom dict.
        redact._custom_cache["key"] = None
        self.assertEqual(redact.load_custom_patterns(), [])

    def test_missing_dict_is_noop(self):
        with mock.patch.dict(os.environ,
                             {"REDACT_LOCAL_JSON": "/nonexistent/redact.local.json"}):
            redact._custom_cache["key"] = None
            out, _ = redact.scrub("plain text with no secrets")
            self.assertEqual(out, "plain text with no secrets")


if __name__ == "__main__":
    unittest.main()
