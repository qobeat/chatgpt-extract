"""uio.py — shared formatting helpers for consistent `gpt` CLI output.

The canonical vocabulary and output conventions these helpers enforce are
documented in the README ("Output conventions & glossary") and should be the
single source of truth. Use these so every command prints the same way:

  - context_line(): one compact "cmd · key val · key val" header line
  - kv():           an aligned label/value line (default 12-char label column)
  - mark():         an "ok" / "FAIL" status token
  - short_basename(): one truncation rule for long export filenames
  - chats() / projects(): consistently pluralized, comma-grouped counts

Canonical noun: a single ChatGPT conversation is a *chat* everywhere in output.
"""
from __future__ import annotations

# Default label column width for key/value lines. Commands with longer labels
# (e.g. `gpt info`'s "Content types") pass an explicit width.
KV_WIDTH = 12

# One rule for shortening long export basenames in tables / path lists.
BASENAME_WIDTH = 44


def context_line(cmd: str, *parts: str) -> str:
    """One compact header: ``cmd · part · part`` (empty parts dropped)."""
    return " · ".join([cmd, *(p for p in parts if p)])


def kv(label: str, value: str, width: int = KV_WIDTH) -> str:
    """Aligned ``label   value`` line."""
    return f"{label:<{width}}{value}"


def mark(ok: bool, good: str = "ok", bad: str = "FAIL") -> str:
    """Status token: ``good`` when ok, else ``bad``."""
    return good if ok else bad


def short_basename(name: str, width: int = BASENAME_WIDTH) -> str:
    """Truncate a long filename to ``…<tail>`` so tables stay aligned."""
    if name and len(name) > width:
        return "…" + name[-(width - 1):]
    return name


def count(n: int, singular: str, plural: str | None = None) -> str:
    """``"1 chat"`` / ``"4,113 chats"`` — comma-grouped, correctly pluralized."""
    word = singular if n == 1 else (plural or singular + "s")
    return f"{n:,} {word}"


def chats(n: int) -> str:
    return count(n, "chat")


def projects(n: int) -> str:
    return count(n, "project")
