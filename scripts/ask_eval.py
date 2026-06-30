#!/usr/bin/env python3
"""
gpt ask-eval — grade `gpt ask` against a labeled battery (answer-level, repeatable).

Phase A's `gpt embed-eval` measures *retrieval* (is the gold chat in the top-k).
This measures the thing that actually regressed: the **answer**. Each battery
question carries a ground-truth grade — `version_equals` / `contains_all` /
`contains_any` / `refuse` — so a one-command run reproduces the 12-question
scorecard in ~1 minute against the EXISTING index (no reindex), making every
later retrieval/synthesis fix measurable.

  gpt ask-eval                                  # full battery, local Ollama
  gpt ask-eval --k 8 --half-life 0              # sweep a retrieval knob
  gpt ask-eval --model qwen3:8b --host 127.0.0.1:11435
  gpt ask-eval --json

Gated on a live local index + Ollama host; prints a clear note and exits 0 when
either is missing, so it never blocks. The grading functions are pure and
offline-testable (tests/test_ask_eval.py).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

DEFAULT_FIXTURE = os.path.join(HERE, os.pardir, "tests", "fixtures",
                               "ask_battery.jsonl")

# Cues that mark a grounded "I couldn't find it" refusal (negative questions).
_REFUSAL_CUES = (
    "couldn't find", "could not find", "cannot find", "can't find",
    "do not contain", "don't contain", "does not contain", "doesn't contain",
    "not in the indexed", "no relevant", "not mention", "does not mention",
    "do not mention", "no information", "not contain information",
    "not find it", "don't have", "do not have", "no mention",
)


# ---------------------------------------------------------------------------
# Pure grading (offline-testable; no numpy / no network)
# ---------------------------------------------------------------------------
def is_refusal(answer: str) -> bool:
    a = (answer or "").lower()
    return any(cue in a for cue in _REFUSAL_CUES)


def extract_versions(text: str) -> list[str]:
    """Ordered `<major>.<minor>` tokens in the text (e.g. '1.23', '2.0')."""
    return re.findall(r"\d+\.\d+", text or "")


def grade_answer(answer: str, grade: dict) -> tuple[bool, str]:
    """Return (passed, reason) for one answer against its grade spec."""
    t = (grade or {}).get("type")
    a = answer or ""
    al = a.lower()
    if t == "refuse":
        ok = is_refusal(a)
        return ok, ("refused" if ok else "did not refuse")
    if t == "contains_all":
        needles = grade.get("needles", [])
        missing = [n for n in needles if n.lower() not in al]
        return (not missing), ("all present" if not missing
                               else f"missing {missing}")
    if t == "contains_any":
        needles = grade.get("needles", [])
        hits = [n for n in needles if n.lower() in al]
        return bool(hits), (f"matched {hits}" if hits
                            else f"none of {needles}")
    if t == "version_equals":
        expected = str(grade.get("expected", ""))
        # A refusal can't satisfy a positive version question.
        if is_refusal(a):
            return False, "refused a positive question"
        versions = extract_versions(a)
        first = versions[0] if versions else None
        return (first == expected), f"first version {first} vs expected {expected}"
    return False, f"unknown grade type {t!r}"


def load_battery(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Live run (retrieval + synthesis + grade)
# ---------------------------------------------------------------------------
def run_battery(specs: list[dict], idx: dict, *, k: int, half_life: float,
                rerank: bool, provider_name: str, model: str | None,
                host: str | None, num_ctx: int | None,
                per_chat: int = 3, entities: dict | None = None,
                budget: float = 15.0) -> list[dict]:
    import math
    import time

    import ask
    import embeddings as emb
    import entities as ent
    from providers import get_provider, ProviderError

    embed_model = idx["manifest"].get("embed_model")
    # Enforce the interactive budget so a too-slow model is flagged UNUSABLE
    # here too (matches `gpt ask`): timeout=ceil(budget), single attempt.
    provider = get_provider(provider_name, model=model, host=host,
                            num_ctx=num_ctx or ask.DEFAULT_ASK_NUM_CTX,
                            timeout=max(1, math.ceil(budget)), max_retries=1)
    results: list[dict] = []
    for spec in specs:
        q = spec["question"]
        t0 = time.monotonic()
        # R6/definition: deterministic entity route (no LLM) for version-
        # superlative and acronym questions.
        routed = ent.route_answer(q, entities)
        if routed:
            elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
            gold = set(spec.get("gold_chat_ids") or [])
            gold_hit = (not gold) or (routed.get("chat_id") in gold)
            passed, reason = grade_answer(routed["answer"], spec.get("grade") or {})
            tag = routed.get("version") or routed.get("intent")
            results.append({"id": spec["id"], "passed": passed,
                            "reason": f"[entity:{routed.get('intent')}] {reason}",
                            "answer": routed["answer"],
                            "grade_type": (spec.get("grade") or {}).get("type"),
                            "gold_hit": gold_hit, "top": [f"entity:{tag}"],
                            "elapsed_ms": elapsed_ms, "unusable": False,
                            "route": "entity"})
            continue
        qvec = emb.embed_one(q, model=embed_model, host=host)
        hits = ask.retrieve(qvec, idx["vectors"], idx["chunks"], k=k,
                            half_life_days=half_life, per_chat=per_chat)
        if rerank:
            hits = ask.lexical_rerank(q, hits)
        _system, prompt, sources = ask.build_prompt(q, hits)
        gold = set(spec.get("gold_chat_ids") or [])
        retrieved = {s.get("chat_id") for s in sources}
        gold_hit = (not gold) or bool(gold & retrieved)
        try:
            answer, _usage = provider.complete(ask.SYSTEM_PROMPT, prompt,
                                               json_mode=False)
        except ProviderError as e:
            elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
            unusable = ask._looks_like_timeout(e, elapsed_ms / 1000.0, budget)
            reason = (f"unusable: exceeded {budget:g}s budget"
                      if unusable else f"synthesis error: {e}")
            results.append({"id": spec["id"], "passed": False,
                            "reason": reason, "answer": "",
                            "grade_type": (spec.get("grade") or {}).get("type"),
                            "gold_hit": gold_hit, "top": _tops(sources),
                            "elapsed_ms": elapsed_ms, "unusable": unusable,
                            "route": "synthesis"})
            continue
        elapsed_ms = round((time.monotonic() - t0) * 1000, 1)
        passed, reason = grade_answer(answer.strip(), spec.get("grade") or {})
        results.append({"id": spec["id"], "passed": passed, "reason": reason,
                        "answer": answer.strip(),
                        "grade_type": (spec.get("grade") or {}).get("type"),
                        "gold_hit": gold_hit, "top": _tops(sources),
                        "elapsed_ms": elapsed_ms,
                        "unusable": elapsed_ms > budget * 1000,
                        "route": "synthesis"})
    return results


def latency_summary(results: list[dict], budget: float) -> dict:
    """Per-run latency/usable verdict for the scorecard and metrics surface."""
    times = [r.get("elapsed_ms") or 0.0 for r in results]
    slowest = max(times) if times else 0.0
    n_unusable = sum(1 for r in results if r.get("unusable"))
    slow = max(results, key=lambda r: r.get("elapsed_ms") or 0.0, default=None)
    return {
        "budget_s": budget,
        "slowest_ms": slowest,
        "slowest_id": (slow or {}).get("id"),
        "n_unusable": n_unusable,
        "usable": n_unusable == 0,
    }


def _tops(sources: list[dict], n: int = 3) -> list[str]:
    return [f"{s.get('title')}·{s.get('update_date')}" for s in sources[:n]]


def render(results: list[dict], budget: float | None = None) -> str:
    n_pass = sum(1 for r in results if r["passed"])
    n_gold = sum(1 for r in results if r["gold_hit"])
    out = [f"ASK-EVAL — {n_pass}/{len(results)} answers correct · "
           f"{n_gold}/{len(results)} retrieved a gold chat", ""]
    out.append(f"{'id':16} {'type':14} {'grade':>5} {'gold':>4} {'ms':>7}  reason")
    out.append("-" * 86)
    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        gold = "ok" if r["gold_hit"] else "—"
        ms = r.get("elapsed_ms")
        ms_s = f"{ms:.0f}" if isinstance(ms, (int, float)) else "—"
        flag = " !" if r.get("unusable") else ""
        out.append(f"{r['id']:16.16} {str(r['grade_type']):14.14} "
                   f"{mark:>5} {gold:>4} {ms_s:>7}  {r['reason']}{flag}")
    if budget is not None:
        ls = latency_summary(results, budget)
        verdict = "USABLE" if ls["usable"] else f"UNUSABLE ({ls['n_unusable']} over budget)"
        out.append("")
        out.append(f"LATENCY — slowest {ls['slowest_ms']:.0f}ms "
                   f"({ls['slowest_id']}) · budget {budget:g}s · {verdict}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt ask-eval",
        description="Grade gpt ask against the labeled battery (answer-level).")
    ap.add_argument("--fixture", default=os.path.abspath(DEFAULT_FIXTURE))
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--half-life", type=float, default=None,
                    help="Recency half-life days (default: config/ask default).")
    ap.add_argument("--rerank", action="store_true")
    ap.add_argument("--per-chat", type=int, default=3,
                    help="Max chunks per chat (diversity cap; 0 = off).")
    ap.add_argument("--no-entity-route", action="store_true",
                    help="Disable deterministic version-superlative routing.")
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default=None)
    ap.add_argument("--host", default=None)
    ap.add_argument("--num-ctx", type=int, default=None)
    ap.add_argument("--budget", type=float, default=None,
                    help="Per-question interactive budget (s); answers over it "
                         "are flagged unusable (default: config ask.budget_s).")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[error] numpy is required. Run: bash setup.sh", file=sys.stderr)
        return 1
    import ask
    import embeddings as emb
    import entities as ent
    import paths

    specs = load_battery(args.fixture)
    run_label = paths.resolve_run_label(args.run_label)
    index_dir = paths.index_dir(run_label=run_label)
    idx = ask.load_index(index_dir)
    if idx is None:
        print("[note] no semantic index found; build it first with `gpt index`. "
              "Skipping ask-eval.", file=sys.stderr)
        return 0
    entities = None if args.no_entity_route else ent.load_entities(index_dir)

    cfg = paths.load_config()
    oll = cfg.get("ollama") or {}
    ask_cfg = cfg.get("ask") or {}
    model = args.model or oll.get("model")
    host = args.host or oll.get("host")
    half_life = (args.half_life if args.half_life is not None
                 else emb.DEFAULT_HALF_LIFE_DAYS)
    budget = args.budget or ask_cfg.get("budget_s") or ask.DEFAULT_BUDGET_S

    # FR-Q16/FR-Q17: pay the one-time cold model load BEFORE the timed battery so
    # the latency verdict reflects the WARM route (the 15s target is a warm
    # target). Best-effort and local-only; a cold first question would otherwise
    # spend minutes loading and falsely flag the route UNUSABLE.
    if args.provider == "ollama" and model:
        try:
            import ollama_probe as _op
            _op.model_gpu_state(model, host, load=True)
        except Exception:
            pass

    try:
        results = run_battery(specs, idx, k=args.k, half_life=half_life,
                              rerank=args.rerank, provider_name=args.provider,
                              model=model, host=host, num_ctx=args.num_ctx,
                              per_chat=args.per_chat, entities=entities,
                              budget=budget)
    except Exception as e:  # noqa: BLE001 - host down / model missing -> skip
        print(f"[note] ask-eval could not run (is Ollama up?): {e}. Skipping.",
              file=sys.stderr)
        return 0

    if args.json:
        n_pass = sum(1 for r in results if r["passed"])
        print(json.dumps({"passed": n_pass, "total": len(results),
                          "model": model, "provider": args.provider,
                          "latency": latency_summary(results, budget),
                          "results": results}, ensure_ascii=False, indent=2))
    else:
        print(render(results, budget=budget), end="")
    return 0


if __name__ == "__main__":
    import interrupt
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt ask-eval"))
