#!/usr/bin/env python3
"""
gpt report — one cross-sweep view of every benchmark in the unified format.

Reads the ADOS Project State files emitted by `gpt state --all`
($DATA_ROOT/states/<workload>__<model>.json) and renders a single markdown
report: one table per *workload*, columns mapped to named Project Geometry
coordinates, with provenance (geometry version, observed dates).

Scores are only comparable WITHIN a workload (oct2024 ran 27 bundles, jun2026
ran 173), so the report never averages across workloads — each workload gets
its own table and is labelled with its input size where known. (FR-D3.)

  gpt state --all        # first: refresh the unified state files
  gpt report             # write docs/cross-sweep-report.md
  gpt report --json      # machine-readable rows instead of markdown
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
sys.path.insert(0, HERE)
import metrics  # noqa: E402
import paths  # noqa: E402

# Report columns -> (coordinate_id, header, source). `source` is "attainment"
# (the 0..100 value) or "native:<metric>" (a raw observation like sec_per_item).
# Every coordinate_id here must be declared in the Project Geometry (guarded by
# assert_columns_declared, mirroring `gpt metrics`).
REPORT_COLUMNS: list[tuple[str, str, str]] = [
    ("COORD-B-COMPLETION", "Compl%", "attainment"),
    ("COORD-B-ACCURACY", "Acc%", "attainment"),
    ("COORD-B-DEPTH", "Depth%", "attainment"),
    ("COORD-B-SCHEMA", "Schema%", "attainment"),
    ("COORD-B-SPEED", "s/item", "native:sec_per_item"),
    ("COORD-B-ENERGY", "Wh/item", "native:wh_per_item"),
]


def column_coordinate_map() -> dict[str, str]:
    """Header -> coordinate_id, for the geometry-declared guard."""
    return {header: cid for cid, header, _src in REPORT_COLUMNS}


def parse_state_filename(name: str) -> tuple[str, str]:
    """`<workload>__<model>.json` -> (workload, model). No '__' -> ('', stem)."""
    stem = os.path.basename(name)
    if stem.endswith(".json"):
        stem = stem[:-5]
    if "__" in stem:
        workload, model = stem.split("__", 1)
        return workload, model
    return "", stem


def extract_coordinates(state: dict) -> dict[str, dict]:
    """Flatten a state's vectors to {coordinate_ref: {attainment, natives}}.

    `natives` is {metric_name: value} so the report can pull sec_per_item /
    wh_per_item that have no absolute 0..100 attainment.
    """
    out: dict[str, dict] = {}
    for vec in state.get("vector_states", []):
        for cv in vec.get("coordinate_values", []):
            ref = cv.get("coordinate_ref")
            if not ref:
                continue
            natives = {n.get("metric"): n.get("value")
                       for n in cv.get("native_observations", [])
                       if n.get("metric")}
            out[ref] = {"attainment": cv.get("attainment_0_100"),
                        "status": cv.get("measurement_status"),
                        "natives": natives}
    return out


def load_states(states_dir: str) -> list[dict]:
    """Load every state file into records sorted by (workload, model)."""
    records: list[dict] = []
    for path in sorted(glob.glob(os.path.join(states_dir, "*.json"))):
        try:
            with open(path, encoding="utf-8") as f:
                state = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        workload, model = parse_state_filename(path)
        records.append({
            "workload": workload,
            "model": model,
            "geometry_id": state.get("geometry_id"),
            "geometry_version": state.get("geometry_version"),
            "observed_at": state.get("observed_at"),
            "coords": extract_coordinates(state),
        })
    records.sort(key=lambda r: (r["workload"], r["model"]))
    return records


def group_by_workload(records: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for r in records:
        groups.setdefault(r["workload"], []).append(r)
    return groups


def _fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "attainment":
        return f"{float(value):.0f}"
    if kind == "native:sec_per_item":
        return f"{float(value):.1f}"
    if kind == "native:wh_per_item":
        return f"{float(value):.3f}"
    return str(value)


def _cell(coords: dict, cid: str, source: str) -> str:
    c = coords.get(cid)
    if not c:
        return "—"
    if source == "attainment":
        return _fmt(c.get("attainment"), source)
    metric = source.split(":", 1)[1]
    return _fmt((c.get("natives") or {}).get(metric), source)


def render_report(records: list[dict]) -> str:
    """Render the full cross-sweep markdown report (pure; no I/O)."""
    groups = group_by_workload(records)
    geom_versions = sorted({str(r["geometry_version"]) for r in records
                            if r.get("geometry_version") is not None})
    geom_id = next((r["geometry_id"] for r in records if r.get("geometry_id")),
                   "—")

    lines: list[str] = []
    lines.append("# Cross-sweep model report (ADOS Project States)")
    lines.append("")
    lines.append(f"- Geometry: `{geom_id}` · version(s): "
                 f"{', '.join(geom_versions) or '—'}")
    lines.append(f"- Workloads: {len(groups)} · states: {len(records)}")
    lines.append("- Scores are comparable **only within a workload** "
                 "(different sweeps ran different input sets); this report "
                 "never averages across workloads.")
    lines.append("")
    coord_note = ", ".join(f"{h}=`{cid}`" for cid, h, _ in REPORT_COLUMNS)
    lines.append(f"Columns → coordinates: {coord_note}")
    lines.append("")

    headers = ["Model"] + [h for _cid, h, _src in REPORT_COLUMNS]
    for workload in sorted(groups):
        rows = groups[workload]
        lines.append(f"## Workload: `{workload}` ({len(rows)} model(s))")
        lines.append("")
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for r in rows:
            cells = [r["model"]]
            for cid, _h, src in REPORT_COLUMNS:
                cells.append(_cell(r["coords"], cid, src))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt report",
        description="Render a cross-sweep markdown report from the unified "
                    "ADOS Project State files (gpt state --all).")
    ap.add_argument("--states-dir", default=None,
                    help="States directory (default: $DATA_ROOT/states).")
    ap.add_argument("--out", default=None,
                    help="Output markdown path (default: docs/cross-sweep-report.md).")
    ap.add_argument("--json", action="store_true",
                    help="Print machine-readable records instead of markdown.")
    args = ap.parse_args(argv)

    # Geometry-declared guard: every report column must name a real coordinate.
    metrics.assert_columns_declared(column_coordinate_map())

    root = paths.data_root() or os.path.join(ROOT, "output")
    states_dir = args.states_dir or os.path.join(root, "states")
    if not os.path.isdir(states_dir):
        sys.stderr.write(
            f"[report] no states at {states_dir}. Run `gpt state --all` first.\n")
        return 1
    records = load_states(states_dir)
    if not records:
        sys.stderr.write(f"[report] no state files in {states_dir}. "
                         f"Run `gpt state --all` first.\n")
        return 1

    if args.json:
        print(json.dumps(records, indent=2, ensure_ascii=False))
        return 0

    md = render_report(records)
    out_path = args.out or os.path.join(ROOT, "docs", "cross-sweep-report.md")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    sys.stderr.write(f"[report] wrote {out_path} "
                     f"({len(records)} states across "
                     f"{len(group_by_workload(records))} workload(s)).\n")
    return 0


if __name__ == "__main__":
    import interrupt
    raise SystemExit(interrupt.run_cli(lambda: main(sys.argv[1:]), "gpt report"))
