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

# Generic threshold for warning before any slow action (e.g. Extract): 5 minutes.
LONG_ACTION_SECONDS = 300

# Observed Extract throughput: ~90 seconds per GB of export .zip (floor ~20s),
# matching the parse-time estimate shown by the status dashboard.
_EXTRACT_SECONDS_PER_GB = 90


def estimate_extract_seconds(total_bytes: int) -> int:
    """Rough wall-time estimate for the Extract step from total .zip bytes."""
    gb = max(0.0, total_bytes) / 1024 ** 3
    return int(max(20, gb * _EXTRACT_SECONDS_PER_GB))


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


def gate_long_action(label: str, est_seconds: int, *, notice: str = "",
                     force_prompt: bool = False, noask: bool = False,
                     threshold: int = LONG_ACTION_SECONDS,
                     stream=sys.stderr) -> bool:
    """Warn (and ask Y/N) before a slow action. Return True to proceed.

    - Prompts only when ``est_seconds`` exceeds ``threshold`` (5 min) OR
      ``force_prompt`` is set (e.g. all inputs already handled = wasted work).
      Otherwise proceeds silently.
    - noask: skip the prompt and proceed.
    - non-interactive (no TTY) without noask: refuse, instruct to pass --noask.
    - default answer is No.
    """
    needs_prompt = force_prompt or est_seconds > threshold

    if notice:
        stream.write(notice.rstrip("\n") + "\n")

    if not needs_prompt:
        return True

    stream.write(
        f"\nAbout to run {label} — estimated time {format_duration(est_seconds)}.\n"
    )
    if est_seconds > threshold:
        stream.write(
            f"  This is longer than {threshold // 60} minutes.\n")

    if noask:
        stream.write("Proceeding (--noask).\n")
        return True

    if not sys.stdin.isatty():
        stream.write(
            f"Refusing to start a non-interactive long run ({label}) without "
            "confirmation.\nRe-run with --noask (or --yes) to proceed.\n")
        return False

    stream.write("Proceed? [y/N] ")
    stream.flush()
    try:
        answer = input().strip().lower()
    except (EOFError, KeyboardInterrupt):
        stream.write("\nAborted.\n")
        return False
    return answer in ("y", "yes")
