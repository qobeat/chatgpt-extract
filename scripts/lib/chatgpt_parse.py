"""
chatgpt_parse.py — shared, dependency-light parsing for OpenAI ChatGPT exports.

Responsibilities
  1. Stream conversations straight out of a (multi-GB) export .zip without
     unpacking the whole archive or loading the whole JSON into memory.
  2. Reconstruct the *canonical* conversation path (current_node -> root),
     so discarded regenerations / forked branches are dropped.
  3. Extract message text robustly across content_type shapes, including
     object-valued `parts` (image/audio pointers) that crash naive parsers.

Streaming backend: `ijson` if available (fast, C-backed), else a pure-stdlib
fallback that decodes the array element-by-element. ijson is strongly
recommended for the 1-2 GB archives.
"""
from __future__ import annotations
import io
import json
import re
import zipfile
from typing import Dict, Iterator, List, Optional, Tuple

import ulog

_SENTINEL = object()

try:
    import ijson  # type: ignore
    _HAVE_IJSON = True
except Exception:  # pragma: no cover
    _HAVE_IJSON = False

import re as _re

# Matches conversations.json and sharded conversations-000.json ... -NNN.json
_CONV_RE = _re.compile(r"^conversations(-\d+)?\.json$", _re.I)

# Known metadata sidecars that are NOT conversation content.
_SIDECAR_HINTS = (
    "asset", "file_names", "file-names", "feedback", "message_feedback",
    "shared_conversations", "model_comparisons", "user", "chat_metadata",
    "group_chats", "library_files", "export_manifest", "user_settings",
    "codex",
)


def find_conversations_entries(zf: zipfile.ZipFile) -> List[str]:
    """
    Return ALL conversation entries, sorted. Modern exports shard conversations
    across conversations-000.json ... conversations-NNN.json; older ones use a
    single conversations.json. Falls back to the largest non-sidecar JSON.
    """
    names = zf.namelist()

    def base(n: str) -> str:
        return n.rsplit("/", 1)[-1].lower()

    def size(n: str) -> int:
        try:
            return zf.getinfo(n).file_size
        except KeyError:
            return 0

    shards = sorted(n for n in names if _CONV_RE.match(base(n)))
    if shards:
        return shards

    # Fallback: largest non-sidecar JSON (single-file exports / odd layouts)
    jsons = [n for n in names if n.lower().endswith(".json")]
    non_sidecar = [n for n in jsons if not any(h in base(n) for h in _SIDECAR_HINTS)]
    pool = non_sidecar or jsons
    if pool:
        return [max(pool, key=size)]

    raise FileNotFoundError(
        "No conversations JSON found in archive. Entries: " + ", ".join(names[:40])
    )


def find_conversations_entry(zf: zipfile.ZipFile) -> str:
    """Back-compat: first/best single entry."""
    return find_conversations_entries(zf)[0]


# --------------------------------------------------------------------------- #
# ZIP entry discovery (see find_conversations_entry above)
# --------------------------------------------------------------------------- #
def _peek_root_kind(zf: zipfile.ZipFile, entry: str) -> str:
    """Return 'array' or 'object' by reading the first non-ws byte (BOM-safe)."""
    with zf.open(entry, "r") as fh:
        head = fh.read(8)
    if head[:3] == b"\xef\xbb\xbf":  # strip UTF-8 BOM
        head = head[3:]
    for byte in head:
        c = chr(byte)
        if c.isspace():
            continue
        return "array" if c == "[" else "object"
    raise ValueError("Empty conversations.json")


def _looks_like_conversation(v) -> bool:
    return isinstance(v, dict) and (
        "mapping" in v or "title" in v or "current_node" in v
    )


# --------------------------------------------------------------------------- #
# Streaming iterator
# --------------------------------------------------------------------------- #
def _iter_one_entry(zf: "zipfile.ZipFile", entry: str) -> Iterator[dict]:
    """Yield conversation dicts from a single entry, auto-detecting root shape."""
    try:
        esize = zf.getinfo(entry).file_size
    except KeyError:
        esize = -1
    ulog.log("READ entry", entry,
             status=f"{esize:,} bytes (backend={'ijson' if _HAVE_IJSON else 'stdlib'})")

    if _HAVE_IJSON:
        strategies = [
            ("array", lambda: ijson.items(zf.open(entry, "r"), "item")),
            ("conversations[]",
             lambda: ijson.items(zf.open(entry, "r"), "conversations.item")),
            ("object-by-id",
             lambda: (v for _, v in ijson.kvitems(zf.open(entry, "r"), ""))),
        ]
        for name, make in strategies:
            gen = make()
            first = next(gen, _SENTINEL)
            if first is _SENTINEL:
                ulog.dbg("PROBE", entry, status=f"strategy '{name}' yielded 0")
                continue
            if not _looks_like_conversation(first):
                ulog.dbg("PROBE", entry, status=f"strategy '{name}' wrong content")
                continue
            ulog.dbg("PARSE", entry, status=f"root shape = {name}")
            yield first
            for item in gen:
                if _looks_like_conversation(item):
                    yield item
            return
        ulog.err("PARSE", entry, error="no strategy matched; skipping shard")
        return

    # ---- stdlib fallback (no ijson) ----
    import sys
    if esize > 200_000_000:
        sys.stderr.write(
            f"[warn] ijson not installed and {entry} is {esize/1e6:.0f} MB; "
            "loading fully into RAM. Install ijson for streaming.\n"
        )
    with zf.open(entry, "r") as fh:
        data = json.load(io.TextIOWrapper(fh, encoding="utf-8-sig"))
    if isinstance(data, list):
        convs = data
    elif isinstance(data, dict) and isinstance(data.get("conversations"), list):
        convs = data["conversations"]
    elif isinstance(data, dict):
        convs = list(data.values())
    else:
        convs = []
    for c in convs:
        if _looks_like_conversation(c):
            yield c


def iter_conversations(zip_path: str) -> Iterator[dict]:
    """
    Yield conversation dicts from ALL conversation shards in the archive
    (conversations.json and/or conversations-000.json ... -NNN.json), one at a
    time with bounded memory. Auto-detects each shard's root shape.
    """
    with zipfile.ZipFile(zip_path, "r") as zf:
        entries = find_conversations_entries(zf)
        ulog.log("SHARDS", zip_path, status=f"{len(entries)} conversation file(s)")
        total = 0
        for entry in entries:
            for conv in _iter_one_entry(zf, entry):
                total += 1
                yield conv
        if total == 0:
            raise RuntimeError(
                "No conversations parsed from any shard. Run "
                "scripts/diagnose.py to inspect the export structure."
            )


# --------------------------------------------------------------------------- #
# Canonical path reconstruction
# --------------------------------------------------------------------------- #
def active_path_nodes(conv: dict) -> List[dict]:
    """Return mapping nodes along current_node -> root, root-first order."""
    mapping = conv.get("mapping") or {}
    if not mapping:
        return []
    leaf = conv.get("current_node")
    if not leaf or leaf not in mapping:
        leaf = _fallback_leaf(mapping)
    chain: List[dict] = []
    seen = set()
    cur = leaf
    while cur and cur in mapping and cur not in seen:
        seen.add(cur)
        node = mapping[cur]
        chain.append(node)
        cur = node.get("parent")
    chain.reverse()
    return chain


def _fallback_leaf(mapping: dict) -> Optional[str]:
    """Latest childless node bearing a message (when current_node is absent)."""
    best_id, best_t = None, -1.0
    for nid, node in mapping.items():
        if node.get("children"):
            continue
        msg = node.get("message") or {}
        t = msg.get("create_time") or 0
        try:
            t = float(t)
        except (TypeError, ValueError):
            t = 0.0
        if t >= best_t:
            best_t, best_id = t, nid
    return best_id


# --------------------------------------------------------------------------- #
# Robust content extraction
# --------------------------------------------------------------------------- #
def message_text(msg: dict) -> Tuple[str, str, str]:
    """
    Return (role, text, content_type) for a message dict.
    Never raises on object-valued parts. Unknown shapes -> ('', '', ctype).
    """
    if not msg:
        return ("", "", "")
    author = msg.get("author") or {}
    role = author.get("role") or ""
    content = msg.get("content") or {}
    ctype = content.get("content_type") or ""

    # code / canvas textdoc
    if ctype == "code":
        txt = content.get("text")
        if isinstance(txt, str):
            return (role, txt.strip(), ctype)

    # user editable context (custom instructions / profile)
    if ctype == "user_editable_context":
        up = content.get("user_profile") or ""
        ui = content.get("user_instructions") or ""
        joined = "\n\n".join(x for x in (up, ui) if x)
        return (role, joined.strip(), ctype)

    # text / multimodal_text -> parts[] may mix str and dict
    parts = content.get("parts")
    if isinstance(parts, list):
        out: List[str] = []
        for p in parts:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                if isinstance(p.get("text"), str):
                    out.append(p["text"])
                else:
                    tag = p.get("content_type") or "asset"
                    out.append(f"[{tag}]")
        return (role, "\n".join(out).strip(), ctype)

    # some exports store plain string text
    if isinstance(content.get("text"), str):
        return (role, content["text"].strip(), ctype)
    return (role, "", ctype)


def conversation_dates(conv: dict) -> Tuple[Optional[float], Optional[float]]:
    def _f(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    return _f(conv.get("create_time")), _f(conv.get("update_time"))


# --------------------------------------------------------------------------- #
# Transcript reduction (token optimization)
# --------------------------------------------------------------------------- #
FENCE_RE = re.compile(r"```([\w+\-.]*)\n(.*?)```", re.S)


def reduce_assistant_text(text: str, max_prose: int = 1200) -> str:
    """
    Strip code-fence *bodies* (the dominant token sink) but keep a one-line
    placeholder noting language, line count, and first line. Prose is kept
    (truncated). User intent/requirements live in prose, not code bodies.
    """
    placeholders: List[str] = []

    def _sub(m: re.Match) -> str:
        lang = (m.group(1) or "txt").strip()
        body = m.group(2).rstrip("\n")
        lines = body.count("\n") + 1 if body else 0
        first = next((ln.strip() for ln in body.splitlines() if ln.strip()), "")
        first = first[:80]
        placeholders.append(f"\u2039code {lang} {lines}ln :: {first}\u203a")
        return f"\n{placeholders[-1]}\n"

    stripped = FENCE_RE.sub(_sub, text)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip()
    if len(stripped) > max_prose:
        stripped = stripped[:max_prose] + " \u2026[truncated]"
    return stripped
