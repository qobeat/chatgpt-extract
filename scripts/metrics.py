#!/usr/bin/env python3
"""
metrics.py — model PERFORMANCE and QUALITY tables from saved comparison data.

Two subcommands, both read-only over artifacts already on disk:

  perf     Speed per model, from one or more summarize_trace.jsonl files.
           Ranks by per-item latency (s/item, lower is faster); also reports
           generation rate (gen tok/s) and total throughput (tok/s).
  quality  ADOS record quality (%) per model, from one or more
           reconstructed_projects.json outputs. Ranks by how completely AND
           how deeply the structured ADOS fields are filled.

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
import interrupt  # noqa: E402
import paths  # noqa: E402
import power as power_lib  # noqa: E402
import gpu_telemetry as gpu_tele  # noqa: E402
import cost as cost_lib  # noqa: E402

GEOMETRY_PATH = os.path.join(ROOT, "geometry", "project-geometry.json")

# Every quality/perf column this tool renders must NAME the ADOS Project
# Coordinate it measures. The Geometry carries each coordinate's `measures` /
# `does_not_measure` boundary, so binding columns to coordinate ids means a new
# column cannot be added without first declaring what it measures — the durable
# guard against silently re-blending the separated quality axes (the original
# "smarter models score worse" bug).
COLUMN_COORDINATES = {
    "completion_pct": "COORD-B-COMPLETION",
    "depth_on_success_pct": "COORD-B-DEPTH",
    "accuracy_pct": "COORD-B-ACCURACY",
    "schema_valid_pct": "COORD-B-SCHEMA",
    "sec_per_item": "COORD-B-SPEED",
    "warm_sec_per_item": "COORD-B-SPEED",
    "wh_per_item": "COORD-B-ENERGY",
}


def declared_coordinate_ids(geometry_path: str = GEOMETRY_PATH) -> set[str]:
    """Coordinate ids declared in the Project Geometry (empty set if the file is
    unavailable, so read-only metrics degrade rather than crash)."""
    try:
        with open(geometry_path, encoding="utf-8") as f:
            geom = json.load(f)
    except (OSError, json.JSONDecodeError):
        return set()
    return {c.get("coordinate_id") for c in geom.get("project_coordinates", [])}


def assert_columns_declared(columns: dict | None = None,
                            geometry_path: str = GEOMETRY_PATH) -> None:
    """Raise ValueError if any rendered column maps to a coordinate not declared
    in the Project Geometry. Adding an undeclared column fails here until a
    coordinate (with measures/does_not_measure) is defined (Task 6 guard)."""
    cols = COLUMN_COORDINATES if columns is None else columns
    declared = declared_coordinate_ids(geometry_path)
    if not declared:
        return  # geometry unreadable: don't block a read-only metrics print
    undeclared = {col: cid for col, cid in cols.items() if cid not in declared}
    if undeclared:
        raise ValueError(
            "gpt metrics: column(s) map to coordinate ids not declared in the "
            f"Project Geometry: {undeclared}. Declare them (with measures / "
            "does_not_measure) in geometry/project-geometry.json before "
            "rendering them.")


def _subscription_providers() -> set[str]:
    """Providers whose marginal cost is $0 (covered by a plan), so $/1k must read
    0 regardless of any notional token price recorded in a historical trace."""
    try:
        pricing = cost_lib.load_pricing()
    except OSError:
        return set()
    out = set()
    for name, prov in (pricing.get("providers") or {}).items():
        if prov.get("subscription"):
            out.add(name)
    return out


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
    subs = _subscription_providers()
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
                          "secs": 0.0, "in_tok": 0, "out_tok": 0, "usd": 0.0,
                          "load_ms": 0.0, "dirs": set()})
                a["dirs"].add(os.path.dirname(os.path.realpath(tf)))
                p = e.get("payload") or {}
                if e.get("event_type") == "LLM_OK":
                    a["ok"] += 1
                    a["secs"] += float(p.get("secs") or 0.0)
                    a["in_tok"] += int(p.get("in_tok") or 0)
                    a["out_tok"] += int(p.get("out_tok") or 0)
                    a["usd"] += float(p.get("usd") or 0.0)
                    a["load_ms"] += float(p.get("load_ms") or 0.0)
                elif e.get("event_type") == "LLM_FAIL":
                    a["fail"] += 1
    rows = []
    for a in agg.values():
        if a["ok"] <= 0 or a["secs"] <= 0:
            continue
        attempted = a["ok"] + a["fail"]
        # Plan-covered providers are $0 marginal even if a historical trace
        # recorded a notional token price (README: "$0 on plan").
        provider = a["model"].split(":", 1)[0]
        usd = 0.0 if provider in subs else a["usd"]
        # Measured GPU energy (FR-B6): integrate the GPU telemetry ledger beside
        # this run's summarize_trace.jsonl. Prefer the rich gpu_trace.jsonl; fall
        # back to the legacy power_trace.jsonl. None when no trace was recorded.
        wh_total = 0.0
        have_power = False
        gpu_summary = None
        for d in a["dirs"]:
            trace = next((os.path.join(d, f) for f in ("gpu_trace.jsonl",
                          "power_trace.jsonl") if os.path.isfile(os.path.join(d, f))),
                         None)
            if trace is None:
                continue
            wh, _dur, n = power_lib.energy_wh_from_trace(trace)
            if n >= 2:
                wh_total += wh
                have_power = True
                if gpu_summary is None:  # attach the first run's full telemetry
                    s = gpu_tele.summarize_trace(trace)
                    if s.get("available"):
                        gpu_summary = s
        # Load-excluded latency (FR-B): subtract the one-time model load (exact,
        # from Ollama load_duration) so big local models are not penalised for a
        # fixed cold-start. None when no load timing was recorded (legacy traces
        # or cloud providers with no VRAM load → warm == wall).
        load_s = a["load_ms"] / 1000.0
        warm_per_item = (round(max(a["secs"] - load_s, 0.0) / a["ok"], 1)
                         if a["load_ms"] > 0 else None)
        rows.append({
            "model": a["model"].rstrip(":") or a["model"],
            "sec_per_item": round(a["secs"] / a["ok"], 1),
            "warm_sec_per_item": warm_per_item,
            "load_s": round(load_s, 1) if a["load_ms"] > 0 else None,
            "gen_tok_s": round(a["out_tok"] / a["secs"], 1),
            "throughput_tok_s": round((a["in_tok"] + a["out_tok"]) / a["secs"], 1),
            "completed": a["ok"],
            "attempted": attempted,
            "completion_rate": round(a["ok"] / attempted, 3) if attempted else 0.0,
            "usd_total": round(usd, 6),
            "usd_per_1k_items": round(usd / a["ok"] * 1000, 4),
            "wh_per_item": round(wh_total / a["ok"], 4) if have_power else None,
            "gpu": gpu_summary,
        })
    # Rank by real per-item speed (lower s/item = faster on top). Total
    # throughput (in+out)/s is NOT the sort key: it is inflated by large input
    # bundles, so a model that merely *ingests* big bundles quickly would
    # outrank one that actually finishes each item sooner. Break ties toward the
    # more reliable model, then the faster generator.
    rows.sort(key=lambda r: (r["sec_per_item"], -r["completion_rate"], -r["gen_tok_s"]))
    return rows


def render_perf(rows: list[dict]) -> str:
    if not rows:
        return "No LLM_OK events found in the given traces.\n"
    has_power = any(r.get("wh_per_item") is not None for r in rows)
    has_warm = any(r.get("warm_sec_per_item") is not None for r in rows)
    out = ["PERFORMANCE — speed per item, lower s/item is faster", ""]
    pw_hdr = f" {'Wh/item':>8}" if has_power else ""
    warm_hdr = f" {'warm s/it':>9} {'load s':>7}" if has_warm else ""
    out.append(f"{'rank':>4}  {'model':28s} {'s/item':>7}{warm_hdr} "
               f"{'gen tok/s':>10} {'tok/s':>8} {'$/1k':>8}{pw_hdr} "
               f"{'completed':>10}")
    for i, r in enumerate(rows, 1):
        pw_cell = ""
        if has_power:
            wh = r.get("wh_per_item")
            pw_cell = f" {wh:>8.4f}" if wh is not None else f" {'—':>8}"
        warm_cell = ""
        if has_warm:
            w = r.get("warm_sec_per_item")
            ld = r.get("load_s")
            warm_cell = (f" {w:>9.1f} {ld:>7.1f}" if w is not None
                         else f" {'—':>9} {'—':>7}")
        out.append(f"{i:>4}  {r['model']:28s} {r['sec_per_item']:>7.1f}{warm_cell} "
                   f"{r['gen_tok_s']:>10.1f} {r['throughput_tok_s']:>8.1f} "
                   f"{r.get('usd_per_1k_items', 0.0):>8.3f}{pw_cell} "
                   f"{r['completed']:>4}/{r['attempted']:<5}")
    out += ["",
            "s/item    = wall-seconds per completed item (rank key; lower is faster)"]
    if has_warm:
        out += ["warm s/it = s/item with the one-time model load excluded "
                "(load s, from Ollama load_duration; — = not recorded/cloud)"]
    out += ["gen tok/s = output tokens / wall-seconds (generation rate)",
            "tok/s     = (input+output tokens) / wall-seconds (total work rate; "
            "inflated by large input bundles, so not the rank key)",
            "$/1k      = measured cloud cost per 1,000 completed items "
            "($0 for local/plan)"]
    if has_power:
        out.append("Wh/item   = measured GPU watt-hours per completed item "
                   "(from --meter-power; FR-B6)")
    out.append("completed = LLM_OK / attempted (reliability; tie-breaker)")
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


# A complete ADOS objective set spans the forming/speeding/governance triad, so
# three is the natural "full credit" target; requirements use the same cap as a
# "substantive set" threshold. Grading by capped count (instead of mere
# presence) makes the score reflect depth — one thin objective no longer scores
# the same as a full, governed set — without rewarding unbounded verbosity.
_DEPTH_CAP = 3


def _depth(seq) -> float:
    """Graded set-completeness: 0 when empty, 1.0 at >= _DEPTH_CAP entries."""
    n = len(seq or [])
    return min(n, _DEPTH_CAP) / _DEPTH_CAP


def _item_quality(it: dict) -> tuple[float, float, float, float]:
    """Per-item ADOS quality on four 0..1 axes.

    goal/archetype_fields are fill signals (presence, fractional coverage);
    objectives/requirements are graded by depth so a fuller, more reasoned set
    scores higher than a single token entry."""
    return (
        1.0 if (it.get("goal") or "").strip() else 0.0,
        _depth(it.get("objectives")),
        _depth(it.get("requirements")),
        _af_fill(it),
    )


def _item_success(it: dict) -> bool:
    """Did the LLM actually produce this record (vs. a deterministic-prior
    fallback)? Reads the honest-failure flag written by summarize.py (FR-B5).
    Legacy outputs without the flag fall back to a content heuristic so older
    runs still rank, but never let a fallback inflate depth-on-success."""
    v = it.get("llm_ok")
    if isinstance(v, bool):
        return v
    cs = it.get("classification_source")
    if cs == "deterministic_prior":
        return False
    if cs == "llm":
        return True
    # Legacy fallback (no flag present): treat as a success only if it carries
    # LLM-authored prose, since a pure fallback leaves goal+objectives empty.
    return bool((it.get("goal") or "").strip()) or bool(it.get("objectives"))


def _item_schema_valid(it: dict) -> bool:
    """Did the model emit clean, schema-shaped JSON (no coercion needed)?
    Reads the flag from summarize.py; legacy outputs fall back to success."""
    v = it.get("schema_valid")
    if isinstance(v, bool):
        return v
    return _item_success(it)


def _item_depth(it: dict) -> float:
    """Mean of the four 0..1 fill/depth axes for one item."""
    return sum(_item_quality(it)) / 4.0


def _item_class(it: dict) -> tuple[str | None, str | None]:
    """(primary_archetype.id, primary_domain_pair.domain) for correctness."""
    pa = (it.get("primary_archetype") or {}).get("id") or None
    dom = (it.get("primary_domain_pair") or {}).get("domain") or None
    return pa, dom


# Difficulty tier -> weight for difficulty-weighted IQ (ontology/difficulty.json).
TIER_WEIGHT = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}


def _item_verifiability(it: dict) -> str | None:
    return it.get("verifiability_class") or None


def _item_cognitive(it: dict) -> str | None:
    return it.get("cognitive_type") or None


def _item_tier(it: dict) -> str | None:
    return (it.get("difficulty") or {}).get("tier") or None


def _iq_and_breakdowns(items: list[dict], ref_idx: dict
                       ) -> tuple[float | None, dict, dict] | None:
    """§4 IQ: difficulty-weighted, reliability-gated accuracy vs the etalon over
    objective+rubric items (SUBJECTIVE items excluded), plus per-skill and
    per-difficulty accuracy (Q4/Q6/Q7). Returns None when the items carry no eval
    facets (legacy runs) so the headline stays the flat accuracy_pct."""
    if not ref_idx:
        return None
    num = den = 0.0
    by_skill: dict[str, list[int]] = {}
    by_diff: dict[str, list[int]] = {}
    has_facets = False
    for it in items:
        if not _item_success(it):
            continue
        slug = it.get("slug")
        if slug not in ref_idx:
            continue
        v, tier, cog = _item_verifiability(it), _item_tier(it), _item_cognitive(it)
        if v or tier or cog:
            has_facets = True
        if v == "subjective":
            continue  # no defensible key — excluded from IQ (reported as pref%)
        correct = 1 if _item_class(it) == ref_idx[slug] else 0
        w = TIER_WEIGHT.get(tier, 1)
        num += w * correct
        den += w
        if cog:
            s = by_skill.setdefault(cog, [0, 0])
            s[0] += correct
            s[1] += 1
        if tier:
            d = by_diff.setdefault(tier, [0, 0])
            d[0] += correct
            d[1] += 1
    if not has_facets:
        return None
    iq = round(num / den * 100, 0) if den else None
    skill_pct = {k: round(c / t * 100, 0) for k, (c, t) in by_skill.items() if t}
    diff_pct = {k: round(c / t * 100, 0) for k, (c, t) in by_diff.items() if t}
    return iq, skill_pct, diff_pct


def resolve_ref_path(spec: str) -> str:
    """Resolve a correctness reference: 'ref=<file|run-label>' or a bare path."""
    raw = spec.split("=", 1)[1] if spec.startswith("ref=") else spec
    expanded = os.path.expanduser(raw)
    if os.path.isfile(expanded):
        return expanded
    cand = paths.reconstructed_json(run_label=paths.resolve_run_label(raw))
    return cand if os.path.isfile(cand) else expanded


def build_ref_index(path: str) -> dict[str, tuple[str | None, str | None]]:
    """Map slug -> (archetype, domain) over the reference run's COMPLETED,
    classified items. This is the answer key for accuracy% (FR-B3)."""
    idx: dict[str, tuple[str | None, str | None]] = {}
    try:
        _doc, items = _load_output(path)
    except (OSError, json.JSONDecodeError) as e:
        sys.stderr.write(f"[warn] reference not loaded {path}: {e}\n")
        return idx
    for it in items:
        if not _item_success(it):
            continue
        slug = it.get("slug")
        pa, dom = _item_class(it)
        if slug and pa and dom:
            idx[slug] = (pa, dom)
    return idx


def _accuracy(items: list[dict],
              ref_idx: dict[str, tuple[str | None, str | None]]
              ) -> tuple[float | None, int]:
    """Accuracy = fraction of the candidate's COMPLETED items whose
    (archetype, domain) matches the reference key, over slugs both classified.
    Distinct from depth: a fully-filled record can still be wrong (FR-B3)."""
    if not ref_idx:
        return None, 0
    comparable = matches = 0
    for it in items:
        if not _item_success(it):
            continue
        slug = it.get("slug")
        if slug not in ref_idx:
            continue
        comparable += 1
        if _item_class(it) == ref_idx[slug]:
            matches += 1
    return (matches / comparable if comparable else None), comparable


def _quality_row(model: str, items: list[dict], n_items: int,
                 ref_idx: dict | None = None) -> dict:
    """Quality row keeping reliability, depth, and schema-validity SEPARATE.

    completion%      = LLM_OK / all items (reliability)
    depth-on-success = mean fill/depth over completed items ONLY (failures
                       excluded, never scored as zero) — closes the artifact in
                       AI_MODEL_TESTS.md §3.5
    schema-valid%    = clean schema-shaped JSON rate over all items
    The four fill axes (goal/obj/req/af) are reported over completed items too.
    These are never blended into a single rank key (FR-B2)."""
    n = len(items) or 1
    success = [it for it in items if _item_success(it)]
    ns = len(success) or 1
    g = sum(_item_quality(it)[0] for it in success) / ns
    o = sum(_item_quality(it)[1] for it in success) / ns
    r = sum(_item_quality(it)[2] for it in success) / ns
    a = sum(_item_quality(it)[3] for it in success) / ns
    depth_on_success = (g + o + r + a) / 4 if success else 0.0
    completion = len(success) / n
    schema_valid = sum(1 for it in items if _item_schema_valid(it)) / n
    row = {
        "model": model,
        "completion_pct": round(completion * 100, 0),
        "depth_on_success_pct": round(depth_on_success * 100, 0),
        "schema_valid_pct": round(schema_valid * 100, 0),
        "goal_pct": round(g * 100, 0),
        "objectives_pct": round(o * 100, 0),
        "requirements_pct": round(r * 100, 0),
        "archetype_fields_pct": round(a * 100, 0),
        "completed": len(success),
        "n_items": n_items,
    }
    if ref_idx is not None:
        acc, comparable = _accuracy(items, ref_idx)
        row["accuracy_pct"] = round(acc * 100, 0) if acc is not None else None
        row["accuracy_n"] = comparable
        iqres = _iq_and_breakdowns(items, ref_idx)
        if iqres is not None:
            iq, skill_pct, diff_pct = iqres
            if iq is not None:
                row["iq"] = iq
            if skill_pct:
                row["accuracy_by_skill"] = skill_pct
            if diff_pct:
                row["accuracy_by_difficulty"] = diff_pct
    return row


def _sort_quality(rows: list[dict]) -> None:
    """Order for display only. Reliability first, then depth-on-success, then
    schema-validity — this is a presentation order, NOT a single blended rank
    key (FR-B2 forbids collapsing the axes into one score)."""
    rows.sort(key=lambda r: (r["completion_pct"], r["depth_on_success_pct"],
                             r["schema_valid_pct"]), reverse=True)


def aggregate_quality_by_model(paths_in: list[str],
                               ref_idx: dict | None = None) -> list[dict]:
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
                bucket[slug] = it
    rows = [_quality_row(m, list(s.values()), len(s), ref_idx)
            for m, s in by_model.items()]
    _sort_quality(rows)
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


def collect_quality(specs: list[str], ref_idx: dict | None = None) -> list[dict]:
    """Each spec is PATH or LABEL=PATH; one completeness row per output file."""
    rows = []
    for spec in specs:
        label, _, path = spec.partition("=") if "=" in spec else ("", "", spec)
        try:
            doc, items = _load_output(path)
        except (OSError, json.JSONDecodeError) as e:
            sys.stderr.write(f"[warn] skip {path}: {e}\n")
            continue
        row = _quality_row(label or _doc_label(doc, path), items, len(items),
                           ref_idx)
        row["path"] = os.path.expanduser(path)
        rows.append(row)
    _sort_quality(rows)
    return rows


def _render_breakdown(rows: list[dict], field: str, title: str,
                      order: list[str] | None = None) -> str:
    """Render a model x cell accuracy table from a per-row {cell: pct} field
    (accuracy_by_skill / accuracy_by_difficulty). Empty when no row carries it."""
    cells: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in (r.get(field) or {}):
            if k not in seen:
                seen.add(k)
                cells.append(k)
    if not cells:
        return ""
    cells = ([c for c in (order or []) if c in seen]
             + [c for c in cells if not order or c not in order])
    out = ["", title, ""]
    out.append(f"{'model':28s} " + " ".join(f"{c[:9]:>9}" for c in cells))
    for r in rows:
        data = r.get(field) or {}
        if not data:
            continue
        line = f"{r['model']:28s} " + " ".join(
            (f"{data[c]:>8.0f}%" if c in data else f"{'—':>9}") for c in cells)
        out.append(line)
    return "\n".join(out) + "\n"


def render_quality(rows: list[dict], by_skill: bool = False,
                   by_difficulty: bool = False) -> str:
    if not rows:
        return "No output files with items found.\n"
    has_acc = any(r.get("accuracy_pct") is not None for r in rows)
    has_iq = any(r.get("iq") is not None for r in rows)
    out = ["QUALITY — reliability, depth-on-success, schema-validity"
           + (", accuracy" if has_acc else "")
           + (", TWA" if has_iq else "")
           + " (reported SEPARATELY, never blended)", ""]
    acc_hdr = f" {'acc%':>6}" if has_acc else ""
    iq_hdr = f" {'TWA':>5}" if has_iq else ""
    out.append(f"{'rank':>4}  {'model':28s} {'compl%':>7} {'depth*':>7} "
               f"{'json%':>6}{acc_hdr}{iq_hdr} {'goal':>5} {'obj':>5} {'req':>5} "
               f"{'af':>5} {'done':>9}")
    for i, r in enumerate(rows, 1):
        acc_cell = ""
        if has_acc:
            av = r.get("accuracy_pct")
            acc_cell = f" {av:>5.0f}%" if av is not None else f" {'—':>6}"
        iq_cell = ""
        if has_iq:
            iv = r.get("iq")
            iq_cell = f" {iv:>5.0f}" if iv is not None else f" {'—':>5}"
        out.append(f"{i:>4}  {r['model']:28s} {r['completion_pct']:>6.0f}% "
                   f"{r['depth_on_success_pct']:>6.0f}% {r['schema_valid_pct']:>5.0f}%"
                   f"{acc_cell}{iq_cell} {r['goal_pct']:>5.0f} {r['objectives_pct']:>5.0f} "
                   f"{r['requirements_pct']:>5.0f} {r['archetype_fields_pct']:>5.0f} "
                   f"{r['completed']:>4}/{r['n_items']:<4}")
    out += ["",
            "compl% = completion = LLM_OK / all items (reliability; NOT blended "
            "into depth)",
            "depth* = depth-on-success = mean(goal,obj,req,af) over COMPLETED "
            "items only (failures excluded, never scored 0 — see "
            "AI_MODEL_TESTS.md §3.5)",
            "json%  = clean schema-shaped JSON rate (coder-model strength; "
            "distinct from reliability)"]
    if has_acc:
        out.append("acc%   = correctness vs the reference run "
                   "(archetype+domain match over shared completed items; "
                   "depth ≠ accuracy)")
    if has_iq:
        out.append("TWA    = task-weighted accuracy: difficulty-weighted accuracy "
                   "over objective+rubric items (subjective excluded; tier weight "
                   "T1..T4 = 1..4). NOT an intelligence score.")
    out += ["goal/obj/req/af = the four depth axes over completed items "
            "(obj/req capped at 3); done = completed/total"]
    body = "\n".join(out) + "\n"
    if by_skill:
        body += _render_breakdown(rows, "accuracy_by_skill",
                                  "ACCURACY BY COGNITIVE SKILL — per skill (Q7)")
    if by_difficulty:
        body += _render_breakdown(rows, "accuracy_by_difficulty",
                                  "ACCURACY BY DIFFICULTY — per tier (Q6)",
                                  order=["T1", "T2", "T3", "T4"])
    return body


# ---------------------------------------------------------------------------
# gpu — auxiliary GPU-telemetry table from the generated benchmark files
# ---------------------------------------------------------------------------
def _gen_path(name: str) -> str:
    return os.path.join(ROOT, "config", "generated", name)


def collect_gpu(model_bench: str | None = None,
                embed_bench: str | None = None) -> list[dict]:
    """Flatten GPU telemetry from the generated benchmark files into table rows.

    Reads gpu-telemetry-summary/1 blocks from config/generated/model_benchmarks.json
    (generation sweep) and embed_benchmarks.json (embedding sweep). Rows whose run
    captured no telemetry (cloud, or legacy back-filled) carry None metrics so the
    renderer shows '—' honestly rather than a fabricated 0."""
    rows: list[dict] = []

    def _row(workload: str, label: str, gpu: dict | None, per_item: float | None,
             per_item_label: str) -> dict:
        g = gpu if isinstance(gpu, dict) and gpu.get("available") else None

        def _s(field, key):
            return (g or {}).get(field, {}).get(key) if g else None
        return {"workload": workload, "label": label,
                "avg_w": _s("power_w", "avg"), "peak_w": _s("power_w", "peak"),
                "peak_temp_c": _s("temp_c", "peak"),
                "avg_util_pct": _s("util_gpu_pct", "avg"),
                "peak_vram_mib": _s("mem_used_mib", "peak"),
                "peak_clock_mhz": _s("clock_sm_mhz", "peak"),
                "energy_wh": (g or {}).get("energy_wh") if g else None,
                "per_item": per_item, "per_item_label": per_item_label,
                "throttled": (g or {}).get("throttled") if g else None}

    mb = model_bench or _gen_path("model_benchmarks.json")
    if os.path.isfile(mb):
        try:
            doc = json.load(open(mb, encoding="utf-8"))
            for key, r in sorted(doc.get("models", {}).items()):
                rows.append(_row("gen", key, r.get("gpu"),
                                 r.get("wh_per_item"), "Wh/item"))
        except (OSError, ValueError):
            pass
    eb = embed_bench or _gen_path("embed_benchmarks.json")
    if os.path.isfile(eb):
        try:
            doc = json.load(open(eb, encoding="utf-8"))
            for key, r in sorted(doc.get("models", {}).items()):
                rows.append(_row("embed", key, r.get("gpu"),
                                 r.get("wh_per_1k"), "Wh/1k"))
        except (OSError, ValueError):
            pass
    return rows


def render_gpu(rows: list[dict]) -> str:
    if not rows:
        return ("No GPU telemetry found. Run a metered sweep "
                "(`gpt benchmark --meter-power` or `gpt embed-eval`).\n")

    def _c(v, fmt="{:>6.0f}"):
        return fmt.format(v) if isinstance(v, (int, float)) else f"{'—':>6}"
    out = ["GPU TELEMETRY — measured per run (— = no telemetry captured)", ""]
    hdr = (f"{'workload':8} {'model / variant':28} {'avgW':>6} {'pkW':>6} "
           f"{'pkC':>6} {'util%':>6} {'pkVRAM':>7} {'pkClk':>6} {'Wh':>7} "
           f"{'per-item':>9} {'thr':>4}")
    out.append(hdr)
    out.append("-" * len(hdr))
    for r in rows:
        thr = "yes" if r["throttled"] else ("no" if r["throttled"] is False else "—")
        out.append(
            f"{r['workload']:8} {r['label']:28.28} {_c(r['avg_w'])} "
            f"{_c(r['peak_w'])} {_c(r['peak_temp_c'])} {_c(r['avg_util_pct'])} "
            f"{_c(r['peak_vram_mib'], '{:>7.0f}')} {_c(r['peak_clock_mhz'])} "
            f"{_c(r['energy_wh'], '{:>7.3f}')} "
            f"{_c(r['per_item'], '{:>9.4f}')} {thr:>4}")
    out += [
        "",
        "avgW/pkW  = mean / peak board power draw, watts (nvidia-smi power.draw)",
        "pkC       = peak core temperature, Celsius (throttle band >= 83C)",
        "util%     = mean GPU compute utilization (utilization.gpu)",
        "pkVRAM    = peak VRAM used, MiB (memory.used)",
        "pkClk     = peak SM clock, MHz (clocks.sm)",
        "Wh        = measured energy over the run (integral of power.draw)",
        "per-item  = Wh/item (gen) or Wh per 1,000 chunks (embed)",
        "thr       = did peak temp reach the thermal-throttle band",
    ]
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
    p_qual.add_argument("--correctness", metavar="ref=<file|run-label>",
                        default=None,
                        help="Add an accuracy%% column: adjudicate each model's "
                             "classification against a REFERENCE run (e.g. "
                             "'ref=cmp-codex' or 'ref=path.json'). Depth ≠ "
                             "accuracy (FR-B3).")
    p_qual.add_argument("--by-skill", action="store_true",
                        help="Add an accuracy-per-cognitive-skill breakdown (Q7); "
                             "needs runs classified with the eval facets.")
    p_qual.add_argument("--by-difficulty", action="store_true",
                        help="Add an accuracy-per-difficulty-tier breakdown (Q6).")
    p_qual.add_argument("--json", action="store_true")

    p_gpu = sub.add_parser("gpu", help="GPU telemetry table from the generated "
                                       "benchmark files (power/temp/util/VRAM/Wh).")
    p_gpu.add_argument("--model-bench", default=None,
                       help="Path to model_benchmarks.json (default: generated).")
    p_gpu.add_argument("--embed-bench", default=None,
                       help="Path to embed_benchmarks.json (default: generated).")
    p_gpu.add_argument("--json", action="store_true")

    args = ap.parse_args(argv)

    # Geometry guard: refuse to render a column that isn't bound to a declared
    # Project Coordinate, so the separated axes can't silently re-blend.
    assert_columns_declared()

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
        ref_idx = None
        if args.correctness:
            ref_path = resolve_ref_path(args.correctness)
            ref_idx = build_ref_index(ref_path)
            sys.stderr.write(f"[note] correctness reference: {ref_path} "
                             f"({len(ref_idx)} classified items)\n")
        rows = collect_quality(specs, ref_idx)
        print(json.dumps(rows, indent=2) if args.json
              else render_quality(rows, by_skill=args.by_skill,
                                  by_difficulty=args.by_difficulty), end="")
        return 0
    if args.cmd == "gpu":
        rows = collect_gpu(args.model_bench, args.embed_bench)
        print(json.dumps(rows, indent=2) if args.json else render_gpu(rows),
              end="")
        return 0
    ap.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "gpt metrics"))
