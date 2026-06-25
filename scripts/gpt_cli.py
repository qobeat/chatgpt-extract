#!/usr/bin/env python3
"""
gpt — unified entrypoint for chatgpt-extract.

Read-only commands are handled here; pipeline commands delegate to the existing
stage scripts so there is a single command to learn:

  (no args)    smart status: show what's parsed, or offer to extract from a zip
  list [GLOB]  list projects (or chats with --chats)
  project GLOB list classified projects (archetype, categories, optional chats)
  category NAME browse by app | idea | project | * (full tree)
  search GLOB  top matches across projects + chats
  info         export statistics
  show SLUG    details for one project (AI summary item if available)
  doctor       environment + provider readiness checks

  run          build steps: Extract -> Cluster -> Bundle (deterministic, no LLM)
  summarize    AI summary (auto-detects provider, asks before running)
  all          run + summarize in one shot
  compare      head-to-head quality of two summary runs (e.g. ollama vs codex)
  metrics      PERFORMANCE (tokens/sec) + QUALITY (completeness %) ranking tables
  arena        combined leaderboard over every model found in saved data
  diagnose     inspect an export .zip (read-only)
  zips         export .zip processing status (ledger + per-chat source_zip)
  zips-verify  check catalog vs all processed exports (nothing missed)
  publish      sanitize the full JSON into published/ for GitHub
  ollama-test  Ollama host/model diagnostics
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))

import paths  # noqa: E402
import store_query as sq  # noqa: E402
import zip_verify  # noqa: E402
import confirm  # noqa: E402
import provider_detect  # noqa: E402
import uio  # noqa: E402

# Approx chats per GB, from observed exports (~4,113 chats in ~1.5 GB).
_CHATS_PER_GB = 2740

DELEGATED = {
    "run": ("run.py", []),
    "all": ("run.py", ["--summarize"]),
    "summarize": (os.path.join("scripts", "summarize.py"), []),
    "compare": (os.path.join("scripts", "compare_runs.py"), []),
    "metrics": (os.path.join("scripts", "metrics.py"), []),
    "arena": (os.path.join("scripts", "arena.py"), []),
    "diagnose": (os.path.join("scripts", "diagnose.py"), []),
    "publish": (os.path.join("scripts", "export_public.py"), []),
}


def _delegate(script_rel: str, prefix: list[str], rest: list[str]) -> int:
    cmd = [sys.executable, os.path.join(REPO, script_rel), *prefix, *rest]
    return subprocess.run(cmd).returncode


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _fmt_date(d: str | None) -> str:
    return d or "—"


def _find_candidate_export(cfg: dict) -> tuple[str, int] | None:
    """Best export .zip to suggest: configured default_zips, else newest .zip
    in export_search_dirs. Does not open the archive."""
    for z in cfg.get("default_zips") or []:
        z = os.path.expanduser(z)
        if z and not z.startswith("/path/to/") and os.path.isfile(z):
            return z, os.path.getsize(z)
    newest: tuple[str, int, float] | None = None
    for d in cfg.get("export_search_dirs") or []:
        d = os.path.expanduser(d)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if not fn.lower().endswith(".zip"):
                continue
            full = os.path.join(d, fn)
            try:
                mtime = os.path.getmtime(full)
                size = os.path.getsize(full)
            except OSError:
                continue
            if newest is None or mtime > newest[2]:
                newest = (full, size, mtime)
    if newest:
        return newest[0], newest[1]
    return None


# ---------------------------------------------------------------------------
# Native commands
# ---------------------------------------------------------------------------
def cmd_status(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt", description="Show pipeline status.")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    st = sq.catalog_state(run_label)

    print(uio.context_line("gpt", f"data root {st['data_root']}"))
    print()

    if not st["has_store"]:
        cfg = paths.load_config()
        cand = _find_candidate_export(cfg)
        print("No parsed data yet.")
        print()
        if cand:
            path, size = cand
            gb = size / 1024 ** 3
            approx = int(gb * _CHATS_PER_GB)
            eta = confirm.format_duration(max(20, gb * 90))
            print(uio.kv("Found export", f"{os.path.basename(path)}  "
                         f"({confirm.format_size(size)}, ~{approx:,} chats)"))
            print(uio.kv("Parse time", f"{eta}  (Extract→Cluster→Bundle, "
                         f"no LLM, no cost)"))
            print("\nNext  gpt run            # parse the export above")
            print("      gpt run --zip PATH # use a different export")
        else:
            print("Next  gpt run --zip <your-export>.zip")
            print("      (or set default_zips / export_search_dirs in "
                  "config/reconstruct.config.local.json)")
        return 0

    print(uio.kv("Catalog", f"{uio.chats(st['n_chats'])} · "
                 f"{uio.projects(st['n_projects'])} · "
                 f"{_fmt_date(st['date_min'])} → {_fmt_date(st['date_max'])}"))

    s4 = st["summary"]
    if not s4:
        cfg = paths.load_config()
        prov, _notes = provider_detect.detect_provider(cfg=cfg)
        print(uio.kv("AI summary", "not run"))
        if prov:
            eta = confirm.format_duration(confirm.eta_seconds(prov, st["n_projects"]))
            print(uio.kv("Provider", f"{prov} (auto-detected) · {eta} for "
                         f"{uio.projects(st['n_projects'])}"))
        else:
            print(uio.kv("Provider", "none detected — install/sign in to codex, "
                         "ollama, or claude (see README)"))
        print("\nNext  gpt summarize --limit 3   ·   gpt all")
        return 0

    if s4.get("schema") == "legacy":
        print(uio.kv("AI summary", "legacy projects[] output found — re-run "
                     "`gpt summarize` for the ADOS schema"))
        return 0

    failed = f" · {s4['n_failed']} failed" if s4.get("n_failed") else ""
    print(uio.kv("AI summary", f"{s4.get('n_items', 0)} classified "
                 f"({s4.get('provider') or '?'}){failed}"))
    print(uio.kv("Output", f"{s4['path']} ({confirm.format_size(s4['size_bytes'])})"))
    print('\nNext  gpt info · gpt zips · gpt zips-verify · gpt list "*ados*" · '
          'gpt publish --review')
    return 0


def _fmt_categories(cats: list[str]) -> str:
    return ",".join(cats) if cats else "—"


def _print_project_help() -> None:
    print("""gpt project — list classified projects matching a glob pattern

Usage:
  gpt project GLOB [options]

GLOB matches slug, title, or cluster titles (substring or wildcards).
Examples:  gpt project "*sat*"   gpt project ados   gpt project "*spark*"

Options:
  --chats         list chats under each project
  --json          machine-readable output
  --limit N       cap number of projects
  --run-label L   read from runs/<L>/

Requires parsed data (gpt run). Categories appear after gpt summarize.

See also:  gpt category app   gpt show SLUG   gpt list""")


def _print_category_help() -> None:
    lines = ["gpt category — browse projects and chats by kind",
             "",
             "Supported categories:"]
    for cat in sq.CATEGORY_IDS:
        lines.append(f"  {cat:<8}  {sq.CATEGORY_HELP[cat]}")
    lines.extend([
        "  *         all categories (full tree) + uncategorized singleton chats",
        "",
        "Usage:",
        "  gpt category NAME [options]",
        "",
        "Options:",
        "  --no-chats      hide per-chat rows (default: show chats)",
        "  --json          machine-readable output",
        "  --limit N       cap projects per category (and uncategorized chats)",
        "  --run-label L   read from runs/<L>/",
        "",
        "Examples:",
        "  gpt category app",
        "  gpt category idea --json",
        "  gpt category *",
        "",
        "Requires gpt summarize for app/idea/project labels.",
    ])
    print("\n".join(lines))


def cmd_project(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help"):
        _print_project_help()
        return 0

    ap = argparse.ArgumentParser(prog="gpt project", add_help=True)
    ap.add_argument("glob")
    ap.add_argument("--chats", action="store_true",
                    help="List chats under each project.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)

    rows = sq.list_projects_enriched(args.glob, limit=args.limit,
                                     run_label=run_label)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(f'No projects matching "{args.glob}".')
        print(f'Try:  gpt project "*"   or   gpt search {args.glob}')
        return 1

    if not sq.load_summary_items(run_label):
        print("(No AI summary yet — run `gpt summarize` for categories/archetypes.)",
              file=sys.stderr)

    print(f'Projects matching "{args.glob}" ({len(rows)}):')
    print(f"{'SLUG':<32} {'CAT':<10} {'ARCHETYPE':<24} {'CHATS':>5} {'VERS':>5}  "
          f"{'UPDATED':<11} TITLE")
    for r in rows:
        arch = (r.get("archetype") or "—")[:24]
        print(f"{r['slug'][:32]:<32} {_fmt_categories(r['categories']):<10} "
              f"{arch:<24} {r['n_conversations']:>5} {r['n_versions']:>5}  "
              f"{_fmt_date(r['end_date']):<11} {r['title'][:36]}")
        if args.chats:
            for ch in r["chats"]:
                print(f"    {_fmt_date(ch['update_date']):<11} {ch['n_turns']:>4}t  "
                      f"{ch['title'][:60]}")
                print(f"      id={ch['id']}")
    return 0


def cmd_category(rest: list[str]) -> int:
    if not rest or rest[0] in ("-h", "--help"):
        _print_category_help()
        return 0

    ap = argparse.ArgumentParser(prog="gpt category", add_help=True)
    ap.add_argument("name", metavar="NAME",
                    help="app | idea | project | * (all)")
    ap.add_argument("--no-chats", action="store_true",
                    help="Hide per-chat rows.")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)

    name = args.name.lower().strip()
    all_tree = name in ("*", "all")
    if not all_tree and name not in sq.CATEGORY_IDS:
        print(f'Unknown category "{args.name}".\n')
        _print_category_help()
        return 2

    tree = sq.list_category_tree(
        categories=None if all_tree else [name],
        include_uncategorized=all_tree,
        limit_per_category=args.limit,
        run_label=run_label,
    )

    if args.json:
        print(json.dumps(tree, ensure_ascii=False, indent=2))
        return 0

    if not tree["has_summary"]:
        print("No AI summary yet — run `gpt summarize` first for categories.")
        print("You can still browse raw projects:  gpt list")
        return 1

    show_chats = not args.no_chats
    sections = sq.CATEGORY_IDS if all_tree else [name]

    for cat in sections:
        projects = tree["categories"].get(cat, [])
        n_chats = sum(len(p["chats"]) for p in projects)
        print(f"\n=== {cat.upper()} — {sq.CATEGORY_HELP[cat]}")
        print(f"{len(projects)} projects · {n_chats} chats\n")
        if not projects:
            print("  (none)")
            continue
        for p in projects:
            tags = _fmt_categories(p["categories"])
            durable = "durable" if p["is_durable_project"] else "one-off"
            print(f"{p['slug']}  ({tags})  {p['title'][:56]}")
            arch = p.get("archetype") or "—"
            print(f"  {arch} · {durable} · {p['n_versions']} version(s) · "
                  f"last {_fmt_date(p['end_date'])}")
            if p.get("goal"):
                g = p["goal"]
                print(f"  goal: {g[:90]}{'…' if len(g) > 90 else ''}")
            if show_chats:
                print("  chats:")
                for ch in p["chats"]:
                    print(f"    {_fmt_date(ch['update_date']):<11} "
                          f"{ch['n_turns']:>4}t  {ch['title'][:52]}")
                    print(f"      id={ch['id']}")

    if all_tree and tree["uncategorized_chats"]:
        unc = tree["uncategorized_chats"]
        print(f"\n=== UNCATEGORIZED — singleton chats (not in a summarized project)")
        print(f"{len(unc)} chats"
              + (f" (showing {args.limit})" if args.limit else "") + "\n")
        if show_chats:
            for ch in unc[:50 if not args.limit else len(unc)]:
                print(f"  {_fmt_date(ch['update_date']):<11} {ch['n_turns']:>4}t  "
                      f"{ch['title'][:52]}")
                print(f"    id={ch['id']}")
            if len(unc) > 50 and not args.limit:
                print(f"  … and {len(unc) - 50} more (use --limit or gpt list --chats)")
        else:
            print("  (use without --no-chats to list them)")

    return 0


def cmd_list(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt list")
    ap.add_argument("glob", nargs="?", default=None)
    ap.add_argument("--chats", action="store_true", help="List chats, not projects.")
    ap.add_argument("--all", action="store_true",
                    help="Include singletons (projects only).")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)

    if args.chats:
        rows = sq.list_chats(args.glob, limit=args.limit, run_label=run_label)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
            return 0
        if not rows:
            print("No chats found.")
            return 0
        print(f"{'UPDATED':<11} {'TURNS':>5}  TITLE")
        for r in rows:
            print(f"{_fmt_date(r['update_date']):<11} {r['n_turns']:>5}  "
                  f"{r['title'][:70]}")
        print(f"\n({len(rows)} chats" + (f' matching \"{args.glob}\"' if args.glob else "") + ")")
        return 0

    rows = sq.list_projects(args.glob, limit=args.limit,
                            include_all=args.all, run_label=run_label)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print("No projects found.")
        return 0
    print(f"{'SLUG':<32} {'CHATS':>5} {'VERS':>5}  {'UPDATED':<11} TITLE")
    for r in rows:
        print(f"{r['slug'][:32]:<32} {r['n_conversations']:>5} {r['n_versions']:>5}  "
              f"{_fmt_date(r['end_date']):<11} {r['title'][:40]}")
    print(f"\n({len(rows)} projects" + (f' matching \"{args.glob}\"' if args.glob else "") + ")")
    return 0


def cmd_search(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt search")
    ap.add_argument("glob")
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    rows = sq.search(args.glob, limit=args.limit, run_label=run_label)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if not rows:
        print(f'No matches for "{args.glob}".')
        return 0
    print(f'Top {len(rows)} for "{args.glob}":')
    for r in rows:
        tag = f"[{r['kind']}]"
        meta = (uio.chats(r['n_conversations']) if r["kind"] == "project"
                else "chat")
        print(f" {tag:<10} {r['slug'][:28]:<28} {meta:<9} "
              f"{_fmt_date(r.get('end_date'))}  {r['title'][:40]}")
    return 0


def cmd_info(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt info")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    s = sq.info_stats(run_label)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
        return 0
    if s["n_chats"] == 0:
        print("No parsed data yet. Run: gpt run --zip <export>.zip")
        return 0

    def top(d: dict, n: int = 4) -> str:
        items = sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:n]
        return " · ".join(f"{k} {v:,}" for k, v in items) or "—"

    w = 14  # wider label column: "Content types" is 13 chars
    print(uio.context_line("gpt info", f"data root {s['data_root']}"))
    print()
    print(uio.kv("Chats", f"{s['n_chats']:,}", w))
    print(uio.kv("Projects", f"{s['n_projects']:,}  "
                 f"({s['n_projects_with_zips']} with version zips)", w))
    print(uio.kv("Date range",
                 f"{_fmt_date(s['date_min'])} → {_fmt_date(s['date_max'])}", w))
    print(uio.kv("Turns", f"~{s['n_turns']:,} (user {s['n_user_turns']:,} / "
                 f"assistant {s['n_assistant_turns']:,})", w))
    print(uio.kv("Content types", top(s['content_types']), w))
    print(uio.kv("File classes", top(s['file_classes']), w))
    s4 = s["summary"]
    if s4 and s4.get("schema") == "items":
        failed = f" · {s4['n_failed']} failed" if s4.get("n_failed") else ""
        print(uio.kv("AI summary", f"done · {s4.get('provider') or '?'} · "
                     f"{s4.get('n_items', 0)} items{failed}", w))
    elif s4 and s4.get("schema") == "legacy":
        print(uio.kv("AI summary",
                     "legacy projects[] output (re-summarize for ADOS schema)", w))
    else:
        print(uio.kv("AI summary", "not run", w))
    print(uio.kv("Disk", f"store {confirm.format_size(s['disk']['store'])} · "
                 f"bundles {confirm.format_size(s['disk']['bundles'])}", w))
    return 0


def cmd_show(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt show")
    ap.add_argument("slug")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    s4 = sq.summary_state(run_label)
    if s4 and s4.get("schema") == "items":
        with open(s4["path"], encoding="utf-8") as f:
            doc = json.load(f)
        for it in doc.get("items", []):
            if it.get("slug") == args.slug:
                pa = it.get("primary_archetype") or {}
                dp = it.get("primary_domain_pair") or {}
                print(f"# {it.get('title', args.slug)}  ({args.slug})")
                print(f"archetype : {pa.get('id')}")
                print(f"domain    : {dp.get('domain')}"
                      + (f"/{dp.get('subdomain')}" if dp.get('subdomain') else ""))
                print(f"goal      : {it.get('goal', '')}")
                if it.get("description"):
                    print(f"\n{it['description']}")
                return 0
    # Fall back to cluster info + bundle path.
    for c in sq.load_clusters(run_label):
        if c.get("slug") == args.slug:
            bundle = os.path.join(sq.store_paths(run_label)["bundles"],
                                  f"{args.slug}.md")
            print(f"# {sq.human_title(args.slug)}  ({args.slug})")
            print(f"chats     : {c.get('n_conversations', 0)}")
            print(f"versions  : {c.get('n_versions', 0)}")
            print(f"dates     : {_fmt_date(c.get('start_date'))} → "
                  f"{_fmt_date(c.get('end_date'))}")
            print(f"bundle    : {bundle}" + (" (missing)" if not os.path.exists(bundle) else ""))
            print("\n(no AI summary yet — run `gpt summarize`)")
            return 0
    print(f"No project with slug '{args.slug}'. Try: gpt search {args.slug}")
    return 1


def cmd_zips(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt zips",
        description="Show which export .zip files were processed and which chats "
                    "they last wrote (zip_ledger.json + index source_zip).")
    ap.add_argument("--zip", action="append", dest="zips", metavar="PATH",
                    help="Also report status for this export (repeatable). "
                         "Useful for zips not yet in the ledger.")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    st = sq.zip_status(run_label, check_paths=args.zips)

    if args.json:
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0

    ledger_s = "ok" if st["has_ledger"] else "not created yet"
    print(uio.context_line("gpt zips", f"data root {st['data_root']}",
                           f"ledger {ledger_s}"))
    print()

    if not st["entries"] and not st["chats_by_source_zip"]:
        print("No exports recorded yet. Run: gpt run --zip <export>.zip")
        if args.zips:
            print("\nChecked paths:")
            for z in args.zips:
                print(f"  {z}  → not in ledger")
        return 0

    print("Newest export first · OWNS = chats this export sources in the catalog "
          "today")
    print("LAST RUN: IN ZIP = opened · SKIP = already up to date · NEW = saved")
    print()
    hdr = (f"{'PARSE':<10} {'DATE':<10} {'SIZE':>7}  {'OWNS':>6}  "
           f"{'IN ZIP':>7} {'SKIP':>7} {'NEW':>5}  EXPORT")
    print(hdr)
    print("-" * len(hdr))
    for e in st["entries"]:
        seen = e["seen"]
        skipped = e["skipped"]
        written = e["written"]
        seen_s = f"{seen:,}" if seen is not None else "—"
        skip_s = f"{skipped:,}" if skipped is not None else "—"
        new_s = f"{written:,}" if written is not None else "—"
        size_s = (confirm.format_size(e["size_bytes"])
                  if e.get("size_bytes") is not None else "—")
        date_s = e.get("export_date") or "—"
        bn = uio.short_basename(e["basename"])
        print(f"{e['status']:<10} {date_s:<10} {size_s:>7}  "
              f"{e['chats_in_store']:>6,}  {seen_s:>7} {skip_s:>7} {new_s:>5}  {bn}")

    cfg = paths.load_config()
    basenames = {e["basename"] for e in st["entries"] if e.get("basename")}
    discovered = zip_verify.discover_zip_paths(basenames, cfg) if basenames else {}
    print()
    print("Export files (date · path · source)")
    for e in st["entries"]:
        bn = e.get("basename") or "?"
        date_s = e.get("export_date") or "—"
        path = e.get("path") or discovered.get(bn)
        if path and os.path.isfile(path):
            src = zip_verify.classify_path_source(path, cfg)
            print(f"  {date_s}  {path}  ({src})")
        else:
            print(f"  {date_s}  NOT FOUND  {bn}")

    print()
    print(uio.kv("Catalog", uio.chats(st["n_chats_in_store"])))
    if len(st["entries"]) > 1:
        print("Newer exports supersede older ones — a large export can show OWNS=0 "
              "if a later export already wrote every chat.")

    if args.zips:
        print("\nNext  not_processed → gpt run --zip <path>")
        print("      full + all SKIP → re-scan is fast (unchanged chats are skipped)")
    return 0


def cmd_zips_verify(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt zips-verify",
        description="Verify the catalog against every export recorded in "
                    "zip_ledger.json. Discovers zip paths from config; "
                    "opens each archive and checks nothing was missed.")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--force-zip-read", action="store_true",
                    help="Re-open every export instead of reusing the per-zip "
                         "hash cache (slow; only needed if a cache is stale).")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    if not args.json:
        if args.force_zip_read:
            print("Re-scanning every export and counting chats "
                  "(--force-zip-read; may take 1–2 min)...", file=sys.stderr)
        else:
            print("Verifying exports (unchanged exports reuse the hash cache; "
                  "any changed export is scanned, which may take 1–2 min)...",
                  file=sys.stderr)
    rep = zip_verify.zip_verify(run_label, force_zip_read=args.force_zip_read)

    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
        return 0 if rep["verdict"] == "ok" else 1

    print(uio.context_line("gpt zips-verify", f"data root {rep['data_root']}",
                           "catalog completeness"))
    print()

    if rep["n_processed_exports"] == 0:
        print("No processed exports in the ledger.")
        print("Next  gpt run --zip <export>.zip")
        return 1

    print(f"Checking {rep['n_processed_exports']} processed export(s)")
    print(f"  zip reads {rep.get('n_zips_scanned', 0)} scanned · "
          f"{rep.get('n_zips_from_cache', 0)} from hash cache"
          f"{' (--force-zip-read)' if rep.get('forced_zip_read') else ''}")
    for src in rep.get("search_sources") or []:
        print(f"  searched  {src}")
    print()
    hdr = (f"{'DATE':<10} {'SIZE':>7}  {'IN ZIP':>7} {'OWNS':>6}  "
           f"{'PARSE':<8} FILE")
    print(hdr)
    print("-" * len(hdr))
    for r in rep["rows"]:
        size_s = (confirm.format_size(r["size_bytes"])
                  if r.get("size_bytes") is not None else "—")
        date_s = r.get("export_date") or "—"
        in_zip_s = f"{r['in_zip']:,}" if r.get("in_zip") is not None else "—"
        file_s = uio.mark(bool(r.get("file_ok")), bad="MISSING")
        bn = uio.short_basename(r["basename"])
        print(f"{date_s:<10} {size_s:>7}  {in_zip_s:>7} {r['owns']:>6,}  "
              f"{r['parse_status']:<8} {file_s}  {bn}")

    print()
    print("Export files (date · read · path · source)")
    for r in rep["rows"]:
        date_s = r.get("export_date") or "—"
        if r.get("file_ok") and r.get("path"):
            read_s = {"cache": "[hash cache]", "scan": "[scanned]"}.get(
                r.get("ids_source"), "")
            src = r.get("source") or "config"
            print(f"  {date_s}  {read_s}  {r['path']}  ({src})")
        else:
            print(f"  {date_s}  NOT FOUND  {r['basename']}")

    print()
    print(f"Catalog chats              {rep['n_catalog']:,}")
    if rep.get("newest_basename"):
        short = uio.short_basename(rep["newest_basename"])
        print(f"Newest export              {short}")
        print(f"  chats in zip             {rep['n_newest_in_zip']:,}")
    print(f"Older-only in catalog      {rep['n_older_only']:,}  "
          f"(in catalog but not in newest export — normal if deleted before that export)")
    print(f"Union across all exports   {rep['n_union_in_exports']:,} unique chats")
    print()
    print("Checks")
    for c in rep["checks"]:
        print(f"  [{uio.mark(c['ok']):<4}]  {c['detail']}")

    if rep.get("older_only_sample_titles") and rep["n_older_only"] > 0:
        print()
        print(f"Older-only sample ({min(5, rep['n_older_only'])} of "
              f"{rep['n_older_only']:,}):")
        for title in rep["older_only_sample_titles"][:5]:
            t = title if len(title) <= 72 else title[:69] + "..."
            print(f"  · {t}")

    print()
    if rep["verdict"] == "ok":
        print("VERDICT: OK — nothing obvious missing from processed exports")
        print()
        print("Note: cannot detect chats OpenAI never exported (temp chats, "
              "deleted before any export, some attachments).")
        return 0

    print("VERDICT: ISSUES — see [FAIL] lines above")
    for msg in rep.get("issues") or []:
        print(f"  ! {msg}")
    print()
    print("Next  fix paths in config/reconstruct.config.local.json, then "
          "re-run  gpt run --zip <export>.zip  for affected exports")
    return 1


def cmd_doctor(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt doctor")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    cfg = paths.load_config()
    w = 14

    print(uio.context_line("gpt doctor"))
    print()
    print(uio.kv("Python", f"{sys.version.split()[0]} ({sys.executable})", w))
    for mod in ("ijson", "jsonschema"):
        try:
            __import__(mod)
            print(uio.kv(mod, "ok", w))
        except ImportError:
            print(uio.kv(mod, "MISSING (run: bash setup.sh)", w))

    st = sq.catalog_state(run_label)
    print(uio.kv("Data root", st['data_root'], w))
    print(uio.kv("Parsed", f"{'yes' if st['has_store'] else 'no'} "
                 f"({uio.chats(st['n_chats'])}, {uio.projects(st['n_projects'])})", w))

    print("Providers")
    for name in provider_detect.DEFAULT_ORDER:
        _prov, notes = provider_detect.detect_provider(order=(name,), cfg=cfg)
        print(f"  {name:<8} {notes[-1].split(': ', 1)[-1] if notes else 'unknown'}")
    return 0


NATIVE = {
    "status": cmd_status,
    "list": cmd_list,
    "project": cmd_project,
    "category": cmd_category,
    "search": cmd_search,
    "info": cmd_info,
    "show": cmd_show,
    "zips": cmd_zips,
    "zips-verify": cmd_zips_verify,
    "doctor": cmd_doctor,
}


COMMON_SCENARIOS = """
Common scenarios (full command lines):

  First parse of an export (Extract -> Cluster -> Bundle; no LLM, no cost)
    gpt run --zip "<your-export>.zip"

  Re-parse / incremental update (newer export; unchanged chats are skipped)
    gpt run --zip "<newer-export>.zip"
    # If a .zip was already fully processed, gpt notifies you before re-scanning.

  Quick test on a small subset
    gpt run --zip "<export>.zip" --limit 200

  Isolated, side-by-side experiment under runs/<label>/
    gpt run --zip "<export>.zip" --run-label modeltest

  Inspect results before spending any LLM time
    gpt info
    gpt list "*ados*"
    gpt project "*sat*"
    gpt category app
    gpt category *
    gpt search meeting

  Preview the AI summary (estimate + item list, ZERO LLM calls)
    gpt summarize --dry-run

  AI summary, quick sample (auto provider; asks first)
    gpt summarize --limit 3

  AI summary with a hard budget cap, non-interactive
    gpt summarize --provider openai --model gpt-5-mini --max-usd 2 --noask

  Everything in one shot (parse + summarize)
    gpt all --zip "<export>.zip"

  Resume a killed summary run
    gpt summarize --resume

  Which export zips are processed / linked to chats
    gpt zips
    gpt zips --zip "<export-a>.zip" --zip "<export-b>.zip"

  Verify catalog completeness (all ledger exports, no paths needed)
    gpt zips-verify

  Publish a GitHub-safe export (scan for PII first)
    gpt publish --review

Notes:
  * Runs estimated to take more than 5 minutes warn before starting.
  * --noask (alias --yes) skips confirmation prompts for non-interactive use.
  * Run 'gpt <command> --help' for the full option list of any command.
""".rstrip()


def _usage() -> None:
    print(__doc__.strip())
    print(COMMON_SCENARIOS)


def main(argv: list[str]) -> int:
    if not argv:
        return cmd_status([])
    cmd, rest = argv[0], argv[1:]
    if cmd in ("-h", "--help", "help"):
        _usage()
        return 0
    if cmd == "ollama-test":
        return subprocess.run([os.path.join(REPO, "ollama_test.sh"), *rest]).returncode
    if cmd in DELEGATED:
        script_rel, prefix = DELEGATED[cmd]
        return _delegate(script_rel, prefix, rest)
    if cmd in NATIVE:
        return NATIVE[cmd](rest)
    sys.stderr.write(f"[error] unknown command: {cmd}\n\n")
    _usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
