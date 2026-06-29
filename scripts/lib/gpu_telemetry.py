"""
gpu_telemetry.py — full GPU telemetry capture + aggregation (schema-backed).

Single source of truth for "what the GPU did during a run". Samples EVERY field
`nvidia-smi` exposes (power, power-limit, temperature, GPU/mem utilization, VRAM,
SM/mem clocks, fan, pstate) once per interval into a JSONL ledger (gpu_trace.jsonl,
one `gpu-telemetry-sample/1` object per line), then aggregates the ledger into a
`gpu-telemetry-summary/1` object (avg/peak/min per metric + energy Wh + throttle
flag). Both shapes are validated by schema/gpu_telemetry.schema.json.

Design notes:
  * Every metric is nullable, so capture degrades gracefully on a host without
    full telemetry, and OLD runs can be back-filled with `null_summary()`.
  * Energy (Wh) is the trapezoidal time-integral of power_w — measured, not
    estimated — so economics tables use real watt-hours.
  * `summarize_trace` also reads the LEGACY power_trace.jsonl ({t, w}) so existing
    generation-benchmark traces aggregate into the same summary shape.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from typing import Optional

SCHEMA_SAMPLE = "gpu-telemetry-sample/1"
SCHEMA_SUMMARY = "gpu-telemetry-summary/1"

# RTX 3090 begins thermal throttling around here; used only for the `throttled` flag.
THROTTLE_TEMP_C = 83.0

# (nvidia-smi query field, ledger key, is_numeric)
_QUERY_FIELDS: tuple[tuple[str, str, bool], ...] = (
    ("power.draw", "power_w", True),
    ("power.limit", "power_limit_w", True),
    ("temperature.gpu", "temp_c", True),
    ("utilization.gpu", "util_gpu_pct", True),
    ("utilization.memory", "util_mem_pct", True),
    ("memory.used", "mem_used_mib", True),
    ("memory.total", "mem_total_mib", True),
    ("clocks.sm", "clock_sm_mhz", True),
    ("clocks.mem", "clock_mem_mhz", True),
    ("fan.speed", "fan_pct", True),
    ("pstate", "pstate", False),
    ("name", "_gpu_name", False),
)

# Metrics summarized as avg/peak/min in the run summary.
STAT_FIELDS = ("power_w", "temp_c", "util_gpu_pct", "util_mem_pct",
               "mem_used_mib", "fan_pct", "clock_sm_mhz")


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def _parse_float(s: str) -> Optional[float]:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def sample(gpu_index: int = 0, timeout: float = 5.0) -> Optional[dict]:
    """One full nvidia-smi sample as a `gpu-telemetry-sample/1` dict (+ _gpu_name).

    Returns None if nvidia-smi is unavailable or the query fails. Unparseable
    fields are set to None rather than dropped.
    """
    if not nvidia_smi_available():
        return None
    query = ",".join(q for q, _k, _n in _QUERY_FIELDS)
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--id={gpu_index}",
             f"--query-gpu={query}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    parts = [p.strip() for p in out[0].split(",")]
    rec: dict = {"t": time.time(), "gpu_index": gpu_index}
    for i, (_q, key, numeric) in enumerate(_QUERY_FIELDS):
        raw = parts[i] if i < len(parts) else ""
        if numeric:
            rec[key] = _parse_float(raw)
        else:
            rec[key] = raw if raw and raw.upper() not in ("[N/A]", "N/A") else None
    return rec


def _ledger_sample(gpu_index: int) -> Optional[dict]:
    """A sample with the non-schema `_gpu_name` helper key stripped out."""
    rec = sample(gpu_index)
    if rec is None:
        return None
    rec.pop("_gpu_name", None)
    return rec


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def _stat3(xs: list[float]) -> dict:
    if not xs:
        return {"avg": None, "peak": None, "min": None}
    return {"avg": round(sum(xs) / len(xs), 2),
            "peak": round(max(xs), 2), "min": round(min(xs), 2)}


def null_summary() -> dict:
    """A schema-valid summary with everything null — for cloud or back-filled runs."""
    s = {"schema": SCHEMA_SUMMARY, "available": False, "gpu_name": None,
         "gpu_index": None, "n_samples": 0, "interval_s": None,
         "duration_s": None, "energy_wh": None, "power_limit_w": None,
         "throttled": None}
    for f in STAT_FIELDS:
        s[f] = {"avg": None, "peak": None, "min": None}
    return s


def summarize_trace(path: str, *, interval_s: float | None = None,
                    gpu_name: str | None = None) -> dict:
    """Aggregate a gpu_trace.jsonl (or legacy power_trace.jsonl) into a summary.

    Reads each JSONL line; tolerates the legacy {t, w} power trace by mapping
    `w` -> power_w. Returns a `gpu-telemetry-summary/1` dict. If no usable
    samples are found, returns `null_summary()`.
    """
    series: dict[str, list[float]] = {f: [] for f in STAT_FIELDS}
    power_pts: list[tuple[float, float]] = []
    limits: list[float] = []
    ts: list[float] = []
    name = gpu_name
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                # Legacy power trace compatibility: {"t", "w"}.
                if "power_w" not in e and isinstance(e.get("w"), (int, float)):
                    e["power_w"] = float(e["w"])
                t = e.get("t")
                if isinstance(t, (int, float)):
                    ts.append(float(t))
                pw = e.get("power_w")
                if isinstance(t, (int, float)) and isinstance(pw, (int, float)):
                    power_pts.append((float(t), float(pw)))
                if isinstance(e.get("power_limit_w"), (int, float)):
                    limits.append(float(e["power_limit_w"]))
                if name is None and e.get("gpu_name"):
                    name = e["gpu_name"]
                for fld in STAT_FIELDS:
                    v = e.get(fld)
                    if isinstance(v, (int, float)):
                        series[fld].append(float(v))
    except OSError:
        return null_summary()

    n = len(ts)
    if n == 0:
        return null_summary()

    energy_wh = _energy_wh(power_pts)
    duration_s = round(max(ts) - min(ts), 1) if len(ts) >= 2 else 0.0
    temps = series["temp_c"]
    peak_temp = max(temps) if temps else None
    summary = {
        "schema": SCHEMA_SUMMARY,
        "available": True,
        "gpu_name": name,
        "gpu_index": None,
        "n_samples": n,
        "interval_s": interval_s,
        "duration_s": duration_s,
        "energy_wh": round(energy_wh, 4) if energy_wh is not None else None,
        "power_limit_w": round(max(limits), 1) if limits else None,
        "throttled": (peak_temp >= THROTTLE_TEMP_C) if peak_temp is not None else None,
    }
    for fld in STAT_FIELDS:
        summary[fld] = _stat3(series[fld])
    return summary


def _energy_wh(points: list[tuple[float, float]]) -> Optional[float]:
    """Trapezoidal integral of (t, watts) points -> watt-hours."""
    if len(points) < 2:
        return None
    points = sorted(points)
    joules = 0.0
    for (t0, w0), (t1, w1) in zip(points, points[1:]):
        dt = t1 - t0
        if dt > 0:
            joules += (w0 + w1) / 2.0 * dt
    return joules / 3600.0


# ---------------------------------------------------------------------------
# Background meter
# ---------------------------------------------------------------------------
class GpuTelemetry:
    """Context manager that samples full GPU telemetry into a JSONL ledger.

    Usage:
        with GpuTelemetry(path, interval=0.5) as tele:
            ... run GPU work ...
        summary = tele.summary()      # gpu-telemetry-summary/1 dict
    """

    def __init__(self, out_path: str, interval: float = 1.0, gpu_index: int = 0):
        self.out_path = out_path
        self.interval = max(0.2, interval)
        self.gpu_index = gpu_index
        self.available = nvidia_smi_available()
        self.gpu_name: Optional[str] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fh = None

    def __enter__(self) -> "GpuTelemetry":
        if not self.available:
            return self
        first = sample(self.gpu_index)
        if first is not None:
            self.gpu_name = first.get("_gpu_name")
        self._fh = open(self.out_path, "w", encoding="utf-8")
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval * 2 + 5)
        if self._fh is not None:
            self._fh.flush()
            self._fh.close()
            self._fh = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            rec = _ledger_sample(self.gpu_index)
            if rec is not None and self._fh is not None:
                self._fh.write(json.dumps(rec) + "\n")
                self._fh.flush()
            self._stop.wait(self.interval)

    def summary(self) -> dict:
        if not self.available:
            return null_summary()
        return summarize_trace(self.out_path, interval_s=self.interval,
                               gpu_name=self.gpu_name)
