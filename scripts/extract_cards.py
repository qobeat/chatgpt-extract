#!/usr/bin/env python3
"""
extract_cards.py  (Extract — deterministic, zero-LLM)

Stream a ChatGPT export .zip and, per conversation, emit:
  * a compact "card" (title, slug candidates, dates, zip filenames, file
    artifacts, version tokens) -> output/store/cards.jsonl
  * a reduced, code-stripped transcript -> output/store/transcripts/<id>.txt
  * an incremental index keyed by conversation id (handles future exports;
    newer update_time wins) -> output/store/index.json

This pass NEVER calls an LLM and NEVER loads the whole JSON into memory.

Usage:
  python scripts/extract_cards.py --zip /path/a.zip [--zip /path/b.zip ...] \
      --out output/store [--limit N] [--verbose]
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
import re
import sys
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import ulog  # noqa: E402
from chatgpt_parse import (  # noqa: E402
    iter_conversations,
    active_path_nodes,
    message_text,
    conversation_dates,
    reduce_assistant_text,
)

ZIP_RE = re.compile(r"[\w][\w.\-]*?\.zip", re.I)
FILE_RE = re.compile(
    r"\b[\w\-./]+\.(?:py|ps1|psm1|md|json|jsonl|sh|ts|js|tsx|jsx|"
    r"yaml|yml|toml|sql|txt|csv|ipynb|cfg|ini|rs|go|c|cpp|h)\b",
    re.I,
)
HEX_RE = re.compile(r"\b[0-9a-f]{8,}\b", re.I)
DATE_RE = re.compile(r"\b\d{4}[-_]\d{2}[-_]\d{2}\b")
VER_RE = re.compile(r"[-_ ]?v?(\d+(?:[._]\d+){0,3})\b", re.I)
SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def epoch_to_date(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return None


def slug_from_zip(name: str) -> str:
    """
    Derive a stable project slug from a version-zip basename by cutting at the
    first date / timestamp / version / hash token. Handles patterns like:
      ollama-test-20260622-045835-test-v1_9_0.zip -> ollama-test
      ollama-test-v1_9.zip                        -> ollama-test
      ados-arena-2026-06-20-final.zip             -> ados-arena
    """
    base = re.sub(r"\.zip$", "", name, flags=re.I)
    cut_patterns = (
        r"[-_ ]\d{4}[-_]\d{2}[-_]\d{2}\b",  # -2026-06-22
        r"[-_ ]\d{8}\b",                     # -20260622
        r"[-_ ]\d{6}\b",                     # -045835 (time)
        r"[-_ ]v\d",                          # -v1
        r"[0-9a-f]{12,}",                    # long hex hash
    )
    cut = len(base)
    for pat in cut_patterns:
        m = re.search(pat, base, re.I)
        if m:
            cut = min(cut, m.start())
    base = base[:cut]
    base = SLUG_STRIP.sub("-", base.lower()).strip("-")
    return re.sub(r"-{2,}", "-", base)


def slug_from_title(title: str) -> str:
    s = SLUG_STRIP.sub("-", (title or "").lower()).strip("-")
    return re.sub(r"-{2,}", "-", s)


VER_TOKEN_RE = re.compile(r"[-_ ]v(\d+(?:[._]\d+){0,3})\b", re.I)

# Junk "zips" that pollute version counts: ChatGPT attachment hashes and bare
# numeric download names like 0.zip / 1.zip. These are NOT project versions.
PURE_HEX_RE = re.compile(r"^[0-9a-f]{8,}$", re.I)
PURE_NUM_RE = re.compile(r"^\d{1,4}$")


def version_of_zip(name: str) -> Optional[str]:
    base = re.sub(r"\.zip$", "", name, flags=re.I)
    m = VER_TOKEN_RE.search(base)
    return m.group(1).replace("_", ".") if m else None


def is_real_version_zip(name: str, slug: str) -> bool:
    """
    A real project-version zip has a meaningful slug. Reject attachment hashes
    (e.g. 6b9487ab....zip), bare numeric names (0.zip), and empty-slug names.
    """
    base = re.sub(r"\.zip$", "", name, flags=re.I)
    if not slug or not slug.strip("-"):
        return False
    if PURE_HEX_RE.match(base) or PURE_NUM_RE.match(base):
        return False
    if PURE_HEX_RE.match(slug) or PURE_NUM_RE.match(slug):
        return False
    return True


CODE_EXT = {"py", "ps1", "psm1", "sh", "ts", "js", "tsx", "jsx", "rs", "go",
            "c", "cpp", "h", "sql"}
DATA_EXT = {"json", "jsonl", "csv", "yaml", "yml", "toml"}
DOC_EXT = {"md", "txt"}
NOTEBOOK_EXT = {"ipynb"}
CONFIG_EXT = {"cfg", "ini"}


def _ext_class(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in CODE_EXT:
        return "code"
    if ext in DATA_EXT:
        return "data"
    if ext in NOTEBOOK_EXT:
        return "notebook"
    if ext in CONFIG_EXT:
        return "config"
    if ext in DOC_EXT:
        return "doc"
    return "other"


def build_card(conv: dict) -> Optional[dict]:
    cid = conv.get("id") or conv.get("conversation_id")
    if not cid:
        return None
    title = conv.get("title") or "untitled"
    ct, ut = conversation_dates(conv)
    nodes = active_path_nodes(conv)

    transcript_lines: List[str] = []
    zips: Dict[str, dict] = {}
    files: set = set()
    full_text_buf: List[str] = []

    ctype_hist: Dict[str, int] = {}
    n_user = n_assistant = 0
    has_code = False
    has_image_asset = False

    for node in nodes:
        role, text, ctype = message_text(node.get("message") or {})
        if role not in ("user", "assistant") or not text:
            continue
        ctype_hist[ctype or "text"] = ctype_hist.get(ctype or "text", 0) + 1
        if ctype == "code" or "```" in text:
            has_code = True
        if "[image]" in text or "[asset]" in text or "[dalle" in text.lower():
            has_image_asset = True
        full_text_buf.append(text)
        if role == "assistant":
            n_assistant += 1
            red = reduce_assistant_text(text)
            transcript_lines.append(f"[assistant] {red}")
        else:
            n_user += 1
            transcript_lines.append(f"[user] {text.strip()}")

    blob = "\n".join(full_text_buf)
    for m in ZIP_RE.finditer(blob):
        zname = m.group(0)
        if zname.lower() in zips:
            continue
        zslug = slug_from_zip(zname)
        zips[zname.lower()] = {
            "filename": zname,
            "slug": zslug,
            "version": version_of_zip(zname),
            "is_version": is_real_version_zip(zname, zslug),
        }
    for m in FILE_RE.finditer(blob):
        files.add(m.group(0))

    # candidate slugs: only REAL version-zip basenames vote strongly (junk
    # attachment hashes / bare-numeric zips must not create or merge clusters).
    slug_votes: Dict[str, int] = {}
    for z in zips.values():
        if z.get("is_version") and z["slug"]:
            slug_votes[z["slug"]] = slug_votes.get(z["slug"], 0) + 3
    ts = slug_from_title(title)
    if ts:
        slug_votes[ts] = slug_votes.get(ts, 0) + 1

    ext_classes: Dict[str, int] = {}
    for fa in files:
        cls = _ext_class(fa)
        ext_classes[cls] = ext_classes.get(cls, 0) + 1

    signals = {
        "content_types": ctype_hist,
        "n_turns": len(transcript_lines),
        "n_user_turns": n_user,
        "n_assistant_turns": n_assistant,
        "file_ext_classes": ext_classes,
        "n_file_artifacts": len(files),
        "has_code": has_code,
        "has_image_asset": has_image_asset,
        "n_version_zips": sum(1 for z in zips.values() if z.get("is_version")),
        "title_keywords": [t for t in slug_from_title(title).split("-") if t][:12],
    }

    return {
        "id": cid,
        "title": title,
        "create_date": epoch_to_date(ct),
        "update_date": epoch_to_date(ut),
        "create_time": ct,
        "update_time": ut,
        "zip_files": list(zips.values()),
        "file_artifacts": sorted(files),
        "slug_votes": slug_votes,
        "signals": signals,
        "transcript": "\n\n".join(transcript_lines),
        "n_turns": len(transcript_lines),
    }


def load_index(path: str) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extract: stream ChatGPT export .zip(s) into reduced "
                    "transcripts + per-conversation cards + incremental store.")
    ap.add_argument("--zip", action="append", required=True, dest="zips",
                    metavar="PATH", help="Export .zip (repeatable).")
    ap.add_argument("--out", default="output/store",
                    help="Store directory (default: output/store).")
    ap.add_argument("--verbose", action="store_true",
                    help="Log every transcript write (default: progress every 500).")
    ap.add_argument("--progress-every", type=int, default=500,
                    help="Progress cadence when not --verbose (default: 500).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after N new/changed conversations (0 = all). "
                         "Useful for fast model testing on a small subset.")
    args = ap.parse_args()
    ulog.set_verbose(args.verbose)
    ulog.set_stage("Extract")

    tdir = os.path.join(args.out, "transcripts")
    os.makedirs(tdir, exist_ok=True)
    ulog.log("MKDIR", tdir, status="ready")
    index_path = os.path.join(args.out, "index.json")
    cards_path = os.path.join(args.out, "cards.jsonl")

    try:
        index = load_index(index_path)
        ulog.log("READ", index_path, status=f"{len(index)} existing records")
    except Exception as e:
        ulog.err("READ", index_path, error=e)
        index = {}

    added, updated, skipped, seen, written = 0, 0, 0, 0, 0
    limit_reached = False
    for zp in args.zips:
        if limit_reached:
            break
        if not os.path.exists(zp):
            ulog.err("READ zip", zp, error="file not found")
            continue
        try:
            zsize = os.path.getsize(zp)
        except OSError:
            zsize = -1
        ulog.log("READ zip", zp, status=f"{zsize:,} bytes")
        try:
            for conv in iter_conversations(zp):
                seen += 1
                cid = conv.get("id") or conv.get("conversation_id")
                if not cid:
                    ulog.dbg("SKIP conv", status="no id")
                    continue
                _, ut = conversation_dates(conv)
                prev = index.get(cid)
                if prev and (prev.get("update_time") or 0) >= (ut or 0):
                    skipped += 1
                    ulog.dbg("SKIP conv", cid, status="unchanged")
                    continue
                card = build_card(conv)
                if not card:
                    ulog.dbg("SKIP conv", cid, status="build failed")
                    continue
                tpath = os.path.join(tdir, f"{cid}.txt")
                try:
                    with open(tpath, "w", encoding="utf-8") as f:
                        f.write(card["transcript"])
                    ulog.dbg("WRITE transcript", tpath,
                             status=f"{len(card['transcript'])} chars")
                except OSError as e:
                    ulog.err("WRITE transcript", tpath, error=e)
                    continue
                meta = {k: v for k, v in card.items() if k != "transcript"}
                meta["source_zip"] = os.path.basename(zp)
                index[cid] = meta
                if prev:
                    updated += 1
                else:
                    added += 1
                written += 1
                if args.limit > 0 and written >= args.limit:
                    ulog.log("LIMIT", zp, status=f"reached --limit {args.limit}")
                    limit_reached = True
                    break
                if not args.verbose and seen % args.progress_every == 0:
                    ulog.log("PROGRESS", zp,
                             status=f"seen={seen} added={added} "
                                    f"updated={updated} skipped={skipped}")
        except Exception as e:
            ulog.err("PARSE zip", zp, error=e)
            raise

    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)
        ulog.log("WRITE", index_path, status=f"{len(index)} records")
    except OSError as e:
        ulog.err("WRITE", index_path, error=e)
    try:
        with open(cards_path, "w", encoding="utf-8") as f:
            for cid, meta in index.items():
                f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        ulog.log("WRITE", cards_path, status=f"{len(index)} cards")
    except OSError as e:
        ulog.err("WRITE", cards_path, error=e)

    ulog.log("DONE", args.out,
             status=f"seen={seen} written={written} added={added} updated={updated} "
                    f"skipped={skipped} total={len(index)}")
    if seen == 0:
        sys.stderr.write(
            "\n[!] 0 conversations parsed from the archive(s).\n"
            "    Inspect the export structure (read-only):\n"
            "      python3 scripts/diagnose.py --zip <your.zip>\n"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
