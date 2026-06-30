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
# The product acronym whose expansion we extract for definitional routing.
ACRONYM = "ADOS"

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


# --- Acronym expansion (definitional routing) -----------------------------
# Patterns that introduce an acronym expansion near the bare token "ADOS". The
# captured phrase is validated by initials (must spell ADOS), so a stray match
# can never produce a wrong expansion.
_DEF_PATTERNS = [
    # ADOS (Agentic Digital Operating System)
    re.compile(r"\bados\b\s*\(\s*([A-Za-z][\w/-]*(?:\s+[A-Za-z][\w/-]*){1,5})\s*\)", re.I),
    # Agentic Digital Operating System (ADOS)
    re.compile(r"([A-Za-z][\w/-]*(?:\s+[A-Za-z][\w/-]*){1,5})\s*\(\s*ados\s*\)", re.I),
    # ADOS stands for / means / short for / : / = / — Expansion
    re.compile(
        r"\bados\b\s*(?:stands?\s+for|means?|is\s+short\s+for|short\s+for"
        r"|is\s+an?\s+acronym\s+for|refers?\s+to|[:=\u2014\u2013])\s+"
        r"([A-Za-z][\w/-]*(?:\s+[A-Za-z][\w/-]*){1,5})", re.I),
]


def _expansion_initials(phrase: str) -> str:
    return "".join(w[0] for w in re.findall(r"[A-Za-z][\w-]*", phrase)).upper()


def extract_definitions(text: str) -> list[str]:
    """Validated `ADOS` expansions in `text` (initials must spell the acronym).

    Returns Title-cased expansions like 'Agentic Digital Operating System'. The
    initials check is what makes this safe: only a phrase whose words' initials
    spell ADOS is accepted, so noise can't fabricate a definition.
    """
    if not text or "ados" not in text.lower():
        return []
    out: list[str] = []
    span = len(ACRONYM)
    for pat in _DEF_PATTERNS:
        for m in pat.findall(text):
            phrase = m if isinstance(m, str) else (m[0] if m else "")
            words = re.findall(r"[A-Za-z][\w-]*", phrase)
            # Slide an acronym-length window so a leading article ("The Agentic
            # ...") or trailing word doesn't defeat the initials check.
            for i in range(0, max(0, len(words) - span) + 1):
                cand = words[i:i + span]
                if len(cand) == span and \
                        _expansion_initials(" ".join(cand)) == ACRONYM:
                    out.append(" ".join(w.capitalize() for w in cand))
                    break
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
    defs: Counter = Counter()
    def_chats: dict[str, set] = defaultdict(set)
    def_per_chat: dict[str, Counter] = defaultdict(Counter)
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
        for d in extract_definitions(text):
            defs[d] += 1
            def_chats[d].add(cid)
            def_per_chat[d][cid] += 1

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

    acronym = None
    if defs:
        exp, cnt = defs.most_common(1)[0]
        top = def_per_chat[exp].most_common(1)[0][0] if def_per_chat[exp] else None
        acronym = {
            "term": ACRONYM,
            "expansion": exp,
            "mentions": cnt,
            "n_chats": len(def_chats[exp]),
            "chat_id": top,
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
            "acronym": acronym,
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


# A definitional question about the bare acronym only ("what is ados?", "what
# does ADOS stand for?", "define ados"). The subject must be just "ados" with
# nothing trailing, so "what is the ados-geometry concept?" or "...ados version?"
# fall through to normal synthesis.
_DEFINITION_Q = re.compile(
    r"^\s*(?:what(?:'s| is| does)?|define|explain|expand)\s+(?:the\s+|does\s+)?"
    r"ados\b\s*(?:acronym|abbreviation)?\s*"
    r"(?:stand(?:s)?\s+for|mean(?:s)?|short\s+for|refer(?:s)?\s+to|abbreviat\w*)?"
    r"\s*\??\s*$",
    re.I)


def definition_intent(question: str) -> str | None:
    """Return 'acronym' for a bare-acronym definitional question, else None."""
    return "acronym" if _DEFINITION_Q.match((question or "").strip()) else None


def answer_definition_query(question: str, entities: dict | None) -> dict | None:
    """Deterministic, cited acronym expansion, or None.

    Routes "what does ADOS stand for / what is ADOS / define ADOS" to the
    expansion mined into the entity index, so the named acceptance question
    answers instantly (no model call) instead of a multi-second synthesis.
    """
    if not entities or definition_intent(question) is None:
        return None
    exp = (entities.get("summary") or {}).get("acronym")
    if not exp or not exp.get("expansion"):
        return None
    # The reference count is metadata about the citation, not the answer; the
    # caller surfaces it under `Sources:` (mentions/n_chats below).
    ans = f"{exp['term']} stands for {exp['expansion']}."
    return {"answer": ans, "intent": "acronym", "term": exp["term"],
            "expansion": exp["expansion"], "version": None,
            "chat_id": exp.get("chat_id"),
            "mentions": exp.get("mentions"), "n_chats": exp.get("n_chats")}


def route_answer(question: str, entities: dict | None) -> dict | None:
    """First deterministic answer for `question` (version superlative or acronym).

    Returns a normalized dict with at least {answer, intent, chat_id}, or None
    when no deterministic route applies (caller falls back to synthesis).
    """
    return (answer_version_query(question, entities)
            or answer_definition_query(question, entities))


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
        ans = f"{v['version']} is the latest stable {product} version."
        newest = summary.get("newest_overall")
        if newest and newest["version"] != v["version"]:
            tail = f" {newest['version']} is newer"
            tail += " but not stable." if newest.get("stable") is False else "."
            ans += tail
        return {"answer": ans, "version": v["version"], "intent": intent,
                "chat_id": v.get("chat_id"),
                "mentions": v.get("mentions"), "n_chats": v.get("n_chats")}
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
        ans = f"{v['version']} is the newest {product} version overall."
    return {"answer": ans, "version": v["version"], "intent": intent,
            "chat_id": v.get("chat_id"),
            "mentions": v.get("mentions"), "n_chats": v.get("n_chats")}
