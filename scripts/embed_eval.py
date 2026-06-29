#!/usr/bin/env python3
"""
gpt embed-eval — measure embedding-model retrieval quality and pick the best.

Builds a transient semantic index over a labeled gold set (gold chats + random
distractors) for each candidate embedding model, then scores how well each model
retrieves the gold chat for every question. Reports Recall@k, MRR@10, and an
abstention margin (so negatives can be told apart from real hits), then prints a
verdict: the best local model, or — if no local model clears --min-recall — the
cheapest viable vendor embedder.

  gpt embed-eval                                   # sweep installed local embedders
  gpt embed-eval --models bge-m3,qwen3-embedding:4b
  gpt embed-eval --variant both                    # chunk-only vs title+chunk
  gpt embed-eval --scope full                       # whole catalog, not a sample
  gpt embed-eval --include-vendor --scrub-cloud     # also price text-embedding-3-small

Read-only: never writes the real index. Local by default ($0, offline); the
vendor leg requires --scrub-cloud + OPENAI_API_KEY and is otherwise skipped.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import embeddings as emb  # noqa: E402
import ollama_probe  # noqa: E402
import paths  # noqa: E402
import store_query as sq  # noqa: E402

# Cheapest reputable vendor embedder, USD per 1M tokens (2026-06 list price).
VENDOR_PRICES = {
    "text-embedding-3-small": 0.02,
    "text-embedding-3-large": 0.13,
}
DEFAULT_VENDOR = "text-embedding-3-small"
KS = (5, 8, 10)


# ---------------------------------------------------------------------------
# Gold set + scope
# ---------------------------------------------------------------------------
def load_eval_set(path: str) -> list[dict]:
    rows: list[dict] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def gather_scope(eval_set: list[dict], *, distractors: int, scope: str,
                 seed: int, run_label: str | None) -> list[dict]:
    """Return chat records {id,title,update_date,text} for the eval scope.

    Always includes every gold chat; `scope=full` adds all remaining chats,
    otherwise a deterministic random sample of `distractors` others.
    """
    cards = sq.load_cards_map(run_label)
    gold: set[str] = set()
    for q in eval_set:
        gold.update(q.get("gold_chat_ids") or [])

    def _rec(cid: str) -> dict | None:
        c = cards.get(cid)
        if not c:
            return None
        text = sq.read_transcript(cid, run_label)
        if not text or not text.strip():
            return None
        return {"id": cid, "title": c.get("title") or "(untitled)",
                "update_date": c.get("update_date") or c.get("create_date") or "",
                "text": text}

    chosen: dict[str, dict] = {}
    for cid in gold:
        r = _rec(cid)
        if r:
            chosen[cid] = r
    others = [cid for cid in cards if cid not in gold]
    if scope == "full":
        pool = others
    else:
        rng = random.Random(seed)
        pool = rng.sample(others, min(distractors, len(others)))
    for cid in pool:
        if cid in chosen:
            continue
        r = _rec(cid)
        if r:
            chosen[cid] = r
    return list(chosen.values())


# ---------------------------------------------------------------------------
# Index build + ranking (per model/variant)
# ---------------------------------------------------------------------------
def chunk_texts(records: list[dict], *, variant: str,
                chunk_size: int, overlap: int) -> tuple[list[str], list[str]]:
    """Return (texts_to_embed, chat_id_per_chunk) for the scope.

    variant 'title_chunk' prepends '<title> (<date>)\n' to each chunk text so
    titles/dates become searchable; 'chunk' embeds the raw chunk only.
    """
    texts: list[str] = []
    chat_ids: list[str] = []
    for rec in records:
        windows = emb.chunk_transcript(rec["text"], size=chunk_size, overlap=overlap)
        prefix = ""
        if variant == "title_chunk":
            prefix = f"{rec['title']} ({rec['update_date']})\n"
        for _s, _e, ctext in windows:
            texts.append(prefix + ctext)
            chat_ids.append(rec["id"])
    return texts, chat_ids


def rank_chats(qvec, vectors, chat_ids: list[str]):
    """Return [(chat_id, best_sim)] ranked desc, one row per chat (best chunk)."""
    import numpy as np
    sims = emb.cosine_sims(qvec, vectors)
    best: dict[str, float] = {}
    for cid, s in zip(chat_ids, sims):
        s = float(s)
        if cid not in best or s > best[cid]:
            best[cid] = s
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    return ranked


def evaluate_model(eval_set, vectors, chat_ids, embed_query) -> dict:
    """Score one built index: per-question rank of gold + abstention sims."""
    pos_recall = {k: 0 for k in KS}
    rr_sum = 0.0
    n_pos = 0
    pos_top1: list[float] = []
    neg_top1: list[float] = []
    per_q: list[dict] = []
    for q in eval_set:
        qvec = embed_query(q["query"])
        ranked = rank_chats(qvec, vectors, chat_ids)
        top1 = ranked[0][1] if ranked else 0.0
        gold = set(q.get("gold_chat_ids") or [])
        if q.get("type") == "negative" or not gold:
            neg_top1.append(top1)
            per_q.append({"id": q["id"], "type": q.get("type"), "top1": round(top1, 3),
                          "rank": None, "hit@8": None})
            continue
        n_pos += 1
        pos_top1.append(top1)
        rank = None
        for i, (cid, _s) in enumerate(ranked, start=1):
            if cid in gold:
                rank = i
                break
        if rank is not None:
            rr_sum += 1.0 / rank
            for k in KS:
                if rank <= k:
                    pos_recall[k] += 1
        per_q.append({"id": q["id"], "type": q.get("type"),
                      "top1": round(top1, 3), "rank": rank,
                      "hit@8": (rank is not None and rank <= 8)})
    recall = {k: (pos_recall[k] / n_pos if n_pos else 0.0) for k in KS}
    mean_pos = sum(pos_top1) / len(pos_top1) if pos_top1 else 0.0
    mean_neg = sum(neg_top1) / len(neg_top1) if neg_top1 else 0.0
    return {
        "recall": recall,
        "mrr10": rr_sum / n_pos if n_pos else 0.0,
        "n_pos": n_pos,
        "pos_top1": round(mean_pos, 3),
        "neg_top1": round(mean_neg, 3),
        "margin": round(mean_pos - mean_neg, 3),
        "per_q": per_q,
    }


# ---------------------------------------------------------------------------
# Embedding backends
# ---------------------------------------------------------------------------
def local_embedder(model: str, host: str | None):
    def _embed(texts):
        return emb.embed_texts(texts, model=model, host=host)
    return _embed


def vendor_embedder(model: str):
    """OpenAI /v1/embeddings batcher; scrubs PII before egress. Needs API key."""
    import redact
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY not set")
    import urllib.request
    url = "https://api.openai.com/v1/embeddings"

    def _embed(texts):
        out = []
        for i in range(0, len(texts), 64):
            window = [redact.scrub(t)[0] for t in texts[i:i + 64]]
            body = json.dumps({"model": model, "input": window}).encode("utf-8")
            req = urllib.request.Request(url, data=body, headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            out.extend([d["embedding"] for d in data["data"]])
        return out
    return _embed


def discover_local_embedders(host: str | None) -> list[str]:
    models = ollama_probe.discover_models(host) or []
    return [m.get("name", "") for m in models
            if (m.get("role") or "") == "embedding" and m.get("name")]


# ---------------------------------------------------------------------------
# Sweep driver
# ---------------------------------------------------------------------------
def run_candidate(label: str, embed_fn, eval_set, records, *, variant,
                  chunk_size, overlap, trace_dir, meter_gpu=True) -> dict:
    import numpy as np
    import gpu_telemetry as tele
    texts, chat_ids = chunk_texts(records, variant=variant,
                                  chunk_size=chunk_size, overlap=overlap)
    safe = label.replace('/', '_').replace(':', '-')
    trace = os.path.join(trace_dir, f"gpu_trace_{safe}_{variant}.jsonl")
    gpu = tele.null_summary()
    t0 = time.time()
    if meter_gpu and tele.nvidia_smi_available():
        with tele.GpuTelemetry(trace, interval=0.5) as meter:
            vecs = embed_fn(texts) if texts else []
        gpu = meter.summary()
    else:
        vecs = embed_fn(texts) if texts else []
    build_s = time.time() - t0
    vectors = np.asarray(vecs, dtype="float32")
    dim = int(vectors.shape[1]) if vectors.ndim == 2 and vectors.shape[0] else 0
    # Query embeddings: embed individually (cached per query within evaluate).
    qcache: dict[str, list] = {}

    def embed_query(text: str):
        if text not in qcache:
            qcache[text] = embed_fn([text])[0]
        return qcache[text]

    res = evaluate_model(eval_set, vectors, chat_ids, embed_query)
    wh = gpu.get("energy_wh")
    res.update({"label": label, "variant": variant, "dim": dim,
                "n_chunks": len(texts), "build_s": round(build_s, 1),
                "tokens_est": sum(len(t) for t in texts) // 4,
                "wh_per_1k": (round(wh / len(texts) * 1000, 4)
                              if (wh is not None and texts) else None),
                "gpu": gpu})
    return res


def print_scorecard(results: list[dict]) -> None:
    def _n(v, fmt="{:>5.0f}"):  # None-safe cell
        return fmt.format(v) if isinstance(v, (int, float)) else f"{'—':>5}"

    def _stat(r, field, key):
        return (r.get("gpu") or {}).get(field, {}).get(key)
    hdr = (f"{'model / variant':30} {'R@5':>5} {'R@8':>5} {'R@10':>5} "
           f"{'MRR':>5} {'marg':>5} {'dim':>5} {'chunks':>7} {'build_s':>8} "
           f"{'avgW':>5} {'pkW':>5} {'pkC':>5} {'util':>5} {'Wh':>7} {'Wh/1k':>7}")
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        rc = r["recall"]
        name = f"{r['label']} · {r['variant']}"
        g = r.get("gpu") or {}
        print(f"{name:30.30} {rc[5]:5.2f} {rc[8]:5.2f} {rc[10]:5.2f} "
              f"{r['mrr10']:5.2f} {r['margin']:5.2f} {r['dim']:5d} "
              f"{r['n_chunks']:7d} {r['build_s']:8.1f} "
              f"{_n(_stat(r, 'power_w', 'avg'))} {_n(_stat(r, 'power_w', 'peak'))} "
              f"{_n(_stat(r, 'temp_c', 'peak'))} {_n(_stat(r, 'util_gpu_pct', 'avg'))} "
              f"{_n(g.get('energy_wh'), '{:>7.3f}')} "
              f"{_n(r.get('wh_per_1k'), '{:>7.4f}')}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt embed-eval",
        description="Score embedding models on a labeled gold retrieval set.")
    ap.add_argument("--fixture", default=os.path.join(
        HERE, "..", "tests", "fixtures", "embed_eval.jsonl"))
    ap.add_argument("--models", default=None,
                    help="Comma-separated embedders (default: installed Ollama "
                         "embedders auto-discovered).")
    ap.add_argument("--host", default=None, help="Ollama host override.")
    ap.add_argument("--scope", choices=("gold+distractors", "full"),
                    default="gold+distractors")
    ap.add_argument("--distractors", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--variant", choices=("chunk", "title_chunk", "both"),
                    default="both")
    ap.add_argument("--min-recall", type=float, default=0.8,
                    help="Best-local Recall@8 below this triggers the vendor leg.")
    ap.add_argument("--chunk-size", type=int, default=emb.DEFAULT_CHUNK_SIZE)
    ap.add_argument("--chunk-overlap", type=int, default=emb.DEFAULT_CHUNK_OVERLAP)
    ap.add_argument("--include-vendor", action="store_true")
    ap.add_argument("--vendor-model", default=DEFAULT_VENDOR)
    ap.add_argument("--scrub-cloud", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(argv)

    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[error] numpy is required. Run: bash setup.sh", file=sys.stderr)
        return 1

    run_label = paths.resolve_run_label(args.run_label)
    trace_dir = os.path.join(tempfile.gettempdir(), f"embed_eval_{run_label}")
    os.makedirs(trace_dir, exist_ok=True)
    eval_set = load_eval_set(os.path.abspath(args.fixture))
    records = gather_scope(eval_set, distractors=args.distractors,
                           scope=args.scope, seed=args.seed, run_label=run_label)
    if not records:
        print("[error] no scope chats (is the catalog parsed?)", file=sys.stderr)
        return 1

    n_pos = sum(1 for q in eval_set if (q.get("gold_chat_ids") and
                                        q.get("type") != "negative"))
    print(f"gpt embed-eval · {len(eval_set)} questions ({n_pos} positive) · "
          f"{len(records)} chats in scope ({args.scope})")

    variants = ("chunk", "title_chunk") if args.variant == "both" else (args.variant,)

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models = discover_local_embedders(args.host)
        if not models:
            print("[error] no local embedders installed; pass --models or "
                  "`ollama pull bge-m3`.", file=sys.stderr)
            return 1
    print(f"Local models: {', '.join(models)}\n")

    results: list[dict] = []
    for model in models:
        try:
            resolved = emb.resolve_embed_model(args.host, preferred=model)
        except emb.EmbeddingError as e:
            print(f"[skip] {model}: {e}", file=sys.stderr)
            continue
        for variant in variants:
            try:
                r = run_candidate(model, local_embedder(resolved, args.host),
                                  eval_set, records, variant=variant,
                                  chunk_size=args.chunk_size,
                                  overlap=args.chunk_overlap, trace_dir=trace_dir)
                results.append(r)
                print(f"  done {model} · {variant}: R@8={r['recall'][8]:.2f} "
                      f"MRR={r['mrr10']:.2f} ({r['build_s']:.0f}s)")
            except Exception as e:  # noqa: BLE001 - keep sweeping other models
                print(f"[skip] {model} · {variant}: {e}", file=sys.stderr)

    if not results:
        print("[error] no model produced a result.", file=sys.stderr)
        return 1

    results.sort(key=lambda r: (r["recall"][8], r["mrr10"]), reverse=True)
    best = results[0]

    # Vendor leg: explicit, or auto when the best local model is too weak.
    vendor_needed = args.include_vendor or best["recall"][8] < args.min_recall
    vendor_result = None
    if vendor_needed:
        toks = best["tokens_est"]
        price = VENDOR_PRICES.get(args.vendor_model, VENDOR_PRICES[DEFAULT_VENDOR])
        full_catalog_toks = 11_700_000  # ~38.9k chunks x ~300 tok (one-time)
        est_usd = full_catalog_toks / 1_000_000 * price
        print(f"\nVendor leg: best local Recall@8={best['recall'][8]:.2f} "
              f"(< --min-recall {args.min_recall}); cheapest = {args.vendor_model} "
              f"~${est_usd:.2f} to embed the full catalog one-time.")
        if not (args.scrub_cloud and os.environ.get("OPENAI_API_KEY")):
            print("  (skipped: needs --scrub-cloud + OPENAI_API_KEY)")
        else:
            try:
                vendor_result = run_candidate(
                    args.vendor_model, vendor_embedder(args.vendor_model),
                    eval_set, records, variant="chunk",
                    chunk_size=args.chunk_size, overlap=args.chunk_overlap,
                    trace_dir=trace_dir, meter_gpu=False)
                results.append(vendor_result)
                results.sort(key=lambda r: (r["recall"][8], r["mrr10"]),
                             reverse=True)
            except Exception as e:  # noqa: BLE001
                print(f"  [vendor skipped] {e}", file=sys.stderr)

    print()
    print_scorecard(results)

    winner = results[0]
    print()
    if winner is best or winner.get("label") in {m for m in models}:
        print(f"VERDICT  best local embedder: {winner['label']} · "
              f"{winner['variant']}  (Recall@8={winner['recall'][8]:.2f}, "
              f"MRR={winner['mrr10']:.2f}).")
        if winner["variant"] == "title_chunk":
            print("         title+date embedding helps — adopt it in gpt index (R1).")
        print(f"         Set ollama.embed_model={winner['label']} and reindex.")
    else:
        print(f"VERDICT  no local model clears Recall@8>={args.min_recall}; "
              f"cheapest viable = {winner['label']}.")

    out_path = write_generated(results, winner, run_label, len(records),
                               args.scope)
    print(f"\nwrote {out_path}")

    if args.json:
        print("\n" + json.dumps({"scope_chats": len(records), "results": results},
                                ensure_ascii=False, indent=2))
    return 0


def write_generated(results: list[dict], winner: dict, run_label: str,
                    scope_chats: int, scope: str) -> str:
    """Persist a committed, schema-shaped embed_benchmarks.json for the analysis
    layer (SUMMARY GPU table). Strips heavy per-question detail; keeps the gpu
    telemetry summary verbatim."""
    from datetime import datetime, timezone
    models: dict[str, dict] = {}
    for r in results:
        key = f"{r['label']}::{r['variant']}"
        models[key] = {
            "label": r["label"], "variant": r["variant"], "dim": r["dim"],
            "n_chunks": r["n_chunks"], "build_s": r["build_s"],
            "recall_at_8": round(r["recall"][8], 3),
            "mrr10": round(r["mrr10"], 3), "margin": round(r["margin"], 3),
            "wh_per_1k": r.get("wh_per_1k"),
            "gpu": r.get("gpu"),
        }
    doc = {
        "_generated": True,
        "generator": "embed_eval.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1.0.0",
        "run_label": run_label,
        "scope": scope,
        "scope_chats": scope_chats,
        "winner": f"{winner['label']}::{winner['variant']}",
        "models": models,
    }
    out_dir = os.path.join(HERE, os.pardir, "config", "generated")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.abspath(os.path.join(out_dir, "embed_benchmarks.json"))
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return out_path


if __name__ == "__main__":
    import interrupt
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt embed-eval"))
