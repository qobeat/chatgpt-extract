"""Per-zip conversation-id scan cache.

The expensive part of reading an export ``.zip`` is fully streaming every
conversation. This cache persists the set of conversation ids found in an
archive, keyed by the same cheap content fingerprint the ledger uses (file size
plus a sha256 over the first/last 1 MiB). When a zip's fingerprint is unchanged,
``gpt zips-verify`` (and any other consumer) can reuse the cached ids instead of
re-opening the archive — avoiding the long full scan.

The cache lives at ``<store>/zip_scan_cache.json`` (per run-label, beside
``zip_ledger.json``). It is purely a performance cache: a miss simply means the
caller scans the archive once and repopulates it.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any, Optional

import zip_ledger

CACHE_NAME = "zip_scan_cache.json"


def cache_path(store: str) -> str:
    return os.path.join(store, CACHE_NAME)


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load(store: str) -> dict[str, Any]:
    path = cache_path(store)
    if not os.path.exists(path):
        return {"scans": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"scans": {}}
    data.setdefault("scans", {})
    return data


def save(store: str, data: dict[str, Any]) -> None:
    os.makedirs(store, exist_ok=True)
    with open(cache_path(store), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _entry_for(data: dict[str, Any], fp: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return a cached entry only if hash AND basename+size match ``fp``.

    The basename+size guard prevents false hits when two different files share a
    content_hash (e.g. distinct empty files in tests).
    """
    entry = data.get("scans", {}).get(fp["content_hash"])
    if entry is None:
        return None
    if entry.get("basename") != fp["basename"] or entry.get("size") != fp["size"]:
        return None
    return entry


def get_ids(store: str, path: str) -> Optional[set[str]]:
    """Return cached conversation ids for ``path`` if its fingerprint matches."""
    try:
        fp = zip_ledger.fingerprint(path)
    except OSError:
        return None
    entry = _entry_for(load(store), fp)
    if entry is None:
        return None
    return {str(i) for i in entry.get("ids", [])}


def put_ids(store: str, path: str, ids: set[str]) -> Optional[dict[str, Any]]:
    """Cache the conversation-id set for ``path`` keyed by its content hash."""
    try:
        fp = zip_ledger.fingerprint(path)
    except OSError:
        return None
    data = load(store)
    entry = {
        "basename": fp["basename"],
        "size": fp["size"],
        "content_hash": fp["content_hash"],
        "ids": sorted(str(i) for i in ids),
        "count": len(ids),
        "scanned_at": _now(),
    }
    data.setdefault("scans", {})[fp["content_hash"]] = entry
    save(store, data)
    return entry
