"""
Offline tests for the `gpt ask` capability router + GPU gate (REQ-5/6/7).

No Ollama, no network, no CLI: the embedder, provider factory, GPU residency
probe, and cloud-engine availability are all faked. These pin the routing
contract:
  - REQ-6: local Ollama is refused when not GPU-resident (unless --allow-cpu);
  - REQ-7: with no local GPU, route to the most capable available cloud engine;
  - precedence "route, then fail": hard error only when nothing is available;
  - REQ-5: budget default is 60 (not 15), --budget 0 disables the abort.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

import numpy as np

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import ask  # noqa: E402
import ask_route  # noqa: E402
import providers  # noqa: E402


def _seed_index(root: str) -> str:
    index_dir = os.path.join(root, "index")
    os.makedirs(index_dir)
    with open(os.path.join(index_dir, "manifest.json"), "w") as f:
        json.dump({"embed_model": "test-embed", "n_chats": 1}, f)
    np.save(os.path.join(index_dir, "vectors.npy"),
            np.array([[1.0, 0.0]], dtype="float32"))
    with open(os.path.join(index_dir, "chunks.jsonl"), "w") as f:
        f.write(json.dumps({"chat_id": "c1", "title": "ADOS", "start": 0,
                            "end": 10, "update_date": "2026-06-19",
                            "text": "ados execute notes"}) + "\n")
    return index_dir


class _FakeProvider:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def complete(self, system, prompt, json_mode=False):
        return "ANSWER [1]", None


class _TimeoutProvider:
    def __init__(self, **kwargs):
        pass

    def complete(self, system, prompt, json_mode=False):
        raise providers.ProviderError("ollama: timed out after 1s")


# ---------------------------------------------------------------------------
# Pure decision (no I/O)
# ---------------------------------------------------------------------------
class PlanRouteTest(unittest.TestCase):
    def test_forced_provider_wins(self):
        p = ask_route.plan_route(route_enabled=True, forced_provider="openai",
                                 local_usable=False)
        self.assertEqual(p, {"action": "forced", "provider": "openai"})

    def test_local_gpu_used_when_usable(self):
        p = ask_route.plan_route(route_enabled=True, forced_provider=None,
                                 local_usable=True)
        self.assertEqual(p["action"], "local")

    def test_no_gpu_falls_to_cloud_order(self):
        p = ask_route.plan_route(route_enabled=True, forced_provider=None,
                                 local_usable=False)
        self.assertEqual(p["action"], "cloud")
        self.assertEqual(p["order"], ["codex", "claude", "cursor"])

    def test_routing_disabled_is_local_only(self):
        p = ask_route.plan_route(route_enabled=False, forced_provider=None,
                                 local_usable=False)
        self.assertEqual(p["action"], "local_only")

    def test_cloud_order_honours_preference(self):
        self.assertEqual(ask_route.cloud_order(["claude"]),
                         ["claude", "codex", "cursor"])
        self.assertEqual(ask_route.cloud_order(["bogus"]),
                         ["codex", "claude", "cursor"])

    def test_cursor_routes_to_composer(self):
        self.assertEqual(ask_route.model_for_engine("cursor"), "composer-2.5")
        self.assertIsNone(ask_route.model_for_engine("codex"))


class BudgetDefaultTest(unittest.TestCase):
    def test_budget_default_is_60_not_15(self):
        self.assertEqual(ask.DEFAULT_BUDGET_S, 60.0)
        self.assertEqual(ask.LATENCY_TARGET_S, 15.0)


# ---------------------------------------------------------------------------
# Integration through ask.main (mocked GPU + provider + cloud availability)
# ---------------------------------------------------------------------------
class RouteIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        _seed_index(self.tmp.name)
        self.env = patch.dict(os.environ,
                              {"RECONSTRUCTOR_DATA_ROOT": self.tmp.name})
        self.env.start()
        self.captured: dict = {}

        def fake_get_provider(name, **kw):
            self.captured["provider"] = name
            self.captured["kw"] = kw
            return _FakeProvider(**kw)

        self._patches = [
            patch("embeddings.embed_one",
                  return_value=np.array([1.0, 0.0], dtype="float32")),
            patch("providers.get_provider", fake_get_provider),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.env.stop()
        self.tmp.cleanup()

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = ask.main(argv + ["--no-daemon"])
        return rc, out.getvalue(), err.getvalue()

    def test_gpu_resident_uses_local_ollama(self):
        with patch("ask.gpu_residency",
                   return_value={"on_gpu": True, "gpu_frac": 1.0,
                                 "size": 1, "size_vram": 1, "note": "ok"}):
            rc, out, _ = self._run(["what is ados-execute?", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.captured["provider"], "ollama")
        self.assertEqual(json.loads(out)["provider"], "ollama")

    def test_no_gpu_routes_to_first_available_cloud(self):
        cpu = {"on_gpu": False, "gpu_frac": 0.0, "size": 1, "size_vram": 0,
               "note": "100% CPU"}
        avail = lambda eng, cfg: (eng == "claude", "ok" if eng == "claude" else "no")
        with patch("ask.gpu_residency", return_value=cpu), \
             patch("ask.engine_available", side_effect=avail):
            rc, out, err = self._run(["what is ados-execute?", "--json"])
        self.assertEqual(rc, 0)
        # codex unavailable -> claude is the most capable available engine.
        self.assertEqual(self.captured["provider"], "claude")
        self.assertEqual(json.loads(out)["provider"], "claude")

    def test_cursor_route_uses_composer_model(self):
        cpu = {"on_gpu": False, "gpu_frac": 0.0, "size": 1, "size_vram": 0,
               "note": "100% CPU"}
        avail = lambda eng, cfg: (eng == "cursor", "ok")
        with patch("ask.gpu_residency", return_value=cpu), \
             patch("ask.engine_available", side_effect=avail):
            rc, out, _ = self._run(["what is ados-execute?", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.captured["provider"], "cursor")
        self.assertEqual(self.captured["kw"].get("model"), "composer-2.5")

    def test_no_gpu_no_cloud_hard_fails(self):
        cpu = {"on_gpu": False, "gpu_frac": 0.0, "size": 1, "size_vram": 0,
               "note": "100% CPU"}
        with patch("ask.gpu_residency", return_value=cpu), \
             patch("ask.engine_available", return_value=(False, "no")):
            rc, _out, err = self._run(["what is ados-execute?"])
        self.assertEqual(rc, ask.EXIT_NO_GPU)
        self.assertIn("not GPU-resident", err)

    def test_forced_ollama_without_gpu_is_blocked(self):
        cpu = {"on_gpu": False, "gpu_frac": 0.0, "size": 1, "size_vram": 0,
               "note": "100% CPU"}
        with patch("ask.gpu_residency", return_value=cpu):
            rc, _out, err = self._run(["q", "--provider", "ollama"])
        self.assertEqual(rc, ask.EXIT_NO_GPU)
        self.assertIn("not GPU-resident", err)

    def test_allow_cpu_skips_gpu_probe(self):
        def boom(*a, **k):
            raise AssertionError("gpu_residency must not be probed with --allow-cpu")
        with patch("ask.gpu_residency", side_effect=boom):
            rc, out, _ = self._run(["q", "--allow-cpu", "--no-route", "--json"])
        self.assertEqual(rc, 0)
        self.assertEqual(self.captured["provider"], "ollama")

    def test_budget_zero_disables_unusable_abort(self):
        # A timeout-raising provider with --budget 0 is a plain failure (rc 1),
        # never the UNUSABLE-over-budget verdict.
        with patch("providers.get_provider", return_value=_TimeoutProvider()):
            rc, _out, err = self._run(
                ["q", "--allow-cpu", "--no-route", "--budget", "0"])
        self.assertEqual(rc, 1)
        self.assertNotIn("unusable", err.lower())

    def test_no_hits_reports_not_found(self):
        # An orthogonal query embedding yields no positive hits -> the fixed
        # not-found sentinel, no guessing (REQ-Output2).
        with patch("embeddings.embed_one",
                   return_value=np.array([0.0, 1.0], dtype="float32")):
            rc, out, _ = self._run(["unrelated cooking question",
                                    "--allow-cpu", "--no-route"])
        self.assertEqual(rc, 0)
        self.assertIn(ask.NOT_FOUND_MSG, out)

    def test_model_refusal_collapses_to_not_found(self):
        class _Refuser:
            def __init__(self, **kw):
                pass

            def complete(self, system, prompt, json_mode=False):
                return "I couldn't find that in the provided chats.", None

        with patch("providers.get_provider", return_value=_Refuser()):
            rc, out, _ = self._run(["q", "--allow-cpu", "--no-route",
                                    "--show-sources"])
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), ask.NOT_FOUND_MSG)  # no sources appended

    def test_show_sources_controls_source_visibility(self):
        # Default: sources hidden. With --show-sources: the cited list appears.
        rc, out, _ = self._run(["what is ados-execute?", "--allow-cpu",
                                "--no-route"])
        self.assertEqual(rc, 0)
        self.assertNotIn("Sources:", out)
        rc, out, _ = self._run(["what is ados-execute?", "--allow-cpu",
                                "--no-route", "--show-sources"])
        self.assertEqual(rc, 0)
        self.assertIn("Sources:", out)
        self.assertIn("id=c1", out)

    def test_details_alias_still_works(self):
        rc, out, _ = self._run(["what is ados-execute?", "--allow-cpu",
                                "--no-route", "--details"])
        self.assertEqual(rc, 0)
        self.assertIn("Sources:", out)


class NotFoundUnitTest(unittest.TestCase):
    def test_is_not_found(self):
        self.assertTrue(ask.is_not_found(""))
        self.assertTrue(ask.is_not_found("   "))
        self.assertTrue(ask.is_not_found("Not found in chat data."))
        self.assertTrue(ask.is_not_found("I could not find this in the chats"))
        self.assertFalse(ask.is_not_found("ADOS stands for Agentic Digital OS [1]"))


class ListModelsTest(unittest.TestCase):
    def test_list_models_prints_paste_commands(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = ask.main(["--list-models"])
        self.assertEqual(rc, 0)
        text = out.getvalue()
        self.assertIn("gpt ask", text)
        # A cloud engine line must advertise the data-egress flag.
        self.assertIn("--scrub-cloud", text)


if __name__ == "__main__":
    unittest.main()
