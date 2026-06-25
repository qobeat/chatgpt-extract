#!/usr/bin/env python3
"""
port_legacy.py  (ONE-TIME migration — not part of the supported pipeline)

Convert a legacy chatgpt-project-reconstructor run (the old `projects[]` schema,
ollama-summarized) into the new ADOS `items[]` schema so it can be read by `gpt`
and compared head-to-head against a current run with `gpt compare`.

What carries over verbatim (ollama-authored prose):
  goal, objectives, requirements, requirements_evolution, and the old
  software-project fields quickstart / how_to_use / how_to_update / use_case
  (mapped into archetype_fields).

What is *synthesized*: the legacy run never produced an ADOS classification, so
each ported item gets the deterministic prior (classify_cluster) as its
primary_archetype / primary_domain_pair and is tagged
`classification_source: "deterministic_prior"`. Treat archetype/domain on the
ollama side as a prior, NOT an ollama judgement (see `gpt compare` notes).

Usage (run once, then the old repo can be deleted):
  python scripts/port_legacy.py \
    --legacy-dir ../chatgpt-project-reconstructor/output/runs/legacy-20260622 \
    --out ~/chatgpt-reconstructor-data/runs/ollama-legacy/reconstructed_projects.json
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
import ulog  # noqa: E402
from classify import load_ontology, classify_cluster  # noqa: E402
from summarize import build_item  # noqa: E402
from trace import sha256_text, write_json, validate_with_jsonschema  # noqa: E402

# Legacy software-project fields -> archetype_fields keys (same names; merged in
# only when the chosen archetype's contract actually declares them).
_LEGACY_AF_KEYS = ("quickstart", "how_to_use", "how_to_update", "use_case")


def _load_clusters_by_slug(legacy_dir: str) -> dict[str, dict]:
    path = os.path.join(legacy_dir, "store", "clusters.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        clusters = json.load(f)
    return {c.get("slug"): c for c in clusters if c.get("slug")}


def _cluster_for(project: dict, clusters: dict[str, dict]) -> dict:
    """Prefer the real legacy cluster (has titles/signals for the prior); else
    synthesize a minimal one from the project record's deterministic facts."""
    slug = project.get("slug")
    cluster = dict(clusters.get(slug) or {})
    cluster.setdefault("slug", slug)
    # The clusters store uses member_ids; legacy projects use source_conversation_ids.
    cluster.setdefault("member_ids", project.get("source_conversation_ids", []))
    for k in ("start_date", "end_date", "n_conversations", "n_versions",
              "version_zip_files", "file_artifacts"):
        if k in project and k not in cluster:
            cluster[k] = project[k]
    return cluster


def _norm_objectives(raw: list) -> list[dict]:
    """Legacy objectives are bare strings; the ADOS schema wants {text, role}."""
    out = []
    for o in raw or []:
        if isinstance(o, dict):
            if o.get("text"):
                out.append(o)
        elif isinstance(o, str) and o.strip():
            out.append({"text": o})
    return out


def _norm_req_evolution(raw: list) -> list[dict]:
    out = []
    for r in raw or []:
        if isinstance(r, dict) and r.get("change"):
            out.append({"date": r.get("date"), "change": r["change"]})
        elif isinstance(r, str) and r.strip():
            out.append({"date": None, "change": r})
    return out


def _parsed_from_legacy(project: dict) -> dict:
    """Shape the ollama-authored legacy fields like an LLM response so build_item
    can merge deterministic facts over them exactly as it does for live runs."""
    af = {k: project.get(k, "") for k in _LEGACY_AF_KEYS}
    return {
        "title": project.get("project_name") or project.get("slug"),
        "description": project.get("description", ""),
        "is_durable_project": (project.get("n_versions", 0) or 0) >= 1,
        # Leave classification empty -> build_item falls back to the prior.
        "primary_archetype": {},
        "secondary_archetypes": [],
        "primary_domain_pair": {},
        "secondary_domain_pairs": [],
        "confidence": 0.0,
        "goal": project.get("goal", ""),
        "objectives": _norm_objectives(project.get("objectives")),
        "requirements": [r for r in (project.get("requirements") or [])
                         if isinstance(r, str) and r.strip()],
        "requirements_evolution": _norm_req_evolution(
            project.get("requirements_evolution")),
        "deliveries": [],
        "archetype_fields": af,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="One-time: port a legacy projects[] run into the new "
                    "ADOS items[] schema.")
    ap.add_argument("--legacy-dir", required=True,
                    help="Legacy run dir with reconstructed_projects.json + "
                         "store/ + bundles/.")
    ap.add_argument("--out", required=True,
                    help="Destination reconstructed_projects.json (items[]).")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    ulog.set_stage("Port")
    legacy_dir = os.path.expanduser(args.legacy_dir)
    out_path = os.path.expanduser(args.out)
    bundles_dir = os.path.join(legacy_dir, "bundles")

    legacy_json = os.path.join(legacy_dir, "reconstructed_projects.json")
    try:
        with open(legacy_json, encoding="utf-8") as f:
            legacy = json.load(f)
    except OSError as e:
        ulog.err("READ", legacy_json, error=e)
        return 1

    projects = legacy.get("projects")
    if projects is None:
        ulog.err("READ", legacy_json,
                 error="not a legacy projects[] document (no 'projects' key)")
        return 1

    generated_by = legacy.get("generated_by") or "ollama:unknown"
    provider, _, model = generated_by.partition(":")
    provider = provider or "ollama"
    model = model or "*"

    ontology = load_ontology()
    ontology_version = ontology["archetypes"].get("version", "?")
    clusters = _load_clusters_by_slug(legacy_dir)
    ulog.log("READ", legacy_json,
             status=f"{len(projects)} legacy projects · {generated_by}")

    items: list[dict] = []
    for project in projects:
        slug = project.get("slug")
        if not slug:
            continue
        cluster = _cluster_for(project, clusters)
        cluster["classify_prior"] = classify_cluster(cluster)

        bhash = ""
        bpath = os.path.join(bundles_dir, f"{slug}.md")
        if os.path.exists(bpath):
            with open(bpath, encoding="utf-8") as f:
                bhash = sha256_text(f.read())

        item = build_item(cluster, _parsed_from_legacy(project), ontology,
                           provider, model, bhash, 0.0)
        item["classification_source"] = "deterministic_prior"
        items.append(item)

    result = {
        "generated_by": f"{generated_by} (ported to ADOS items[] schema)",
        "provider": provider,
        "model": model,
        "ontology_version": ontology_version,
        "ported_from": os.path.abspath(legacy_json),
        "classification_source": "deterministic_prior",
        "n_items": len(items),
        "n_failed": 0,
        "failed_slugs": [],
        "cost_usd": 0.0,
        "items": items,
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    write_json(out_path, result)
    ulog.log("WRITE", out_path, status=f"{len(items)} items")

    if not args.no_validate:
        schema_path = os.path.join(ROOT, "schema", "extracted_item_schema.json")
        ok, errors = validate_with_jsonschema(result, schema_path)
        if not ok:
            ulog.err("VALIDATE", out_path,
                     error=f"{len(errors)} schema issue(s): {errors[:5]}")
            return 2
        ulog.log("VALIDATE", out_path, status="schema OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(interrupt.run_cli(main, "port-legacy"))
