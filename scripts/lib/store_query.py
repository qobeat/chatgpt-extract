"""Read-only queries over the deterministic store for the `gpt` CLI.

Loads per-chat cards (`cards.jsonl`), project clusters (`clusters.json`), the
optional AI summary output (`reconstructed_projects.json`), and the run manifest
to answer `gpt` (status), `gpt list`, `gpt search`, `gpt project`, `gpt category`,
and `gpt info` without ever touching an LLM.
"""
from __future__ import annotations

import fnmatch
import json
import os
import re
from typing import Callable, Iterator

import paths  # noqa: E402  (scripts/lib is on sys.path)
import run_log  # noqa: E402
import zip_ledger  # noqa: E402

_WILDCARD = set("*?[]")

# User-facing browse buckets (see `gpt category --help`).
CATEGORY_IDS = ("app", "idea", "project")
IDEA_ARCHETYPES = frozenset({"knowledge_qa", "research_analysis", "content_writing"})

CATEGORY_HELP: dict[str, str] = {
    "app": "Runnable user-facing applications (primary_archetype: software_app).",
    "idea": "Exploratory threads — Q&A, research, or writing; not a durable project.",
    "project": "Multi-session work you iterated on (is_durable_project).",
}


def store_paths(run_label: str | None = None) -> dict[str, str]:
    """Resolve all artifact paths for a (possibly labeled) run."""
    store = paths.store_dir(run_label=run_label)
    return {
        "store": store,
        "cards": os.path.join(store, "cards.jsonl"),
        "clusters": os.path.join(store, "clusters.json"),
        "index": os.path.join(store, "index.json"),
        "transcripts": os.path.join(store, "transcripts"),
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


def _glob_to_regex(pattern: str) -> str:
    """Translate a glob pattern to a regex fragment (no anchors).

    `*` -> `.*`, `?` -> `.`, `[...]` character classes pass through, every other
    character is escaped. Unlike `fnmatch.translate` this adds no anchors, so the
    caller can wrap it with word-boundary lookarounds for `-w` matching.
    """
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        c = pattern[i]
        if c == "*":
            out.append(".*")
        elif c == "?":
            out.append(".")
        elif c == "[":
            j = i + 1
            if j < n and pattern[j] in ("!", "^"):
                j += 1
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:  # unterminated class -> treat '[' literally
                out.append(re.escape(c))
            else:
                inner = pattern[i + 1:j]
                if inner.startswith(("!", "^")):
                    inner = "^" + inner[1:]
                out.append("[" + inner + "]")
                i = j + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def _make_matcher(pattern: str, *, ignore_case: bool = False,
                  word: bool = False) -> Callable[[str], bool]:
    """Build a predicate `fn(text) -> bool` for the search commands.

    - word=False (contains): a literal pattern uses a fast substring test; a
      pattern with glob metacharacters is wrapped as `*pattern*` (only where a
      `*` is not already present) and matched against the whole string.
    - word=True (whole-word): the glob is matched against word tokens using
      non-word-boundary lookarounds. `_` is a word char, so `usage_events`
      counts as a single token.
    - ignore_case lowercases both sides (contains) or compiles with re.I (word).
    """
    if word:
        rx = re.compile(r"(?<!\w)" + _glob_to_regex(pattern) + r"(?!\w)",
                        re.IGNORECASE if ignore_case else 0)
        return lambda text: bool(rx.search(text or ""))

    if _WILDCARD & set(pattern):
        glob = pattern
        if not glob.startswith("*"):
            glob = "*" + glob
        if not glob.endswith("*"):
            glob = glob + "*"
        if ignore_case:
            glob = glob.lower()
            return lambda text: fnmatch.fnmatchcase((text or "").lower(), glob)
        return lambda text: fnmatch.fnmatchcase(text or "", glob)

    needle = pattern.lower() if ignore_case else pattern
    if ignore_case:
        return lambda text: needle in (text or "").lower()
    return lambda text: needle in (text or "")


def build_highlight_regex(pattern: str, *, ignore_case: bool = False,
                          word: bool = False):
    """Compile a regex that locates `pattern` occurrences for colorizing.

    Unlike the contains matcher (which tests the whole string), this finds the
    individual spans to highlight. `word` wraps the glob with non-word-boundary
    lookarounds; `ignore_case` compiles with re.I. Returns None for an empty
    pattern.
    """
    if not pattern:
        return None
    frag = _glob_to_regex(pattern)
    if word:
        frag = r"(?<!\w)" + frag + r"(?!\w)"
    return re.compile(frag, re.IGNORECASE if ignore_case else 0)


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


def load_summary_items(run_label: str | None = None) -> dict[str, dict]:
    """slug -> summarized item from reconstructed_projects.json (items[] schema)."""
    path = store_paths(run_label)["reconstructed"]
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return {}
    if "items" not in doc:
        return {}
    out: dict[str, dict] = {}
    for it in doc.get("items", []):
        slug = it.get("slug")
        if slug:
            out[str(slug)] = it
    return out


def item_categories(item: dict) -> list[str]:
    """Return browse categories for a summarized item (may be multiple)."""
    arch = (item.get("primary_archetype") or {}).get("id", "")
    durable = bool(item.get("is_durable_project"))
    cats: list[str] = []
    if arch == "software_app":
        cats.append("app")
    if durable:
        cats.append("project")
    if arch in IDEA_ARCHETYPES and not durable:
        cats.append("idea")
    return cats


def load_cards_map(run_label: str | None = None) -> dict[str, dict]:
    return {c["id"]: c for c in iter_cards(run_label) if c.get("id")}


def _cluster_map(run_label: str | None = None) -> dict[str, dict]:
    return {c["slug"]: c for c in load_clusters(run_label) if c.get("slug")}


def _chat_rows(cluster: dict, cards: dict[str, dict]) -> list[dict]:
    rows = []
    for cid in cluster.get("member_ids") or []:
        c = cards.get(cid, {})
        rows.append({
            "id": cid,
            "title": c.get("title") or "(untitled)",
            "update_date": c.get("update_date") or c.get("create_date"),
            "n_turns": c.get("n_turns", 0),
            "source_zip": c.get("source_zip"),
        })
    rows.sort(key=lambda r: r["update_date"] or "", reverse=True)
    return rows


def _project_detail(cluster: dict, item: dict | None,
                    cards: dict[str, dict]) -> dict:
    cats = item_categories(item) if item else []
    pa = (item or {}).get("primary_archetype") or {}
    row = {
        "slug": cluster.get("slug", "?"),
        "title": (item or {}).get("title") or human_title(cluster.get("slug", "?")),
        "categories": cats,
        "archetype": pa.get("id"),
        "is_durable_project": bool((item or {}).get("is_durable_project")),
        "n_conversations": cluster.get("n_conversations", 0),
        "n_versions": cluster.get("n_versions", 0),
        "n_passes": (item or {}).get("n_passes", cluster.get("n_versions", 0)),
        "start_date": cluster.get("start_date"),
        "end_date": cluster.get("end_date"),
        "goal": (item or {}).get("goal", ""),
        "classified": item is not None,
        "chats": _chat_rows(cluster, cards),
    }
    return row


def list_projects_enriched(query: str | None = None, limit: int = 0,
                           include_all: bool = False,
                           run_label: str | None = None) -> list[dict]:
    """Projects matching GLOB with summary categories and optional chat rows."""
    items = load_summary_items(run_label)
    cards = load_cards_map(run_label)
    rows: list[dict] = []
    for c in load_clusters(run_label):
        if not include_all and not is_project(c):
            continue
        if query and not _cluster_matches(c, query):
            continue
        slug = c.get("slug", "?")
        rows.append(_project_detail(c, items.get(slug), cards))
    rows.sort(key=lambda r: (r["n_versions"], r["end_date"] or ""), reverse=True)
    return rows[:limit] if limit > 0 else rows


def list_category_tree(*, categories: list[str] | None = None,
                       include_uncategorized: bool = False,
                       limit_per_category: int = 0,
                       run_label: str | None = None) -> dict:
    """Browse summarized projects grouped by app / idea / project."""
    items = load_summary_items(run_label)
    clusters = _cluster_map(run_label)
    cards = load_cards_map(run_label)
    want = list(categories or CATEGORY_IDS)
    tree: dict[str, list[dict]] = {k: [] for k in want}
    classified_chat_ids: set[str] = set()

    for slug, item in items.items():
        cats = item_categories(item)
        cluster = clusters.get(slug)
        if cluster is None:
            continue
        row = _project_detail(cluster, item, cards)
        for cid in row["chats"]:
            classified_chat_ids.add(cid["id"])
        for cat in cats:
            if cat in tree:
                tree[cat].append(row)

    for cat in tree:
        tree[cat].sort(key=lambda r: (r["n_versions"], r["end_date"] or ""),
                       reverse=True)
        if limit_per_category > 0:
            tree[cat] = tree[cat][:limit_per_category]

    uncategorized: list[dict] = []
    if include_uncategorized:
        for c in cards.values():
            cid = c.get("id")
            if not cid or cid in classified_chat_ids:
                continue
            uncategorized.append({
                "id": cid,
                "title": c.get("title") or "(untitled)",
                "update_date": c.get("update_date") or c.get("create_date"),
                "n_turns": c.get("n_turns", 0),
                "source_zip": c.get("source_zip"),
            })
        uncategorized.sort(key=lambda r: r["update_date"] or "", reverse=True)
        if limit_per_category > 0:
            uncategorized = uncategorized[:limit_per_category]

    return {
        "categories": tree,
        "uncategorized_chats": uncategorized,
        "has_summary": bool(items),
        "n_classified_chats": len(classified_chat_ids),
        "n_total_chats": len(cards),
    }


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


def _transcript_path(card_id: str, run_label: str | None = None) -> str:
    return os.path.join(store_paths(run_label)["transcripts"], f"{card_id}.txt")


def _read_transcript(card_id: str, run_label: str | None = None) -> str:
    path = _transcript_path(card_id, run_label)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, ValueError):
        return ""


def _first_matching_line(text: str, match: Callable[[str], bool]) -> str:
    for line in text.splitlines():
        if match(line):
            return line.strip()
    return ""


def search_transcripts(pattern: str, *, ignore_case: bool = False,
                       word: bool = False, scope_all: bool = False,
                       limit: int = 0,
                       run_label: str | None = None,
                       on_progress: Callable[[], None] | None = None) -> list[dict]:
    """Find chats whose reduced transcript text matches `pattern`.

    With `scope_all`, also matches the chat title and any `file_artifacts`
    filename, so a filename mentioned in the chat counts even if the reduced
    transcript dropped it (assistant code bodies are stripped). Returns rows
    sorted by update_date desc, capped by `limit` (0 = all).

    `on_progress`, if given, is called once per scanned card so callers can
    surface progress (e.g. on Ctrl+C); it must not raise.
    """
    match = _make_matcher(pattern, ignore_case=ignore_case, word=word)
    rows: list[dict] = []
    for c in iter_cards(run_label):
        if on_progress is not None:
            on_progress()
        cid = c.get("id")
        if not cid:
            continue
        text = _read_transcript(cid, run_label)
        matched_in = ""
        snippet = ""
        if match(text):
            matched_in = "text"
            snippet = _first_matching_line(text, match)
        elif scope_all and match(c.get("title") or ""):
            matched_in = "title"
            snippet = c.get("title") or ""
        elif scope_all and any(match(fa) for fa in (c.get("file_artifacts") or [])):
            matched_in = "file"
            snippet = next((fa for fa in (c.get("file_artifacts") or [])
                            if match(fa)), "")
        if not matched_in:
            continue
        rows.append({
            "id": cid,
            "title": c.get("title") or "(untitled)",
            "update_date": c.get("update_date") or c.get("create_date"),
            "n_turns": c.get("n_turns", 0),
            "snippet": snippet,
            "matched_in": matched_in,
        })
    rows.sort(key=lambda r: r["update_date"] or "", reverse=True)
    return rows[:limit] if limit > 0 else rows


def search_attachments(pattern: str, *, ignore_case: bool = False,
                       word: bool = False, limit: int = 0,
                       run_label: str | None = None,
                       on_progress: Callable[[], None] | None = None) -> list[dict]:
    """Find chats whose attachment or file_artifact names match `pattern`.

    Searches both the card `attachments` (truly attached files) and
    `file_artifacts` (filenames detected anywhere in the chat text).

    `on_progress`, if given, is called once per scanned card so callers can
    surface progress (e.g. on Ctrl+C); it must not raise.
    """
    match = _make_matcher(pattern, ignore_case=ignore_case, word=word)
    rows: list[dict] = []
    for c in iter_cards(run_label):
        if on_progress is not None:
            on_progress()
        cid = c.get("id")
        if not cid:
            continue
        names = list(c.get("attachments") or []) + list(c.get("file_artifacts") or [])
        matched = [n for n in names if match(n)]
        if not matched:
            continue
        # Preserve order while removing duplicates.
        seen: set[str] = set()
        uniq = [n for n in matched if not (n in seen or seen.add(n))]
        rows.append({
            "id": cid,
            "title": c.get("title") or "(untitled)",
            "update_date": c.get("update_date") or c.get("create_date"),
            "n_turns": c.get("n_turns", 0),
            "matched_files": uniq,
        })
    rows.sort(key=lambda r: r["update_date"] or "", reverse=True)
    return rows[:limit] if limit > 0 else rows


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


def _ledger_status(entry: dict) -> str:
    """Classify a zip_ledger entry: full pass, partial (--limit), or empty."""
    seen = int(entry.get("seen", 0))
    if seen <= 0:
        return "empty"
    written = int(entry.get("written", 0))
    skipped = int(entry.get("skipped", 0))
    if written + skipped >= seen:
        return "full"
    return "partial"


def _export_date_from_basename(basename: str) -> str | None:
    """Parse YYYY-MM-DD from a ChatGPT export basename, if present."""
    import re
    m = re.search(r"-(\d{4}-\d{2}-\d{2})-", basename)
    return m.group(1) if m else None


def _resolve_zip_size(path: str | None, ledger: dict | None) -> int | None:
    if ledger is not None and ledger.get("size") is not None:
        return int(ledger["size"])
    if path and os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return None
    return None


def _chats_by_source_zip(index_path: str) -> dict[str, int]:
    if not os.path.exists(index_path):
        return {}
    try:
        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)
    except (OSError, ValueError):
        return {}
    counts: dict[str, int] = {}
    for meta in index.values():
        sz = meta.get("source_zip")
        if sz:
            counts[str(sz)] = counts.get(str(sz), 0) + 1
    return counts


def _zip_entry_row(*, basename: str, path: str | None, ledger: dict | None,
                   chats_in_store: int) -> dict:
    if ledger is None:
        if path and os.path.isfile(path):
            status = "not_processed"
        elif chats_in_store > 0:
            status = "indexed"  # chats tagged in index, zip not in ledger
        else:
            status = "missing"
        return {
            "basename": basename,
            "path": path,
            "export_date": _export_date_from_basename(basename),
            "size_bytes": _resolve_zip_size(path, None),
            "status": status,
            "chats_in_store": chats_in_store,
            "seen": None,
            "added": None,
            "updated": None,
            "skipped": None,
            "written": None,
            "first_processed": None,
            "last_processed": None,
            "runs": None,
        }
    return {
        "basename": basename,
        "path": path,
        "export_date": _export_date_from_basename(basename),
        "size_bytes": _resolve_zip_size(path, ledger),
        "status": _ledger_status(ledger),
        "chats_in_store": chats_in_store,
        "seen": ledger.get("seen"),
        "added": ledger.get("added"),
        "updated": ledger.get("updated"),
        "skipped": ledger.get("skipped"),
        "written": ledger.get("written"),
        "first_processed": ledger.get("first_processed"),
        "last_processed": ledger.get("last_processed"),
        "runs": ledger.get("runs"),
    }


def zip_status(run_label: str | None = None,
               check_paths: list[str] | None = None) -> dict:
    """Export zip processing state from zip_ledger.json + index source_zip."""
    p = store_paths(run_label)
    store = p["store"]
    ledger_path = zip_ledger.ledger_path(store)
    ledger_data = zip_ledger.load(store)
    by_source = _chats_by_source_zip(p["index"])

    entries: list[dict] = []
    seen_basenames: set[str] = set()

    for ledger in sorted(
            ledger_data.get("zips", {}).values(),
            key=lambda e: e.get("last_processed") or ""):
        bn = ledger.get("basename", "?")
        seen_basenames.add(bn)
        path = None
        if check_paths:
            for cp in check_paths:
                if os.path.basename(cp) == bn:
                    path = cp
                    break
        entries.append(_zip_entry_row(
            basename=bn, path=path, ledger=ledger,
            chats_in_store=by_source.get(bn, 0)))

    for raw in check_paths or []:
        path = os.path.expanduser(raw)
        bn = os.path.basename(path)
        if bn in seen_basenames:
            continue
        prior = zip_ledger.lookup(store, path) if os.path.isfile(path) else None
        if prior is not None:
            seen_basenames.add(bn)
            entries.append(_zip_entry_row(
                basename=bn, path=path, ledger=prior,
                chats_in_store=by_source.get(bn, 0)))
        else:
            entries.append(_zip_entry_row(
                basename=bn, path=path, ledger=None,
                chats_in_store=by_source.get(bn, 0)))

    for bn, count in sorted(by_source.items(), key=lambda kv: kv[0]):
        if bn not in seen_basenames:
            entries.append(_zip_entry_row(
                basename=bn, path=None, ledger=None,
                chats_in_store=count))

    # Newest export first (by embedded export date, then last_processed).
    entries.sort(
        key=lambda e: (
            e.get("export_date") or "",
            e.get("last_processed") or "",
            e.get("basename") or "",
        ),
        reverse=True,
    )

    return {
        "data_root": p["data_root"],
        "store": store,
        "ledger_path": ledger_path,
        "index_path": p["index"],
        "has_ledger": os.path.exists(ledger_path),
        "entries": entries,
        "chats_by_source_zip": by_source,
        "n_chats_in_store": sum(by_source.values()),
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
