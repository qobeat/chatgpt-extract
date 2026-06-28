#!/usr/bin/env python3
"""
project_state.py — emit an ADOS Project State from a benchmark sweep.

A Project State is an append-only, evidence-backed OBSERVATION of one Project
Geometry version (schema/ados/project-state.schema.json). It turns the metric
tables into values against NAMED coordinates, so "qwen3:8b scored 16% accuracy"
becomes a typed observation against COORD-B-ACCURACY rather than a number in a
doc that can silently re-blend.

This reuses scripts/metrics.py to read the same artifacts `gpt metrics` does, so
the state can never drift from the rendered tables. One state file describes one
provider's observation against the Geometry for one named sweep.

Usage:
  gpt state --model codex --reference ref=cmp-oct2-codex
  gpt state --runs 'cmp-oct2-*' --model gemma4:31b --out runs/cmp/project-state.json
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)
import interrupt  # noqa: E402
import metrics  # noqa: E402
import paths  # noqa: E402

GEOMETRY_PATH = os.path.join(ROOT, "geometry", "project-geometry.json")
SCHEMA_PATH = os.path.join(ROOT, "schema", "ados", "project-state.schema.json")

# Quality-row %% columns that map directly onto a 0..100 coordinate attainment.
_QUALITY_ATTAINMENT = {
    "COORD-B-COMPLETION": "completion_pct",
    "COORD-B-DEPTH": "depth_on_success_pct",
    "COORD-B-ACCURACY": "accuracy_pct",
    "COORD-B-SCHEMA": "schema_valid_pct",
}

_TOKEN_RE = re.compile(r"[^A-Za-z0-9._:-]+")


def _token(s: str) -> str:
    """Coerce a label to the schema's id/ref pattern (^[A-Za-z0-9][...]*)."""
    t = _TOKEN_RE.sub("-", s).strip("-")
    return t or "x"


def load_geometry() -> dict:
    with open(GEOMETRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def _coordinate_value(coord_ref: str, attainment: float | None,
                      status: str, native: list[dict], evidence: list[str],
                      confidence: float) -> dict:
    return {
        "coordinate_ref": coord_ref,
        "attainment_0_100": attainment,
        "measurement_status": status,
        "native_observations": native,
        "evidence_refs": sorted(set(evidence)),
        "confidence": confidence,
    }


def build_benchmark_vector(qrow: dict | None, prow: dict | None,
                           evidence: list[str]) -> dict:
    """VEC-BENCHMARK coordinate values for one provider from its metric rows."""
    qrow = qrow or {}
    prow = prow or {}
    values: list[dict] = []

    for coord_ref, col in _QUALITY_ATTAINMENT.items():
        v = qrow.get(col)
        measured = isinstance(v, (int, float))
        native: list[dict] = []
        if coord_ref == "COORD-B-COMPLETION" and "completed" in qrow:
            native = [{"metric": "completed", "value": qrow.get("completed"),
                       "unit": "items"},
                      {"metric": "n_items", "value": qrow.get("n_items"),
                       "unit": "items"}]
        values.append(_coordinate_value(
            coord_ref,
            float(v) if measured else None,
            "measured" if measured else "unknown",
            native,
            evidence,
            0.7 if measured else 0.0))

    # Speed: real latency is the native observation; there is no absolute 0..100
    # without a chosen "best tier", so attainment stays null but the metric is
    # recorded (measured) so the decision can read it.
    spi = prow.get("sec_per_item")
    values.append(_coordinate_value(
        "COORD-B-SPEED", None,
        "measured" if isinstance(spi, (int, float)) else "unknown",
        ([{"metric": "sec_per_item", "value": spi, "unit": "seconds"}]
         if isinstance(spi, (int, float)) else []),
        evidence, 0.7 if isinstance(spi, (int, float)) else 0.0))

    # Energy is diagnostic; record measured Wh/item when a power trace existed.
    wh = prow.get("wh_per_item")
    values.append(_coordinate_value(
        "COORD-B-ENERGY", None,
        "measured" if isinstance(wh, (int, float)) else "unknown",
        ([{"metric": "wh_per_item", "value": wh, "unit": "watt_hours"}]
         if isinstance(wh, (int, float)) else []),
        evidence, 0.7 if isinstance(wh, (int, float)) else 0.0))

    return {"vector_ref": "VEC-BENCHMARK", "coordinate_values": values}


def build_state(geom: dict, model_label: str, qrow: dict | None,
                prow: dict | None, *, sweep: str, evidence: list[str],
                coverage: float | None = None,
                observed_at: str | None = None) -> dict:
    """Assemble a schema-valid Project State for one provider observation.

    The benchmark vector carries the measured per-provider coordinates. The
    catalog/decision vectors are recorded as `unknown` unless evidence is
    supplied (coverage from an extract log; the verdict from an audit), so the
    state never claims attainment it did not observe."""
    obs = observed_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    ev = [_token(e) for e in (evidence or []) if e]
    state_id = _token(f"STATE-{model_label}-{sweep}")

    bench_vec = build_benchmark_vector(qrow, prow, ev)

    cov_measured = isinstance(coverage, (int, float))
    catalog_vec = {
        "vector_ref": "VEC-CATALOG",
        "coordinate_values": [_coordinate_value(
            "COORD-C-COVERAGE",
            float(coverage) if cov_measured else None,
            "measured" if cov_measured else "unknown",
            [], ev, 0.7 if cov_measured else 0.0)],
    }
    decision_vec = {
        "vector_ref": "VEC-DECISION",
        "coordinate_values": [_coordinate_value(
            "COORD-D-VERDICT", None, "unknown", [], ev, 0.0)],
    }

    return {
        "schema_version": "1.0.0",
        "state_id": state_id,
        "project_ref": geom["project_ref"],
        "geometry_id": geom["geometry_id"],
        "geometry_version": geom["geometry_version"],
        "pass_ref": None,
        "observation_role": "evaluation_snapshot",
        "observed_at": obs,
        "vector_states": [bench_vec, catalog_vec, decision_vec],
    }


def validate_state(state: dict) -> None:
    """Best-effort schema validation (skipped if jsonschema is unavailable)."""
    try:
        import jsonschema
    except Exception:
        return
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.Draft202012Validator(schema).validate(state)


def _scoped_paths(runs_glob: str) -> tuple[list[str], list[str]]:
    root = paths.data_root()
    if not root:
        raise SystemExit("[state] $DATA_ROOT not set; cannot scope --runs.")
    base = os.path.join(root, "runs")
    outs = sorted(glob.glob(os.path.join(base, runs_glob,
                                         "reconstructed_projects.json")))
    traces = sorted(glob.glob(os.path.join(base, runs_glob,
                                           "summarize_trace.jsonl")))
    return outs, traces


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt state",
        description="Emit an ADOS Project State (typed observation against the "
                    "Project Geometry coordinates) from a benchmark sweep.")
    ap.add_argument("--model", default=None,
                    help="Provider/model label to observe (e.g. 'codex', "
                         "'ollama:gemma4:31b'). Default: the reference model, "
                         "else the first quality row.")
    ap.add_argument("--runs", metavar="GLOB", default=None,
                    help="Scope to run-labels matching GLOB under $DATA_ROOT/runs.")
    ap.add_argument("--reference", metavar="ref=<file|run-label>", default=None,
                    help="Accuracy etalon run (adds COORD-B-ACCURACY).")
    ap.add_argument("--coverage", type=float, default=None,
                    help="COORD-C-COVERAGE attainment 0..100 (from an extract log).")
    ap.add_argument("--out", default=None,
                    help="Output path. Default: geometry/project-state.json.")
    ap.add_argument("--json", action="store_true",
                    help="Print the state to stdout and write nothing.")
    args = ap.parse_args(argv)

    if args.runs:
        outs, traces = _scoped_paths(args.runs)
        sweep = args.runs
    else:
        outs, traces = metrics.discover_outputs(), metrics.discover_traces()
        sweep = "discovered"
    ref_idx = (metrics.build_ref_index(metrics.resolve_ref_path(args.reference))
               if args.reference else None)
    quality = metrics.aggregate_quality_by_model(outs, ref_idx)
    perf = metrics.collect_perf(traces)
    if not quality and not perf:
        sys.stderr.write("[state] no metric data found; run a sweep first.\n")
        return 0

    qmap = {r["model"]: r for r in quality}
    pmap = {r["model"]: r for r in perf}

    target = args.model
    if target is None:
        if args.reference:
            ref_raw = args.reference.split("=", 1)[-1]
            target = next((m for m in qmap if ref_raw in m), None)
        target = target or (quality[0]["model"] if quality else perf[0]["model"])

    if target not in qmap and target not in pmap:
        sys.stderr.write(f"[state] model '{target}' not found in sweep. "
                         f"Available: {', '.join(sorted(set(qmap) | set(pmap)))}\n")
        return 1

    geom = load_geometry()
    evidence = ["summarize_trace.jsonl", "reconstructed_projects.json"]
    if args.reference:
        evidence.append(args.reference.split("=", 1)[-1])
    state = build_state(geom, target, qmap.get(target), pmap.get(target),
                        sweep=sweep, evidence=evidence, coverage=args.coverage)
    validate_state(state)

    if args.json:
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0

    out_path = args.out or os.path.join(ROOT, "geometry", "project-state.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)
        f.write("\n")
    sys.stderr.write(f"[state] wrote {out_path} for '{target}' "
                     f"(geometry v{geom['geometry_version']}).\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt state"))
