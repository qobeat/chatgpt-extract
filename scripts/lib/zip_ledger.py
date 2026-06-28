"""Per-zip "already handled" ledger.

Records which export .zip archives have been processed by the Extract step so a
re-run can notify the user instead of silently re-scanning a 1.5 GB+ archive only
to skip every (unchanged) conversation.

Identity is a cheap content fingerprint: file size plus a sha256 over the first
and last 1 MiB. This is robust to rename/re-download (same bytes -> same hash)
without reading the whole archive, keeping Extract fast on large exports.

The ledger lives at ``<store>/zip_ledger.json`` (per run-label, beside
``index.json``).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from typing import Any, Optional

LEDGER_NAME = "zip_ledger.json"

# Bytes read from each end for the content hash (1 MiB).
_CHUNK = 1024 * 1024


def ledger_path(store: str) -> str:
    return os.path.join(store, LEDGER_NAME)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def content_hash(path: str, size: int) -> str:
    """sha256 over size + first 1 MiB + last 1 MiB (whole file if smaller)."""
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    with open(path, "rb") as f:
        head = f.read(_CHUNK)
        h.update(head)
        if size > _CHUNK:
            tail_start = max(_CHUNK, size - _CHUNK)
            f.seek(tail_start)
            h.update(f.read(_CHUNK))
    return h.hexdigest()


def fingerprint(path: str) -> dict[str, Any]:
    """Return ``{basename, size, mtime, content_hash}`` for an existing file."""
    st = os.stat(path)
    return {
        "basename": os.path.basename(path),
        "size": st.st_size,
        "mtime": st.st_mtime,
        "content_hash": content_hash(path, st.st_size),
    }


def load(store: str) -> dict[str, Any]:
    path = ledger_path(store)
    if not os.path.exists(path):
        return {"zips": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"zips": {}}
    data.setdefault("zips", {})
    return data


def save(store: str, data: dict[str, Any]) -> None:
    os.makedirs(store, exist_ok=True)
    with open(ledger_path(store), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _match(data: dict[str, Any], fp: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Find a prior entry by content_hash, falling back to basename+size."""
    zips = data.get("zips", {})
    entry = zips.get(fp["content_hash"])
    if entry is not None:
        return entry
    for e in zips.values():
        if e.get("basename") == fp["basename"] and e.get("size") == fp["size"]:
            return e
    return None


def lookup(store: str, path: str) -> Optional[dict[str, Any]]:
    """Return the prior ledger entry for ``path``, or None if never handled."""
    try:
        fp = fingerprint(path)
    except OSError:
        return None
    return _match(load(store), fp)


def record(store: str, path: str, stats: dict[str, Any]) -> dict[str, Any]:
    """Upsert the ledger entry for ``path`` with this run's per-zip ``stats``.

    ``stats`` keys: seen, added, updated, skipped, written, shards_total,
    shards_parsed. ``shards_parsed < shards_total`` flags a lost shard so
    COORD-C-COVERAGE can treat it as a visible miss, not a silent drop.
    """
    data = load(store)
    fp = fingerprint(path)
    key = fp["content_hash"]
    now = _now()
    prev = _match(data, fp)
    if prev is not None:
        entry = prev
        entry["last_processed"] = now
        entry["runs"] = int(entry.get("runs", 1)) + 1
    else:
        entry = {
            "first_processed": now,
            "last_processed": now,
            "runs": 1,
        }
    entry.update({
        "basename": fp["basename"],
        "size": fp["size"],
        "mtime": fp["mtime"],
        "content_hash": fp["content_hash"],
        "seen": int(stats.get("seen", 0)),
        "added": int(stats.get("added", 0)),
        "updated": int(stats.get("updated", 0)),
        "skipped": int(stats.get("skipped", 0)),
        "written": int(stats.get("written", 0)),
        "shards_total": int(stats.get("shards_total", 0)),
        "shards_parsed": int(stats.get("shards_parsed", 0)),
    })
    data.setdefault("zips", {})[key] = entry
    save(store, data)
    return entry
