"""
ulog.py — tiny timestamped logger for read/write operations.

Format:
  [YYYY-MM-DD HH:MM:SS] [Stage] EVENT  path  :: status  | ERROR: details

The optional [Stage] tag names the pipeline step (Extract / Cluster / Bundle /
Summarize). Set it once per process with set_stage(); it is omitted entirely
when unset, so existing call sites are unaffected.

Use:
  from ulog import log, dbg, set_verbose, set_stage, ok, err
  set_stage("Summarize")             # tag every subsequent line
  log("READ", "/path/file.zip", status="opened")
  dbg("WRITE", path)                 # only prints when verbose
  err("READ", path, error=str(e))    # status=ERROR, includes details
"""
from __future__ import annotations
import datetime as _dt
import sys as _sys

_VERBOSE = False
_STAGE: str | None = None


def set_verbose(v: bool) -> None:
    global _VERBOSE
    _VERBOSE = bool(v)


def set_stage(name: str | None) -> None:
    """Tag every subsequent log line with a pipeline stage name (or None)."""
    global _STAGE
    _STAGE = name or None


def _ts() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(event: str, path=None, status: str = "ok", error=None,
        stream=_sys.stderr) -> None:
    parts = [f"[{_ts()}]"]
    if _STAGE:
        parts.append(f"{_STAGE:<9}")
    parts.append(f"{event:<12}")
    if path is not None:
        parts.append(str(path))
    parts.append(f":: {status}")
    if error:
        parts.append(f"| ERROR: {error}")
    stream.write("  ".join(p for p in parts if p) + "\n")
    stream.flush()


def ok(event: str, path=None, status: str = "ok") -> None:
    log(event, path, status=status)


def err(event: str, path=None, error=None) -> None:
    log(event, path, status="ERROR", error=error)


def dbg(event: str, path=None, status: str = "ok", error=None) -> None:
    if _VERBOSE:
        log(event, path, status=status, error=error)
