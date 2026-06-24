"""
trace.py — governed traceability + atomic IO helpers.

Patterns ported from ollama-test (ollama_test/core.py): atomic write_json,
fsync'd append_jsonl, a sequenced TraceWriter, and optional jsonschema
validation. Used by the provider layer to keep an auditable per-run ledger of
LLM calls, costs, and circuit-breaker events.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
from typing import Any


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path: str, data: Any) -> None:
    """Atomic JSON write (temp file + replace)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def append_jsonl(path: str, obj: dict[str, Any]) -> None:
    """Durable append of one JSON object per line (fsync'd)."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


class TraceWriter:
    """Sequenced JSONL trace for one run (ADOS evidence trail)."""

    def __init__(self, path: str, run_id: str):
        self.path = path
        self.run_id = run_id
        self.sequence = 0

    def event(self, event_type: str, message: str,
              payload: dict[str, Any] | None = None,
              severity: str = "INFO") -> dict[str, Any]:
        self.sequence += 1
        e = {
            "run_id": self.run_id,
            "sequence": self.sequence,
            "ts_utc": utc_now(),
            "severity": severity,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        if self.path:
            append_jsonl(self.path, e)
        return e


def validate_with_jsonschema(obj: Any, schema_path: str) -> tuple[bool, list[str]]:
    """
    Validate obj against a JSON Schema file. Returns (ok, errors).
    Degrades gracefully to (True, ["jsonschema not installed"]) when the
    optional dependency is missing, so validation never hard-blocks a run.
    """
    try:
        import jsonschema  # type: ignore
    except Exception:
        return True, ["jsonschema not installed; skipped validation"]
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)
    except OSError as e:
        return False, [f"cannot read schema {schema_path}: {e}"]
    validator = jsonschema.Draft7Validator(schema)
    errors = [
        f"{'/'.join(str(p) for p in err.path) or '<root>'}: {err.message}"
        for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.path))
    ]
    return (len(errors) == 0), errors
