#!/usr/bin/env python3
"""
gpt ask — answer a question from your own chats (semantic, local, cited).

Embeds the question with the same local model that built the index, retrieves
the most relevant transcript chunks (similarity x recency, so the *latest*
chats win on near-ties), and asks a generation model to answer using only that
retrieved context — printing the answer plus a cited Sources list.

Local by default (Ollama, $0, no data egress). Using a cloud/CLI provider
requires --scrub-cloud, which redacts PII (emails, paths, tokens, phones) from
the question and context before anything leaves the machine (NFR-P2).

  gpt ask "what is the latest ADOS README.md format?"
  gpt ask "what is the ados-geometry concept?" --k 10
  gpt ask "what are the ADOS requirements?" --since 2026-01-01
  gpt ask "..." --provider openai --model gpt-5-mini --scrub-cloud

Run `gpt index` first to build the index.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import embeddings as emb  # noqa: E402
import paths  # noqa: E402
import redact  # noqa: E402
import uio  # noqa: E402

# Providers other than local Ollama send data off-box (API or signed-in CLI),
# so they are gated behind --scrub-cloud.
LOCAL_PROVIDERS = {"ollama"}

SYSTEM_PROMPT = (
    "You answer questions using ONLY the provided excerpts from the user's own "
    "ChatGPT history. Each excerpt is tagged [n] with its chat title and date. "
    "Rules:\n"
    "- Cite the excerpts you use inline as [n].\n"
    "- If several excerpts conflict, prefer the most recent date and say so.\n"
    "- If the excerpts do not contain the answer, say you couldn't find it in "
    "the indexed chats — do not invent details.\n"
    "- Be concise and concrete."
)


# ---------------------------------------------------------------------------
# Index loading
# ---------------------------------------------------------------------------
def load_index(index_dir: str):
    """Return {manifest, vectors(np.ndarray), chunks(list)} or None if absent."""
    man_path = os.path.join(index_dir, "manifest.json")
    vec_path = os.path.join(index_dir, "vectors.npy")
    chunk_path = os.path.join(index_dir, "chunks.jsonl")
    if not (os.path.isfile(man_path) and os.path.isfile(vec_path)
            and os.path.isfile(chunk_path)):
        return None
    import numpy as np
    with open(man_path, encoding="utf-8") as f:
        manifest = json.load(f)
    vectors = np.load(vec_path)
    chunks = []
    with open(chunk_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return {"manifest": manifest, "vectors": vectors, "chunks": chunks}


# ---------------------------------------------------------------------------
# Retrieval + prompt assembly (pure; numpy via embeddings helpers)
# ---------------------------------------------------------------------------
def retrieve(qvec, vectors, chunks, *, k: int = 8,
             half_life_days: float = emb.DEFAULT_HALF_LIFE_DAYS,
             since: str | None = None, now=None) -> list[dict]:
    """Rank chunks by similarity x recency; return the top `k` as dicts.

    Each result is the chunk dict plus `sim` (cosine) and `score` (final). A
    `since` (YYYY-MM-DD) date drops older chunks entirely. Deterministic on
    ties (lower row index first).
    """
    import numpy as np
    if vectors is None or getattr(vectors, "shape", (0,))[0] == 0 or not chunks:
        return []
    sims = emb.cosine_sims(qvec, vectors)
    weights = np.asarray(
        [emb.recency_weight(c.get("update_date"), half_life_days=half_life_days,
                            now=now) for c in chunks], dtype="float32")
    final = sims * weights
    if since:
        keep = np.asarray(
            [1.0 if (c.get("update_date") or "")[:10] >= since else 0.0
             for c in chunks], dtype="float32")
        final = final * keep
    order = emb.top_indices(final, k)
    out: list[dict] = []
    for i in order:
        if float(final[i]) <= 0.0:
            continue
        hit = dict(chunks[i])
        hit["sim"] = float(sims[i])
        hit["score"] = float(final[i])
        out.append(hit)
    return out


def build_prompt(question: str, hits: list[dict]) -> tuple[str, str, list[dict]]:
    """Assemble (system, user_prompt, sources) from retrieved chunks.

    Sources are de-duplicated by chat in first-seen order and numbered [1..N];
    every excerpt in the prompt is tagged with its source number so the model
    can cite it. Returns the sources list as ordered dicts for printing.
    """
    sources: list[dict] = []
    num_by_chat: dict[str, int] = {}
    blocks: list[str] = []
    for hit in hits:
        cid = hit.get("chat_id", "")
        if cid not in num_by_chat:
            num_by_chat[cid] = len(sources) + 1
            sources.append({
                "n": num_by_chat[cid],
                "chat_id": cid,
                "title": hit.get("title") or "(untitled)",
                "update_date": hit.get("update_date") or "",
            })
        n = num_by_chat[cid]
        title = hit.get("title") or "(untitled)"
        date = hit.get("update_date") or "?"
        text = (hit.get("text") or "").strip()
        blocks.append(f"[{n}] {title} ({date})\n{text}")
    context = "\n\n".join(blocks)
    user_prompt = (
        f"Question: {question}\n\n"
        f"Excerpts from your chats (newest-weighted):\n\n{context}\n\n"
        f"Answer the question using only these excerpts, citing [n]."
    )
    return SYSTEM_PROMPT, user_prompt, sources


def format_sources(sources: list[dict]) -> str:
    lines = ["Sources:"]
    for s in sources:
        date = s.get("update_date") or "—"
        lines.append(f"  [{s['n']}] {s.get('title', '(untitled)')} · {date} · "
                     f"id={s.get('chat_id', '')}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt ask",
        description="Answer a question from your chats (semantic, local, cited).")
    ap.add_argument("question", nargs="+", help="The question to answer.")
    ap.add_argument("--k", type=int, default=8,
                    help="Number of transcript chunks to retrieve (default 8).")
    ap.add_argument("--provider", default="ollama",
                    help="Synthesis provider (default ollama; cloud needs "
                         "--scrub-cloud).")
    ap.add_argument("--model", default=None,
                    help="Synthesis model (default: config ollama.model).")
    ap.add_argument("--host", default=None, help="Ollama host override.")
    ap.add_argument("--num-ctx", type=int, default=None,
                    help="Context window for local synthesis (default: config).")
    ap.add_argument("--half-life", type=float, default=emb.DEFAULT_HALF_LIFE_DAYS,
                    help="Recency half-life in days (0 disables decay).")
    ap.add_argument("--since", default=None,
                    help="Only consider chats updated on/after YYYY-MM-DD.")
    ap.add_argument("--show-context", action="store_true",
                    help="Print the retrieved excerpts before the answer.")
    ap.add_argument("--scrub-cloud", action="store_true",
                    help="Redact PII and allow a cloud/CLI provider.")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(argv)
    question = " ".join(args.question).strip()
    if not question:
        print("[error] empty question", file=sys.stderr)
        return 2

    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[error] numpy is required for `gpt ask`. Run: bash setup.sh",
              file=sys.stderr)
        return 1

    run_label = paths.resolve_run_label(args.run_label)
    index_dir = paths.index_dir(run_label=run_label)
    idx = load_index(index_dir)
    if idx is None:
        print(f"No semantic index found at {index_dir}.", file=sys.stderr)
        print("Build it first:  gpt index", file=sys.stderr)
        return 1

    provider_name = (args.provider or "ollama").lower()
    is_local = provider_name in LOCAL_PROVIDERS
    if not is_local and not args.scrub_cloud:
        print(f"[error] provider '{provider_name}' sends data off-box. Re-run "
              f"with --scrub-cloud to redact PII first, or use --provider "
              f"ollama (local).", file=sys.stderr)
        return 2

    cfg = paths.load_config()
    embed_model = idx["manifest"].get("embed_model")
    try:
        qvec = emb.embed_one(question, model=embed_model, host=args.host)
    except emb.EmbeddingError as e:
        print(f"[error] could not embed the question: {e}", file=sys.stderr)
        return 1

    hits = retrieve(qvec, idx["vectors"], idx["chunks"], k=args.k,
                    half_life_days=args.half_life, since=args.since)
    if not hits:
        print("No relevant chats found for that question"
              + (f" since {args.since}" if args.since else "")
              + ". Try a broader question, a larger --k, or rebuild the index.")
        return 0

    system, prompt, sources = build_prompt(question, hits)

    if args.show_context:
        print(uio.context_line("gpt ask", f"{len(hits)} excerpts",
                               f"{len(sources)} chats"))
        for h in hits:
            print(f"\n--- score {h['score']:.3f} (sim {h['sim']:.3f}) · "
                  f"{h.get('title')} · {h.get('update_date')} · "
                  f"id={h.get('chat_id')}")
            print((h.get("text") or "")[:500])
        print()

    n_findings = 0
    if not is_local:
        system, sf = redact.scrub(system)
        prompt, pf = redact.scrub(prompt)
        n_findings = len(sf) + len(pf)

    from providers import get_provider, ProviderError
    prov_kwargs: dict = {"model": args.model or (cfg.get("ollama") or {}).get("model")}
    if is_local:
        oll = cfg.get("ollama") or {}
        prov_kwargs["host"] = args.host or oll.get("host")
        prov_kwargs["num_ctx"] = args.num_ctx or oll.get("num_ctx") or 32768
    if not prov_kwargs["model"]:
        prov_kwargs["model"] = "gpt-oss:20b"

    try:
        provider = get_provider(provider_name, **prov_kwargs)
        text, _usage = provider.complete(system, prompt, json_mode=False)
    except ProviderError as e:
        print(f"[error] synthesis failed: {e}", file=sys.stderr)
        # Still show the sources so the user can read the chats directly.
        print("\n" + format_sources(sources), file=sys.stderr)
        return 1

    if not is_local and n_findings:
        print(uio.context_line("gpt ask",
                               f"scrubbed {n_findings} PII match(es) before "
                               f"{provider_name}"))
    print(text.strip())
    print("\n" + format_sources(sources))
    return 0


if __name__ == "__main__":
    import interrupt
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt ask"))
