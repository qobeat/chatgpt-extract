#!/usr/bin/env python3
"""
Catalog entity index — deterministic version/stability facts for `gpt ask`.

Dense retrieval ranks *similar* text, but it cannot reliably answer
version-superlative questions ("what is the newest / latest stable version?")
because the answer is a fact about the whole catalog, not a single passage. This
module extracts a small, product-scoped table of versions, how often each is
mentioned, in how many chats, and whether it is flagged unstable — then derives
two deterministic verdicts (newest_overall, latest_stable) with a citation.

`gpt ask` routes superlative version queries to these verdicts (intent routing)
instead of hoping the language model picks the right number out of a flooded
context. Everything here is pure stdlib and offline-testable; no numpy, no
network. The index is derived data, rebuildable from chunks at any time.

Design notes (grounded in the real catalog):
- Versions are only counted when *product-qualified* (`ados-profile-vX.Y`,
  `package_version=X.Y`, `profile vX.Y`) so unrelated tokens (numpy 2.1, gemini
  1.5, "section 1.2") don't pollute the table.
- Instability is detected only in product-scoped sentences and attributed only
  to the version the negation grammatically governs ("do not approve v2.0"),
  so "do not approve v2.0 as a clean successor to v1.23" flags 2.0, not 1.23.
- latest_stable requires substantial support (a real release is referenced a
  lot), which excludes short-lived *attempts* (e.g. 1.24) that out-number a
  stable release in version but not in actual usage.
"""
from __future__ import annotations

import datetime as _dt
import json as _json
import os as _os
import re
from collections import Counter, defaultdict

ENTITIES_FILENAME = "entities.json"

PRODUCT = "ados-profile"

# A product-qualified version: the number must hang off a product anchor.
QUALIFIED_VERSION = re.compile(
    r"(?:ados[-_ ]?profile?[-_ ]?v?|package_version\s*[=:]\s*\"?|\bprofile\s+v)"
    r"(\d+\.\d+(?:\.\d+)?)",
    re.I,
)
_PRODUCT_CONTEXT = re.compile(r"ados[-_ ]?profil", re.I)
# Instability cues where the version is the grammatical object of the negation.
_NEG_OBJ = re.compile(
    r"(?:do not approve|don'?t approve|not approve|reject(?:ing|ed)?)\s+v?(\d+\.\d+)",
    re.I,
)
_NEG_SUBJ = re.compile(
    r"v?(\d+\.\d+)\s+(?:is\s+)?(?:not stable|unstable|not yet stable|is not approved)",
    re.I,
)
_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")

# Selection thresholds (validated against the live catalog).
MIN_CHATS = 2          # a real version is referenced by >1 chat
SUPPORT_FRAC = 0.15    # a stable release carries >=15% of the modal version's mentions


def major_minor(token: str) -> str:
    """Collapse a version token to `major.minor` ('1.23.0' -> '1.23')."""
    parts = token.split(".")
    return ".".join(parts[:2]) if len(parts) >= 2 else token


def version_key(version: str) -> tuple[int, int]:
    """Numeric sort key so 1.23 > 1.4 and 2.0 > 1.23 (not string order)."""
    parts = (version.split(".") + ["0", "0"])[:2]
    try:
        return (int(parts[0]), int(parts[1]))
    except ValueError:
        return (-1, -1)


def extract_qualified_versions(text: str) -> list[str]:
    """Product-qualified `major.minor` version tokens found in `text`."""
    return [major_minor(m) for m in QUALIFIED_VERSION.findall(text or "")]


def find_unstable_versions(text: str) -> set[str]:
    """`major.minor` versions flagged unstable in product-scoped sentences."""
    out: set[str] = set()
    if not text or not _PRODUCT_CONTEXT.search(text):
        return out
    for sent in _SENT_SPLIT.split(text):
        for pat in (_NEG_OBJ, _NEG_SUBJ):
            for m in pat.findall(sent):
                out.add(major_minor(m))
    return out


def _instability_evidence(text: str) -> str | None:
    if not text or not _PRODUCT_CONTEXT.search(text):
        return None
    for sent in _SENT_SPLIT.split(text):
        if _NEG_OBJ.search(sent) or _NEG_SUBJ.search(sent):
            return sent.strip()[:160]
    return None


def select_newest(versions: dict, *, min_chats: int = MIN_CHATS) -> dict | None:
    """Highest-numbered product version with real support (>=min_chats chats)."""
    cands = [v for v, rec in versions.items() if len(rec["chats"]) >= min_chats]
    if not cands:
        return None
    v = max(cands, key=version_key)
    rec = versions[v]
    return {
        "version": v,
        "stable": rec.get("unstable_votes", 0) == 0,
        "mentions": rec["mentions"],
        "n_chats": len(rec["chats"]),
        "chat_id": rec.get("top_chat"),
        "evidence": rec.get("evidence"),
    }


def select_latest_stable(versions: dict, *, min_chats: int = MIN_CHATS,
                         support_frac: float = SUPPORT_FRAC) -> dict | None:
    """Highest-numbered version that is not flagged unstable and is well-supported.

    The support floor (a fraction of the most-mentioned version) is what
    separates a real stable release from a brief upgrade *attempt* that has a
    higher number but little actual usage.
    """
    if not versions:
        return None
    mode = max(rec["mentions"] for rec in versions.values())
    floor = support_frac * mode
    cands = [
        v for v, rec in versions.items()
        if len(rec["chats"]) >= min_chats
        and rec.get("unstable_votes", 0) == 0
        and rec["mentions"] >= floor
    ]
    if not cands:
        return None
    v = max(cands, key=version_key)
    rec = versions[v]
    return {
        "version": v,
        "stable": True,
        "mentions": rec["mentions"],
        "n_chats": len(rec["chats"]),
        "chat_id": rec.get("top_chat"),
        "evidence": None,
    }


def build_entities(records, *, product: str = PRODUCT,
                   source_chunks: int | None = None) -> dict:
    """Build the entity index from chunk records.

    `records` is any iterable of dicts with `chat_id`, `title`, `text`. Returns
    a schema-valid `ados-entities/1` document.
    """
    mentions: Counter = Counter()
    chats: dict[str, set] = defaultdict(set)
    per_chat: dict[str, Counter] = defaultdict(Counter)
    unstable: Counter = Counter()
    evidence: dict[str, str] = {}
    n = 0
    for rec in records:
        n += 1
        text = (rec.get("text") or "") + " " + (rec.get("title") or "")
        cid = rec.get("chat_id") or ""
        for v in extract_qualified_versions(text):
            mentions[v] += 1
            chats[v].add(cid)
            per_chat[v][cid] += 1
        for v in find_unstable_versions(text):
            unstable[v] += 1
            evidence.setdefault(v, _instability_evidence(text) or "")

    versions: dict[str, dict] = {}
    for v, cnt in mentions.items():
        top_chat = per_chat[v].most_common(1)[0][0] if per_chat[v] else None
        versions[v] = {
            "mentions": cnt,
            "chats": sorted(chats[v]),
            "unstable_votes": int(unstable.get(v, 0)),
            "top_chat": top_chat,
            "evidence": evidence.get(v) or None,
        }

    return {
        "schema": "ados-entities/1",
        "product": product,
        "built_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source_chunks": source_chunks if source_chunks is not None else n,
        "versions": versions,
        "summary": {
            "newest_overall": select_newest(versions),
            "latest_stable": select_latest_stable(versions),
        },
    }


# ---------------------------------------------------------------------------
# Intent routing (pure; offline-testable)
# ---------------------------------------------------------------------------
_SUPERLATIVE = re.compile(r"\b(newest|latest|most recent|current|highest|overall)\b", re.I)
_TOPIC = re.compile(r"\b(version|release|profile)\b", re.I)
_STABLE_PHRASE = re.compile(r"\b(stable version|latest stable|current stable|most recent stable|stable release)\b", re.I)
_NEWEST_CUE = re.compile(r"\b(newest|overall|highest|latest version|most recent version|current version)\b", re.I)


def version_superlative_intent(question: str) -> str | None:
    """Classify a question as 'newest', 'latest_stable', or None.

    Only identity questions ("what is the ... version?") are routed; "why is
    v2.0 not stable" is an explanation request and must reach normal synthesis.
    """
    q = (question or "").lower()
    if re.search(r"\bwhy\b|\bhow\b", q):
        return None
    if not re.search(r"\bwhat(?:'s| is| are)?\b|\bwhich\b", q):
        return None
    if not (_SUPERLATIVE.search(q) or _STABLE_PHRASE.search(q)):
        return None
    if not _TOPIC.search(q):
        return None
    # "newest ... overall" wins even when the sentence also asks "is it stable".
    if _NEWEST_CUE.search(q):
        return "newest"
    if _STABLE_PHRASE.search(q) or "stable" in q:
        return "latest_stable"
    return "newest"


def load_entities(index_dir: str) -> dict | None:
    """Load `entities.json` from an index dir, or None if absent/unreadable."""
    path = _os.path.join(index_dir, ENTITIES_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            return _json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def write_entities(index_dir: str, doc: dict) -> str:
    """Write the entity index to `<index_dir>/entities.json`; return the path."""
    _os.makedirs(index_dir, exist_ok=True)
    path = _os.path.join(index_dir, ENTITIES_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        _json.dump(doc, f, ensure_ascii=False, indent=2)
    return path


def answer_version_query(question: str, entities: dict | None) -> dict | None:
    """Deterministic, cited answer for a superlative version query, or None.

    Returns {answer, version, intent, chat_id} when the entity index can answer;
    None when the question isn't a version superlative or the data is missing
    (caller falls back to normal retrieval + synthesis).
    """
    if not entities:
        return None
    intent = version_superlative_intent(question)
    if intent is None:
        return None
    summary = entities.get("summary") or {}
    product = entities.get("product") or PRODUCT
    if intent == "latest_stable":
        v = summary.get("latest_stable")
        if not v:
            return None
        ans = (f"{v['version']} is the latest stable {product} version "
               f"(the dominant explicit versioned release — {v['mentions']} "
               f"references across {v['n_chats']} chats).")
        newest = summary.get("newest_overall")
        if newest and newest["version"] != v["version"]:
            tail = f" {newest['version']} is newer"
            tail += " but not stable." if newest.get("stable") is False else "."
            ans += tail
        return {"answer": ans, "version": v["version"], "intent": intent,
                "chat_id": v.get("chat_id")}
    # newest
    v = summary.get("newest_overall")
    if not v:
        return None
    if v.get("stable") is False:
        note = "but it is not stable"
        if v.get("evidence"):
            note += f': "{v["evidence"]}"'
        stable = summary.get("latest_stable")
        if stable:
            note += f". The latest stable release is {stable['version']}"
        ans = f"{v['version']} is the newest {product} version overall, {note}."
    else:
        ans = (f"{v['version']} is the newest {product} version overall "
               f"({v['mentions']} references across {v['n_chats']} chats).")
    return {"answer": ans, "version": v["version"], "intent": intent,
            "chat_id": v.get("chat_id")}
