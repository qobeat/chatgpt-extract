#!/usr/bin/env python3
"""
compare_runs.py — head-to-head quality comparison of two AI-summary runs over
the SAME projects (e.g. ollama vs codex).

Each side is a reconstructed_projects.json (new ADOS items[] schema; a legacy
projects[] doc is also accepted and normalized). Items are joined on `slug`, so
the comparison is restricted to projects both runs covered.

Two kinds of metric:
  - Prose quality (both runs authored these): goal/objectives/requirements fill,
    description length, archetype-field coverage. This is the real provider vs
    provider signal.
  - Classification agreement: how often the two runs agree on primary archetype
    and domain. NOTE: if a side's items are tagged classification_source=
    "deterministic_prior" (e.g. the ported legacy ollama run, which never had an
    LLM classify), its archetype/domain is the prior — so agreement there means
    "the other run kept the prior", not an LLM-vs-LLM classification match.

Usage:
  python scripts/compare_runs.py A B [--names ollama codex] [--out report.md] [--json]
  # A/B may be a file path, a run-label, or 'flat' for the default (unlabeled) run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import paths  # noqa: E402


def _nonempty(v) -> bool:
    return (isinstance(v, str) and bool(v.strip())) or (isinstance(v, list) and bool(v))


def resolve_doc_path(arg: str) -> str:
    """Accept a file path, a run-label, or 'flat'/'default' (unlabeled run)."""
    expanded = os.path.expanduser(arg)
    if os.path.isfile(expanded):
        return expanded
    if arg in ("flat", "default", "-"):
        return paths.reconstructed_json(run_label=None)
    cand = paths.reconstructed_json(run_label=paths.resolve_run_label(arg))
    return cand if os.path.isfile(cand) else expanded


def _normalize_item(it: dict, legacy: bool) -> dict:
    """Project either schema onto the fields the comparison needs."""
    if legacy:
        objectives = it.get("objectives") or []
        af = {k: it.get(k, "") for k in
              ("quickstart", "how_to_use", "how_to_update", "use_case")}
        return {
            "slug": it.get("slug"),
            "archetype": None,
            "domain": None,
            "goal": it.get("goal", "") or "",
            "n_objectives": len([o for o in objectives if _nonempty(o)]),
            "n_requirements": len(it.get("requirements") or []),
            "desc_len": len(it.get("description", "") or ""),
            "af_fill": _af_fill(af),
            "classification_source": "none",
        }
    pa = it.get("primary_archetype") or {}
    pdp = it.get("primary_domain_pair") or {}
    return {
        "slug": it.get("slug"),
        "archetype": pa.get("id") or None,
        "domain": pdp.get("domain") or None,
        "goal": it.get("goal", "") or "",
        "n_objectives": len(it.get("objectives") or []),
        "n_requirements": len(it.get("requirements") or []),
        "desc_len": len(it.get("description", "") or ""),
        "af_fill": _af_fill(it.get("archetype_fields") or {}),
        "classification_source": it.get("classification_source") or "llm",
    }


def _af_fill(af: dict) -> float:
    if not af:
        return 0.0
    filled = sum(1 for v in af.values() if _nonempty(v))
    return filled / len(af)


def load_doc(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        doc = json.load(f)
    legacy = "items" not in doc and "projects" in doc
    raw = doc.get("items") if not legacy else doc.get("projects")
    items = [_normalize_item(it, legacy) for it in (raw or []) if it.get("slug")]
    name = doc.get("provider") or (doc.get("generated_by") or "?").split(":")[0]
    return {
        "path": path,
        "name": name,
        "generated_by": doc.get("generated_by", "?"),
        "schema": "legacy projects[]" if legacy else "items[]",
        "classification_source": doc.get("classification_source")
        or (items[0]["classification_source"] if items else "llm"),
        "by_slug": {it["slug"]: it for it in items},
        "items": items,
    }


def _side_metrics(items: list[dict]) -> dict:
    n = len(items) or 1
    classified = sum(1 for it in items
                     if it["archetype"] and it["domain"] and it["goal"].strip())
    return {
        "n": len(items),
        "classified_rate": classified / n,
        "goal_fill": sum(1 for it in items if it["goal"].strip()) / n,
        "objectives_fill": sum(1 for it in items if it["n_objectives"]) / n,
        "requirements_fill": sum(1 for it in items if it["n_requirements"]) / n,
        "avg_objectives": sum(it["n_objectives"] for it in items) / n,
        "avg_desc_len": sum(it["desc_len"] for it in items) / n,
        "af_fill": sum(it["af_fill"] for it in items) / n,
    }


def compare(a: dict, b: dict, max_diffs: int) -> dict:
    overlap = sorted(set(a["by_slug"]) & set(b["by_slug"]))
    both_classified = [s for s in overlap
                       if a["by_slug"][s]["archetype"] and b["by_slug"][s]["archetype"]]
    arch_agree = sum(1 for s in both_classified
                     if a["by_slug"][s]["archetype"] == b["by_slug"][s]["archetype"])
    dom_agree = sum(1 for s in overlap
                    if a["by_slug"][s]["domain"]
                    and a["by_slug"][s]["domain"] == b["by_slug"][s]["domain"])
    diffs = [
        {"slug": s,
         "a_archetype": a["by_slug"][s]["archetype"],
         "b_archetype": b["by_slug"][s]["archetype"]}
        for s in both_classified
        if a["by_slug"][s]["archetype"] != b["by_slug"][s]["archetype"]
    ]
    # Prose head-to-head over the overlap only.
    a_over = [a["by_slug"][s] for s in overlap]
    b_over = [b["by_slug"][s] for s in overlap]
    goal_both = sum(1 for s in overlap
                    if a["by_slug"][s]["goal"].strip() and b["by_slug"][s]["goal"].strip())
    goal_a_only = sum(1 for s in overlap
                      if a["by_slug"][s]["goal"].strip() and not b["by_slug"][s]["goal"].strip())
    goal_b_only = sum(1 for s in overlap
                      if b["by_slug"][s]["goal"].strip() and not a["by_slug"][s]["goal"].strip())
    n_over = len(overlap) or 1
    return {
        "n_overlap": len(overlap),
        "n_a_only": len(set(a["by_slug"]) - set(b["by_slug"])),
        "n_b_only": len(set(b["by_slug"]) - set(a["by_slug"])),
        "archetype_agree_rate": (arch_agree / len(both_classified)) if both_classified else None,
        "n_both_classified": len(both_classified),
        "domain_agree_rate": (dom_agree / n_over),
        "goal_both": goal_both,
        "goal_a_only": goal_a_only,
        "goal_b_only": goal_b_only,
        "goal_neither": len(overlap) - goal_both - goal_a_only - goal_b_only,
        "side_a_overlap": _side_metrics(a_over),
        "side_b_overlap": _side_metrics(b_over),
        "archetype_diffs": diffs[:max_diffs],
        "n_archetype_diffs": len(diffs),
    }


def _pct(x) -> str:
    return f"{x:.0%}" if isinstance(x, (int, float)) else "n/a"


def render_report(a: dict, b: dict, na: str, nb: str, c: dict) -> str:
    sa, sb = c["side_a_overlap"], c["side_b_overlap"]
    prior_note = ""
    for nm, side in ((na, a), (nb, b)):
        if side["classification_source"] == "deterministic_prior":
            prior_note += (
                f"\n> **{nm}** classification is the *deterministic prior* "
                f"(the {nm} run never had an LLM classify), so archetype/domain "
                f"agreement below reflects how often **{nb if nm == na else na}** "
                f"kept that prior — not an LLM-vs-LLM match.\n")
    lines = [
        f"# Run comparison — {na} vs {nb}",
        "",
        f"- **{na}**: `{a['generated_by']}` · {a['schema']} · {sa['n']} items · `{a['path']}`",
        f"- **{nb}**: `{b['generated_by']}` · {b['schema']} · {sb['n']} items · `{b['path']}`",
        f"- **Joined on slug:** {c['n_overlap']} shared "
        f"(only {na}: {c['n_a_only']} · only {nb}: {c['n_b_only']})",
        prior_note,
        "## Prose quality (over shared projects — both runs authored these)",
        "",
        f"| Metric | {na} | {nb} |",
        "|---|---|---|",
        f"| Goal filled | {_pct(sa['goal_fill'])} | {_pct(sb['goal_fill'])} |",
        f"| Objectives filled | {_pct(sa['objectives_fill'])} | {_pct(sb['objectives_fill'])} |",
        f"| Avg objectives / item | {sa['avg_objectives']:.1f} | {sb['avg_objectives']:.1f} |",
        f"| Requirements filled | {_pct(sa['requirements_fill'])} | {_pct(sb['requirements_fill'])} |",
        f"| Archetype-field coverage | {_pct(sa['af_fill'])} | {_pct(sb['af_fill'])} |",
        f"| Avg description chars | {sa['avg_desc_len']:.0f} | {sb['avg_desc_len']:.0f} |",
        f"| ADOS-classified (arch+domain+goal) | {_pct(sa['classified_rate'])} | {_pct(sb['classified_rate'])} |",
        "",
        f"**Goal coverage:** both {c['goal_both']} · only {na} {c['goal_a_only']} · "
        f"only {nb} {c['goal_b_only']} · neither {c['goal_neither']}",
        "",
        "## Classification agreement (shared projects)",
        "",
        f"- **Primary archetype agree:** {_pct(c['archetype_agree_rate'])} "
        f"({c['n_both_classified']} comparable)",
        f"- **Primary domain agree:** {_pct(c['domain_agree_rate'])}",
        f"- **Archetype disagreements:** {c['n_archetype_diffs']}",
        "",
    ]
    if c["archetype_diffs"]:
        lines += [
            f"### Top archetype disagreements (slug — {na} → {nb})",
            "",
            f"| slug | {na} | {nb} |",
            "|---|---|---|",
        ]
        lines += [f"| {d['slug']} | {d['a_archetype']} | {d['b_archetype']} |"
                  for d in c["archetype_diffs"]]
        lines.append("")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare two AI-summary runs over the same projects.")
    ap.add_argument("a", help="Run A: file path, run-label, or 'flat'.")
    ap.add_argument("b", help="Run B: file path, run-label, or 'flat'.")
    ap.add_argument("--names", nargs=2, metavar=("A", "B"), default=None,
                    help="Display names (default: provider from each doc).")
    ap.add_argument("--out", default=None,
                    help="Markdown report path (default: under data root / comparisons).")
    ap.add_argument("--max-diffs", type=int, default=25,
                    help="Max archetype-disagreement rows in the report.")
    ap.add_argument("--json", action="store_true",
                    help="Print the comparison as JSON to stdout (no report file).")
    args = ap.parse_args()

    pa, pb = resolve_doc_path(args.a), resolve_doc_path(args.b)
    for p in (pa, pb):
        if not os.path.isfile(p):
            sys.stderr.write(f"[!] Not found: {p}\n")
            return 1
    a, b = load_doc(pa), load_doc(pb)
    na, nb = (args.names if args.names else (a["name"], b["name"]))
    if na == nb:
        na, nb = f"{na}-A", f"{nb}-B"

    c = compare(a, b, args.max_diffs)

    if args.json:
        print(json.dumps({"a": a["generated_by"], "b": b["generated_by"],
                          "names": [na, nb], **c}, ensure_ascii=False, indent=2,
                         default=str))
        return 0

    report = render_report(a, b, na, nb, c)
    out = args.out
    if not out:
        base = paths.data_root() or os.path.join(ROOT, "output")
        out = os.path.join(base, "comparisons", f"{na}-vs-{nb}.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(report)

    # Console digest.
    sys.stderr.write(report)
    sys.stderr.write(f"\n[compare] Report written: {out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
