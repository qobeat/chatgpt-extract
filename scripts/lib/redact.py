"""
redact.py — shared PII detection + active redaction transform.

One pattern set, two egress points (the privacy boundary):
  (a) publish boundary — `export_public.py` (commit to the public repo)
  (b) cloud pre-send   — `summarize.py` before any cloud provider call

`find()` is detect-only (used by `gpt publish --review`). `scrub()` is the
active transform: it replaces each match with a typed placeholder
(‹email›/‹path›/‹phone›/‹token›) instead of merely warning (NFR-P2). Both share
PATTERNS, so the detector and the transform can never disagree.

Patterns are deliberately broadened beyond email + macOS paths to Linux/WSL
home paths, phone numbers, obvious API keys/tokens, JWTs, PEM private-key
blocks, and IPv4 addresses (NFR-P2 / NFR-P3). They are conservative on free
prose to avoid mangling normal text (e.g. version numbers are not treated as
phone numbers, and IPv4 octets are range-checked).
"""
from __future__ import annotations

import re
from typing import List, Tuple

# Typed placeholders (guillemets keep them visually distinct from real content).
PH_EMAIL = "\u2039email\u203a"
PH_PATH = "\u2039path\u203a"
PH_PHONE = "\u2039phone\u203a"
PH_TOKEN = "\u2039token\u203a"
PH_IP = "\u2039ip\u203a"

Finding = Tuple[str, str]  # (kind, matched_text)


# Order matters: more specific / higher-risk patterns first so a token inside a
# path-like string is not mis-typed. Each entry: (compiled, kind, placeholder).
PATTERNS: List[Tuple[re.Pattern, str, str]] = [
    # Emails.
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
     "email", PH_EMAIL),

    # PEM private-key blocks (header is enough to flag the secret).
    (re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
     "private key", PH_TOKEN),

    # API keys / tokens with well-known shapes.
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "openai key", PH_TOKEN),
    (re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
     "github token", PH_TOKEN),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws access key", PH_TOKEN),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "google api key", PH_TOKEN),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), "slack token", PH_TOKEN),
    # JSON Web Tokens (three base64url segments, leading header "eyJ").
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
     "jwt", PH_TOKEN),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}\b"),
     "bearer token", PH_TOKEN),

    # Home / user paths (macOS, Linux, WSL, Windows).
    (re.compile(r"/Users/[^\s\"'<>]+"), "macOS home path", PH_PATH),
    (re.compile(r"/mnt/[a-zA-Z]/Users/[^\s\"'<>]+"), "WSL windows path", PH_PATH),
    (re.compile(r"/home/[^\s\"'<>]+"), "linux home path", PH_PATH),
    (re.compile(r"[A-Za-z]:\\Users\\[^\s\"'<>]+"), "windows path", PH_PATH),
    (re.compile(r"\\Users\\[^\s\"'<>]+"), "windows backslash path", PH_PATH),

    # Phone numbers (E.164 and common separated forms). Anchored to avoid
    # eating version strings: requires a leading + or a (NNN) group, or 10+
    # digits with separators.
    (re.compile(r"\+\d{1,3}[\s\-]?\(?\d{2,4}\)?[\s\-]?\d{3}[\s\-]?\d{3,4}\b"),
     "phone", PH_PHONE),
    (re.compile(r"\(\d{3}\)\s?\d{3}[\s\-]\d{4}\b"), "phone", PH_PHONE),
    (re.compile(r"\b\d{3}[\-]\d{3}[\-]\d{4}\b"), "phone", PH_PHONE),

    # IPv4 addresses (each octet 0-255 to avoid eating version strings).
    (re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
                r"(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"), "ip address", PH_IP),

    # Provenance field marker (kept from the original detector).
    (re.compile(r"source_conversation_ids"), "conversation id field", PH_TOKEN),
]


def find(text: str) -> List[Finding]:
    """Detect-only: return [(kind, matched_text), ...] for every pattern hit."""
    findings: List[Finding] = []
    if not text:
        return findings
    for pattern, kind, _ph in PATTERNS:
        for match in pattern.finditer(text):
            findings.append((kind, match.group()))
    return findings


def scrub(text: str) -> Tuple[str, List[Finding]]:
    """Active transform: replace every match with its typed placeholder.

    Returns (scrubbed_text, findings). Applying patterns in PATTERNS order keeps
    the result deterministic; later patterns operate on text where earlier,
    higher-risk matches are already placeholders."""
    findings: List[Finding] = []
    if not text:
        return text, findings
    out = text
    for pattern, kind, placeholder in PATTERNS:
        def _sub(m: re.Match) -> str:
            findings.append((kind, m.group()))
            return placeholder
        out = pattern.sub(_sub, out)
    return out, findings


def scrub_obj(obj):
    """Recursively scrub every string inside a JSON-like structure.

    Used by the cloud pre-send scrubber on a bundle/payload and by the publish
    transform on free-text fields. Keys are left intact; only values change."""
    if isinstance(obj, str):
        return scrub(obj)[0]
    if isinstance(obj, list):
        return [scrub_obj(v) for v in obj]
    if isinstance(obj, dict):
        return {k: scrub_obj(v) for k, v in obj.items()}
    return obj
