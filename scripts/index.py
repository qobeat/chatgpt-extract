#!/usr/bin/env python3
"""
gpt index — build a local semantic index over your chat transcripts.

Embeds each reduced transcript (chunked) with a local Ollama embedding model
(bge-m3 by default) and writes three files under $DATA_ROOT/index/:

  vectors.npy   float32 [n_chunks, dim] embedding matrix
  chunks.jsonl  one line per row: chat id, title, update_date, char span, text
  manifest.json embed model, dims, per-chat content hash (for incremental runs)

It is incremental: a re-run re-embeds only chats whose transcript/title/date
changed (by content hash) and reuses the rest, so adding a new export is cheap.
Everything runs locally — no cloud, no cost, no data egress.

  gpt index                 # build/update the index for the default data root
  gpt index --rebuild       # ignore the cache and re-embed everything
  gpt index --model bge-m3  # force a specific installed embedding model
  gpt index --run-label L   # index runs/<L>/store instead
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from typing import Callable, Iterable, Iterator

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import embeddings as emb  # noqa: E402
import interrupt  # noqa: E402
import paths  # noqa: E402
import store_query as sq  # noqa: E402
import uio  # noqa: E402

MANIFEST_SCHEMA = "chat-embedding-index/1"


def _now_iso() -> str:
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def content_hash(title: str, update_date: str, text: str) -> str:
    """Stable identity of a chat's indexed content (re-embed only on change)."""
    h = hashlib.sha1()
    h.update((title or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((update_date or "").encode("utf-8"))
    h.update(b"\x00")
    h.update((text or "").encode("utf-8"))
    return h.hexdigest()


def iter_chat_records(run_label: str | None = None) -> Iterator[dict]:
    """Yield {id,title,update_date,text} for every chat with a transcript."""
    for c in sq.iter_cards(run_label):
        cid = c.get("id")
        if not cid:
            continue
        text = sq.read_transcript(cid, run_label)
        if not text or not text.strip():
            continue
        yield {
            "id": cid,
            "title": c.get("title") or "(untitled)",
            "update_date": c.get("update_date") or c.get("create_date") or "",
            "text": text,
        }


def load_existing(index_dir: str):
    """Load a prior index as {manifest, vectors(np.ndarray), chunks(list)}.

    Returns None when no usable index is present. Tolerant of partial writes:
    any load failure is treated as 'no cache' so a rebuild just starts fresh.
    """
    man_path = os.path.join(index_dir, "manifest.json")
    vec_path = os.path.join(index_dir, "vectors.npy")
    chunk_path = os.path.join(index_dir, "chunks.jsonl")
    if not (os.path.isfile(man_path) and os.path.isfile(vec_path)
            and os.path.isfile(chunk_path)):
        return None
    try:
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
    except Exception:
        return None
    if manifest.get("schema") != MANIFEST_SCHEMA:
        return None
    return {"manifest": manifest, "vectors": vectors, "chunks": chunks}


def build_index(records: Iterable[dict],
                embed_fn: Callable[[list[str]], list[list[float]]],
                *, embed_model: str,
                chunk_size: int = emb.DEFAULT_CHUNK_SIZE,
                chunk_overlap: int = emb.DEFAULT_CHUNK_OVERLAP,
                existing: dict | None = None,
                rebuild: bool = False,
                on_progress: Callable[[str, bool], None] | None = None) -> dict:
    """Assemble an index from `records`, reusing unchanged chats when possible.

    `embed_fn(texts) -> list[vectors]` is injected so tests can supply a fake
    embedder. `on_progress(chat_id, reused)` is called per chat. Returns
    {"vectors": np.ndarray, "chunks": [...], "manifest": {...}, "stats": {...}}.
    Output ordering is deterministic: chats sorted by id, chunks in span order.
    """
    import numpy as np

    prev_by_chat: dict[str, dict] = {}
    if existing and not rebuild:
        man = existing["manifest"]
        vectors = existing["vectors"]
        chunks = existing["chunks"]
        for cid, meta in (man.get("chats") or {}).items():
            r0, r1 = int(meta.get("row_start", 0)), int(meta.get("row_end", 0))
            if 0 <= r0 <= r1 <= len(chunks) and r1 <= vectors.shape[0]:
                prev_by_chat[cid] = {
                    "hash": meta.get("hash"),
                    "vectors": vectors[r0:r1],
                    "chunks": chunks[r0:r1],
                }

    # First pass: decide per chat (reuse vs (re)embed) and collect texts to embed.
    plan: list[dict] = []
    to_embed_texts: list[str] = []
    to_embed_refs: list[tuple[int, int]] = []  # (plan_idx, local_chunk_idx)
    n_reused = n_embedded = 0
    for rec in sorted(records, key=lambda r: r["id"]):
        cid = rec["id"]
        h = content_hash(rec["title"], rec["update_date"], rec["text"])
        prev = prev_by_chat.get(cid)
        windows = emb.chunk_transcript(rec["text"], size=chunk_size,
                                       overlap=chunk_overlap)
        if not windows:
            continue
        entry = {"id": cid, "title": rec["title"],
                 "update_date": rec["update_date"], "hash": h,
                 "windows": windows, "vectors": None, "reused": False}
        if prev is not None and prev.get("hash") == h \
                and prev["vectors"].shape[0] == len(windows):
            entry["vectors"] = prev["vectors"]
            entry["reused"] = True
            n_reused += 1
        else:
            pidx = len(plan)
            # R1: embed title+date WITH the chunk so version/ADR tokens that live
            # in the title (e.g. "ados-profil-v1.23.zip") become retrievable. The
            # stored chunk text (for display/citations) stays the bare chunk.
            prefix = f"{rec['title']} ({rec['update_date']})\n"
            for li, (_s, _e, ctext) in enumerate(windows):
                to_embed_refs.append((pidx, li))
                to_embed_texts.append(prefix + ctext)
            n_embedded += 1
        plan.append(entry)
        if on_progress is not None:
            on_progress(cid, entry["reused"])

    # Embed everything that changed in one batched call set.
    new_vecs: list[list[float]] = embed_fn(to_embed_texts) if to_embed_texts else []
    # Scatter the returned vectors back onto their chats.
    per_chat_new: dict[int, dict[int, list[float]]] = {}
    for (pidx, li), vec in zip(to_embed_refs, new_vecs):
        per_chat_new.setdefault(pidx, {})[li] = vec
    for pidx, entry in enumerate(plan):
        if entry["vectors"] is None:
            got = per_chat_new.get(pidx, {})
            entry["vectors"] = np.asarray(
                [got[i] for i in range(len(entry["windows"]))], dtype="float32")

    # Second pass: stack rows + build chunk metadata + manifest in row order.
    rows: list = []
    chunk_meta: list[dict] = []
    chats_manifest: dict[str, dict] = {}
    dim = 0
    for entry in plan:
        vecs = entry["vectors"]
        if vecs is None or getattr(vecs, "shape", (0,))[0] == 0:
            continue
        r0 = len(chunk_meta)
        for (s, e, ctext), vec in zip(entry["windows"], vecs):
            rows.append(vec)
            chunk_meta.append({
                "row": len(chunk_meta),
                "chat_id": entry["id"],
                "title": entry["title"],
                "update_date": entry["update_date"],
                "start": s,
                "end": e,
                "text": ctext,
            })
        r1 = len(chunk_meta)
        dim = dim or (int(vecs.shape[1]) if vecs.ndim == 2 and vecs.shape[1] else 0)
        chats_manifest[entry["id"]] = {
            "hash": entry["hash"],
            "title": entry["title"],
            "update_date": entry["update_date"],
            "n_chunks": r1 - r0,
            "row_start": r0,
            "row_end": r1,
        }

    if rows:
        vectors = np.asarray(rows, dtype="float32")
        dim = int(vectors.shape[1])
    else:
        vectors = np.zeros((0, dim), dtype="float32")

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "embed_model": embed_model,
        "embed_input": "title_chunk",
        "dim": dim,
        "built_at": _now_iso(),
        "chunk_size": chunk_size,
        "chunk_overlap": chunk_overlap,
        "n_chats": len(chats_manifest),
        "n_chunks": len(chunk_meta),
        "chats": chats_manifest,
    }
    return {
        "vectors": vectors,
        "chunks": chunk_meta,
        "manifest": manifest,
        "stats": {"n_chats": len(chats_manifest), "n_chunks": len(chunk_meta),
                  "n_reused": n_reused, "n_embedded": n_embedded},
    }


def write_index(index_dir: str, result: dict) -> None:
    """Write vectors.npy + chunks.jsonl + manifest.json (parent dirs created)."""
    import numpy as np
    os.makedirs(index_dir, exist_ok=True)
    vec_path = os.path.join(index_dir, "vectors.npy")
    chunk_path = os.path.join(index_dir, "chunks.jsonl")
    man_path = os.path.join(index_dir, "manifest.json")
    np.save(vec_path, result["vectors"])  # path ends in .npy -> written as-is
    tmp = chunk_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for row in result["chunks"]:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    os.replace(tmp, chunk_path)
    tmp = man_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(result["manifest"], f, ensure_ascii=False, indent=2)
    os.replace(tmp, man_path)
    # Refresh the derived entity index (version/stability facts). Best-effort:
    # it is rebuildable any time via `gpt build-entities`, so never block a
    # successful index write on it.
    try:
        import entities as ent
        ent.write_entities(index_dir, ent.build_entities(
            result["chunks"], source_chunks=len(result["chunks"])))
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt index",
        description="Build/update the local semantic index over chat transcripts.")
    ap.add_argument("--model", default=None,
                    help="Embedding model (default: installed bge-m3, else "
                         "qwen3-embedding).")
    ap.add_argument("--host", default=None, help="Ollama host override.")
    ap.add_argument("--chunk-size", type=int, default=emb.DEFAULT_CHUNK_SIZE)
    ap.add_argument("--chunk-overlap", type=int, default=emb.DEFAULT_CHUNK_OVERLAP)
    ap.add_argument("--rebuild", action="store_true",
                    help="Ignore the cache and re-embed every chat.")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(argv)

    try:
        import numpy  # noqa: F401
    except ImportError:
        print("[error] numpy is required for `gpt index`. Run: bash setup.sh",
              file=sys.stderr)
        return 1

    run_label = paths.resolve_run_label(args.run_label)
    st = sq.catalog_state(run_label)
    if not st.get("has_store"):
        print("No parsed data yet. Run: gpt run --zip <export>.zip",
              file=sys.stderr)
        return 1

    if not emb.ollama_probe.host_available(args.host):
        host = emb.ollama_probe.normalize_host(args.host)
        print(f"[error] Ollama host unreachable at {host}. Start `ollama serve` "
              f"and retry.", file=sys.stderr)
        return 1
    try:
        model = emb.resolve_embed_model(args.host, preferred=args.model)
    except emb.EmbeddingError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    index_dir = paths.index_dir(run_label=run_label)
    existing = None if args.rebuild else load_existing(index_dir)

    n_chats = st.get("n_chats", 0)
    interrupt.set_total(n_chats, unit="chats")
    print(uio.context_line("gpt index", f"model {model}",
                           f"{'rebuild' if args.rebuild else 'incremental'}"))
    print(f"Indexing up to {n_chats:,} chats into {index_dir} ...")

    def _embed(texts: list[str]) -> list[list[float]]:
        return emb.embed_texts(texts, model=model, host=args.host)

    def _progress(_cid: str, _reused: bool) -> None:
        interrupt.advance()

    records = list(iter_chat_records(run_label))
    result = build_index(records, _embed, embed_model=model,
                         chunk_size=args.chunk_size,
                         chunk_overlap=args.chunk_overlap,
                         existing=existing, rebuild=args.rebuild,
                         on_progress=_progress)
    write_index(index_dir, result)

    s = result["stats"]
    print(uio.kv("Indexed", f"{s['n_chats']:,} chats · {s['n_chunks']:,} chunks"))
    print(uio.kv("Embedded", f"{s['n_embedded']:,} changed · "
                 f"{s['n_reused']:,} reused from cache"))
    print(f"\nNext  gpt ask \"what is the latest ADOS README.md format?\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt index"))
