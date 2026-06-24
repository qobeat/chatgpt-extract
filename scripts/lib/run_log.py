"""Append-only run log and stage timing for RUN_SUMMARY generation."""
from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _data_root(explicit: str | None = None) -> str:
    if explicit:
        return os.path.abspath(explicit)
    from paths import data_root, store_dir  # noqa: WPS433

    dr = data_root()
    if dr:
        return os.path.abspath(dr)
    # store_dir() -> .../output/store or .../data/store
    return os.path.abspath(os.path.dirname(store_dir()))


def commands_log_path(root: str | None = None) -> str:
    return os.path.join(_data_root(root), "RUN_COMMANDS.log")


def manifest_path(root: str | None = None) -> str:
    return os.path.join(_data_root(root), ".run_manifest.json")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def append_command(cmd: str, root: str | None = None) -> None:
    path = commands_log_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {cmd.strip()}\n")


def read_commands(root: str | None = None, last_n: int = 20) -> str:
    path = commands_log_path(root)
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        lines = [ln.rstrip() for ln in f if ln.strip()]
    if last_n > 0:
        lines = lines[-last_n:]
    # Strip timestamps for display; keep command text only
    out = []
    for ln in lines:
        if ln.startswith("[") and "] " in ln:
            out.append(ln.split("] ", 1)[1])
        else:
            out.append(ln)
    return "\n".join(out)


def load_manifest(root: str | None = None) -> dict[str, Any]:
    path = manifest_path(root)
    if not os.path.exists(path):
        return {"stages": {}, "commands": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(data: dict[str, Any], root: str | None = None) -> None:
    path = manifest_path(root)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def stage_start(name: str, root: str | None = None) -> None:
    data = load_manifest(root)
    data.setdefault("stages", {})[name] = {"started_utc": _now()}
    save_manifest(data, root)


def stage_end(name: str, root: str | None = None, **extra: Any) -> None:
    data = load_manifest(root)
    stage = data.setdefault("stages", {}).setdefault(name, {})
    stage["ended_utc"] = _now()
    if stage.get("started_utc"):
        t0 = dt.datetime.fromisoformat(stage["started_utc"])
        t1 = dt.datetime.fromisoformat(stage["ended_utc"])
        stage["seconds"] = round((t1 - t0).total_seconds(), 2)
    stage.update(extra)
    save_manifest(data, root)


def record_run_start(root: str | None = None) -> None:
    save_manifest({"started_utc": _now(), "stages": {}, "commands": []}, root)


def stage_seconds(manifest: dict[str, Any], name: str) -> float | None:
    sec = manifest.get("stages", {}).get(name, {}).get("seconds")
    return float(sec) if sec is not None else None
