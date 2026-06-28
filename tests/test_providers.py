"""Unit tests for the provider factory and the CLI providers' offline behavior.

These run with no network and no plan spend: they only check the factory mapping
and that preflight fails clearly when a CLI binary/token is absent.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
from providers import PROVIDERS, ProviderError, get_provider  # noqa: E402
from providers.codex_provider import CodexProvider  # noqa: E402
from providers.claude_cli_provider import ClaudeCliProvider  # noqa: E402


class ProviderFactoryTest(unittest.TestCase):
    def test_new_providers_registered(self):
        self.assertIn("codex", PROVIDERS)
        self.assertIn("claude", PROVIDERS)

    def test_factory_returns_codex(self):
        prov = get_provider("codex", model="")
        self.assertIsInstance(prov, CodexProvider)
        self.assertEqual(prov.name, "codex")

    def test_factory_returns_claude(self):
        prov = get_provider("claude", model="")
        self.assertIsInstance(prov, ClaudeCliProvider)
        self.assertEqual(prov.name, "claude")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ProviderError):
            get_provider("nope", model="")


class CodexPreflightTest(unittest.TestCase):
    def test_missing_binary_fails_clearly(self):
        prov = CodexProvider(model="", binary="codex-does-not-exist-xyz")
        ok, msg = prov.preflight()
        self.assertFalse(ok)
        self.assertIn("not found on PATH", msg)
        self.assertIn("ChatGPT", msg)


class CodexNoWebTest(unittest.TestCase):
    def test_web_search_off_by_default(self):
        cmd = CodexProvider(model="")._build_cmd()
        self.assertIn("tools.web_search=false", cmd)
        self.assertIn("read-only", cmd)

    def test_allow_web_opt_in(self):
        cmd = CodexProvider(model="", allow_web=True)._build_cmd()
        self.assertNotIn("tools.web_search=false", cmd)


class ClaudePreflightTest(unittest.TestCase):
    def test_missing_binary_fails_clearly(self):
        prov = ClaudeCliProvider(model="", binary="claude-does-not-exist-xyz")
        ok, msg = prov.preflight()
        self.assertFalse(ok)
        self.assertIn("not found on PATH", msg)

    def test_web_tools_disallowed_by_default(self):
        cmd = ClaudeCliProvider(model="")._build_cmd()
        self.assertIn("--disallowedTools", cmd)
        self.assertIn("WebSearch", cmd)
        self.assertIn("WebFetch", cmd)

    def test_allow_web_opt_in(self):
        cmd = ClaudeCliProvider(model="", allow_web=True)._build_cmd()
        self.assertNotIn("--disallowedTools", cmd)

    def test_child_env_drops_api_key(self):
        prev = os.environ.get("ANTHROPIC_API_KEY")
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-should-be-dropped"
        try:
            prov = ClaudeCliProvider(model="")
            env = prov._child_env()
            self.assertNotIn("ANTHROPIC_API_KEY", env)
        finally:
            if prev is None:
                os.environ.pop("ANTHROPIC_API_KEY", None)
            else:
                os.environ["ANTHROPIC_API_KEY"] = prev


if __name__ == "__main__":
    unittest.main()
