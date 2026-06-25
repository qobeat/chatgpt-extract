#!/usr/bin/env python3
"""
arena.py — combined PERFORMANCE + QUALITY leaderboard across every model that
already produced data in the saved comparison artifacts.

This command does NOT run any model. It scans the data already on disk —
summarize traces and reconstructed outputs — discovers which models actually
classified something, and prints both ranking tables for them. To add a model
to the arena, generate its data first with `gpt summarize` (or the manual
comparison runs in the README); there is no point naming a model that has not
processed any of the available data.

Usage:
  python scripts/arena.py                      # all models found in saved data
  python scripts/arena.py qwen2.5-coder:14b codex   # restrict to named models
  python scripts/arena.py --json
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import interrupt  # noqa: E402
import paths  # noqa: E402
sys.path.insert(0, HERE)
import metrics  # noqa: E402


def _filter(rows: list[dict], wanted: list[str]) -> list[dict]:
    """Keep rows whose model matches any requested name (exact or substring)."""
    if not wanted:
        return rows
    return [r for r in rows
            if any(w == r["model"] or w in r["model"] for w in wanted)]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt arena",
        description="PERFORMANCE + QUALITY leaderboard over every model found "
                    "in the saved comparison data (read-only; runs nothing).")
    ap.add_argument("models", nargs="*",
                    help="Optional model-name filters (exact or substring). "
                         "Default: every model present in the saved data.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    traces = metrics.discover_traces()
    outputs = metrics.discover_outputs()
    perf = _filter(metrics.collect_perf(traces), args.models)
    qual = _filter(metrics.aggregate_quality_by_model(outputs), args.models)

    found = sorted({r["model"] for r in perf} | {r["model"] for r in qual})

    if args.json:
        print(json.dumps({"models_found": found, "n_traces": len(traces),
                          "n_outputs": len(outputs), "performance": perf,
                          "quality": qual}, indent=2))
        return 0

    if not found:
        sys.stderr.write(
            "[arena] No model data found. Generate some first, e.g.\n"
            "        ./gpt summarize --limit 10 --provider ollama --model qwen2.5-coder:14b\n")
        return 1

    sys.stderr.write(f"[arena] models in saved data: {', '.join(found)}\n")
    sys.stderr.write(f"[arena] sources: {len(traces)} trace(s), {len(outputs)} output(s)\n\n")
    out = metrics.render_perf(perf) + "\n" + metrics.render_quality(qual)
    print(out, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt arena"))
