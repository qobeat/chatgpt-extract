#!/usr/bin/env python3
"""
gpt — unified entrypoint for chatgpt-extract.

Read-only commands are handled here; pipeline commands delegate to the existing
stage scripts so there is a single command to learn:

  (no args)    smart status: show what's parsed, or offer to extract from a zip
  list [GLOB]  list projects (or chats with --chats)
  project GLOB list classified projects (archetype, categories, optional chats)
  category NAME browse by app | idea | project | * (full tree)
  search PATTERN  find chats by transcript text [-i -w -a] or file names [-f]
  ask QUESTION    answer a question from your chats (semantic, local, cited; --budget/--auto-serve)
  ask-serve    warm `ask` daemon (keeps index+engine resident for ~2s answers)
  index        build/update the local semantic index used by `gpt ask`
  build-entities derive the version/stability facts `gpt ask` cites (no re-embed)
  ask-eval     grade `gpt ask` against the labeled verification battery
  embed-eval   compare local embedding models (recall/MRR/energy) for the index
  cat [IDS]    print chat text; piped from search shows match context windows
               (--before/--after/--context-lines-no/--max-parts/--max-lines/--reverse/--color) [alias: chat]
  info         export statistics
  show SLUG    details for one project (AI summary item if available)
  doctor       environment + provider readiness checks

  run          build steps: Extract -> Cluster -> Bundle (deterministic, no LLM)
  summarize    AI summary (auto-detects provider, asks before running) [alias: sum]
  all          run + summarize in one shot
  compare      head-to-head quality of two summary runs (e.g. ollama vs codex)
  metrics      PERFORMANCE (s/item, $/1k, Wh/item) + QUALITY (completion /
               depth-on-success / schema-valid / accuracy) ranking tables
  state        emit an ADOS Project State (typed observation vs. the geometry)
               (use `state --all` to unify every sweep into one format)
  report       cross-sweep markdown report from the unified Project States
  arena        combined leaderboard over every model found in saved data
  gen-model-benchmarks  regenerate config/generated/model_benchmarks.json (typed,
               machine-owned) from the metric (FR-D2) [alias: gen-model-notes]
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
import re
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
import interrupt  # noqa: E402

# Approx chats per GB, from observed exports (~4,113 chats in ~1.5 GB).
_CHATS_PER_GB = 2740

DELEGATED = {
    "run": ("run.py", []),
    "all": ("run.py", ["--summarize"]),
    "summarize": (os.path.join("scripts", "summarize.py"), []),
    "compare": (os.path.join("scripts", "compare_runs.py"), []),
    "metrics": (os.path.join("scripts", "metrics.py"), []),
    "index": (os.path.join("scripts", "index.py"), []),
    "ask": (os.path.join("scripts", "ask.py"), []),
    "ask-serve": (os.path.join("scripts", "ask_daemon.py"), []),
    "embed-eval": (os.path.join("scripts", "embed_eval.py"), []),
    "ask-eval": (os.path.join("scripts", "ask_eval.py"), []),
    "build-entities": (os.path.join("scripts", "build_entities.py"), []),
    "state": (os.path.join("scripts", "project_state.py"), []),
    "report": (os.path.join("scripts", "report.py"), []),
    "arena": (os.path.join("scripts", "arena.py"), []),
    "diagnose": (os.path.join("scripts", "diagnose.py"), []),
    "publish": (os.path.join("scripts", "export_public.py"), []),
    "gen-model-benchmarks": (os.path.join("scripts", "gen_model_benchmarks.py"), []),
    # Back-compat alias: the generator was renamed gen_model_notes -> gen_model_benchmarks.
    "gen-model-notes": (os.path.join("scripts", "gen_model_benchmarks.py"), []),
}

# Command aliases resolved before dispatch (e.g. `gpt sum` == `gpt summarize`).
ALIASES = {
    "sum": "summarize",
    "chat": "cat",
}


def _delegate(script_rel: str, prefix: list[str], rest: list[str]) -> int:
    cmd = [sys.executable, os.path.join(REPO, script_rel), *prefix, *rest]
    try:
        return interrupt.propagate_child(subprocess.run(cmd).returncode)
    except KeyboardInterrupt:
        # The child got the same SIGINT and already printed its own clean
        # message; stay quiet and relay the standard interrupt exit code.
        return interrupt.SIGINT_EXIT


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
    print('\nNext  gpt ask "..." · gpt info · gpt zips-verify · '
          'gpt list "*ados*" · gpt publish --review')
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
    ap = argparse.ArgumentParser(
        prog="gpt search",
        description="Search chat transcript text (default) or attachment/file "
                    "names (-f) for PATTERN.",
        epilog="PATTERN is a substring by default (wrapped as *PATTERN*); pass a "
               "glob (*, ?, [..]) for wildcards. Note: assistant code-block "
               "bodies are stripped from transcripts, so a string that only "
               "appears inside a code block may not match text search; -f/-a "
               "(which include file_artifacts) still catch filenames.")
    ap.add_argument("pattern")
    ap.add_argument("-i", "--ignore-case", action="store_true",
                    help="Case-insensitive match (default: case-sensitive).")
    ap.add_argument("-w", "--word", action="store_true",
                    help="Whole-word match (no implicit *PATTERN* wildcards).")
    scope = ap.add_mutually_exclusive_group()
    scope.add_argument("-f", "--attachments", action="store_true",
                       help="Search attachment + file_artifact names instead of text.")
    scope.add_argument("-a", "--all", action="store_true",
                       help="Search transcript text PLUS title and file_artifacts.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap results (default 0 = all).")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)

    # Publish progress so a Ctrl+C mid-scan reports how far we got.
    interrupt.set_total(sq.catalog_state(run_label).get("n_chats", 0), unit="chats")
    _bump = lambda: interrupt.advance()  # noqa: E731

    if args.attachments:
        rows = sq.search_attachments(args.pattern, ignore_case=args.ignore_case,
                                     word=args.word, limit=args.limit,
                                     run_label=run_label, on_progress=_bump)
    else:
        rows = sq.search_transcripts(args.pattern, ignore_case=args.ignore_case,
                                     word=args.word, scope_all=args.all,
                                     limit=args.limit, run_label=run_label,
                                     on_progress=_bump)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0

    flags = []
    if args.ignore_case:
        flags.append("-i")
    if args.word:
        flags.append("-w")
    if args.attachments:
        flags.append("-f")
    if args.all:
        flags.append("-a")
    scope_label = ("attachment/file names" if args.attachments
                   else "text+title+files" if args.all else "transcript text")
    suffix = f" [{' '.join(flags)}]" if flags else ""
    if not rows:
        print(f'No {scope_label} matches for "{args.pattern}"{suffix}.')
        return 0

    print(f'{len(rows)} chat(s) matching "{args.pattern}" in {scope_label}{suffix}:')
    print(f"{'UPDATED':<11} {'TURNS':>5}  TITLE")
    for r in rows:
        print(f"{_fmt_date(r['update_date']):<11} {r['n_turns']:>5}  "
              f"{r['title'][:70]}")
        print(f"  id={r['id']}")
        if args.attachments:
            print(f"  files: {', '.join(r['matched_files'])}")
        elif r.get("snippet"):
            snip = r["snippet"]
            print(f"  [{r.get('matched_in', 'text')}] "
                  f"{snip[:100]}{'…' if len(snip) > 100 else ''}")
    return 0


_ID_RE = re.compile(r"id=(\S+)")
_PATTERN_RE = re.compile(r'matching "(.*?)"')
_FLAGS_RE = re.compile(r"\[([^\]]*)\]\s*:")


def _parse_search_stream(text: str) -> dict:
    """Parse piped `gpt search` output: ordered unique chat ids plus the
    highlight context (pattern + -i/-w) from the `matching "..." [..]:` header."""
    ids: list[str] = []
    seen: set[str] = set()
    for m in _ID_RE.finditer(text):
        cid = m.group(1)
        if cid not in seen:
            seen.add(cid)
            ids.append(cid)
    pm = _PATTERN_RE.search(text)
    pattern = pm.group(1) if pm else None
    ignore_case = word = False
    fm = _FLAGS_RE.search(text)
    if fm:
        tokens = fm.group(1).split()
        ignore_case = "-i" in tokens
        word = "-w" in tokens
    return {"ids": ids, "pattern": pattern,
            "ignore_case": ignore_case, "word": word}


_HL_ON = "\x1b[1;33m"
_HL_OFF = "\x1b[0m"


def _highlight(text: str, rx) -> str:
    if rx is None:
        return text
    return rx.sub(lambda m: f"{_HL_ON}{m.group(0)}{_HL_OFF}" if m.group(0)
                  else m.group(0), text)


def _trim_lines(parts: list[dict], max_lines: int, reverse: bool) -> list[dict]:
    """Cap the total transcript lines across parts, trimming the boundary part
    at line granularity. Forward keeps the head; reverse keeps the tail."""
    seq = list(reversed(parts)) if reverse else list(parts)
    out: list[dict] = []
    used = 0
    for p in seq:
        size = p["end"] - p["start"] + 1
        if used + size <= max_lines:
            out.append(dict(p))
            used += size
            if used == max_lines:
                break
            continue
        remaining = max_lines - used
        if remaining <= 0:
            break
        q = dict(p)
        if reverse:
            q["start"] = q["end"] - remaining + 1
        else:
            q["end"] = q["start"] + remaining - 1
        out.append(q)
        break
    if reverse:
        out.reverse()
    return out


def _plan_cat_parts(matches: list[int], total_lines: int, *, before: int = 8,
                    after: int = 3, context_no: int | None = None,
                    max_parts: int = 0, max_lines: int = 0,
                    reverse: bool = False) -> dict:
    """Plan the context blocks to print for a chat (pure, no I/O).

    Each matched line becomes a part with a [start, end] window. `context_no`
    overrides before/after with a centered window of that many total lines
    (<=1 -> grep mode: just the matched line). `max_parts`/`max_lines` cap the
    output (keeping the last ones when `reverse`). Parts are renumbered 1..K in
    file order. Returns {grep_mode, parts:[{p, matched_line, start, end}],
    total_found}.
    """
    total_found = len(matches)
    grep_mode = False
    if context_no is not None:
        if context_no <= 1:
            grep_mode = True
            above = below = 0
        else:
            extra = context_no - 1
            above = extra // 2
            below = extra - above
    else:
        above, below = before, after

    parts: list[dict] = []
    for m in matches:
        parts.append({
            "matched_line": m,
            "start": max(1, m - above),
            "end": min(total_lines, m + below) if total_lines else m,
        })

    if max_parts and max_parts > 0 and len(parts) > max_parts:
        parts = parts[-max_parts:] if reverse else parts[:max_parts]

    if max_lines and max_lines > 0:
        if grep_mode:
            if len(parts) > max_lines:
                parts = parts[-max_lines:] if reverse else parts[:max_lines]
        else:
            parts = _trim_lines(parts, max_lines, reverse)

    for i, p in enumerate(parts, 1):
        p["p"] = i
    return {"grep_mode": grep_mode, "parts": parts, "total_found": total_found}


def _render_context(text: str, rx, hl, path: str, args) -> None:
    """Print context blocks around each pattern match plus a per-chat footer."""
    lines = text.split("\n")
    total = len(lines)
    matches = [i for i, ln in enumerate(lines, 1) if rx.search(ln)]
    plan = _plan_cat_parts(matches, total, before=args.before, after=args.after,
                           context_no=args.context_no, max_parts=args.max_parts,
                           max_lines=args.max_lines, reverse=args.reverse)
    parts = plan["parts"]

    if not matches:
        print("  (no in-text matches; matched via title/file scope)")
    elif plan["grep_mode"]:
        for p in parts:
            m = p["matched_line"]
            print(f"{m}:{_highlight(lines[m - 1], hl)}")
    else:
        for p in parts:
            s, e, m = p["start"], p["end"], p["matched_line"]
            print(f"Part {p['p']}, Matched Line: {m}, Context: {e - s} lines, "
                  f"start line: {s}, end line: {e}")
            for ln_no in range(s, e + 1):
                print(_highlight(lines[ln_no - 1], hl))

    shown = len(parts)
    total_found = plan["total_found"]
    shown_s = f", shown {shown}" if shown != total_found else ""
    print(f"Found {total_found} part(s){shown_s} · file: {path}")


def cmd_cat(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(
        prog="gpt cat",
        description="Print chat transcript(s). Standalone (ids as args) prints "
                    "the whole transcript; piped from `gpt search` it prints "
                    "context windows around each match.",
        epilog="Examples:\n"
               "  gpt search -i usage_events | gpt cat --color\n"
               "  gpt search usage_events | gpt cat --max-parts 2 --reverse\n"
               "  gpt search usage_events | gpt cat --context-lines-no 1\n"
               "  gpt cat 69f50d43-... --pattern usage --color",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="Chat id(s); omit to read from stdin.")
    ap.add_argument("--color", action="store_true",
                    help="Colorize the search pattern in the output.")
    ap.add_argument("--pattern", default=None,
                    help="Pattern to highlight (overrides the piped one).")
    ap.add_argument("-i", "--ignore-case", action="store_true",
                    help="Case-insensitive highlight (default: from pipe).")
    ap.add_argument("-w", "--word", action="store_true",
                    help="Whole-word highlight (default: from pipe).")
    ap.add_argument("--no-header", action="store_true",
                    help="Omit the per-chat header line.")
    # Context-window options (piped mode only).
    ap.add_argument("--before", type=int, default=8,
                    help="Lines shown above each match (piped; default 8).")
    ap.add_argument("--after", type=int, default=3,
                    help="Lines shown below each match (piped; default 3).")
    ap.add_argument("--context-lines-no", dest="context_no", type=int, default=None,
                    help="Total lines per block incl. the match (overrides "
                         "--before/--after, centered); 1 = grep style.")
    ap.add_argument("--max-parts", type=int, default=0,
                    help="Show only the first P match blocks (0 = all).")
    ap.add_argument("--max-lines", type=int, default=0,
                    help="Cap total transcript lines across blocks (0 = all).")
    ap.add_argument("--reverse", action="store_true",
                    help="With a limit set, keep the LAST parts/lines, not first.")
    ap.add_argument("--run-label", default=None)
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)

    ids = list(args.ids)
    piped = False
    pattern = args.pattern
    ignore_case = args.ignore_case
    word = args.word

    if not ids:
        if sys.stdin.isatty():
            ap.print_help()
            return 2
        piped = True
        parsed = _parse_search_stream(sys.stdin.read())
        ids = parsed["ids"]
        if pattern is None:
            pattern = parsed["pattern"]
        if not args.ignore_case:
            ignore_case = parsed["ignore_case"]
        if not args.word:
            word = parsed["word"]

    if not ids:
        print("No chat ids given. Pipe `gpt search` output or pass ids.",
              file=sys.stderr)
        return 1

    rx = sq.build_highlight_regex(pattern, ignore_case=ignore_case,
                                  word=word) if pattern else None
    hl = rx if args.color else None
    context_mode = piped and rx is not None

    n_ok = 0
    for cid in ids:
        text = sq.read_transcript(cid, run_label)
        if not text:
            print(f"[warn] no transcript for id={cid}", file=sys.stderr)
            continue
        n_ok += 1
        if not args.no_header:
            meta = sq.chat_meta(cid, run_label)
            if meta:
                print(f"\n==> {meta['title']}  ({cid})  "
                      f"{_fmt_date(meta['update_date'])} · {meta['n_turns']}t <==")
            else:
                print(f"\n==> ({cid}) <==")
        if context_mode:
            _render_context(text, rx, hl, sq.transcript_path(cid, run_label), args)
        else:
            print(_highlight(text, hl))
    return 0 if n_ok else 1


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
    runs = s.get("runs") or {}
    if runs.get("n_runs"):
        labels = [r.get("label") for r in runs.get("runs", [])[:3] if r.get("label")]
        more = runs["n_runs"] - len(labels)
        shown = " · ".join(labels) + (f" · +{more} more" if more > 0 else "")
        latest = runs.get("latest")
        print(uio.kv("Runs", f"{runs['n_runs']} catalogued"
                     f"{f' · latest {latest}' if latest else ''}", w))
        if shown:
            print(uio.kv("", shown, w))
    return 0


def cmd_show(rest: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gpt show")
    ap.add_argument("slug")
    ap.add_argument("--run-label", default=None)
    ap.add_argument("--json", action="store_true",
                    help="Machine-readable record for piping (FR-U2).")
    args = ap.parse_args(rest)
    run_label = paths.resolve_run_label(args.run_label)
    s4 = sq.summary_state(run_label)
    if s4 and s4.get("schema") == "items":
        with open(s4["path"], encoding="utf-8") as f:
            doc = json.load(f)
        for it in doc.get("items", []):
            if it.get("slug") == args.slug:
                if args.json:
                    print(json.dumps(it, ensure_ascii=False, indent=2))
                    return 0
                pa = it.get("primary_archetype") or {}
                dp = it.get("primary_domain_pair") or {}
                print(f"# {it.get('title', args.slug)}  ({args.slug})")
                print(f"archetype : {pa.get('id')}")
                print(f"domain    : {dp.get('domain')}"
                      + (f"/{dp.get('subdomain')}" if dp.get('subdomain') else ""))
                print(f"goal      : {it.get('goal', '')}")
                src = it.get("classification_source")
                if src:
                    print(f"source    : {src}"
                          + ("" if it.get("llm_ok", True) else " (LLM failed — fallback)"))
                if it.get("description"):
                    print(f"\n{it['description']}")
                return 0
    # Fall back to cluster info + bundle path.
    for c in sq.load_clusters(run_label):
        if c.get("slug") == args.slug:
            bundle = os.path.join(sq.store_paths(run_label)["bundles"],
                                  f"{args.slug}.md")
            if args.json:
                print(json.dumps({
                    "slug": args.slug, "summarized": False,
                    "n_conversations": c.get("n_conversations", 0),
                    "n_versions": c.get("n_versions", 0),
                    "start_date": c.get("start_date"),
                    "end_date": c.get("end_date"),
                    "bundle": bundle, "bundle_exists": os.path.exists(bundle),
                }, ensure_ascii=False, indent=2))
                return 0
            print(f"# {sq.human_title(args.slug)}  ({args.slug})")
            print(f"chats     : {c.get('n_conversations', 0)}")
            print(f"versions  : {c.get('n_versions', 0)}")
            print(f"dates     : {_fmt_date(c.get('start_date'))} → "
                  f"{_fmt_date(c.get('end_date'))}")
            print(f"bundle    : {bundle}" + (" (missing)" if not os.path.exists(bundle) else ""))
            print("\n(no AI summary yet — run `gpt summarize`)")
            return 0
    if args.json:
        print(json.dumps({"slug": args.slug, "found": False}))
        return 1
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
    # numpy backs the semantic index (gpt index / gpt ask); optional elsewhere.
    try:
        import numpy as _np  # noqa: F401
        print(uio.kv("numpy", f"ok (gpt index/ask) · {_np.__version__}", w))
    except ImportError:
        print(uio.kv("numpy", "MISSING — gpt index/ask disabled (bash setup.sh)", w))

    st = sq.catalog_state(run_label)
    data_root = st['data_root']
    writable = os.access(data_root, os.W_OK) if os.path.isdir(data_root) else False
    print(uio.kv("Data root", f"{data_root} "
                 f"({'writable' if writable else 'NOT writable / missing'})", w))
    print(uio.kv("Parsed", f"{'yes' if st['has_store'] else 'no'} "
                 f"({uio.chats(st['n_chats'])}, {uio.projects(st['n_projects'])})", w))

    # GPU readiness for local Ollama + power metering (NFR-R2 / FR-B6).
    try:
        import power as _power  # noqa: E402  (scripts/lib on sys.path)
        gpu = "nvidia-smi present (GPU metering available)" if \
            _power.nvidia_smi_available() else "no nvidia-smi (CPU only; local LLM slow)"
    except Exception:
        gpu = "unknown"
    print(uio.kv("GPU", gpu, w))

    print("Providers")
    for name in provider_detect.DEFAULT_ORDER:
        _prov, notes = provider_detect.detect_provider(order=(name,), cfg=cfg)
        print(f"  {name:<8} {notes[-1].split(': ', 1)[-1] if notes else 'unknown'}")

    _print_summarize_recipes(cfg)
    return 0


def _print_summarize_recipes(cfg: dict) -> None:
    """Copy-paste commands for running the AI summary on selected models.

    The Extract->Cluster->Bundle input is deterministic, so `--limit N` feeds the
    SAME N projects to every model — the basis for a fair speed/quality compare.
    """
    import ollama_probe  # noqa: E402  (scripts/lib on sys.path)

    lw = 24
    print()
    print("Run AI summary on selected models")
    print("  Deterministic input · --limit N picks the same N projects for every model")
    print(f"  {'full model bank':<{lw}} ./gpt summarize            (no args: list every model by name)")
    print(f"  {'run by name only':<{lw}} ./gpt summarize --model <NAME>   (provider auto-filled from the bank)")
    print(f"  {'codex (ChatGPT plan)':<{lw}} ./gpt summarize --limit 10")
    print(f"  {'any ollama model':<{lw}} ./gpt summarize --limit 10 --provider ollama --model <MODEL>")
    print(f"  {'isolate a run':<{lw}} add --run-label <NAME>  (writes runs/<NAME>/, leaves other data untouched)")
    print(f"  {'rank speed + quality':<{lw}} ./gpt arena")

    host = (cfg.get("ollama") or {}).get("host")
    if not ollama_probe.host_available(host):
        print("  ollama models            host unreachable — start `ollama serve`, then re-run `./gpt doctor`")
        return
    models = ollama_probe.discover_models(host)
    # Embedding models can't generate text, so they're not usable for summarize.
    usable = [m for m in models if (m.get("role") or "generation") != "embedding"]
    if not usable:
        print("  ollama models            no text models installed — `ollama pull <model>`, then re-run `./gpt doctor`")
        return
    skipped = len(models) - len(usable)
    note = f" ({skipped} embedding-only hidden)" if skipped else ""
    print(f"  Installed ollama models ({len(usable)}){note} — copy a line to run:")
    for m in sorted(usable, key=lambda x: -(x.get("size_gb") or 0)):
        name = m.get("name", "")
        role = m.get("role") or "generation"
        size = m.get("size_gb")
        tag = f"  # {role}" + (f", {size:.1f} GB" if isinstance(size, (int, float)) else "")
        print(f"    ./gpt summarize --limit 10 --provider ollama --model {name}{tag}")


NATIVE = {
    "status": cmd_status,
    "list": cmd_list,
    "project": cmd_project,
    "category": cmd_category,
    "search": cmd_search,
    "cat": cmd_cat,
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

  Find chats by content or attached files
    gpt search meeting                  # chats whose text contains "meeting"
    gpt search -i usage_events          # case-insensitive text search
    gpt search -w usage                 # whole-word match (not "usaged")
    gpt search -a usage_events          # text + title + filenames mentioned
    gpt search -f usage_events.csv      # chats where that file was attached/seen

  Ask your chats a question (semantic, local via Ollama, $0, cited sources)
    gpt index                                  # build the index first (one time)
    gpt ask "what is the latest stable ados-profile version?"
    gpt ask "what is the ados-geometry concept?" --k 10
    gpt ask "..." --json                       # machine-readable answer + sources

  Verify ask quality (does it actually answer correctly?)
    gpt ask-eval                               # grade the 12-question battery
    gpt ask-eval --no-entity-route             # A/B: disable version routing
    gpt build-entities --show                  # show the version/stability facts ask cites

  Read matching chats (piped = context windows around each match; --color highlights)
    gpt search -i usage_events | gpt cat --color
    gpt search usage_events | gpt cat --before 5 --after 2     # tune the window
    gpt search usage_events | gpt cat --context-lines-no 1     # grep style (lineno:line)
    gpt search usage_events | gpt cat --max-parts 2 --reverse  # last 2 matches
    gpt cat <chat-id> --pattern usage --color                 # standalone: whole chat

  List the model bank (every model you can run by name; provider auto-filled)
    gpt summarize                 # no args -> prints the bank
    gpt summarize --list-models

  Run a model by NAME only (provider + options come from the model bank)
    gpt summarize --model composer-2.5 --limit 10
    gpt summarize --model gpt-oss:20b --limit 10

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
    cmd = ALIASES.get(cmd, cmd)
    if cmd in ("-h", "--help", "help"):
        _usage()
        return 0
    if cmd == "ollama-test":
        try:
            return interrupt.propagate_child(
                subprocess.run([os.path.join(REPO, "ollama_test.sh"), *rest]).returncode)
        except KeyboardInterrupt:
            return interrupt.SIGINT_EXIT
    if cmd in DELEGATED:
        script_rel, prefix = DELEGATED[cmd]
        return _delegate(script_rel, prefix, rest)
    if cmd in NATIVE:
        try:
            return NATIVE[cmd](rest)
        except KeyboardInterrupt:
            interrupt.report(f"gpt {cmd}")
            return interrupt.SIGINT_EXIT
    sys.stderr.write(f"[error] unknown command: {cmd}\n\n")
    _usage()
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
