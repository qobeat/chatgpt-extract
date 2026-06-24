#!/usr/bin/env python3
"""
build_bundles.py  (Stage 3 — deterministic, zero-LLM)

Turn each cluster into a single token-capped bundle file the LLM can ingest in
one shot. Each bundle = deterministic facts (JSON header) + reduced transcripts
of its member conversations, ordered chronologically, hard-capped by a
character budget (~4 chars/token heuristic).

Bundles land in output/bundles/<slug>.md  and a bundles/INDEX.json lists them.

Usage:
  python scripts/build_bundles.py --store output/store --out output/bundles \
      [--char-budget 48000]
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import ulog  # noqa: E402
import paths  # noqa: E402


def _pack_transcripts(members, index, tdir, budget) -> List[str]:
    """
    Fair-share packing so EVERY conversation contributes to the bundle — the
    newest chats (and therefore the latest requirements_evolution) are never
    dropped. Small conversations are kept whole; their unused budget is
    redistributed (waterfall) to larger ones, which are truncated to their share
    with an explicit marker. Members must already be in chronological order.
    """
    loaded = []
    for cid in members:
        meta = index.get(cid, {})
        tpath = os.path.join(tdir, f"{cid}.txt")
        if not os.path.exists(tpath):
            ulog.dbg("READ transcript", tpath, status="missing, skipped")
            continue
        try:
            with open(tpath, "r", encoding="utf-8") as tf:
                body = tf.read()
        except OSError as e:
            ulog.err("READ transcript", tpath, error=e)
            continue
        header = (f"\n\n--- conversation {cid} | {meta.get('create_date')} | "
                  f"{meta.get('title')} ---\n")
        loaded.append((header, body))
    if not loaded:
        return []

    n = len(loaded)
    allocations: List[int] = [0] * n
    remaining = max(0, budget)
    unassigned = list(range(n))
    # Waterfall: repeatedly hand each unassigned conversation an equal share and
    # lock in any that fit whole, freeing their surplus for the rest.
    while unassigned and remaining > 0:
        share = remaining // len(unassigned)
        if share <= 0:
            break
        progressed = False
        for i in list(unassigned):
            need = len(loaded[i][0]) + len(loaded[i][1])
            if need <= share:
                allocations[i] = need
                remaining -= need
                unassigned.remove(i)
                progressed = True
        if not progressed:
            # Remaining conversations are all larger than an equal share: split
            # the rest of the budget evenly and truncate each to its allocation.
            share = remaining // len(unassigned)
            for i in unassigned:
                allocations[i] = share
            break

    chunks: List[str] = []
    for i, (header, body) in enumerate(loaded):
        alloc = allocations[i]
        full = header + body
        if len(full) <= alloc:
            chunks.append(full)
        else:
            keep = max(0, alloc - len(header))
            note = "\n[...conversation truncated to fit bundle budget...]"
            chunks.append(header + body[:keep] + note)
    return chunks


def _cleanup_orphan_bundles(out_dir: str, kept_slugs: set[str]) -> int:
    """Remove stale .md bundles whose slug is no longer in the cluster set."""
    removed = 0
    for path in glob.glob(os.path.join(out_dir, "*.md")):
        slug = os.path.splitext(os.path.basename(path))[0]
        if slug not in kept_slugs:
            try:
                os.remove(path)
                ulog.log("REMOVE orphan", path, status="stale bundle")
                removed += 1
            except OSError as e:
                ulog.err("REMOVE orphan", path, error=e)
    return removed


def main() -> int:
    cfg = paths.load_config()
    default_char_budget = int(cfg.get("char_budget_per_bundle", 48000))

    ap = argparse.ArgumentParser(
        description="Stage 3: build one token-capped LLM bundle per cluster.")
    ap.add_argument("--store", default="output/store",
                    help="Store dir with clusters.json + transcripts/ (default: output/store).")
    ap.add_argument("--out", default="output/bundles",
                    help="Bundle output directory (default: output/bundles).")
    ap.add_argument("--char-budget", type=int, default=None,
                    help=f"Max chars per bundle (~4 chars/token; default: "
                         f"{default_char_budget} from config).")
    ap.add_argument("--min-versions", type=int, default=1,
                    help="Only bundle clusters with >= this many version zips "
                         "(default: 1 = real projects; use 0 for all clusters).")
    ap.add_argument("--no-cleanup", action="store_true",
                    help="Do not remove orphan .md bundles from a prior run.")
    args = ap.parse_args()

    char_budget = args.char_budget if args.char_budget is not None else default_char_budget

    os.makedirs(args.out, exist_ok=True)
    ulog.log("MKDIR", args.out, status="ready")
    tdir = os.path.join(args.store, "transcripts")
    clusters_path = os.path.join(args.store, "clusters.json")
    index_path = os.path.join(args.store, "index.json")
    try:
        with open(clusters_path, "r", encoding="utf-8") as f:
            clusters = json.load(f)
        ulog.log("READ", clusters_path, status=f"{len(clusters)} clusters")
    except OSError as e:
        ulog.err("READ", clusters_path, error=e)
        return 1

    kept = [c for c in clusters
            if c.get("n_versions", 0) >= args.min_versions
            or c.get("n_conversations", 0) >= 2]
    ulog.log("FILTER", clusters_path,
             status=f"{len(kept)} projects kept / {len(clusters)} clusters "
                    f"(min_versions={args.min_versions})")
    clusters = kept

    if not args.no_cleanup:
        kept_slugs = {c["slug"] for c in clusters}
        n_removed = _cleanup_orphan_bundles(args.out, kept_slugs)
        if n_removed:
            ulog.log("CLEANUP", args.out, status=f"removed {n_removed} orphan bundles")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        ulog.log("READ", index_path, status=f"{len(index)} records")
    except OSError as e:
        ulog.err("READ", index_path, error=e)
        index = {}

    bundle_index = []
    for c in clusters:
        slug = c["slug"]
        titles = c["titles"]
        max_titles = 40
        titles_field = (
            titles if len(titles) <= max_titles
            else titles[:max_titles] + [f"...(+{len(titles) - max_titles} more)"]
        )
        facts = {
            "slug": slug,
            "start_date": c["start_date"],
            "end_date": c["end_date"],
            "n_conversations": c["n_conversations"],
            "n_versions": c["n_versions"],
            "version_zip_files": c["version_zip_files"],
            "file_artifacts": c["file_artifacts"][:60],
            "titles": titles_field,
        }
        parts: List[str] = []
        parts.append("# DETERMINISTIC FACTS (authoritative — copy verbatim)\n")
        parts.append("```json\n" + json.dumps(facts, ensure_ascii=False, indent=2) + "\n```\n")
        parts.append("\n# REDUCED TRANSCRIPTS (chronological; code bodies stripped)\n")

        members = sorted(
            c["member_ids"],
            key=lambda cid: (index.get(cid, {}).get("create_time") or 0),
        )
        budget = char_budget - len("".join(parts))
        parts.extend(_pack_transcripts(members, index, tdir, budget))

        out_path = os.path.join(args.out, f"{slug}.md")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("".join(parts))
            ulog.log("WRITE bundle", out_path,
                     status=f"{sum(len(p) for p in parts):,} chars")
        except OSError as e:
            ulog.err("WRITE bundle", out_path, error=e)
            continue
        bundle_index.append({
            "slug": slug,
            "bundle": os.path.relpath(out_path),
            "n_conversations": c["n_conversations"],
            "chars": sum(len(p) for p in parts),
        })

    idx_path = os.path.join(args.out, "INDEX.json")
    try:
        with open(idx_path, "w", encoding="utf-8") as f:
            json.dump(bundle_index, f, ensure_ascii=False, indent=2)
        ulog.log("WRITE", idx_path, status=f"{len(bundle_index)} bundles")
    except OSError as e:
        ulog.err("WRITE", idx_path, error=e)
    total = sum(b["chars"] for b in bundle_index)
    ulog.log("DONE", args.out,
             status=f"{len(bundle_index)} bundles, ~{total//4} tokens total")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
