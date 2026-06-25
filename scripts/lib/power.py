"""
power.py — optional GPU power metering for the benchmark (FR-B6).

Samples `nvidia-smi --query-gpu=power.draw` in a background thread during a run
and writes a power trace (JSONL of {t, w}). The energy used (watt-hours) is the
time-integral of power, so `gpt metrics` can report Wh/item alongside $/1,000
items and decide the keep-vs-return economics on MEASURED, not estimated, power.

Degrades gracefully: if nvidia-smi is absent the meter is a no-op (the run still
works, just without a power trace).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from typing import Optional


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def _sample_watts(gpu_index: int, timeout: float = 5.0) -> Optional[float]:
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--id={gpu_index}",
             "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout, check=True,
        ).stdout.strip().splitlines()
    except (OSError, subprocess.SubprocessError):
        return None
    if not out:
        return None
    try:
        return float(out[0].strip())
    except ValueError:
        return None


def energy_wh_from_trace(path: str) -> tuple[float, float, int]:
    """Trapezoidal integral of a power trace → (watt_hours, duration_s, n)."""
    samples: list[tuple[float, float]] = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                    samples.append((float(e["t"]), float(e["w"])))
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    continue
    except OSError:
        return 0.0, 0.0, 0
    if len(samples) < 2:
        return 0.0, 0.0, len(samples)
    samples.sort()
    joules = 0.0
    for (t0, w0), (t1, w1) in zip(samples, samples[1:]):
        dt = t1 - t0
        if dt > 0:
            joules += (w0 + w1) / 2.0 * dt           # W·s
    duration = samples[-1][0] - samples[0][0]
    return joules / 3600.0, duration, len(samples)   # J→Wh


class PowerMeter:
    """Context manager that samples GPU power into a JSONL trace.

    Usage:
        with PowerMeter(path) as meter:
            ... run work ...
        wh = meter.summary()["wh"]
    """

    def __init__(self, out_path: str, interval: float = 1.0, gpu_index: int = 0):
        self.out_path = out_path
        self.interval = max(0.2, interval)
        self.gpu_index = gpu_index
        self.available = nvidia_smi_available()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._fh = None

    def __enter__(self) -> "PowerMeter":
        if not self.available:
            return self
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
            w = _sample_watts(self.gpu_index)
            if w is not None and self._fh is not None:
                self._fh.write(json.dumps({"t": time.time(), "w": w}) + "\n")
                self._fh.flush()
            self._stop.wait(self.interval)

    def summary(self) -> dict:
        if not self.available:
            return {"available": False, "wh": 0.0, "duration_s": 0.0, "n": 0}
        wh, duration, n = energy_wh_from_trace(self.out_path)
        return {"available": True, "wh": round(wh, 4),
                "duration_s": round(duration, 1), "n": n}
