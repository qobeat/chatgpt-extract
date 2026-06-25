#!/usr/bin/env python3
"""
export_public.py — sanitize the full reconstructed items JSON for GitHub.

Strips conversation provenance and raw signal internals, normalizes zip paths to
basenames, and optionally writes per-item markdown under published/projects/.
Operates on the ADOS-grounded extracted_item schema (items[]).

Usage:
  python scripts/export_public.py
  python scripts/export_public.py --md --review
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "lib"))
import paths  # noqa: E402
import confirm  # noqa: E402

STRIP_FIELDS = frozenset({
    "source_conversation_ids",
    "member_ids",
    "signal_summary",
    "bundle_sha",
    "cost_usd",
})

PII_PATTERNS = [
    (re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"), "email"),
    (re.compile(r"/Users/[^\s\"']+"), "macOS home path"),
    (re.compile(r"/mnt/c/Users/[^\s\"']+"), "Windows user path"),
    (re.compile(r"\\Users\\[^\s\"']+"), "Windows backslash path"),
    (re.compile(r"source_conversation_ids"), "conversation id field"),
]


def basename_only(name: str) -> str:
    return os.path.basename(name.replace("\\", "/"))


def sanitize_item(item: dict) -> dict:
    out = {k: v for k, v in item.items() if k not in STRIP_FIELDS}
    cleaned = []
    for z in out.get("version_zip_files") or []:
        if isinstance(z, dict):
            entry = dict(z)
            if "filename" in entry:
                entry["filename"] = basename_only(str(entry["filename"]))
            cleaned.append(entry)
        elif isinstance(z, str):
            cleaned.append({"filename": basename_only(z)})
    out["version_zip_files"] = cleaned
    return out


def sanitize_document(doc: dict) -> dict:
    items = [sanitize_item(p) for p in doc.get("items", [])]
    return {
        "generated_by": doc.get("generated_by", "export_public.py"),
        "provider": doc.get("provider"),
        "model": doc.get("model"),
        "ontology_version": doc.get("ontology_version"),
        "n_items": len(items),
        "items": items,
    }


def review_text(label: str, text: str) -> list[str]:
    findings = []
    for pattern, kind in PII_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(f"{label}: possible {kind}: {match.group()[:80]}")
    return findings


def review_document(doc: dict) -> list[str]:
    findings: list[str] = []
    findings.extend(review_text("document", json.dumps(doc, ensure_ascii=False)))
    for p in doc.get("items", []):
        slug = p.get("slug", "?")
        for field in ("goal", "description"):
            val = p.get(field)
            if isinstance(val, str) and val.strip():
                findings.extend(review_text(f"{slug}.{field}", val))
        for k, v in (p.get("archetype_fields") or {}).items():
            if isinstance(v, str) and v.strip():
                findings.extend(review_text(f"{slug}.archetype_fields.{k}", v))
    return findings


def _pair_str(pair: dict) -> str:
    if not pair:
        return "?"
    dom = pair.get("domain", "?")
    sub = pair.get("subdomain")
    return f"{dom}/{sub}" if sub else dom


def item_to_markdown(item: dict) -> str:
    slug = item.get("slug", "unknown")
    pa = item.get("primary_archetype") or {}
    lines = [
        f"# {item.get('title', slug)}",
        "",
        f"**Slug:** `{slug}`",
        f"**Primary archetype:** `{pa.get('id', '?')}`"
        + (f" — {pa.get('rationale')}" if pa.get("rationale") else ""),
        f"**Primary domain:** `{_pair_str(item.get('primary_domain_pair') or {})}`",
        f"**Durable project:** {'yes' if item.get('is_durable_project') else 'no (one-off)'}",
    ]
    sec_a = item.get("secondary_archetypes") or []
    if sec_a:
        lines.append("**Secondary archetypes:** "
                     + ", ".join(f"`{a.get('id')}`" for a in sec_a if a.get("id")))
    if item.get("start_date") or item.get("end_date"):
        lines.append(f"**Dates:** {item.get('start_date') or '?'} → "
                     f"{item.get('end_date') or '?'}")
    lines += [
        f"**Passes/versions:** {item.get('n_passes', item.get('n_versions', 0))} "
        f"({item.get('n_conversations', 0)} conversations)",
        "",
        "## Goal",
        "",
        item.get("goal") or "_Not set._",
        "",
    ]
    objs = item.get("objectives") or []
    if objs:
        lines += ["## Objectives", ""]
        for o in objs:
            if isinstance(o, dict):
                role = f" _({o.get('role')})_" if o.get("role") else ""
                lines.append(f"- {o.get('text', '')}{role}")
            else:
                lines.append(f"- {o}")
        lines.append("")
    af = item.get("archetype_fields") or {}
    if af:
        lines += ["## Archetype fields", ""]
        for k, v in af.items():
            if isinstance(v, list):
                if v:
                    lines.append(f"- **{k}:**")
                    lines += [f"  - {x}" for x in v]
            elif v:
                lines.append(f"- **{k}:** {v}")
        lines.append("")
    if item.get("requirements_evolution"):
        lines += ["## Requirements evolution", ""]
        for ev in item["requirements_evolution"]:
            lines.append(f"- **{ev.get('date') or '?'}:** {ev.get('change', '')}")
        lines.append("")
    zips = item.get("version_zip_files") or []
    if zips:
        lines += ["## Version archives", ""]
        for z in zips:
            fn = z.get("filename") if isinstance(z, dict) else str(z)
            ver = z.get("version") if isinstance(z, dict) else None
            lines.append(f"- `{fn}`" + (f" (v{ver})" if ver else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Export sanitized extracted-item summaries for GitHub.")
    ap.add_argument("--in", dest="in_path", default=None)
    ap.add_argument("--out", dest="out_path", default=None)
    ap.add_argument("--md", action="store_true",
                    help="Also write published/projects/<slug>.md per item.")
    ap.add_argument("--review", action="store_true",
                    help="Print PII/path warnings; exit 1 if any found.")
    args = ap.parse_args()

    in_path = paths.reconstructed_json(args.in_path)
    out_path = paths.published_json(args.out_path)

    if not os.path.exists(in_path):
        sys.stderr.write(f"[error] Input not found: {in_path}\n")
        return 1
    with open(in_path, "r", encoding="utf-8") as f:
        doc = json.load(f)

    public = sanitize_document(doc)
    public["generated_by"] = f"export_public.py (from {os.path.basename(in_path)})"

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(public, f, ensure_ascii=False, indent=2)

    in_size = os.path.getsize(in_path)
    out_size = os.path.getsize(out_path)
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rel_out = os.path.relpath(out_path, repo_root)

    print("gpt publish — GitHub-safe catalog export")
    print("=" * 44)
    print("Copies AI summaries from your private data root into this repo's")
    print("published/ folder so you can commit a redacted catalog to GitHub.")
    print()
    print(f"  From (private)  {in_path}")
    print(f"                  {public['n_items']} items · {confirm.format_size(in_size)}")
    print(f"  To (public)     {out_path}")
    print(f"                  {public['n_items']} items · {confirm.format_size(out_size)}")
    print()
    print("  Removed         chat IDs, member IDs, signal internals,")
    print("                  bundle hashes, per-item cost fields")
    print("  Kept            titles, archetypes, goals, archetype_fields, dates")

    if args.md:
        md_dir = os.path.join(os.path.dirname(out_path), "projects")
        os.makedirs(md_dir, exist_ok=True)
        for p in public["items"]:
            md_path = os.path.join(md_dir, f"{p.get('slug', 'unknown')}.md")
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(item_to_markdown(p))
        print(f"  Also wrote      {len(public['items'])} markdown files under "
              f"{os.path.join(os.path.dirname(rel_out), 'projects')}/")

    if args.review:
        findings = review_document(public)
        if findings:
            print()
            print("  Review          FAILED — possible personal data found:")
            for line in findings[:20]:
                print(f"    - {line}")
            if len(findings) > 20:
                print(f"    … and {len(findings) - 20} more")
            print()
            print("  Fix findings before: git add published/")
            return 1
        print("  Review          passed (no obvious emails or home paths)")
    else:
        print("  Review          skipped (pass --review to scan before git commit)")

    print()
    print("  Next:  git -C", repo_root, "diff", rel_out)
    print("         git -C", repo_root, "add", rel_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
