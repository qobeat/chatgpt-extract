"""FR-B4: structured-output enforcement + retry-on-parse-failure.

Asserts the Ollama provider requests format=json, and that summarize's
complete_with_retry retries exactly once on a single malformed response before
succeeding (and records an honest failure when all attempts are malformed).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))

from providers.ollama_provider import OllamaProvider  # noqa: E402
from providers.base import Usage  # noqa: E402


def _load(name: str, relpath: str):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(SCRIPTS, relpath))
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


summarize = _load("summarize", "summarize.py")


class _FakeProvider:
    """Returns the queued responses in order; counts complete() calls."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def complete(self, system, prompt, json_mode=True):
        self.calls += 1
        if self._responses:
            text = self._responses.pop(0)
        else:
            text = self._responses[-1] if self._responses else "{}"
        return text, Usage(input_tokens=10, output_tokens=5)


class OllamaFormatJsonTest(unittest.TestCase):
    def test_format_json_set_when_json_mode(self):
        captured = {}

        prov = OllamaProvider(model="qwen3:8b")

        def fake_post(url, payload, headers, **_kw):
            captured["payload"] = payload
            return {"message": {"content": "{}"}, "prompt_eval_count": 1,
                    "eval_count": 1}

        prov._post_json = fake_post  # type: ignore[assignment]
        prov.complete("sys", "user", json_mode=True)
        self.assertEqual(captured["payload"].get("format"), "json")

    def test_no_format_when_json_mode_off(self):
        captured = {}
        prov = OllamaProvider(model="qwen3:8b")

        def fake_post(url, payload, headers, **_kw):
            captured["payload"] = payload
            return {"message": {"content": "x"}, "prompt_eval_count": 1,
                    "eval_count": 1}

        prov._post_json = fake_post  # type: ignore[assignment]
        prov.complete("sys", "user", json_mode=False)
        self.assertNotIn("format", captured["payload"])


class RetryOnParseMissTest(unittest.TestCase):
    def test_single_malformed_triggers_exactly_one_retry(self):
        prov = _FakeProvider(["not json at all", '{"goal": "ok"}'])
        retries = []
        parsed, in_tok, out_tok, attempts, err, timing = \
            summarize.complete_with_retry(
                prov, "sys", "prompt", max_parse_retries=1,
                on_retry=lambda a: retries.append(a))
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.get("goal"), "ok")
        self.assertEqual(prov.calls, 2)        # one retry, not coerced to empty
        self.assertEqual(attempts, 2)
        self.assertEqual(retries, [1])         # exactly one retry signalled
        self.assertEqual(in_tok, 20)           # tokens summed across attempts
        self.assertEqual(err, "")
        self.assertIn("load_ms", timing)       # timing dict surfaced

    def test_all_malformed_records_failure_after_bounded_retries(self):
        prov = _FakeProvider(["nope", "still nope"])
        parsed, _in, _out, attempts, err, _timing = summarize.complete_with_retry(
            prov, "sys", "prompt", max_parse_retries=1)
        self.assertIsNone(parsed)              # honest failure, not empty coercion
        self.assertEqual(prov.calls, 2)        # 1 try + 1 retry, bounded
        self.assertEqual(attempts, 2)

    def test_no_retry_when_disabled(self):
        prov = _FakeProvider(["nope", '{"goal": "ok"}'])
        parsed, _in, _out, attempts, _err, _timing = summarize.complete_with_retry(
            prov, "sys", "prompt", max_parse_retries=0)
        self.assertIsNone(parsed)
        self.assertEqual(prov.calls, 1)
        self.assertEqual(attempts, 1)

    def test_clean_first_response_no_retry(self):
        prov = _FakeProvider(['{"goal": "ok"}', "unused"])
        parsed, _in, _out, attempts, _err, _timing = summarize.complete_with_retry(
            prov, "sys", "prompt", max_parse_retries=1)
        self.assertIsNotNone(parsed)
        self.assertEqual(prov.calls, 1)
        self.assertEqual(attempts, 1)


class RawSchemaValidTest(unittest.TestCase):
    def test_clean_json_is_schema_valid(self):
        parsed = {
            "primary_archetype": {"id": "software_app"},
            "primary_domain_pair": {"domain": "software_engineering"},
            "goal": "g", "objectives": [], "requirements": [],
            "archetype_fields": {},
        }
        self.assertTrue(summarize.raw_schema_valid(parsed))

    def test_malformed_string_field_is_not_schema_valid(self):
        # Weak model emitted a bare string where an object is expected.
        parsed = {"primary_archetype": "software_app", "goal": "g"}
        self.assertFalse(summarize.raw_schema_valid(parsed))


if __name__ == "__main__":
    unittest.main()
