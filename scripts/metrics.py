#!/usr/bin/env python3
"""
metrics.py — model PERFORMANCE and QUALITY tables from saved comparison data.

Two subcommands, both read-only over artifacts already on disk:

  perf     Throughput (tokens/sec) per model, from one or more
           summarize_trace.jsonl files. Ranks models by end-to-end throughput.
  quality  ADOS completeness (%) per model, from one or more
           reconstructed_projects.json outputs. Ranks models by completeness.

Both auto-discover the usual locations when no paths are given:
  - traces : $DATA_ROOT/summarize_trace.jsonl and output/runs/*/summarize_trace.jsonl
  - outputs: $DATA_ROOT/reconstructed_projects.json and
             output/runs/*/reconstructed*.json

Usage:
  python scripts/metrics.py perf
  python scripts/metrics.py perf path/to/summarize_trace.jsonl --json
  python scripts/metrics.py quality
  python scripts/metrics.py quality codex=A.json qwen=B.json --json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import paths  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _nonempty(v) -> bool:
    return (isinstance(v, str) and bool(v.strip())) or (isinstance(v, list) and bool(v))


def _data_root() -> str:
    return paths.data_root() or os.path.join(ROOT, "output")


# ---------------------------------------------------------------------------
# perf — throughput from traces
# ---------------------------------------------------------------------------
def _dedupe_realpath(paths_in: list[str]) -> list[str]:
    """Drop duplicates that resolve to the same file (e.g. the runs/latest symlink)."""
    seen: set[str] = set()
    out: list[str] = []
    for p in sorted(paths_in):
        rp = os.path.realpath(p)
        if rp in seen:
            continue
        seen.add(rp)
        out.append(p)
    return out


def discover_traces() -> list[str]:
    dr = _data_root()
    found = glob.glob(os.path.join(ROOT, "output", "runs", "*", "summarize_trace.jsonl"))
    found += glob.glob(os.path.join(dr, "runs", "*", "summarize_trace.jsonl"))
    root_trace = os.path.join(dr, "summarize_trace.jsonl")
    if os.path.isfile(root_trace):
        found.append(root_trace)
    return _dedupe_realpath(found)


def collect_perf(traces: list[str]) -> list[dict]:
    """Aggregate per model (run_id) across the given trace files."""
    agg: dict[str, dict] = {}
    for tf in traces:
        try:
            fh = open(tf, encoding="utf-8")
        except OSError:
            continue
        with fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                rid = e.get("run_id") or "?"
                a = agg.setdefault(
                    rid, {"model": rid, "ok": 0, "fail": 0,
                          "secs": 0.0, "in_tok": 0, "out_tok": 0})
                p = e.get("payload") or {}
                if e.get("event_type") == "LLM_OK":
                    a["ok"] += 1
                    a["secs"] += float(p.get("secs") or 0.0)
                    a["in_tok"] += int(p.get("in_tok") or 0)
                    a["out_tok"] += int(p.get("out_tok") or 0)
                elif e.get("event_type") == "LLM_FAIL":
                    a["fail"] += 1
    rows = []
    for a in agg.values():
        if a["ok"] <= 0 or a["secs"] <= 0:
            continue
        attempted = a["ok"] + a["fail"]
        rows.append({
            "model": a["model"].rstrip(":") or a["model"],
            "throughput_tok_s": round((a["in_tok"] + a["out_tok"]) / a["secs"], 1),
            "gen_tok_s": round(a["out_tok"] / a["secs"], 1),
            "sec_per_item": round(a["secs"] / a["ok"], 1),
            "completed": a["ok"],
            "attempted": attempted,
            "completion_rate": round(a["ok"] / attempted, 3) if attempted else 0.0,
        })
    rows.sort(key=lambda r: r["throughput_tok_s"], reverse=True)
    return rows


def render_perf(rows: list[dict]) -> str:
    if not rows:
        return "No LLM_OK events found in the given traces.\n"
    out = ["PERFORMANCE — end-to-end throughput, higher is faster", ""]
    out.append(f"{'rank':>4}  {'model':28s} {'tok/s':>8} {'gen tok/s':>10} "
               f"{'s/item':>7} {'completed':>10}")
    for i, r in enumerate(rows, 1):
        out.append(f"{i:>4}  {r['model']:28s} {r['throughput_tok_s']:>8.1f} "
                   f"{r['gen_tok_s']:>10.1f} {r['sec_per_item']:>7.1f} "
                   f"{r['completed']:>4}/{r['attempted']:<5}")
    out += ["",
            "tok/s     = (input+output tokens) / wall-seconds over completed items",
            "gen tok/s = output tokens / wall-seconds (generation rate)",
            "s/item    = wall-seconds per completed item",
            "completed = LLM_OK / attempted (reliability)"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# quality — ADOS completeness from outputs
# ---------------------------------------------------------------------------
def discover_outputs() -> list[str]:
    dr = _data_root()
    found = []
    root_out = os.path.join(dr, "reconstructed_projects.json")
    if os.path.isfile(root_out):
        found.append(root_out)
    found += glob.glob(os.path.join(ROOT, "output", "runs", "*", "reconstructed*.json"))
    found += glob.glob(os.path.join(dr, "runs", "*", "reconstructed*.json"))
    return _dedupe_realpath(found)


def _af_fill(item: dict) -> float:
    af = item.get("archetype_fields") or {}
    if not af:
        return 0.0
    return sum(1 for v in af.values() if _nonempty(v)) / len(af)


def _load_output(path: str) -> tuple[dict, list[dict]]:
    with open(os.path.expanduser(path), encoding="utf-8") as f:
        doc = json.load(f)
    return doc, (doc.get("items") or doc.get("projects") or [])


def _item_quality(it: dict) -> tuple[float, float, float, float]:
    """Per-item field-fill: (goal, objectives, requirements, archetype_fields)."""
    return (
        1.0 if (it.get("goal") or "").strip() else 0.0,
        1.0 if it.get("objectives") else 0.0,
        1.0 if it.get("requirements") else 0.0,
        _af_fill(it),
    )


def _quality_row(model: str, im: list[tuple], n_items: int) -> dict:
    n = len(im) or 1
    g = sum(m[0] for m in im) / n
    o = sum(m[1] for m in im) / n
    r = sum(m[2] for m in im) / n
    a = sum(m[3] for m in im) / n
    return {
        "model": model,
        "completeness_pct": round((g + o + r + a) / 4 * 100, 0),
        "goal_pct": round(g * 100, 0),
        "objectives_pct": round(o * 100, 0),
        "requirements_pct": round(r * 100, 0),
        "archetype_fields_pct": round(a * 100, 0),
        "n_items": n_items,
    }


def aggregate_quality_by_model(paths_in: list[str]) -> list[dict]:
    """Completeness per model across all output files, de-duplicated by slug.

    Use for the leaderboard view where each model that ever produced saved data
    appears exactly once (vs. collect_quality, which is one row per file)."""
    by_model: dict[str, dict[str, tuple]] = {}
    for path in paths_in:
        try:
            doc, items = _load_output(path)
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"[warn] skip {path}: {e}\n")
            continue
        # Exclude ported runs whose classification is the deterministic prior
        # (e.g. ollama-legacy) — they were never LLM-classified, so they would
        # conflate a real LLM model's leaderboard numbers.
        if doc.get("classification_source") == "deterministic_prior":
            continue
        model = _doc_label(doc, path).rstrip(":")
        bucket = by_model.setdefault(model, {})
        for i, it in enumerate(items):
            slug = it.get("slug") or f"_{i}"
            if slug not in bucket:
                bucket[slug] = _item_quality(it)
    rows = [_quality_row(m, list(s.values()), len(s)) for m, s in by_model.items()]
    rows.sort(key=lambda r: r["completeness_pct"], reverse=True)
    return rows


def _doc_label(doc: dict, path: str) -> str:
    gen = doc.get("generated_by")
    if gen and gen != "?":
        return gen.split(" ")[0]
    prov = doc.get("provider")
    model = doc.get("model")
    if prov and model and model != "*":
        return f"{prov}:{model}"
    return prov or os.path.basename(os.path.dirname(path)) or os.path.basename(path)


def collect_quality(specs: list[str]) -> list[dict]:
    """Each spec is PATH or LABEL=PATH; one completeness row per output file."""
    rows = []
    for spec in specs:
        label, _, path = spec.partition("=") if "=" in spec else ("", "", spec)
        try:
            doc, items = _load_output(path)
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"[warn] skip {path}: {e}\n")
            continue
        row = _quality_row(label or _doc_label(doc, path),
                           [_item_quality(it) for it in items], len(items))
        row["path"] = os.path.expanduser(path)
        rows.append(row)
    rows.sort(key=lambda r: r["completeness_pct"], reverse=True)
    return rows


def render_quality(rows: list[dict]) -> str:
    if not rows:
        return "No output files with items found.\n"
    out = ["QUALITY — ADOS completeness, higher is better", ""]
    out.append(f"{'rank':>4}  {'model':28s} {'compl%':>7} "
               f"{'goal':>5} {'obj':>5} {'req':>5} {'af':>5} {'items':>6}")
    for i, r in enumerate(rows, 1):
        out.append(f"{i:>4}  {r['model']:28s} {r['completeness_pct']:>6.0f}% "
                   f"{r['goal_pct']:>5.0f} {r['objectives_pct']:>5.0f} "
                   f"{r['requirements_pct']:>5.0f} {r['archetype_fields_pct']:>5.0f} "
                   f"{r['n_items']:>6}")
    out += ["",
            "compl% = mean(goal, objectives, requirements, archetype_fields) fill",
            "         scored against the same ontology contract for every model"]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt metrics",
        description="Model PERFORMANCE (tokens/sec) and QUALITY (ADOS "
                    "completeness percent) tables from saved comparison data.")
    sub = ap.add_subparsers(dest="cmd")

    p_perf = sub.add_parser("perf", help="Throughput (tokens/sec) from traces.")
    p_perf.add_argument("traces", nargs="*",
                        help="summarize_trace.jsonl path(s). Default: auto-discover.")
    p_perf.add_argument("--json", action="store_true")

    p_qual = sub.add_parser("quality", help="ADOS completeness (percent) from outputs.")
    p_qual.add_argument("outputs", nargs="*",
                        help="reconstructed_projects.json path(s) or LABEL=PATH. "
                             "Default: auto-discover.")
    p_qual.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)

    if args.cmd == "perf":
        traces = [os.path.expanduser(t) for t in args.traces] or discover_traces()
        if not args.traces:
            sys.stderr.write(f"[note] traces: {', '.join(traces) or '(none found)'}\n")
        rows = collect_perf(traces)
        print(json.dumps(rows, indent=2) if args.json else render_perf(rows), end="")
        return 0
    if args.cmd == "quality":
        specs = args.outputs or discover_outputs()
        if not args.outputs:
            sys.stderr.write(f"[note] outputs: {', '.join(specs) or '(none found)'}\n")
        rows = collect_quality(specs)
        print(json.dumps(rows, indent=2) if args.json else render_quality(rows), end="")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
