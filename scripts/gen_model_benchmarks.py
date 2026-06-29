#!/usr/bin/env python3
"""
gen_model_benchmarks.py — regenerate config/generated/model_benchmarks.json from
the corrected metric (FR-B2/B3/D2). Formerly gen_model_notes.py.

The old design wrote a fragile free-text `note` string ("compl 23/27 · depth* 78%
…") straight into config/models.json — easy to hand-edit, hard to parse, and it
mixed machine-owned numbers into a hand-curated file. This script instead emits a
MACHINE-OWNED, TYPED file: each model maps to typed columns (completion_pct,
depth_on_success_pct, accuracy_pct, sec_per_item, wh_per_item, …) so the verdict
can never silently drift from the numbers and the axes stay SEPARATE (never blended
into one rank — AI_MODEL_TESTS.md §3.5).

Upsert semantics: re-running updates the models present in the sweep, KEEPS models
not in it, and ADDS newly-seen models. Latest-snapshot only (no history array).

Usage:
  python scripts/gen_model_benchmarks.py --runs 'cmp-oct2-*' --reference ref=cmp-oct2-codex
  python scripts/gen_model_benchmarks.py --check     # exit 1 if the file is stale (CI)
  python scripts/gen_model_benchmarks.py --json      # print proposed models, write nothing
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)
import interrupt  # noqa: E402
import metrics  # noqa: E402
import paths  # noqa: E402

OUT_PATH = os.path.join(ROOT, "config", "generated", "model_benchmarks.json")
SCHEMA_PATH = os.path.join(ROOT, "schema", "model_benchmarks.schema.json")

# Default benchmark metadata (overridable on the CLI). These describe the rig the
# sweep was run on; the numbers themselves come from the run artifacts.
_DEFAULT_GPU = "RTX 3090 24GB"
_DEFAULT_NUM_CTX = 16384

# model_benchmark keys allowed by schema/model_benchmarks.schema.json. Anything
# the metric rows carry beyond these (load_s, throughput_tok_s, attempted, …) is
# intentionally dropped: additionalProperties is false on the schema.
_PCT_FROM_QUALITY = (
    "depth_on_success_pct", "schema_valid_pct", "accuracy_pct",
    "goal_pct", "objectives_pct", "requirements_pct", "archetype_fields_pct",
)
_NUM_FROM_PERF = ("sec_per_item", "warm_sec_per_item", "gen_tok_s",
                  "usd_per_1k_items", "wh_per_item")


def bench_key(model_id: str) -> str:
    """Normalize a metric `model` id to the schema's 'provider:name' key.

    Metric ids are mixed: 'ollama:qwen3:8b' and 'cursor:composer-2.5' already
    carry a provider, but bare cloud labels ('codex', 'claude') do not. The schema
    key pattern is ^[a-z0-9_]+:.+$ and the bank keys entries 'provider:name', so a
    bare label becomes 'codex' -> 'codex:codex'."""
    mid = model_id.rstrip(":")
    return mid if ":" in mid else f"{mid}:{mid}"


def build_row(qrow: dict | None, prow: dict | None) -> dict | None:
    """Typed per-model row from a quality row and/or a perf row.

    Returns None when neither source has data. Reliability, depth, and correctness
    stay as SEPARATE fields (FR-B2); there is no blended score."""
    if not qrow and not prow:
        return None
    row: dict = {}
    if qrow:
        row["n_items"] = int(qrow.get("n_items") or 0)
        row["completed"] = int(qrow.get("completed") or 0)
        row["completion_pct"] = float(qrow.get("completion_pct") or 0.0)
        for k in _PCT_FROM_QUALITY:
            v = qrow.get(k)
            if isinstance(v, (int, float)):
                row[k] = float(v)
    else:
        # perf-only model: derive reliability from the trace counts.
        completed = int(prow.get("completed") or 0)
        attempted = int(prow.get("attempted") or completed)
        row["n_items"] = attempted
        row["completed"] = completed
        row["completion_pct"] = round(float(prow.get("completion_rate") or 0.0) * 100, 0)
    if prow:
        for k in _NUM_FROM_PERF:
            v = prow.get(k)
            if isinstance(v, (int, float)):
                row[k] = float(v)
        # Full GPU telemetry summary (gpu-telemetry-summary/1) when the run
        # captured it; omitted (not null) when absent, like wh_per_item.
        gpu = prow.get("gpu")
        if isinstance(gpu, dict) and gpu.get("available"):
            row["gpu"] = gpu
    return row


def _scoped_paths(runs_glob: str) -> tuple[list[str], list[str]]:
    """Resolve reconstructed/trace paths for runs matching a run-label glob under
    $DATA_ROOT/runs (e.g. 'cmp-oct2-*'). Scoping the metric to one defined sweep
    keeps the file reproducible instead of folding in every stale run."""
    root = paths.data_root()
    if not root:
        raise SystemExit("[gen-model-benchmarks] $DATA_ROOT not set; cannot scope "
                         "--runs. Set RECONSTRUCTOR_DATA_ROOT or config data_root.")
    base = os.path.join(root, "runs")
    outs = sorted(glob.glob(os.path.join(base, runs_glob, "reconstructed_projects.json")))
    traces = sorted(glob.glob(os.path.join(base, runs_glob, "summarize_trace.jsonl")))
    return outs, traces


def compute_models(runs_glob: str | None,
                   reference: str | None) -> dict[str, dict]:
    """Build the {provider:name -> typed row} map for the given sweep."""
    if runs_glob:
        outs, traces = _scoped_paths(runs_glob)
    else:
        outs, traces = metrics.discover_outputs(), metrics.discover_traces()
    ref_idx = (metrics.build_ref_index(metrics.resolve_ref_path(reference))
               if reference else None)
    quality = metrics.aggregate_quality_by_model(outs, ref_idx)
    perf = metrics.collect_perf(traces)
    qmap = {bench_key(r["model"]): r for r in quality}
    pmap = {bench_key(r["model"]): r for r in perf}
    out: dict[str, dict] = {}
    for key in sorted(set(qmap) | set(pmap)):
        row = build_row(qmap.get(key), pmap.get(key))
        if row is not None:
            out[key] = row
    return out


def load_existing() -> dict:
    if not os.path.exists(OUT_PATH):
        return {}
    with open(OUT_PATH, encoding="utf-8") as f:
        return json.load(f)


def upsert(existing: dict, fresh: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """Merge fresh rows over the existing models map: update keys in the sweep,
    keep keys not in it, add new ones. Never delete. Returns (merged, changed)."""
    merged = dict(existing.get("models") or {})
    changed: list[str] = []
    for key, row in fresh.items():
        if merged.get(key) != row:
            changed.append(key)
        merged[key] = row
    return merged, changed


def build_document(models: dict[str, dict], reference: str | None,
                   gpu: str, num_ctx: int, date: str) -> dict:
    sample_items = max((m.get("n_items", 0) for m in models.values()), default=0)
    return {
        "_generated": True,
        "generator": "gen_model_benchmarks.py",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": "1.0.0",
        "benchmark": {
            "date": date,
            "gpu": gpu,
            "sample_items": sample_items,
            "num_ctx": num_ctx,
            "reference": reference or "(none)",
        },
        "models": models,
    }


def _validate(doc: dict) -> None:
    """Best-effort self-validation against the schema (skipped if jsonschema or
    the schema file is unavailable)."""
    try:
        import jsonschema  # noqa: E402
    except Exception:
        return
    try:
        with open(SCHEMA_PATH, encoding="utf-8") as f:
            schema = json.load(f)
    except OSError:
        return
    jsonschema.validate(doc, schema)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt gen-model-benchmarks",
        description="Regenerate config/generated/model_benchmarks.json (typed, "
                    "machine-owned) from the corrected metric.")
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if the generated file is stale (CI guard); write nothing.")
    ap.add_argument("--json", action="store_true",
                    help="Print the proposed models map and write nothing.")
    ap.add_argument("--runs", metavar="GLOB", default=None,
                    help="Scope the metric to run-labels matching GLOB under "
                         "$DATA_ROOT/runs (e.g. 'cmp-oct2-*').")
    ap.add_argument("--reference", metavar="ref=<file|run-label>", default=None,
                    help="Accuracy etalon run (e.g. 'ref=cmp-oct2-codex').")
    ap.add_argument("--gpu", default=_DEFAULT_GPU, help="Hardware label for metadata.")
    ap.add_argument("--num-ctx", type=int, default=_DEFAULT_NUM_CTX,
                    help="Context window held constant across the sweep.")
    ap.add_argument("--date", default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    help="Benchmark date (ISO-8601); defaults to today.")
    args = ap.parse_args(argv)

    fresh = compute_models(args.runs, args.reference)
    if not fresh:
        sys.stderr.write("[gen-model-benchmarks] no metric data found; run "
                         "benchmark runs first. Nothing to regenerate.\n")
        return 0

    existing = load_existing()
    merged, changed = upsert(existing, fresh)

    if args.json:
        print(json.dumps(merged, indent=2, ensure_ascii=False))
        return 0

    if args.check:
        if changed:
            sys.stderr.write(
                f"[gen-model-benchmarks] STALE: {', '.join(changed)}\n"
                f"Run: python scripts/gen_model_benchmarks.py "
                f"--runs '{args.runs or '*'}' --reference {args.reference or '(none)'}\n")
            return 1
        sys.stderr.write("[gen-model-benchmarks] file matches the latest metric.\n")
        return 0

    doc = build_document(merged, args.reference, args.gpu, args.num_ctx, args.date)
    _validate(doc)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    if changed:
        sys.stderr.write(f"[gen-model-benchmarks] updated {len(changed)} model(s): "
                         f"{', '.join(changed)}\n")
    else:
        sys.stderr.write("[gen-model-benchmarks] file already current (rewrote metadata).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt gen-model-benchmarks"))
