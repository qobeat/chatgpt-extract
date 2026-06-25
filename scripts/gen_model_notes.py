#!/usr/bin/env python3
"""
gen_model_notes.py — regenerate config/models.json `note` verdicts from the
CORRECTED metric (FR-D2).

The old notes hand-wrote a blended "74% depth, 8/10 done" verdict. This script
derives each note from the separated metric columns (completion,
depth-on-success, schema-valid, optional accuracy, s/item, $/1k, Wh/item) so the
verdicts can never silently drift from the numbers, and regenerates them
whenever the metric changes.

Usage:
  python scripts/gen_model_notes.py            # rewrite notes in place
  python scripts/gen_model_notes.py --check    # exit 1 if notes are stale
  python scripts/gen_model_notes.py --json      # print proposed notes, write nothing
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)
import interrupt  # noqa: E402
import metrics  # noqa: E402

MODELS_PATH = os.path.join(ROOT, "config", "models.json")


def _pct(v) -> str | None:
    return f"{v:.0f}%" if isinstance(v, (int, float)) else None


def format_note(qrow: dict | None, prow: dict | None) -> str | None:
    """Build a data-derived verdict from the separated metric columns.

    Returns None when there is no data for the model (caller keeps the existing
    note). The format NEVER blends reliability and depth into one number."""
    if not qrow and not prow:
        return None
    parts: list[str] = []
    if qrow:
        parts.append(f"compl {qrow.get('completed', 0)}/{qrow.get('n_items', 0)}")
        d = _pct(qrow.get("depth_on_success_pct"))
        if d is not None:
            parts.append(f"depth* {d}")
        j = _pct(qrow.get("schema_valid_pct"))
        if j is not None:
            parts.append(f"json {j}")
        a = qrow.get("accuracy_pct")
        if a is not None:
            parts.append(f"acc {a:.0f}%")
    if prow:
        parts.append(f"{prow.get('sec_per_item', 0):.1f} s/item")
        usd1k = prow.get("usd_per_1k_items")
        if isinstance(usd1k, (int, float)) and usd1k > 0:
            parts.append(f"${usd1k:.2f}/1k")
        wh = prow.get("wh_per_item")
        if isinstance(wh, (int, float)):
            parts.append(f"{wh:.3f} Wh/item")
    return " · ".join(parts) if parts else None


def _candidates(entry: dict) -> list[str]:
    name = entry.get("name", "")
    prov = entry.get("provider", "")
    return [name, f"{prov}:{name}"]


def _match(rows: list[dict], entry: dict) -> dict | None:
    cands = _candidates(entry)
    name = entry.get("name", "")
    for r in rows:
        m = r.get("model", "")
        if m in cands or m == name or m.endswith(f":{name}"):
            return r
    return None


def regenerate(models: dict, quality_rows: list[dict],
               perf_rows: list[dict]) -> tuple[dict, list[str]]:
    """Return (new_models, changed_names). Only entries with metric data get a
    new note; others are left untouched."""
    changed: list[str] = []
    new = json.loads(json.dumps(models))  # deep copy
    for entry in new.get("models", []):
        if entry.get("skip"):
            continue
        qrow = _match(quality_rows, entry)
        prow = _match(perf_rows, entry)
        note = format_note(qrow, prow)
        if note and note != entry.get("note"):
            entry["note"] = note
            changed.append(entry.get("name", "?"))
    return new, changed


def load_metric_rows() -> tuple[list[dict], list[dict]]:
    quality = metrics.aggregate_quality_by_model(metrics.discover_outputs())
    perf = metrics.collect_perf(metrics.discover_traces())
    return quality, perf


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="gpt gen-model-notes",
                                 description="Regenerate config/models.json note "
                                             "verdicts from the corrected metric.")
    ap.add_argument("--check", action="store_true",
                    help="Exit 1 if any note is stale (CI guard); write nothing.")
    ap.add_argument("--json", action="store_true",
                    help="Print proposed {name: note} and write nothing.")
    args = ap.parse_args(argv)

    with open(MODELS_PATH, encoding="utf-8") as f:
        models = json.load(f)
    quality, perf = load_metric_rows()
    if not quality and not perf:
        sys.stderr.write("[gen-model-notes] no metric data found under $DATA_ROOT; "
                         "run benchmark runs first. Nothing to regenerate.\n")
        return 0
    new, changed = regenerate(models, quality, perf)

    if args.json:
        print(json.dumps({e["name"]: e.get("note") for e in new["models"]},
                         indent=2, ensure_ascii=False))
        return 0
    if args.check:
        if changed:
            sys.stderr.write(f"[gen-model-notes] STALE notes: {', '.join(changed)}\n"
                             f"Run: python scripts/gen_model_notes.py\n")
            return 1
        sys.stderr.write("[gen-model-notes] notes match the latest metric.\n")
        return 0

    if changed:
        with open(MODELS_PATH, "w", encoding="utf-8") as f:
            json.dump(new, f, indent=2, ensure_ascii=False)
            f.write("\n")
        sys.stderr.write(f"[gen-model-notes] updated {len(changed)} note(s): "
                         f"{', '.join(changed)}\n")
    else:
        sys.stderr.write("[gen-model-notes] notes already current.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt gen-model-notes"))
