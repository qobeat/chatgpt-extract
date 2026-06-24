#!/usr/bin/env python3
"""
run.py — orchestrate the deterministic pipeline (Stages 1-3: extract -> cluster
-> classify -> bundle), optionally chaining Stage 4 (multi-provider LLM summary)
with --summarize.

Usage:
  python run.py --zip /path/a.zip --zip /path/b.zip
  python run.py --zip /path/a.zip --summarize --provider ollama --model gpt-oss:20b
  python run.py --zip /path/a.zip --summarize --provider openai --model gpt-5-mini --max-usd 2 --yes
  # Stage 4 separately:
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
        description="Orchestrate deterministic Stages 1-3 (extract -> cluster -> "
                    "classify -> bundle). Add --summarize to chain Stage 4 "
                    "(multi-provider LLM) in one shot.")
    ap.add_argument("--zip", action="append", dest="zips", metavar="PATH",
                    help="Export .zip (repeatable). Falls back to 'default_zips' "
                         "in config/reconstruct.config.local.json.")
    ap.add_argument("--run-label", default=None,
                    help="Isolate output under output/runs/<label>/.")
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
    # Stage 4 chaining
    ap.add_argument("--summarize", action="store_true",
                    help="One-shot: after Stages 1-3, run Stage 4 (LLM).")
    ap.add_argument("--provider", default="ollama",
                    choices=["ollama", "openai", "anthropic", "cursor"])
    ap.add_argument("--model", default=None)
    ap.add_argument("--num-ctx", type=int, default=None)
    ap.add_argument("--max-usd", type=float, default=None)
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    char_budget = args.char_budget if args.char_budget is not None else default_char_budget
    run_label = args.run_label

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
        sum_args = ["--provider", args.provider, "--store", store,
                    "--bundles", bundles, "--min-versions", str(args.min_versions)]
        if run_label:
            sum_args += ["--run-label", run_label]
        if args.model:
            sum_args += ["--model", args.model]
        if args.num_ctx is not None:
            sum_args += ["--num-ctx", str(args.num_ctx)]
        if args.max_usd is not None:
            sum_args += ["--max-usd", str(args.max_usd)]
        if args.yes:
            sum_args.append("--yes")
        sys.stderr.write("\n[run] Stages 1-3 done; chaining into Stage 4 "
                         "(--summarize)\n")
        return run_rc("summarize.py", *sum_args)

    out_json = paths.reconstructed_json(run_label=run_label)
    hint = f"./ollama.sh --provider {args.provider}"
    if args.model:
        hint += f" --model {args.model}"
    if run_label:
        hint += f" --run-label {run_label}"
    sys.stderr.write(
        "\n[next] LLM summary step (Stage 4):\n"
        f"  {hint}\n"
        f"\n  Full JSON lands at: {out_json}\n"
        "  Publish to GitHub:  python scripts/export_public.py --review\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
