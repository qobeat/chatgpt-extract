#!/usr/bin/env python3
"""
recover_rollouts.py — rebuild a summarize output JSON from the Codex CLI's own
per-call rollout logs.

The codex provider runs one `codex exec` per item, and the CLI records each call
(prompt + model answer) under ~/.codex/sessions/<Y>/<M>/<D>/rollout-*.jsonl. A
summarize run that is killed before it finishes loses the items it held in memory
(older runs only write the output JSON at the very end) — but the answers are
still on disk in those rollouts. This tool reconstructs the completed items so a
killed run loses nothing; re-run `gpt summarize --resume` afterwards to finish.

Each recovered item is built exactly like a live run (deterministic facts merged
over the model output, archetype contract enforced) and carries the correct
`bundle_sha`, so `--resume` reuses it instead of re-calling the model.

Usage:
  python scripts/recover_rollouts.py --out ~/chatgpt-reconstructor-data/reconstructed_projects.json
  python scripts/recover_rollouts.py --sessions ~/.codex/sessions/2026/06/24 --after-min 90
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, HERE)

import ulog  # noqa: E402
import paths  # noqa: E402
from classify import load_ontology, classify_cluster  # noqa: E402
from summarize import build_item, parse_json_object  # noqa: E402
from trace import sha256_text, write_json, validate_with_jsonschema  # noqa: E402

_SLUG_RE = re.compile(r"reduced transcripts\) for slug '([^']+)'")


def _text_of(payload: dict) -> str:
    content = payload.get("content")
    if isinstance(content, list):
        return " ".join(s.get("text", "") for s in content
                        if isinstance(s, dict))
    return content if isinstance(content, str) else ""


def _extract(path: str) -> tuple[str, dict] | None:
    """Return (slug, parsed_answer) from one rollout file, or None."""
    try:
        rows = [json.loads(ln) for ln in open(path, encoding="utf-8") if ln.strip()]
    except (OSError, json.JSONDecodeError):
        return None
    slug = None
    answer = None
    for r in rows:
        if r.get("type") != "response_item":
            continue
        p = r.get("payload", {})
        txt = _text_of(p)
        if p.get("role") == "user":
            m = _SLUG_RE.search(txt)
            if m:
                slug = m.group(1)
        elif p.get("role") == "assistant" and txt.strip():
            answer = txt  # keep the last assistant message
    if not slug or not answer:
        return None
    parsed = parse_json_object(answer)
    return (slug, parsed) if parsed else None


def main() -> int:
    cfg = paths.load_config()
    default_sessions = os.path.expanduser(
        os.path.join("~/.codex/sessions", time.strftime("%Y/%m/%d")))

    ap = argparse.ArgumentParser(
        description="Rebuild a summarize output JSON from Codex rollout logs.")
    ap.add_argument("--sessions", default=default_sessions,
                    help=f"Rollout dir (default: {default_sessions}).")
    ap.add_argument("--store", default=None)
    ap.add_argument("--bundles", default=None)
    ap.add_argument("--out", default=None,
                    help="Destination reconstructed_projects.json (default: data root).")
    ap.add_argument("--model", default="*")
    ap.add_argument("--max-chars", type=int,
                    default=int(cfg.get("char_budget_per_bundle", 48000)))
    ap.add_argument("--after-min", type=int, default=0,
                    help="Only rollouts modified in the last N minutes (0 = all).")
    ap.add_argument("--no-validate", action="store_true")
    args = ap.parse_args()

    ulog.set_stage("Recover")
    store = paths.store_dir(args.store)
    bundles = paths.bundles_dir(args.bundles)
    out_path = args.out or paths.reconstructed_json()
    out_path = os.path.expanduser(out_path)

    ontology = load_ontology()
    ontology_version = ontology["archetypes"].get("version", "?")

    with open(os.path.join(store, "clusters.json"), encoding="utf-8") as f:
        clusters = {c["slug"]: c for c in json.load(f) if c.get("slug")}

    files = sorted(glob.glob(os.path.join(os.path.expanduser(args.sessions),
                                          "*.jsonl")),
                   key=os.path.getmtime)
    if args.after_min > 0:
        cutoff = time.time() - args.after_min * 60
        files = [f for f in files if os.path.getmtime(f) >= cutoff]
    ulog.log("SCAN", args.sessions, status=f"{len(files)} rollout files")

    recovered: dict[str, dict] = {}   # slug -> parsed answer (latest wins)
    for fp in files:
        got = _extract(fp)
        if got:
            recovered[got[0]] = got[1]

    items: list[dict] = []
    skipped_no_bundle = 0
    for slug, parsed in recovered.items():
        cluster = clusters.get(slug)
        if cluster is None:
            continue
        bpath = os.path.join(bundles, f"{slug}.md")
        if not os.path.exists(bpath):
            # Not part of this run's universe (summarize only processes bundled
            # clusters); likely a stale/earlier codex session. Skip.
            skipped_no_bundle += 1
            continue
        cluster.setdefault("classify_prior", classify_cluster(cluster))
        with open(bpath, encoding="utf-8") as f:
            bundle = f.read()
        truncated = bundle if len(bundle) <= args.max_chars else \
            bundle[:args.max_chars] + "\n[...truncated...]"
        bhash = sha256_text(truncated)
        items.append(build_item(cluster, parsed, ontology, "codex",
                                args.model, bhash, 0.0))

    items.sort(key=lambda it: it["slug"])
    result = {
        "generated_by": "codex: (recovered from ~/.codex rollout logs)",
        "provider": "codex",
        "model": args.model,
        "ontology_version": ontology_version,
        "recovered_from_rollouts": True,
        "n_items": len(items),
        "n_failed": 0,
        "failed_slugs": [],
        "cost_usd": 0.0,
        "items": items,
    }
    write_json(out_path, result)
    ulog.log("WRITE", out_path,
             status=f"{len(items)} recovered items"
                    + (f" ({skipped_no_bundle} stale/no-bundle skipped)"
                       if skipped_no_bundle else ""))

    if not args.no_validate:
        ok, errors = validate_with_jsonschema(
            result, os.path.join(ROOT, "schema", "extracted_item_schema.json"))
        if not ok:
            ulog.err("VALIDATE", out_path,
                     error=f"{len(errors)} schema issue(s): {errors[:5]}")
            return 2
        ulog.log("VALIDATE", out_path, status="schema OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
