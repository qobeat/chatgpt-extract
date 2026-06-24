#!/usr/bin/env python3
"""
run.py — orchestrate the deterministic build steps (Extract -> Cluster ->
Bundle), optionally chaining the AI summary step (Summarize, multi-provider)
with --summarize.

Usage:
  python run.py --zip /path/a.zip --zip /path/b.zip
  python run.py --zip /path/a.zip --summarize --provider ollama --model gpt-oss:20b
  python run.py --zip /path/a.zip --summarize --provider openai --model gpt-5-mini --max-usd 2 --yes
  # AI summary separately:
  python scripts/summarize.py --provider anthropic --model claude-sonnet-4 --run-label modeltest
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "scripts", "lib"))
import paths  # noqa: E402
import run_log  # noqa: E402
import confirm  # noqa: E402
import zip_ledger  # noqa: E402


def run(mod: str, *cli: str):
    cmd = [sys.executable, os.path.join(HERE, "scripts", mod), *cli]
    sys.stderr.write("[run] " + " ".join(cmd) + "\n")
    subprocess.run(cmd, check=True)


def run_rc(mod: str, *cli: str) -> int:
    cmd = [sys.executable, os.path.join(HERE, "scripts", mod), *cli]
    sys.stderr.write("[run] " + " ".join(cmd) + "\n")
    return subprocess.run(cmd).returncode


def main() -> int:
    cfg = paths.load_config()
    default_char_budget = cfg.get("char_budget_per_bundle", 48000)

    ap = argparse.ArgumentParser(
        description="Orchestrate the deterministic build steps "
                    "(Extract -> Cluster -> Bundle). Add --summarize to chain "
                    "the AI summary step (Summarize, multi-provider) in one shot.")
    ap.add_argument("--zip", action="append", dest="zips", metavar="PATH",
                    help="Export .zip (repeatable). Falls back to 'default_zips' "
                         "in config/reconstruct.config.local.json.")
    ap.add_argument("--run-label", default=None,
                    help="Optional: isolate under runs/<label>/ (updates runs/latest). "
                         "Omit for default store/bundles at data root. "
                         "Use 'latest' to target the most recent labeled run.")
    ap.add_argument("--limit", type=int, default=0,
                    help="Process only the first N new/changed conversations (0=all).")
    ap.add_argument("--store", default=None)
    ap.add_argument("--bundles", default=None)
    ap.add_argument("--min-slug-votes", type=int, default=3)
    ap.add_argument("--merge-cap", type=int, default=12,
                    help="Mega-merge guard for generic title slugs (see cluster_projects).")
    ap.add_argument("--char-budget", type=int, default=None,
                    help=f"Max chars per LLM bundle (default: {default_char_budget}).")
    ap.add_argument("--min-versions", type=int, default=1,
                    help="Bundle only clusters with >= N version zips (default 1; 0=all).")
    ap.add_argument("--verbose", action="store_true")
    # AI summary chaining
    ap.add_argument("--summarize", action="store_true",
                    help="One-shot: after the build steps, run the AI summary step.")
    ap.add_argument("--provider", default=None,
                    choices=["ollama", "openai", "anthropic", "cursor",
                             "codex", "claude"],
                    help="AI summary provider (with --summarize). Default: "
                         "auto-detect codex -> ollama -> claude.")
    ap.add_argument("--model", default=None)
    ap.add_argument("--num-ctx", type=int, default=None)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--limit-summarize", type=int, default=0,
                    help="Cap the AI summary to the first N projects (with --summarize).")
    ap.add_argument("--yes", "--noask", dest="noask", action="store_true",
                    help="Skip the AI summary confirmation prompt.")
    args = ap.parse_args()

    char_budget = args.char_budget if args.char_budget is not None else default_char_budget
    run_label = paths.resolve_run_label(args.run_label)
    if args.run_label == "latest" and not run_label:
        ap.error("No runs/latest pointer — pass an explicit --run-label or run "
                 "the build steps with a label first.")

    zips = args.zips
    if not zips:
        cfg_zips = cfg.get("default_zips") or []
        zips = [os.path.expanduser(z) for z in cfg_zips if z
                and not z.startswith("/path/to/")]
        if zips:
            sys.stderr.write(
                f"[run] No --zip given; using {len(zips)} default_zips from config.\n")
    if not zips:
        ap.error("No export .zip provided. Pass --zip PATH or set 'default_zips' "
                 "in config/reconstruct.config.local.json.")

    store = paths.store_dir(args.store, run_label=run_label)
    bundles = paths.bundles_dir(args.bundles, run_label=run_label)
    root = paths.run_data_root(store=store, run_label=run_label)

    if run_label:
        os.makedirs(store, exist_ok=True)
        os.makedirs(bundles, exist_ok=True)
        paths.update_latest_pointer(run_label)
        sys.stderr.write(f"[run] Isolated run: {paths.run_root(run_label)}\n")

    # --- pre-flight: notify on already-handled zips + warn before a long run ---
    total_bytes = 0
    handled: list[tuple[str, dict]] = []
    present_zips = 0
    for z in zips:
        if not os.path.exists(z):
            continue
        present_zips += 1
        try:
            total_bytes += os.path.getsize(z)
        except OSError:
            pass
        prior = zip_ledger.lookup(store, z)
        if prior is not None:
            handled.append((z, prior))

    notice_lines: list[str] = []
    for z, prior in handled:
        first = (prior.get("first_processed") or "")[:10]
        notice_lines.append(
            f"[note] Already handled: {os.path.basename(z)} "
            f"(first seen {first or '?'}, {prior.get('seen', 0):,} conversations). "
            f"Re-scan will skip unchanged conversations.")
    notice = "\n".join(notice_lines)

    est_seconds = confirm.estimate_extract_seconds(total_bytes)
    # All provided (present) zips already handled = a likely-wasted re-scan: ask
    # even if the estimate is under the long-run threshold.
    all_handled = present_zips > 0 and len(handled) == present_zips
    if not confirm.gate_long_action(
            "the build steps (Extract -> Cluster -> Bundle)", est_seconds,
            notice=notice, force_prompt=all_handled, noask=args.noask):
        sys.stderr.write("[run] Declined; nothing parsed.\n")
        return 3

    run_log.append_command(" ".join(["./run.sh"] + sys.argv[1:]), root)
    run_log.record_run_start(root)

    zip_args = []
    for z in zips:
        zip_args += ["--zip", z]

    extract_args = [*zip_args, "--out", store]
    if args.limit > 0:
        extract_args += ["--limit", str(args.limit)]
    if args.verbose:
        extract_args.append("--verbose")
    run_log.stage_start("extract", root)
    run("extract_cards.py", *extract_args)
    run_log.stage_end("extract", root)

    run_log.stage_start("cluster", root)
    run("cluster_projects.py", "--store", store,
        "--min-slug-votes", str(args.min_slug_votes),
        "--merge-cap", str(args.merge_cap))
    run_log.stage_end("cluster", root)

    run_log.stage_start("classify", root)
    run("classify.py", "--store", store)
    run_log.stage_end("classify", root)

    run_log.stage_start("bundle", root)
    run("build_bundles.py", "--store", store, "--out", bundles,
        "--char-budget", str(char_budget),
        "--min-versions", str(args.min_versions))
    run_log.stage_end("bundle", root)

    if args.summarize:
        sum_args = ["--store", store, "--bundles", bundles,
                    "--min-versions", str(args.min_versions)]
        if args.provider:
            sum_args += ["--provider", args.provider]
        if run_label:
            sum_args += ["--run-label", run_label]
        if args.model:
            sum_args += ["--model", args.model]
        if args.num_ctx is not None:
            sum_args += ["--num-ctx", str(args.num_ctx)]
        if args.max_usd is not None:
            sum_args += ["--max-usd", str(args.max_usd)]
        if args.limit_summarize > 0:
            sum_args += ["--limit", str(args.limit_summarize)]
        if args.noask:
            sum_args.append("--noask")
        sys.stderr.write("\n[run] Build steps done (Extract/Cluster/Bundle); "
                         "starting AI summary (--summarize)\n")
        return run_rc("summarize.py", *sum_args)

    out_json = paths.reconstructed_json(run_label=run_label)
    hint = "gpt summarize"
    if args.provider:
        hint += f" --provider {args.provider}"
    if args.model:
        hint += f" --model {args.model}"
    if run_label:
        hint += f" --run-label {run_label}"
    sys.stderr.write(
        "\n[next] AI summary step (Summarize):\n"
        f"  {hint}\n"
        f"\n  Full JSON lands at: {out_json}\n"
        "  Publish to GitHub:  python scripts/export_public.py --review\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
