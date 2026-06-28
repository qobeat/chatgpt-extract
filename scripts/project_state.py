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
import zip_ledger  # noqa: E402

GEOMETRY_PATH = os.path.join(ROOT, "geometry", "project-geometry.json")
SCHEMA_PATH = os.path.join(ROOT, "schema", "ados", "project-state.schema.json")

# A *workload* is the identity of a benchmark sweep's input set (which projects,
# how many). Scores are only comparable WITHIN a workload — oct2024 ran 27
# bundles, jun2026 ran 173, so they must never be averaged together. Run-labels
# are matched in order; the first hit wins, else the run-label is its own
# workload so nothing is silently merged. (FR-D3 / NFR-Q5.)
WORKLOADS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^cmp-oct2(\b|[-_])", re.IGNORECASE), "oct2024-cmp"),
    (re.compile(r"^perf.*20260626", re.IGNORECASE), "jun2026-perf"),
    (re.compile(r"^ollama-legacy", re.IGNORECASE), "legacy-ollama"),
]


def workload_for(run_label: str) -> str:
    """Map a run-label to its workload id; unknown labels map to themselves."""
    for rx, wid in WORKLOADS:
        if rx.search(run_label or ""):
            return wid
    return _token(run_label or "unknown")

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


def coverage_from_store(store: str) -> tuple[float | None, list[dict]]:
    """Measure COORD-C-COVERAGE from the extract ledger for a store.

    Coverage attainment = captured / seen over all processed zips, where
    captured = seen - skipped (a silently-dropped conversation lowers the
    score). Returns (attainment_0_100 or None, native_observations). None when
    no extract has run (seen==0) so the coordinate stays `unknown`, never a
    false zero. (FR-C1/C2 → COORD-C-COVERAGE.)
    """
    try:
        data = zip_ledger.load(store)
    except Exception:
        return None, []
    zips = list((data.get("zips") or {}).values())
    seen = sum(int(z.get("seen", 0) or 0) for z in zips)
    skipped = sum(int(z.get("skipped", 0) or 0) for z in zips)
    written = sum(int(z.get("written", 0) or 0) for z in zips)
    if seen <= 0:
        return None, []
    captured = max(0, seen - skipped)
    attainment = round(100.0 * captured / seen, 1)
    natives = [
        {"metric": "seen", "value": seen, "unit": "conversations"},
        {"metric": "skipped", "value": skipped, "unit": "conversations"},
        {"metric": "written", "value": written, "unit": "conversations"},
    ]
    return attainment, natives


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


def gate_observations(qrow: dict | None, coverage: float | None,
                      coverage_natives: list[dict] | None) -> list[dict]:
    """Mandatory-gate evidence (rubric GATE-COVERAGE / GATE-SCHEMA) as natives.

    Each gate becomes a `{metric, value, unit:'gate'}` observation:
      * GATE-COVERAGE — `pass` when extract skipped==0, `fail` when any was
        dropped, `unknown` without an extract ledger.
      * GATE-SCHEMA — `pass` at 100% schema-valid, `cap_50` below (the rubric
        caps quality axes), `unknown` when not measured.
    Recorded on COORD-D-VERDICT so a reader sees whether a gate blocks the
    verdict before trusting the quality axes (NFR-P / FR-D follow-up).
    """
    skipped = next((n.get("value") for n in (coverage_natives or [])
                    if n.get("metric") == "skipped"), None)
    if coverage is None:
        cov_gate = "unknown"
    elif isinstance(skipped, (int, float)) and skipped > 0:
        cov_gate = "fail"
    else:
        cov_gate = "pass"

    sv = (qrow or {}).get("schema_valid_pct")
    if not isinstance(sv, (int, float)):
        schema_gate = "unknown"
    elif sv >= 100:
        schema_gate = "pass"
    else:
        schema_gate = "cap_50"

    return [
        {"metric": "GATE-COVERAGE", "value": cov_gate, "unit": "gate"},
        {"metric": "GATE-SCHEMA", "value": schema_gate, "unit": "gate"},
    ]


def build_state(geom: dict, model_label: str, qrow: dict | None,
                prow: dict | None, *, sweep: str, evidence: list[str],
                coverage: float | None = None,
                coverage_natives: list[dict] | None = None,
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
            coverage_natives or [], ev, 0.7 if cov_measured else 0.0)],
    }
    # The verdict stays a human audit (attainment null), but it now carries the
    # mandatory-gate evidence the rubric reads, so the score is gate-aware: a
    # failed coverage/schema gate is visible on the decision coordinate itself.
    decision_vec = {
        "vector_ref": "VEC-DECISION",
        "coordinate_values": [_coordinate_value(
            "COORD-D-VERDICT", None, "unknown",
            gate_observations(qrow, coverage, coverage_natives), ev, 0.0)],
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


def discover_run_labels() -> list[str]:
    """Run-labels under $DATA_ROOT/runs that carry a sweep artifact."""
    root = paths.data_root()
    if not root:
        return []
    base = os.path.join(root, "runs")
    if not os.path.isdir(base):
        return []
    labels: set[str] = set()
    for name in os.listdir(base):
        d = os.path.join(base, name)
        if not os.path.isdir(d) or name == "latest":
            continue
        if (glob.glob(os.path.join(d, "reconstructed*.json"))
                or os.path.isfile(os.path.join(d, "summarize_trace.jsonl"))):
            labels.add(name)
    return sorted(labels)


def states_for_run(geom: dict, run_label: str,
                   reference: str | None = None
                   ) -> list[tuple[str, str, dict]]:
    """Emit one Project State per model observed in a single sweep run.

    Returns [(workload, model_label, state_dict), ...] for `run_label`. The
    state itself stays schema-valid (no extra keys); its sweep workload is
    carried alongside (and survives on disk via the filename + evidence_refs).
    """
    outs, traces = _scoped_paths(run_label)
    ref_idx = (metrics.build_ref_index(metrics.resolve_ref_path(reference))
               if reference else None)
    quality = metrics.aggregate_quality_by_model(outs, ref_idx)
    perf = metrics.collect_perf(traces)
    qmap = {r["model"]: r for r in quality}
    pmap = {r["model"]: r for r in perf}
    models = sorted(set(qmap) | set(pmap))
    workload = workload_for(run_label)
    evidence = ["summarize_trace.jsonl", "reconstructed_projects.json", run_label]
    cov, cov_natives = coverage_from_store(paths.store_dir(run_label=run_label))
    if cov is not None:
        evidence.append("zip_ledger.json")
    out: list[tuple[str, str, dict]] = []
    for model in models:
        state = build_state(geom, model, qmap.get(model), pmap.get(model),
                            sweep=workload, evidence=evidence,
                            coverage=cov, coverage_natives=cov_natives)
        validate_state(state)
        out.append((workload, model, state))
    return out


def run_all(states_dir: str, reference: str | None = None) -> dict:
    """Emit states/<workload>__<model>.json for every discovered sweep.

    Returns a small summary {n_runs, n_states, workloads, files} for the CLI.
    Workload identity lives in the filename (`<workload>__<model>.json`) so the
    state JSON stays exactly the strict ADOS schema.
    """
    geom = load_geometry()
    os.makedirs(states_dir, exist_ok=True)
    labels = discover_run_labels()
    files: list[str] = []
    workloads: set[str] = set()
    n_states = 0
    for label in labels:
        for workload, model, state in states_for_run(geom, label,
                                                      reference=reference):
            workloads.add(workload)
            fname = f"{_token(workload)}__{_token(model)}.json"
            path = os.path.join(states_dir, fname)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                f.write("\n")
            files.append(path)
            n_states += 1
    return {"n_runs": len(labels), "n_states": n_states,
            "workloads": sorted(workloads), "files": files}


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
    ap.add_argument("--all", action="store_true",
                    help="Batch: emit one state per (workload, model) for every "
                         "discovered sweep into --states-dir.")
    ap.add_argument("--states-dir", default=None,
                    help="Output dir for --all (default: $DATA_ROOT/states).")
    ap.add_argument("--json", action="store_true",
                    help="Print the state to stdout and write nothing.")
    args = ap.parse_args(argv)

    if args.all:
        root = paths.data_root() or os.path.join(ROOT, "output")
        states_dir = args.states_dir or os.path.join(root, "states")
        summary = run_all(states_dir, reference=args.reference)
        if args.json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 0
        if not summary["n_states"]:
            sys.stderr.write("[state] no sweeps found under $DATA_ROOT/runs.\n")
            return 0
        sys.stderr.write(
            f"[state] wrote {summary['n_states']} state(s) from "
            f"{summary['n_runs']} sweep(s) into {states_dir}\n"
            f"[state] workloads: {', '.join(summary['workloads'])}\n")
        return 0

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
    # Explicit --coverage wins; otherwise measure it from the default extract
    # ledger (a --runs glob can span labels, so we don't guess one there).
    cov, cov_natives = args.coverage, None
    if cov is None and not args.runs:
        cov, cov_natives = coverage_from_store(paths.store_dir())
    if cov is not None:
        evidence.append("zip_ledger.json")
    state = build_state(geom, target, qmap.get(target), pmap.get(target),
                        sweep=sweep, evidence=evidence, coverage=cov,
                        coverage_natives=cov_natives)
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
