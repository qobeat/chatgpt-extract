"""Time/cost estimation and the interactive confirmation gate for the AI
summary step (Summarize).

Any AI summary run can cost money (API providers) or take a long time (every
provider — even local Ollama is well over a few seconds per item). So the gate
applies to all providers and is shown after the cost estimate, before the first
call. Bypass with --noask (alias --yes); --dry-run never reaches the gate.
"""
from __future__ import annotations

import sys

# Rough seconds-per-item by provider (medians from smoke runs; estimate only).
_PER_ITEM_SECONDS = {
    "ollama": 45,
    "codex": 28,
    "claude": 30,
    "cursor": 30,
    "openai": 8,
    "anthropic": 8,
}

# An AI summary run shorter than this would not be worth gating on time alone.
GATE_MIN_SECONDS = 5


def eta_seconds(provider: str, n_items: int) -> int:
    return int(_PER_ITEM_SECONDS.get(provider, 30) * max(0, n_items))


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 90:
        return f"~{seconds}s"
    minutes = seconds / 60
    if minutes < 90:
        return f"~{minutes:.0f} min"
    return f"~{minutes / 60:.1f} hr"


def format_size(num_bytes: int) -> str:
    val = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024 or unit == "TB":
            return f"{val:.0f} {unit}" if unit == "B" else f"{val:.1f} {unit}"
        val /= 1024
    return f"{num_bytes} B"


def gate(provider: str, model: str, n_items: int, *,
         est_usd: float = 0.0, subscription: bool = False,
         noask: bool = False, stream=sys.stderr) -> bool:
    """Show estimate + ask Y/N. Return True to proceed.

    - noask: skip the prompt and proceed.
    - non-interactive (no TTY) without noask: refuse, instruct to pass --noask.
    - default answer is No.
    """
    eta = eta_seconds(provider, n_items)
    if subscription or est_usd <= 0:
        cost_line = "covered by your plan/quota (not token-billed)"
    else:
        cost_line = f"~${est_usd:.2f}"

    plan = "ChatGPT plan" if provider == "codex" else (
        "Claude plan" if provider == "claude" else (
            "Cursor plan" if provider == "cursor" else (
                "local, $0" if provider == "ollama" else "API, pay-per-token")))

    stream.write(
        f"\nAbout to run the AI summary step (Summarize) — provider '{provider}'"
        f"{(' model ' + model) if model else ''} ({plan})\n"
        f"  Items:     {n_items}\n"
        f"  Est. time: {format_duration(eta)}\n"
        f"  Est. cost: {cost_line}\n"
    )

    if noask:
        stream.write("Proceeding (--noask).\n")
        return True

    if not sys.stdin.isatty():
        stream.write(
            "Refusing to start a non-interactive AI summary run without confirmation.\n"
            "Re-run with --noask (or --yes) to proceed, or --dry-run to preview.\n")
        return False

    stream.write("Proceed? [y/N] ")
    stream.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        stream.write("\nAborted.\n")
        return False
    return answer in ("y", "yes")
