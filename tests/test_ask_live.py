"""Live, end-to-end checks for the semantic Q&A system (`gpt index` + `gpt ask`).

These exercise the REAL local embedding model and (optionally) a real local
generation model, so they only run when an Ollama host with an embedder is
reachable — otherwise they SKIP, keeping the offline suite green.

  * retrieval (fast, default when Ollama is up): real bge-m3 embeddings must
    surface the right chat for the example questions
    ("what is the ADOS README.md format?", "what are the ados-evaluate skills?").
  * synthesis (slow, opt-in via GPT_ASK_LIVE_SYNTH=1): full `gpt ask` returns a
    grounded, cited answer using a small local generation model.
"""
from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(SCRIPTS, "lib"))
sys.path.insert(0, SCRIPTS)

import ask  # noqa: E402
import embeddings as emb  # noqa: E402
import index as ix  # noqa: E402
import ollama_probe  # noqa: E402

# A tiny synthetic corpus that stands in for the user's chats on these topics.
CORPUS = [
    {"id": "ados-readme", "title": "ADOS README.md format",
     "update_date": "2026-06-20",
     "text": ("The latest ADOS README.md format opens with a YAML metadata "
              "header — name, version, status, and an AUTHORITY_REF that points "
              "to project-geometry.json — followed by normative sections: "
              "Purpose, Geometry, Coordinates, and Lifecycle.")},
    {"id": "ados-evaluate", "title": "ados-evaluate skills",
     "update_date": "2026-06-22",
     "text": ("The ados-evaluate skill set covers: defining project coordinates "
              "with measures and does_not_measure, building an evaluation rubric "
              "with weighted axes and mandatory gates, and emitting a Project "
              "State as a typed observation against the geometry.")},
    {"id": "noise", "title": "weekend baking",
     "update_date": "2025-03-01",
     "text": "I tried a new sourdough recipe and the crust came out great."},
]


def _ollama_ready() -> tuple[bool, str]:
    if not ollama_probe.host_available(None):
        return False, "Ollama host not reachable"
    try:
        emb.resolve_embed_model(None)
    except emb.EmbeddingError as e:
        return False, str(e)
    return True, ""


def _small_gen_model() -> str | None:
    models = ollama_probe.discover_models(None) or []
    gens = [m for m in models if (m.get("role") or "generation") != "embedding"]
    gens.sort(key=lambda m: (m.get("size_gb") or 1e9))
    return gens[0]["name"] if gens else None


def _build_temp_index() -> str:
    model = emb.resolve_embed_model(None)
    result = ix.build_index(CORPUS, lambda t: emb.embed_texts(t, model=model),
                            embed_model=model)
    d = tempfile.mkdtemp()
    ix.write_index(os.path.join(d, "index"), result)  # mimic $DATA_ROOT/index
    return d


@unittest.skipUnless(_ollama_ready()[0], _ollama_ready()[1])
class SemanticRetrievalLiveTest(unittest.TestCase):
    """Real embeddings rank the right chat first for the example questions."""

    @classmethod
    def setUpClass(cls):
        cls.model = emb.resolve_embed_model(None)
        cls.result = ix.build_index(
            CORPUS, lambda t: emb.embed_texts(t, model=cls.model),
            embed_model=cls.model)

    def _top_source(self, question: str, *, half_life_days: float = 180.0) -> str:
        qvec = emb.embed_one(question, model=self.model)
        hits = ask.retrieve(qvec, self.result["vectors"], self.result["chunks"],
                            k=3, half_life_days=half_life_days)
        self.assertTrue(hits, "expected at least one retrieved chunk")
        _system, _prompt, sources = ask.build_prompt(question, hits)
        return sources[0]["chat_id"]

    def test_ados_readme_question(self):
        self.assertEqual(
            self._top_source("what is the ADOS README.md format?"),
            "ados-readme")

    def test_ados_evaluate_question(self):
        self.assertEqual(
            self._top_source("what are the ados-evaluate skills?"),
            "ados-evaluate")

    def test_unrelated_question_surfaces_unrelated_chat(self):
        # Pure semantic ranking (recency disabled): a baking question must rank
        # the baking chat first, proving topic separation by meaning.
        top = self._top_source("how do I bake sourdough bread?",
                               half_life_days=0)
        self.assertEqual(top, "noise")


@unittest.skipUnless(_ollama_ready()[0], _ollama_ready()[1])
@unittest.skipUnless(os.environ.get("GPT_ASK_LIVE_SYNTH") == "1",
                     "set GPT_ASK_LIVE_SYNTH=1 to run the slow synthesis path")
class AskSynthesisLiveTest(unittest.TestCase):
    """Full `gpt ask` returns a grounded, cited answer (small local model)."""

    def test_end_to_end_answer_with_sources(self):
        data_root = _build_temp_index()
        model = _small_gen_model()
        self.assertIsNotNone(model, "no local generation model installed")
        old = os.environ.get("RECONSTRUCTOR_DATA_ROOT")
        os.environ["RECONSTRUCTOR_DATA_ROOT"] = data_root
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = ask.main(["what is the ADOS README.md format?",
                               "--provider", "ollama", "--model", model,
                               "--num-ctx", "4096", "--k", "4"])
            out = buf.getvalue()
        finally:
            if old is None:
                os.environ.pop("RECONSTRUCTOR_DATA_ROOT", None)
            else:
                os.environ["RECONSTRUCTOR_DATA_ROOT"] = old
        self.assertEqual(rc, 0)
        self.assertIn("Sources:", out)
        self.assertIn("id=ados-readme", out)
        self.assertGreater(len(out.strip()), 40)


if __name__ == "__main__":
    unittest.main()
