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
  gpt ask "what is the ados-geometry concept?" --k 10 --rerank
  gpt ask "what are the ADOS requirements?" --since 2026-01-01
  gpt ask "..." --provider openai --model gpt-5-mini --scrub-cloud
  gpt ask "..." --json                 # machine-readable answer + sources

Run `gpt index` first to build the index. Without one, `gpt ask` degrades to a
keyword scan over transcripts (warns, still returns the most relevant chats)
rather than erroring. Sources carry chunk char-offsets so a citation points at
an exact transcript region.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import embeddings as emb  # noqa: E402
import entities as ent  # noqa: E402
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
             since: str | None = None, now=None,
             per_chat: int = 3, pool_factor: int = 4) -> list[dict]:
    """Rank chunks by similarity x recency; return the top `k` as dicts.

    R3 per-chat diversity cap: with `per_chat > 0`, scan a larger candidate pool
    (`k * pool_factor`) but admit at most `per_chat` chunks from any single
    `chat_id`, so one long version-enumeration chat can't flood the top-k and
    crowd out the chat that actually answers the question. `per_chat=0` disables
    the cap (legacy behaviour: pure top-k).

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
    pool = k if per_chat <= 0 else min(len(chunks), max(k * pool_factor, k))
    order = emb.top_indices(final, pool)
    out: list[dict] = []
    seen: dict[str, int] = {}
    for i in order:
        if float(final[i]) <= 0.0:
            continue
        if per_chat > 0:
            cid = chunks[i].get("chat_id")
            if seen.get(cid, 0) >= per_chat:
                continue
            seen[cid] = seen.get(cid, 0) + 1
        hit = dict(chunks[i])
        hit["sim"] = float(sims[i])
        hit["score"] = float(final[i])
        out.append(hit)
        if len(out) >= k:
            break
    return out


def lexical_rerank(question: str, hits: list[dict]) -> list[dict]:
    """Re-order `hits` by blending the semantic score with lexical overlap.

    A lightweight, dependency-free re-rank: each hit's final score is its
    retrieval `score` nudged by the fraction of distinct question words that
    appear in the excerpt. This sharpens precision when several chunks are
    semantically close but only some actually mention the asked-about terms.
    Deterministic; a full cross-encoder re-rank remains a future option.
    """
    qwords = {w for w in re_words(question) if len(w) > 2}
    if not qwords or not hits:
        return list(hits)
    ranked = []
    for i, hit in enumerate(hits):
        words = set(re_words(hit.get("text") or ""))
        overlap = len(qwords & words) / len(qwords)
        base = float(hit.get("score") or 0.0)
        ranked.append((-(base * (1.0 + overlap)), i, hit))
    ranked.sort(key=lambda t: (t[0], t[1]))
    return [h for _s, _i, h in ranked]


def re_words(text: str) -> list[str]:
    """Lowercased alphanumeric word tokens (helper for lexical scoring)."""
    import re
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def build_prompt(question: str, hits: list[dict]) -> tuple[str, str, list[dict]]:
    """Assemble (system, user_prompt, sources) from retrieved chunks.

    Sources are de-duplicated by chat in first-seen order and numbered [1..N];
    every excerpt in the prompt is tagged with its source number so the model
    can cite it. Each source also carries the char span of its first matching
    chunk (`start`/`end`) so a citation points at an exact transcript region.
    Returns the sources list as ordered dicts for printing.
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
                "start": hit.get("start"),
                "end": hit.get("end"),
            })
        n = num_by_chat[cid]
        title = hit.get("title") or "(untitled)"
        date = hit.get("update_date") or "?"
        span = ""
        if isinstance(hit.get("start"), int) and isinstance(hit.get("end"), int):
            span = f" chars {hit['start']}-{hit['end']}"
        text = (hit.get("text") or "").strip()
        blocks.append(f"[{n}] {title} ({date}){span}\n{text}")
    context = "\n\n".join(blocks)
    user_prompt = (
        f"Question: {question}\n\n"
        f"Excerpts from your chats (newest-weighted):\n\n{context}\n\n"
        f"Answer the question using only these excerpts, citing [n]."
    )
    return SYSTEM_PROMPT, user_prompt, sources


def source_for_chat(idx: dict, chat_id: str | None) -> list[dict]:
    """Build a single-entry sources list (citation) for a routed answer."""
    if not chat_id:
        return []
    for c in idx.get("chunks", []):
        if c.get("chat_id") == chat_id:
            return [{"n": 1, "chat_id": chat_id,
                     "title": c.get("title") or "(untitled)",
                     "update_date": c.get("update_date") or "",
                     "start": c.get("start"), "end": c.get("end")}]
    return [{"n": 1, "chat_id": chat_id, "title": "(untitled)",
             "update_date": "", "start": None, "end": None}]


def format_sources(sources: list[dict]) -> str:
    lines = ["Sources:"]
    for s in sources:
        date = s.get("update_date") or "—"
        span = ""
        if isinstance(s.get("start"), int) and isinstance(s.get("end"), int):
            span = f" · chars {s['start']}-{s['end']}"
        lines.append(f"  [{s['n']}] {s.get('title', '(untitled)')} · {date} · "
                     f"id={s.get('chat_id', '')}{span}")
    return "\n".join(lines)


def keyword_fallback(question: str, run_label: str | None,
                     k: int) -> list[dict]:
    """Sources-shaped keyword hits when no semantic index exists.

    Scans transcripts for the question's salient words (longest first) so
    `gpt ask` still returns the most relevant chats — degraded, but useful —
    instead of erroring out. No embeddings, no LLM.
    """
    import store_query as sq
    words = sorted({w for w in re_words(question) if len(w) > 3},
                   key=len, reverse=True)
    rows: list[dict] = []
    seen: set[str] = set()
    for w in words or [question]:
        for r in sq.search_transcripts(w, ignore_case=True, scope_all=True,
                                       limit=k, run_label=run_label):
            cid = r.get("id")
            if cid in seen:
                continue
            seen.add(cid)
            rows.append({
                "n": len(rows) + 1,
                "chat_id": cid,
                "title": r.get("title") or "(untitled)",
                "update_date": r.get("update_date") or "",
                "snippet": r.get("snippet") or "",
            })
            if len(rows) >= k:
                return rows
    return rows


def index_is_stale(idx: dict, run_label: str | None) -> bool:
    """True when the catalog holds more chats than the index captured.

    A cheap freshness signal: after `gpt run` adds chats, the index built
    before it will under-cover the catalog until `gpt index` re-runs.
    """
    try:
        import store_query as sq
        st = sq.catalog_state(run_label)
        return int(st.get("n_chats") or 0) > int(
            (idx.get("manifest") or {}).get("n_chats") or 0)
    except Exception:
        return False


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
    ap.add_argument("--per-chat", type=int, default=3,
                    help="Max chunks admitted per chat (diversity cap; 0 = off). "
                         "Stops one long chat from flooding the top-K.")
    ap.add_argument("--no-entity-route", action="store_true",
                    help="Disable deterministic version-superlative answers from "
                         "the entity index (force retrieval + synthesis).")
    ap.add_argument("--since", default=None,
                    help="Only consider chats updated on/after YYYY-MM-DD.")
    ap.add_argument("--show-context", action="store_true",
                    help="Print the retrieved excerpts before the answer.")
    ap.add_argument("--rerank", action="store_true",
                    help="Blend a lexical-overlap re-rank into retrieval for "
                         "sharper precision on the top-K.")
    ap.add_argument("--json", action="store_true",
                    help="Emit a JSON object (answer + sources) for scripting.")
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
        # No embeddings yet: degrade to a keyword scan rather than error out, so
        # `gpt ask` still surfaces the most relevant chats (FR-Q follow-up).
        fb = keyword_fallback(question, run_label, args.k)
        note = (f"No semantic index at {index_dir}; answered by keyword scan. "
                f"Build the index for grounded answers:  gpt index")
        if args.json:
            print(json.dumps({"question": question, "answer": None,
                              "mode": "keyword_fallback", "note": note,
                              "sources": fb}, ensure_ascii=False, indent=2))
            return 0
        print(f"[warn] {note}", file=sys.stderr)
        if not fb:
            print("No chats matched those keywords either. Run: gpt index",
                  file=sys.stderr)
            return 1
        for s in fb:
            snip = (s.get("snippet") or "").strip()
            print(f"  [{s['n']}] {s['title']} · {s.get('update_date') or '—'} · "
                  f"id={s['chat_id']}")
            if snip:
                print(f"      … {snip[:160]}")
        return 0

    # R6 intent routing: a version-superlative question ("newest / latest stable
    # version?") is a fact about the whole catalog, not a passage — answer it
    # deterministically from the entity index with a citation, before involving
    # the language model. Local, no data egress, repeatable.
    if not args.no_entity_route:
        routed = ent.answer_version_query(question, ent.load_entities(index_dir))
        if routed:
            sources = source_for_chat(idx, routed.get("chat_id"))
            if args.json:
                print(json.dumps({
                    "question": question, "answer": routed["answer"],
                    "route": "entity", "intent": routed["intent"],
                    "version": routed["version"], "sources": sources,
                }, ensure_ascii=False, indent=2))
                return 0
            print(routed["answer"])
            if sources:
                print("\n" + format_sources(sources))
            return 0

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

    if index_is_stale(idx, run_label):
        print(uio.context_line("gpt ask", "index may be stale vs the catalog; "
                               "run `gpt index` to refresh"), file=sys.stderr)

    hits = retrieve(qvec, idx["vectors"], idx["chunks"], k=args.k,
                    half_life_days=args.half_life, since=args.since,
                    per_chat=args.per_chat)
    if args.rerank:
        hits = lexical_rerank(question, hits)
    if not hits:
        if args.json:
            print(json.dumps({"question": question, "answer": None,
                              "sources": []}, ensure_ascii=False, indent=2))
            return 0
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

    if args.json:
        print(json.dumps({
            "question": question,
            "answer": text.strip(),
            "provider": provider_name,
            "scrubbed_pii": n_findings if not is_local else 0,
            "sources": sources,
        }, ensure_ascii=False, indent=2))
        return 0

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
