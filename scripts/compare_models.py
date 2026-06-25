#!/usr/bin/env python3
"""
compare_models.py — benchmark Ollama models on an isolated run's bundle set.

Runs the AI summary per model against output/runs/<label>/bundles and writes a
comparison report with timing, JSON-valid rate, and ollama-test probe metrics.

Usage:
  ./run.sh --zip export.zip --run-label modeltest --limit 50
  python scripts/compare_models.py --run-label modeltest --limit-clusters 5
  python scripts/compare_models.py --run-label modeltest --models gpt-oss:20b qwen2.5-coder:14b
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "lib"))
import paths  # noqa: E402
import ollama_probe  # noqa: E402


def _fill_rate(item: dict) -> float:
    """Coverage of the ADOS-meaningful fields, incl. archetype_fields contract."""
    filled = 0
    total = 0
    for k in ("goal", "objectives"):
        total += 1
        val = item.get(k)
        if (isinstance(val, list) and val) or (isinstance(val, str) and val.strip()):
            filled += 1
    af = item.get("archetype_fields") or {}
    for v in af.values():
        total += 1
        if (isinstance(v, list) and v) or (isinstance(v, str) and v.strip()):
            filled += 1
    return filled / total if total else 0.0


def _classified_rate(items: list[dict]) -> float:
    """Fraction with a valid primary archetype + domain + non-empty goal."""
    if not items:
        return 0.0
    ok = sum(1 for p in items
             if (p.get("primary_archetype") or {}).get("id")
             and (p.get("primary_domain_pair") or {}).get("domain")
             and (p.get("goal") or "").strip())
    return ok / len(items)


def _run_summarize(run_label: str, model: str, limit_clusters: int,
                   host: str | None, out_path: str, extra: list[str],
                   provider: str = "ollama") -> tuple[int, float]:
    cmd = [
        sys.executable,
        os.path.join(HERE, "summarize.py"),
        "--provider", provider,
        "--run-label", run_label,
        "--model", model,
        "--out", out_path,
        "--no-preflight",
        "--yes",
    ]
    if limit_clusters > 0:
        cmd += ["--limit", str(limit_clusters)]
    if host:
        cmd += ["--host", host]
    cmd += extra
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=ROOT)
    return proc.returncode, time.time() - t0


def _probe_metrics(model: str, host: str | None) -> dict[str, Any]:
    result = ollama_probe.run_generation_probe(model, host=host, timeout=120)
    if not result:
        return {"probe_available": False}
    metrics = result.get("metrics") or {}
    return {
        "probe_available": True,
        "probe_status": result.get("status"),
        "probe_total_ms": metrics.get("total_ms"),
        "probe_tokens_per_sec": metrics.get("visible_tokens_per_sec"),
        "probe_eval_tokens": metrics.get("eval_tokens"),
    }


def _load_items(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("items") or data.get("projects") or []


def _write_report(run_label: str, rows: list[dict]) -> str:
    run_dir = paths.run_root(run_label)
    out_path = os.path.join(run_dir, "model_comparison.md")
    lines = [
        f"# Model comparison — run `{run_label}`",
        "",
        "| Model | Probe tok/s | Summarize s | Items | Classified | Field fill | Exit |",
        "|-------|-------------|-------------|-------|------------|------------|------|",
    ]
    for r in rows:
        tps = r.get("probe_tokens_per_sec")
        tps_s = f"{tps:.3f}" if isinstance(tps, (int, float)) else "n/a"
        lines.append(
            f"| {r['model']} | {tps_s} | {r['summarize_seconds']:.1f} | "
            f"{r['n_items']} | {r['classified_rate']:.0%} | "
            f"{r['fill_rate']:.0%} | {r['exit_code']} |"
        )
    lines += [
        "",
        "## Notes",
        "",
        "- **Probe tok/s**: quick smoke from `ollama-test` (`run_generation_probe`).",
        "- **Summarize s**: wall time for the AI summary on this run's bundles.",
        "- **Classified**: items with a valid primary archetype + domain + goal.",
        "- **Field fill**: coverage of goal/objectives + archetype-contract fields.",
        "",
        f"Per-model JSON: `{run_dir}/by-model/<model>.json`",
        "",
        "Ad-hoc diagnostics: `./ollama_test.sh models` or `./ollama_test.sh test <model>`",
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return out_path


def main() -> int:
    cfg = paths.load_config()
    ollama_cfg = cfg.get("ollama") or {}
    default_host = ollama_cfg.get("host")

    ap = argparse.ArgumentParser(
        description="Compare Ollama models on an isolated run's bundle set.")
    ap.add_argument("--run-label", required=True,
                    help="Isolated run label (output/runs/<label>/).")
    ap.add_argument("--provider", default="ollama",
                    help="LLM provider to benchmark (default: ollama).")
    ap.add_argument("--models", nargs="*", default=None,
                    help="Models to test (default: all installed via ollama_probe).")
    ap.add_argument("--limit-clusters", type=int, default=0,
                    help="Summarize only first N clusters per model (0 = all).")
    ap.add_argument("--host", default=None,
                    help=f"Ollama host (default: {default_host or 'from config'}).")
    ap.add_argument("--skip-probe", action="store_true",
                    help="Skip ollama-test generation probe before summarize.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pass --dry-run to summarize (no LLM calls).")
    args = ap.parse_args()

    host = args.host or default_host
    run_label = args.run_label
    run_dir = paths.run_root(run_label)
    bundles = paths.bundles_dir(run_label=run_label)

    if not os.path.isdir(bundles):
        sys.stderr.write(
            f"[error] Bundles not found: {bundles}\n"
            f"        Run first: ./run.sh --zip <export.zip> --run-label {run_label} --limit 50\n"
        )
        return 1

    models = args.models
    if not models:
        models = ollama_probe.installed_models(host)
    if not models:
        sys.stderr.write("[error] No models found. Check Ollama or pass --models.\n")
        return 1

    by_model_dir = os.path.join(run_dir, "by-model")
    os.makedirs(by_model_dir, exist_ok=True)

    rows: list[dict] = []
    summarize_extra = ["--dry-run"] if args.dry_run else []

    for model in models:
        sys.stderr.write(f"\n[run] model={model}\n")
        skip_probe = args.skip_probe or args.dry_run or args.provider != "ollama"
        probe = {} if skip_probe else _probe_metrics(model, host)

        safe_name = model.replace(":", "_").replace("/", "_")
        out_json = os.path.join(by_model_dir, f"{safe_name}.json")
        exit_code, elapsed = _run_summarize(
            run_label, model, args.limit_clusters, host, out_json, summarize_extra,
            provider=args.provider,
        )
        items = _load_items(out_json)
        row = {
            "model": model,
            "exit_code": exit_code,
            "summarize_seconds": elapsed,
            "n_items": len(items),
            "classified_rate": _classified_rate(items),
            "fill_rate": (
                sum(_fill_rate(p) for p in items) / len(items)
                if items else 0.0
            ),
            **probe,
        }
        rows.append(row)
        sys.stderr.write(
            f"  summarize={elapsed:.1f}s items={len(items)} exit={exit_code}\n"
        )

    report = _write_report(run_label, rows)
    sys.stderr.write(f"\n[done] Report: {report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
