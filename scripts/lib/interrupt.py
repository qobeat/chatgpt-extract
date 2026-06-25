"""interrupt.py — uniform Ctrl+C handling for the `gpt` CLI process tree.

Pressing Ctrl+C in a terminal sends SIGINT to the whole foreground process
group, so without coordination every layer (gpt -> run.py -> stage script)
prints its own traceback. This module enforces a single convention:

  * A *leaf* process (the one doing the in-process work) prints one clean line
    via :func:`run_cli` and exits with code 130 (128 + SIGINT).
  * An *orchestrator* (a process that shells out to a child) stays silent and
    just relays the child's 130 via :func:`propagate_child` — the child already
    printed the message.

Commands may publish lightweight progress (`set_total`, `advance`, `note`) so an
interrupt can show how far along it was, e.g. ``scanned 1,234 / 4,122 chats``.
"""
from __future__ import annotations

import signal
import sys
from typing import Callable

# Standard shell exit code for a process terminated by SIGINT.
SIGINT_EXIT = 128 + signal.SIGINT  # 130 on POSIX

_progress: dict[str, object] = {"done": 0, "total": 0, "unit": "", "label": ""}


def reset() -> None:
    """Clear any published progress state."""
    _progress.update(done=0, total=0, unit="", label="")


def set_total(n: int, unit: str = "") -> None:
    """Declare the total number of items and an optional unit (e.g. ``chats``)."""
    _progress["total"] = int(n)
    if unit:
        _progress["unit"] = unit


def advance(label: str = "", unit: str = "") -> None:
    """Count one item of work; optionally record what is being processed."""
    _progress["done"] = int(_progress["done"]) + 1  # type: ignore[arg-type]
    if label:
        _progress["label"] = label
    if unit:
        _progress["unit"] = unit


def note(label: str) -> None:
    """Record the current activity without advancing the counter."""
    _progress["label"] = label


def _state_str() -> str:
    done = int(_progress["done"])  # type: ignore[arg-type]
    total = int(_progress["total"])  # type: ignore[arg-type]
    unit = str(_progress["unit"])
    label = str(_progress["label"])
    parts: list[str] = []
    if total:
        parts.append(f"{done:,} / {total:,}{(' ' + unit) if unit else ''}")
    elif done:
        parts.append(f"{done:,}{(' ' + unit) if unit else ''}")
    if label:
        parts.append(label)
    return " · ".join(parts)


def report(name: str, stream=None) -> None:
    """Write one clean ``interrupted by ^C`` line, with progress if available."""
    if stream is None:
        stream = sys.stderr
    line = f"\n[interrupted] ^C · {name}"
    state = _state_str()
    if state:
        line += f" · {state}"
    stream.write(line + "\n")
    stream.flush()


def run_cli(main_fn: Callable[[], int | None], name: str) -> int:
    """Run a leaf CLI ``main`` and turn Ctrl+C into a clean message + code 130.

    Use as ``raise SystemExit(interrupt.run_cli(main, "gpt search"))``.
    """
    try:
        return main_fn() or 0
    except KeyboardInterrupt:
        report(name)
        return SIGINT_EXIT


def propagate_child(returncode: int) -> int:
    """Map a child process's interrupt exit into a quiet 130 for orchestrators.

    A child killed by SIGINT reports either 130 (it handled the interrupt and
    exited via :func:`run_cli`) or ``-SIGINT`` (uncaught signal). Either way the
    child already printed, so we relay 130 without printing again. Other codes
    pass through unchanged.
    """
    if returncode in (SIGINT_EXIT, -signal.SIGINT):
        return SIGINT_EXIT
    return returncode
