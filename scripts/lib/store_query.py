"""Read-only queries over the deterministic store for the `gpt` CLI.

Loads per-chat cards (`cards.jsonl`), project clusters (`clusters.json`), the
optional AI summary output (`reconstructed_projects.json`), and the run manifest
to answer `gpt` (status), `gpt list`, `gpt search`, and `gpt info` without ever
touching an LLM.
"""
from __future__ import annotations

import fnmatch
import json
import os
from typing import Iterator

import paths  # noqa: E402  (scripts/lib is on sys.path)
import run_log  # noqa: E402

_WILDCARD = set("*?[]")


def store_paths(run_label: str | None = None) -> dict[str, str]:
    """Resolve all artifact paths for a (possibly labeled) run."""
    store = paths.store_dir(run_label=run_label)
    return {
        "store": store,
        "cards": os.path.join(store, "cards.jsonl"),
        "clusters": os.path.join(store, "clusters.json"),
        "index": os.path.join(store, "index.json"),
        "bundles": paths.bundles_dir(run_label=run_label),
        "reconstructed": paths.reconstructed_json(run_label=run_label),
        "data_root": paths.run_data_root(store=store, run_label=run_label),
    }


def human_title(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").strip().title() or slug


def _matches(text: str, query: str) -> bool:
    if not query:
        return True
    text = (text or "").lower()
    query = query.lower()
    if _WILDCARD & set(query):
        return fnmatch.fnmatch(text, query)
    return query in text


def load_clusters(run_label: str | None = None) -> list[dict]:
    path = store_paths(run_label)["clusters"]
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def iter_cards(run_label: str | None = None) -> Iterator[dict]:
    path = store_paths(run_label)["cards"]
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def is_project(cluster: dict) -> bool:
    """Same filter the AI summary step uses to decide what becomes a bundle/item."""
    return cluster.get("n_versions", 0) >= 1 or cluster.get("n_conversations", 0) >= 2


def _cluster_matches(cluster: dict, query: str) -> bool:
    if _matches(cluster.get("slug", ""), query):
        return True
    if _matches(human_title(cluster.get("slug", "")), query):
        return True
    return any(_matches(t, query) for t in (cluster.get("titles") or []))


def list_projects(query: str | None = None, limit: int = 0,
                  include_all: bool = False,
                  run_label: str | None = None) -> list[dict]:
    rows = []
    for c in load_clusters(run_label):
        if not include_all and not is_project(c):
            continue
        if query and not _cluster_matches(c, query):
            continue
        rows.append({
            "slug": c.get("slug", "?"),
            "title": human_title(c.get("slug", "?")),
            "n_conversations": c.get("n_conversations", 0),
            "n_versions": c.get("n_versions", 0),
            "start_date": c.get("start_date"),
            "end_date": c.get("end_date"),
        })
    rows.sort(key=lambda r: (r["n_versions"], r["end_date"] or ""), reverse=True)
    return rows[:limit] if limit > 0 else rows


def list_chats(query: str | None = None, limit: int = 0,
               run_label: str | None = None) -> list[dict]:
    rows = []
    for c in iter_cards(run_label):
        if query and not _matches(c.get("title", ""), query):
            continue
        rows.append({
            "id": c.get("id", "?"),
            "title": c.get("title") or "(untitled)",
            "update_date": c.get("update_date"),
            "n_turns": c.get("n_turns", 0),
        })
    rows.sort(key=lambda r: r["update_date"] or "", reverse=True)
    return rows[:limit] if limit > 0 else rows


def search(query: str, limit: int = 10,
           run_label: str | None = None) -> list[dict]:
    """Mixed project+chat matches: projects first (by versions), then chats."""
    out: list[dict] = []
    for p in list_projects(query, limit=limit, run_label=run_label):
        out.append({"kind": "project", **p})
    if len(out) < limit:
        for ch in list_chats(query, limit=limit, run_label=run_label):
            out.append({
                "kind": "chat",
                "slug": ch["id"][:8],
                "title": ch["title"],
                "end_date": ch["update_date"],
                "n_conversations": 1,
                "n_versions": 0,
            })
            if len(out) >= limit:
                break
    return out[:limit]


def summary_state(run_label: str | None = None) -> dict | None:
    """Summary of the AI summary output if present."""
    path = store_paths(run_label)["reconstructed"]
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if "items" not in doc:  # legacy projects[] schema — not a v2 AI summary output
        return {"schema": "legacy", "path": path}
    return {
        "schema": "items",
        "path": path,
        "n_items": doc.get("n_items", len(doc.get("items", []))),
        "n_failed": doc.get("n_failed", 0),
        "provider": doc.get("provider"),
        "model": doc.get("model"),
        "size_bytes": os.path.getsize(path),
    }


def catalog_state(run_label: str | None = None) -> dict:
    """High-level state used by the smart `gpt` status command."""
    p = store_paths(run_label)
    have_clusters = os.path.exists(p["clusters"])
    clusters = load_clusters(run_label) if have_clusters else []
    n_chats = sum(1 for _ in iter_cards(run_label)) if os.path.exists(p["cards"]) else 0
    projects = [c for c in clusters if is_project(c)]
    dates = [c.get("start_date") for c in clusters if c.get("start_date")]
    dates += [c.get("end_date") for c in clusters if c.get("end_date")]
    return {
        "data_root": p["data_root"],
        "has_store": os.path.exists(p["cards"]),
        "has_clusters": have_clusters,
        "n_chats": n_chats,
        "n_projects": len(projects),
        "date_min": min(dates) if dates else None,
        "date_max": max(dates) if dates else None,
        "summary": summary_state(run_label),
    }


def info_stats(run_label: str | None = None) -> dict:
    """Aggregate statistics for `gpt info`."""
    clusters = load_clusters(run_label)
    projects = [c for c in clusters if is_project(c)]
    content_types: dict[str, int] = {}
    file_classes: dict[str, int] = {}
    n_turns = n_user = n_assistant = 0
    n_chats = 0
    dmin = dmax = None
    for c in iter_cards(run_label):
        n_chats += 1
        sig = c.get("signals") or {}
        n_turns += sig.get("n_turns", 0)
        n_user += sig.get("n_user_turns", 0)
        n_assistant += sig.get("n_assistant_turns", 0)
        for k, v in (sig.get("content_types") or {}).items():
            content_types[k] = content_types.get(k, 0) + v
        for k, v in (sig.get("file_ext_classes") or {}).items():
            file_classes[k] = file_classes.get(k, 0) + v
        d = c.get("update_date") or c.get("create_date")
        if d:
            dmin = d if dmin is None or d < dmin else dmin
            dmax = d if dmax is None or d > dmax else dmax
    p = store_paths(run_label)
    return {
        "data_root": p["data_root"],
        "n_chats": n_chats,
        "n_projects": len(projects),
        "n_projects_with_zips": sum(1 for c in projects if c.get("n_versions", 0) > 0),
        "date_min": dmin,
        "date_max": dmax,
        "n_turns": n_turns,
        "n_user_turns": n_user,
        "n_assistant_turns": n_assistant,
        "content_types": content_types,
        "file_classes": file_classes,
        "summary": summary_state(run_label),
        "disk": {
            "store": _dir_size(p["store"]),
            "bundles": _dir_size(p["bundles"]),
        },
    }


def _dir_size(path: str) -> int:
    total = 0
    if not os.path.isdir(path):
        return 0
    for root, _dirs, files in os.walk(path):
        for fn in files:
            try:
                total += os.path.getsize(os.path.join(root, fn))
            except OSError:
                pass
    return total
