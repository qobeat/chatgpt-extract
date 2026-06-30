#!/usr/bin/env python3
"""
gpt build-entities — derive the catalog version/stability entity index.

Scans the existing index chunks (no re-embedding, no GPU) and writes
`<index_dir>/entities.json`, which powers deterministic, cited answers to
version-superlative questions in `gpt ask` (newest / latest stable). Safe to run
any time after `gpt index`; `gpt index` also refreshes it automatically.

  gpt build-entities            # build from the current index
  gpt build-entities --show     # build and print the derived verdicts
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

import entities as ent  # noqa: E402
import paths  # noqa: E402


def _iter_chunks(index_dir: str):
    path = os.path.join(index_dir, "chunks.jsonl")
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt build-entities",
                                 description="Build the version/stability entity index.")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--product", default=ent.PRODUCT,
                    help=f"Product whose versions to track (default {ent.PRODUCT}).")
    ap.add_argument("--show", action="store_true", help="Print derived verdicts.")
    args = ap.parse_args(argv)

    run_label = paths.resolve_run_label(args.run_label)
    index_dir = paths.index_dir(run_label=run_label)
    chunks_path = os.path.join(index_dir, "chunks.jsonl")
    if not os.path.isfile(chunks_path):
        print(f"[error] no index chunks at {chunks_path}. Run: gpt index",
              file=sys.stderr)
        return 1

    records = list(_iter_chunks(index_dir))
    doc = ent.build_entities(records, product=args.product,
                             source_chunks=len(records))
    out = ent.write_entities(index_dir, doc)

    summary = doc["summary"]
    n_ver = len(doc["versions"])
    print(f"[ok] entity index: {n_ver} {args.product} versions from "
          f"{len(records)} chunks -> {out}")
    if args.show:
        for label in ("newest_overall", "latest_stable"):
            v = summary.get(label)
            if v:
                tag = "" if v.get("stable", True) else "  (unstable)"
                print(f"  {label:16} = {v['version']}{tag}  "
                      f"[{v['mentions']} mentions / {v['n_chats']} chats]")
                if v.get("evidence"):
                    print(f"      evidence: {v['evidence']}")
            else:
                print(f"  {label:16} = (none)")
        acr = summary.get("acronym")
        if acr:
            print(f"  {'acronym':16} = {acr['term']} -> {acr['expansion']}  "
                  f"[{acr.get('mentions')} mentions / {acr.get('n_chats')} chats]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
