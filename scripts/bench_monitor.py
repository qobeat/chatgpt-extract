#!/usr/bin/env python3
"""
bench_monitor.py — GPU / Ollama health monitor for the model benchmark sweep.

Why this exists (FR-B6, NFR-R2): a local benchmark is only valid if the model is
actually running ON THE GPU. A reboot (or a too-large KV cache) can silently drop
Ollama into CPU-only mode, where the RTX 3090 sits idle, throughput collapses to
~2 tok/s, and the measured Wh/item + s/item are meaningless. This tool turns that
failure mode (and a few neighbours) into a detectable, fixable signal:

  - `check`  one-shot preflight + GPU-on assertion (optionally `--warm` loads the
             model and verifies `ollama ps` reports it on the GPU). Exit 2 = FATAL.
  - `watch`  samples every --interval seconds while a summarize PID is alive,
             classifies health, appends a JSONL health trace, and exits non-zero
             if it ever saw a FATAL (e.g. CPU spill) so the driver can restart
             Ollama BEFORE the next model.

Detected problems and their fixes (the "monitoring command lines" the benchmark
needs):

  HOST_DOWN     Ollama host unreachable        -> sudo systemctl restart ollama
  CPU_SPILL     model PROCESSOR shows CPU       -> sudo systemctl restart ollama;
                                                   if it recurs, lower --num-ctx
                                                   (KV cache too big for 24 GB) or
                                                   pick a smaller model
  GPU_IDLE      GPU util ~0% during an active   -> check `ollama ps`; restart
                run (stall / silent CPU spill)     ollama if PROCESSOR != GPU
  VRAM_FULL     VRAM >97% used                  -> lower --num-ctx / smaller model
  LOG_ERRORS    error/timeout lines in the run  -> read the log; usually a VRAM
                                                   spill (timeout) or parse failure
  NO_NVIDIA_SMI nvidia-smi missing              -> install NVIDIA drivers in WSL

Dependency-free (urllib + subprocess); degrades gracefully when nvidia-smi or the
Ollama host is absent.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))

DEFAULT_HOST = "http://127.0.0.1:11434"

# problem-code -> (human description, fix command line) -------------------------
FIXES: dict[str, tuple[str, str]] = {
    "HOST_DOWN": (
        "Ollama host unreachable",
        "sudo systemctl restart ollama   # or: ollama serve",
    ),
    "CPU_SPILL": (
        "model is running on CPU (PROCESSOR != 100% GPU) — GPU idle, ~2 tok/s, "
        "invalidates speed/power numbers",
        "sudo systemctl restart ollama   # re-attaches the RTX 3090; if it "
        "recurs, lower --num-ctx or pick a smaller model",
    ),
    "GPU_IDLE": (
        "GPU utilization ~0% while a run is active — likely a CPU spill or a stall",
        "check `ollama ps` PROCESSOR; sudo systemctl restart ollama if not 100% GPU",
    ),
    "VRAM_FULL": (
        "VRAM >97% used — high risk of a CPU spill on the next/large bundle",
        "lower --num-ctx (smaller KV cache) or choose a smaller model",
    ),
    "MODEL_NOT_LOADED": (
        "model is not currently loaded in Ollama",
        "no action — it loads on first call (one-time VRAM load)",
    ),
    "LOG_ERRORS": (
        "error/timeout lines found in the run log",
        "read the log tail; a timeout usually means a VRAM spill (NFR-R2)",
    ),
    "NO_NVIDIA_SMI": (
        "nvidia-smi not found — cannot verify GPU placement or meter power",
        "install NVIDIA drivers / nvidia-utils in WSL",
    ),
}

ERROR_PATTERNS = (
    "error", "timed out", "timeout", "traceback", "vram", "spill",
    "cuda", "out of memory", "oom", "exhausted", "breaker",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --- raw probes ----------------------------------------------------------------
def gpu_snapshot(index: int = 0, timeout: float = 5.0) -> dict:
    """One nvidia-smi sample: name, util%, mem used/total MiB, power W."""
    if shutil.which("nvidia-smi") is None:
        return {"available": False}
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--id={index}",
             "--query-gpu=name,utilization.gpu,memory.used,memory.total,power.draw",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return {"available": False}
    if not out:
        return {"available": False}
    parts = [p.strip() for p in out[0].split(",")]

    def _f(i: int) -> float:
        try:
            return float(parts[i])
        except (IndexError, ValueError):
            return 0.0
    mem_used, mem_total = _f(2), _f(3)
    return {
        "available": True,
        "name": parts[0] if parts else "?",
        "util_pct": _f(1),
        "mem_used_mib": mem_used,
        "mem_total_mib": mem_total,
        "mem_frac": round(mem_used / mem_total, 3) if mem_total else 0.0,
        "power_w": _f(4),
    }


def ollama_ps(host: str = DEFAULT_HOST, timeout: float = 5.0) -> list[dict]:
    """Parse `GET /api/ps` (loaded models + size_vram). Falls back to []."""
    url = host.rstrip("/") + "/api/ps"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8") or "{}")
    except Exception:
        return []
    rows: list[dict] = []
    for m in (data.get("models") or []):
        total = float(m.get("size") or 0)
        vram = float(m.get("size_vram") or 0)
        gpu_frac = (vram / total) if total else 0.0
        rows.append({
            "name": m.get("name") or m.get("model") or "?",
            "size": total,
            "size_vram": vram,
            "gpu_frac": round(gpu_frac, 3),
            # Mirror the `ollama ps` PROCESSOR column semantics.
            "processor": _processor_label(gpu_frac),
        })
    return rows


def _processor_label(gpu_frac: float) -> str:
    if gpu_frac >= 0.99:
        return "100% GPU"
    if gpu_frac <= 0.01:
        return "100% CPU"
    cpu = round((1 - gpu_frac) * 100)
    gpu = round(gpu_frac * 100)
    return f"{cpu}%/{gpu}% CPU/GPU"


def host_up(host: str = DEFAULT_HOST, timeout: float = 3.0) -> bool:
    url = host.rstrip("/") + "/api/version"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def model_loaded_row(rows: list[dict], model: str) -> dict | None:
    if not model:
        return None
    base = model.split(":")[0]
    for r in rows:
        n = r.get("name", "")
        if n == model or n.startswith(base + ":") or n.split(":")[0] == base:
            return r
    return None


def processor_is_gpu(processor: str) -> bool:
    p = (processor or "").upper()
    return "GPU" in p and "CPU" not in p


def scan_log_errors(path: str, tail_bytes: int = 8192) -> list[str]:
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - tail_bytes))
            chunk = f.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    hits = []
    for line in chunk.splitlines():
        low = line.lower()
        if any(p in low for p in ERROR_PATTERNS):
            hits.append(line.strip()[:200])
    return hits[-8:]


# --- classification ------------------------------------------------------------
def classify(model: str, host: str, gpu: dict, ps_rows: list[dict],
             log_errors: list[str], running: bool,
             gpu_idle_strikes: int = 0) -> dict:
    """Return {status, codes, issues, fixes} from a single sample.

    status: OK | WARN | FATAL. FATAL means the current benchmark sample is
    invalid (host down, or the model dropped to CPU)."""
    codes: list[str] = []
    issues: list[str] = []

    if not host_up(host):
        codes.append("HOST_DOWN")
    if not gpu.get("available"):
        codes.append("NO_NVIDIA_SMI")

    row = model_loaded_row(ps_rows, model)
    if row is not None:
        if not processor_is_gpu(row["processor"]):
            codes.append("CPU_SPILL")
            issues.append(f"{row['name']} PROCESSOR={row['processor']} "
                          f"(vram_frac={row['gpu_frac']})")
    elif model and running:
        codes.append("MODEL_NOT_LOADED")

    if gpu.get("available"):
        if gpu.get("mem_frac", 0.0) > 0.97:
            codes.append("VRAM_FULL")
            issues.append(f"VRAM {gpu['mem_used_mib']:.0f}/{gpu['mem_total_mib']:.0f} MiB")
        # GPU idle during an active run, with the model loaded on GPU, for a few
        # consecutive samples => stall. (Idle while loaded-on-CPU is CPU_SPILL.)
        if (running and row is not None and processor_is_gpu(row["processor"])
                and gpu.get("util_pct", 0.0) < 1.0 and gpu_idle_strikes >= 2):
            codes.append("GPU_IDLE")

    if log_errors:
        codes.append("LOG_ERRORS")
        issues.extend(log_errors[-3:])

    fatal = {"HOST_DOWN", "CPU_SPILL"}
    warn = {"VRAM_FULL", "GPU_IDLE", "LOG_ERRORS", "NO_NVIDIA_SMI",
            "MODEL_NOT_LOADED"}
    if any(c in fatal for c in codes):
        status = "FATAL"
    elif any(c in warn for c in codes):
        status = "WARN"
    else:
        status = "OK"
    fixes = [f"{c}: {FIXES[c][1]}" for c in codes if c in FIXES]
    return {"status": status, "codes": codes, "issues": issues, "fixes": fixes}


def sample(model: str, host: str, log: str, running: bool,
           gpu_idle_strikes: int = 0) -> dict:
    gpu = gpu_snapshot()
    rows = ollama_ps(host)
    errs = scan_log_errors(log) if log else []
    health = classify(model, host, gpu, rows, errs, running, gpu_idle_strikes)
    health["t"] = now_iso()
    health["gpu"] = gpu
    health["ps"] = rows
    return health


def _fmt_line(h: dict, model: str) -> str:
    gpu = h.get("gpu", {})
    g = (f"util={gpu.get('util_pct', 0):.0f}% "
         f"mem={gpu.get('mem_used_mib', 0):.0f}/{gpu.get('mem_total_mib', 0):.0f}MiB "
         f"pwr={gpu.get('power_w', 0):.0f}W") if gpu.get("available") else "gpu=n/a"
    row = model_loaded_row(h.get("ps", []), model)
    proc = row["processor"] if row else "(not loaded)"
    extra = ""
    if h["codes"]:
        extra = "  ! " + ",".join(h["codes"])
    return f"[{h['t']}] {h['status']:<5} {model or '-'} | {g} | proc={proc}{extra}"


def restart_ollama(wait_s: float = 6.0) -> bool:
    """Best-effort `sudo systemctl restart ollama` then wait for the host."""
    try:
        subprocess.run(["sudo", "-n", "systemctl", "restart", "ollama"],
                       capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    deadline = time.time() + wait_s + 30
    while time.time() < deadline:
        if host_up():
            return True
        time.sleep(1.0)
    return host_up()


def warm_load(model: str, host: str, num_ctx: int, timeout: float = 120.0) -> bool:
    """Force a 1-token generation so the model loads into VRAM, so a following
    `ollama ps` reports its real CPU/GPU placement."""
    payload = {
        "model": model, "prompt": "ok", "stream": False,
        "keep_alive": "5m",
        "options": {"num_predict": 1, "num_ctx": num_ctx},
    }
    req = urllib.request.Request(
        host.rstrip("/") + "/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


# --- commands ------------------------------------------------------------------
def cmd_check(args) -> int:
    host = args.host or DEFAULT_HOST
    if args.warm and args.model:
        sys.stderr.write(f"[monitor] warming {args.model} (num_ctx={args.num_ctx})...\n")
        warm_load(args.model, host, args.num_ctx)
    h = sample(args.model, host, args.log, running=bool(args.warm))
    print(_fmt_line(h, args.model))
    for iss in h["issues"]:
        print(f"   - {iss}")
    for fix in h["fixes"]:
        print(f"   FIX {fix}")

    if h["status"] == "FATAL" and args.autofix:
        print("[monitor] FATAL — attempting fix: sudo systemctl restart ollama")
        if restart_ollama():
            if args.warm and args.model:
                warm_load(args.model, host, args.num_ctx)
            h = sample(args.model, host, args.log, running=bool(args.warm))
            print("[monitor] after restart: " + _fmt_line(h, args.model))

    if args.json:
        print(json.dumps(h, ensure_ascii=False))
    if h["status"] == "FATAL":
        return 2
    if h["status"] == "WARN" and args.strict:
        return 2
    return 0


def cmd_watch(args) -> int:
    host = args.host or DEFAULT_HOST
    health_fh = open(args.health_out, "w", encoding="utf-8") if args.health_out else None
    worst = "OK"
    fatal_codes: set[str] = set()
    idle_strikes = 0
    i = 0

    def alive() -> bool:
        if args.pid:
            try:
                os.kill(args.pid, 0)
                return True
            except (ProcessLookupError, PermissionError, OSError):
                return False
        return i < args.max_iters

    sys.stderr.write(
        f"[monitor] watch model={args.model} interval={args.interval}s "
        f"pid={args.pid or '(none)'} -> {args.health_out or '(stdout)'}\n")
    while alive():
        gpu_now = gpu_snapshot()
        loaded = model_loaded_row(ollama_ps(host), args.model)
        if (gpu_now.get("available") and gpu_now.get("util_pct", 0.0) < 1.0
                and loaded is not None):
            idle_strikes += 1
        else:
            idle_strikes = 0
        h = sample(args.model, host, args.log, running=True,
                   gpu_idle_strikes=idle_strikes)
        line = _fmt_line(h, args.model)
        print(line, flush=True)
        for fix in h["fixes"]:
            print(f"   FIX {fix}", flush=True)
        if health_fh:
            health_fh.write(json.dumps(h, ensure_ascii=False) + "\n")
            health_fh.flush()
        order = {"OK": 0, "WARN": 1, "FATAL": 2}
        if order[h["status"]] > order[worst]:
            worst = h["status"]
        if h["status"] == "FATAL":
            fatal_codes.update(c for c in h["codes"] if c in {"HOST_DOWN", "CPU_SPILL"})
        i += 1
        # Sleep in small slices so we notice the PID exiting promptly.
        slept = 0.0
        while slept < args.interval and alive():
            time.sleep(min(1.0, args.interval - slept))
            slept += 1.0

    summary = {"t": now_iso(), "model": args.model, "worst_status": worst,
               "fatal_codes": sorted(fatal_codes), "samples": i}
    print(f"[monitor] DONE model={args.model} worst={worst} "
          f"fatal={sorted(fatal_codes) or '-'} samples={i}", flush=True)
    if health_fh:
        health_fh.write(json.dumps({"summary": summary}, ensure_ascii=False) + "\n")
        health_fh.close()
    return 2 if worst == "FATAL" else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="bench_monitor",
        description="GPU/Ollama health monitor for the benchmark sweep.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="one-shot preflight + GPU-on assertion")
    c.add_argument("--model", default="")
    c.add_argument("--host", default=None)
    c.add_argument("--num-ctx", type=int, default=16384)
    c.add_argument("--log", default="")
    c.add_argument("--warm", action="store_true",
                   help="load the model first, then verify it is on the GPU")
    c.add_argument("--autofix", action="store_true",
                   help="on FATAL, restart ollama and re-check once")
    c.add_argument("--strict", action="store_true",
                   help="treat WARN as a non-zero exit too")
    c.add_argument("--json", action="store_true")
    c.set_defaults(func=cmd_check)

    w = sub.add_parser("watch", help="sample every --interval s while a PID runs")
    w.add_argument("--model", default="")
    w.add_argument("--host", default=None)
    w.add_argument("--interval", type=float, default=30.0)
    w.add_argument("--pid", type=int, default=0,
                   help="watch until this PID exits (the summarize process)")
    w.add_argument("--max-iters", type=int, default=10_000,
                   help="fallback bound when no --pid is given")
    w.add_argument("--log", default="", help="run log to scan for error lines")
    w.add_argument("--health-out", default="",
                   help="JSONL health trace path (+ a final summary line)")
    w.set_defaults(func=cmd_watch)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
