"""NFR-R2: a CPU-spilled/hung local Ollama item must fail with ONE clean kill,
not retry the socket timeout ~4× (which burns ~4×timeout before giving up).

These tests drive the shared HTTP poster with a monkeypatched urlopen so they
run fully offline: they assert the local path makes exactly one attempt on a
TimeoutError, while the cloud path still retries transport errors.
"""
from __future__ import annotations

import os
import socket
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts", "lib"))
import providers.base as base  # noqa: E402
from providers.base import Provider, ProviderError, RetryableError  # noqa: E402
from providers.ollama_provider import OllamaProvider  # noqa: E402


class _CountingTimeout:
    """Stand-in for urllib.request.urlopen that always times out, counting calls
    and never sleeping (backoff is stubbed out so the test is instant)."""

    def __init__(self, exc: BaseException):
        self.calls = 0
        self._exc = exc

    def __call__(self, *_a, **_kw):
        self.calls += 1
        raise self._exc


class OllamaCleanKillTest(unittest.TestCase):
    def setUp(self):
        self._orig_urlopen = base.urllib.request.urlopen
        self._orig_backoff = Provider._backoff
        # Never actually sleep during the (would-be) backoff.
        Provider._backoff = lambda *_a, **_kw: None  # type: ignore[assignment]

    def tearDown(self):
        base.urllib.request.urlopen = self._orig_urlopen
        Provider._backoff = self._orig_backoff  # type: ignore[assignment]

    def test_ollama_single_attempt_on_timeout(self):
        spy = _CountingTimeout(TimeoutError("timed out"))
        base.urllib.request.urlopen = spy
        prov = OllamaProvider(model="gemma4:31b", host="http://localhost:11434",
                              timeout=1)
        with self.assertRaises(ProviderError):
            prov.complete("sys", "prompt")
        self.assertEqual(spy.calls, 1, "local Ollama path must not retry a timeout")

    def test_ollama_single_attempt_on_wrapped_socket_timeout(self):
        # urllib often wraps a socket timeout in a URLError(reason=timeout).
        spy = _CountingTimeout(urllib.error.URLError(socket.timeout("timed out")))
        base.urllib.request.urlopen = spy
        prov = OllamaProvider(model="gemma4:31b", host="http://localhost:11434",
                              timeout=1)
        with self.assertRaises(ProviderError):
            prov.complete("sys", "prompt")
        self.assertEqual(spy.calls, 1)

    def test_cloud_path_still_retries_timeout(self):
        # A provider that does NOT opt out keeps the resilient retry behavior.
        spy = _CountingTimeout(TimeoutError("timed out"))
        base.urllib.request.urlopen = spy
        prov = Provider(model="x", timeout=1, max_retries=4)
        with self.assertRaises(RetryableError):
            prov._post_json("http://example/api", {"a": 1},
                            {"Content-Type": "application/json"})
        self.assertEqual(spy.calls, 4, "default path should retry up to max_retries")


if __name__ == "__main__":
    unittest.main()
