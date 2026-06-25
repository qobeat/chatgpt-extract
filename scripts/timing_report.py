#!/usr/bin/env python3
"""
timing_report.py — separate model load/warm time from inference time.

The `s/item` in `metrics.py perf` averages wall-seconds over completed items,
which silently folds in the one-time cost of loading the model into VRAM (paid
on the first call of each run; `keep_alive` keeps it warm thereafter). This tool
splits that out so latency comparisons are honest.

Two sources of truth, in priority order, per completed item:
  1. EXACT   — `load_ms` recorded in the trace payload (Ollama `load_duration`).
               Present only for runs made after the provider was instrumented.
  2. ESTIMATE — when no `load_ms` is present (legacy runs): the cold-load is
               attributed to the first completed item, estimated as
               `secs(first) - median(secs(rest))`. Labelled "~" in the report.

Reported per run:
  items, fails, s/item (all, = current metric), warm s/item (load excluded),
  load (exact or ~est), and gen-only s/item when EXACT timing is available.

Usage:
  python scripts/timing_report.py                       # auto: $DATA_ROOT/runs/cmp-*/
  python scripts/timing_report.py runs/cmp-oct-*/summarize_trace.jsonl
  python scripts/timing_report.py --glob 'runs/cmp-oct-*' --md report.md
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
import interrupt  # noqa: E402
import paths  # noqa: E402


def _discover() -> list[str]:
    root = paths.data_root()
    pats = [
        os.path.join(root, "runs", "*", "summarize_trace.jsonl"),
        os.path.join(root, "summarize_trace.jsonl"),
    ]
    found: list[str] = []
    for p in pats:
        found.extend(sorted(glob.glob(p)))
    return found


def _expand(args_paths: list[str], glob_pat: str | None) -> list[str]:
    out: list[str] = []
    if glob_pat:
        for d in sorted(glob.glob(glob_pat)):
            tf = d if d.endswith(".jsonl") else os.path.join(d, "summarize_trace.jsonl")
            if os.path.isfile(tf):
                out.append(tf)
    for p in args_paths:
        if os.path.isdir(p):
            tf = os.path.join(p, "summarize_trace.jsonl")
            if os.path.isfile(tf):
                out.append(tf)
        elif os.path.isfile(p):
            out.append(p)
        else:
            out.extend(sorted(glob.glob(p)))
    return out or _discover()


def _parse_trace(path: str) -> dict:
    """Return per-run timing aggregates from one summarize_trace.jsonl."""
    run_id = None
    ok_items: list[dict] = []   # ordered by sequence: {"secs", "load_ms", "eval_ms"}
    fails = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            run_id = run_id or e.get("run_id")
            et = e.get("event_type")
            p = e.get("payload") or {}
            if et == "LLM_OK":
                ok_items.append({
                    "seq": e.get("sequence") or 0,
                    "secs": float(p.get("secs") or 0.0),
                    "load_ms": p.get("load_ms"),
                    "eval_ms": p.get("eval_ms"),
                })
            elif et == "LLM_FAIL":
                fails += 1
    ok_items.sort(key=lambda d: d["seq"])
    return {"run_id": run_id or os.path.basename(os.path.dirname(path)),
            "path": path, "ok": ok_items, "fails": fails}


def _summarize(agg: dict) -> dict | None:
    ok = agg["ok"]
    n = len(ok)
    if n == 0:
        return None
    secs = [d["secs"] for d in ok]
    total = sum(secs)
    s_per_item = total / n

    have_exact = any(d.get("load_ms") is not None for d in ok)
    if have_exact:
        load_s = sum((d.get("load_ms") or 0) for d in ok) / 1000.0
        eval_total = sum((d.get("eval_ms") or 0) for d in ok) / 1000.0
        gen_only = eval_total / n if eval_total else None
        warm_total = max(total - load_s, 0.0)
        warm_per_item = warm_total / n
        load_kind = "exact"
    else:
        # Legacy estimate: attribute the cold load to the first completed item.
        if n >= 2:
            warm_med = statistics.median(secs[1:])
            load_s = max(secs[0] - warm_med, 0.0)
            warm_per_item = warm_med
        else:
            load_s = 0.0
            warm_per_item = s_per_item
        gen_only = None
        load_kind = "est"
    return {
        "run_id": agg["run_id"],
        "items": n,
        "fails": agg["fails"],
        "s_per_item": s_per_item,
        "warm_s_per_item": warm_per_item,
        "load_s": load_s,
        "load_kind": load_kind,
        "gen_only_s_per_item": gen_only,
    }


def _fmt_rows(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["warm_s_per_item"])
    head = (f"{'model':30s} {'items':>5} {'fail':>4} "
            f"{'s/item':>7} {'warm s/it':>9} {'load s':>9} {'gen s/it':>8}")
    out = ["TIMING — load/warm separated from inference (warm = load excluded)",
           "", head, "-" * len(head)]
    for r in rows:
        load = (f"{r['load_s']:.1f}" if r['load_kind'] == "exact"
                else f"~{r['load_s']:.1f}")
        gen = f"{r['gen_only_s_per_item']:.2f}" if r['gen_only_s_per_item'] else "n/a"
        out.append(f"{r['run_id']:30.30s} {r['items']:>5} {r['fails']:>4} "
                   f"{r['s_per_item']:>7.1f} {r['warm_s_per_item']:>9.1f} "
                   f"{load:>9} {gen:>8}")
    out += ["",
            "s/item      = wall-seconds per completed item (current metric; includes load)",
            "warm s/it   = s/item with the one-time model load excluded",
            "load s      = model load into VRAM; 'exact' from Ollama load_duration, "
            "'~' estimated as secs(first) - median(rest)",
            "gen s/it    = generation-only seconds/item (exact runs only)"]
    return "\n".join(out)


def _md_rows(rows: list[dict]) -> str:
    rows = sorted(rows, key=lambda r: r["warm_s_per_item"])
    out = ["| model | items | fails | s/item | warm s/item | load s | gen s/item |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        load = (f"{r['load_s']:.1f}" if r['load_kind'] == "exact"
                else f"~{r['load_s']:.1f}")
        gen = f"{r['gen_only_s_per_item']:.2f}" if r['gen_only_s_per_item'] else "n/a"
        out.append(f"| {r['run_id']} | {r['items']} | {r['fails']} | "
                   f"{r['s_per_item']:.1f} | {r['warm_s_per_item']:.1f} | "
                   f"{load} | {gen} |")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="Separate model load/warm from inference time.")
    ap.add_argument("paths", nargs="*", help="trace files or run dirs (default: auto-discover).")
    ap.add_argument("--glob", default=None, help="glob of run dirs/trace files.")
    ap.add_argument("--md", default=None, help="also write a markdown table to this path.")
    ap.add_argument("--json", action="store_true", help="emit JSON rows to stdout.")
    args = ap.parse_args()

    traces = _expand(args.paths, args.glob)
    if not traces:
        sys.stderr.write("[error] no summarize_trace.jsonl found.\n")
        return 1

    rows = []
    for tf in traces:
        s = _summarize(_parse_trace(tf))
        if s:
            rows.append(s)
    if not rows:
        sys.stderr.write("[error] no completed items in the given traces.\n")
        return 1

    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        print(_fmt_rows(rows))
    if args.md:
        with open(args.md, "w", encoding="utf-8") as f:
            f.write(_md_rows(rows) + "\n")
        sys.stderr.write(f"[done] markdown -> {args.md}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "timing-report"))
