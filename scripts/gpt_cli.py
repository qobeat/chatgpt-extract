#!/usr/bin/env python3
"""
gpt — unified entrypoint for chatgpt-extract.

Read-only commands are handled here; pipeline commands delegate to the existing
stage scripts so there is a single command to learn:

  (no args)    smart status: show what's parsed, or offer to extract from a zip
  list [GLOB]  list projects (or chats with --chats)
  search GLOB  top matches across projects + chats
  info         export statistics
  show SLUG    details for one project (AI summary item if available)
  doctor       environment + provider readiness checks

  run          build steps: Extract -> Cluster -> Bundle (deterministic, no LLM)
  summarize    AI summary (auto-detects provider, asks before running)
  all          run + summarize in one shot
  compare      head-to-head quality of two summary runs (e.g. ollama vs codex)
  diagnose     inspect an export .zip (read-only)
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
import confirm  # noqa: E402
import provider_detect  # noqa: E402

# Approx conversations per GB, from observed exports (~4,113 convs in ~1.5 GB).
_CONVS_PER_GB = 2740

DELEGATED = {
    "run": ("run.py", []),
    "all": ("run.py", ["--summarize"]),
    "summarize": (os.path.join("scripts", "summarize.py"), []),
    "compare": (os.path.join("scripts", "compare_runs.py"), []),
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

    print(f"chatgpt-extract — data root: {st['data_root']}")
    print()

    if not st["has_store"]:
        cfg = paths.load_config()
        cand = _find_candidate_export(cfg)
        print("No parsed data yet.")
        if cand:
            path, size = cand
            gb = size / 1024 ** 3
            approx = int(gb * _CONVS_PER_GB)
            eta = confirm.format_duration(max(20, gb * 90))
            print(f"\nFound export:  {os.path.basename(path)}  "
                  f"({confirm.format_size(size)}, ~{approx:,} conversations)")
            print(f"Parse time:    {eta}  (Extract→Cluster→Bundle, no LLM, no cost)")
            print("\nNext:  gpt run            # parse the export above")
            print("       gpt run --zip PATH # use a different export")
        else:
            print("\nNext:  gpt run --zip <your-export>.zip")
            print("  (or set default_zips / export_search_dirs in "
                  "config/reconstruct.config.local.json)")
        return 0

    print(f"Parsed:    {st['n_chats']:,} chats · {st['n_projects']:,} projects · "
          f"{_fmt_date(st['date_min'])} → {_fmt_date(st['date_max'])}")

    s4 = st["summary"]
    if not s4:
        cfg = paths.load_config()
        prov, _notes = provider_detect.detect_provider(cfg=cfg)
        print("AI summary: not run")
        print()
        if prov:
            eta = confirm.format_duration(confirm.eta_seconds(prov, st["n_projects"]))
            print(f"Provider:  {prov} (auto-detected)")
            print(f"Estimate:  {eta} for {st['n_projects']} items")
        else:
            print("Provider:  none detected — install/sign in to codex, ollama, "
                  "or claude (see README)")
        print("\nNext:  gpt summarize --limit 3   # quick sample (asks first)")
        print("       gpt all                   # full catalog")
        return 0

    if s4.get("schema") == "legacy":
        print("AI summary: legacy projects[] output found (re-run `gpt summarize` "
              "for the new ADOS schema)")
        return 0

    failed = f" · {s4['n_failed']} failed" if s4.get("n_failed") else ""
    print(f"AI summary: {s4.get('n_items', 0)} classified "
          f"({s4.get('provider') or '?'}){failed}")
    print(f"Output:    {s4['path']} ({confirm.format_size(s4['size_bytes'])})")
    print('\nNext:  gpt info · gpt list "*ados*" · gpt publish --review')
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
        meta = (f"{r['n_conversations']} chats" if r["kind"] == "project"
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

    print(f"Data root      {s['data_root']}")
    print(f"Chats          {s['n_chats']:,}")
    print(f"Projects       {s['n_projects']:,}  ({s['n_projects_with_zips']} with version zips)")
    print(f"Date range     {_fmt_date(s['date_min'])} → {_fmt_date(s['date_max'])}")
    print(f"Turns          ~{s['n_turns']:,} (user {s['n_user_turns']:,} / "
          f"assistant {s['n_assistant_turns']:,})")
    print(f"Content types  {top(s['content_types'])}")
    print(f"File classes   {top(s['file_classes'])}")
    s4 = s["summary"]
    if s4 and s4.get("schema") == "items":
        failed = f" · {s4['n_failed']} failed" if s4.get("n_failed") else ""
        print(f"AI summary     done · {s4.get('provider') or '?'} · "
              f"{s4.get('n_items', 0)} items{failed}")
    elif s4 and s4.get("schema") == "legacy":
        print("AI summary     legacy projects[] output (re-summarize for ADOS schema)")
    else:
        print("AI summary     not run")
    print(f"Disk           store {confirm.format_size(s['disk']['store'])} · "
          f"bundles {confirm.format_size(s['disk']['bundles'])}")
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


def cmd_doctor(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt doctor")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    cfg = paths.load_config()

    print(f"Python         {sys.version.split()[0]} ({sys.executable})")
    for mod in ("ijson", "jsonschema"):
        try:
            __import__(mod)
            print(f"{mod:<14} ok")
        except ImportError:
            print(f"{mod:<14} MISSING (run: bash setup.sh)")

    st = sq.catalog_state(run_label)
    print(f"Data root      {st['data_root']}")
    print(f"Parsed         {'yes' if st['has_store'] else 'no'} "
          f"({st['n_chats']:,} chats, {st['n_projects']:,} projects)")

    print("Providers:")
    for name in provider_detect.DEFAULT_ORDER:
        _prov, notes = provider_detect.detect_provider(order=(name,), cfg=cfg)
        print(f"  {name:<8} {notes[-1].split(': ', 1)[-1] if notes else 'unknown'}")
    return 0


NATIVE = {
    "status": cmd_status,
    "list": cmd_list,
    "search": cmd_search,
    "info": cmd_info,
    "show": cmd_show,
    "doctor": cmd_doctor,
}


def _usage() -> None:
    print(__doc__.strip())


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
