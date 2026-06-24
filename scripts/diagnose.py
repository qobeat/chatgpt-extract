#!/usr/bin/env python3
"""
diagnose.py — inspect a ChatGPT export .zip and report its actual structure.

Run this when extract_cards reports total=0, or whenever a new export behaves
unexpectedly. It does NOT modify anything.

Usage:
  python3 scripts/diagnose.py --zip /path/to/export.zip
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import chatgpt_parse as P  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    args = ap.parse_args()

    print(f"ijson available: {P._HAVE_IJSON}")
    if not os.path.exists(args.zip):
        print(f"[error] missing file: {args.zip}")
        return 1

    with zipfile.ZipFile(args.zip, "r") as zf:
        print("\n=== ZIP entries ===")
        for info in zf.infolist():
            print(f"  {info.file_size:>14,}  {info.filename}")

        try:
            entries = P.find_conversations_entries(zf)
        except FileNotFoundError as e:
            print(f"\n[error] {e}")
            return 1
        print(f"\nconversation shards: {len(entries)}")
        for e in entries[:50]:
            try:
                sz = zf.getinfo(e).file_size
            except KeyError:
                sz = -1
            print(f"  {sz:>14,}  {e}")
        entry = entries[0]
        print(f"\nprobing first shard: {entry}")

        with zf.open(entry, "r") as fh:
            head = fh.read(400)
        print("\n=== first 400 bytes ===")
        print(repr(head))
        try:
            print("\nroot kind (peek):", P._peek_root_kind(zf, entry))
        except Exception as e:
            print("peek failed:", e)

    print("\n=== strategy probe (first 3 conversations) ===")
    try:
        n = 0
        for conv in P.iter_conversations(args.zip):
            n += 1
            keys = list(conv.keys())[:12]
            cid = conv.get("id") or conv.get("conversation_id")
            title = conv.get("title")
            has_map = "mapping" in conv
            has_cur = "current_node" in conv
            print(f"  #{n} id={cid!r} title={title!r} "
                  f"mapping={has_map} current_node={has_cur}")
            print(f"      keys: {keys}")
            if n >= 3:
                break
        if n == 0:
            print("  >>> 0 conversations yielded by all strategies.")
            print("  >>> Paste the 'first 400 bytes' above back to debug the shape.")
        else:
            print(f"\n[ok] iterator works; sample yielded {n} conversation(s).")
    except Exception as e:
        print(f"  iterator error: {e}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
