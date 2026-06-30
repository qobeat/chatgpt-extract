#!/usr/bin/env python3
"""
ask IPC — tiny line-delimited-JSON protocol over a unix socket.

Shared by the warm daemon ([scripts/ask_daemon.py](scripts/ask_daemon.py)) and
the `gpt ask` thin client ([scripts/ask.py](scripts/ask.py)) so both agree on
the wire format without importing each other (avoids a circular import).

Wire format: one UTF-8 JSON object per message, terminated by a single newline.

Request  : {"op": "ask"|"ping"|"shutdown", "question": str, "k": int, ...}
Response  : {"ok": bool, ...}  (ask -> answer/sources/route/elapsed_ms/timings)
"""
from __future__ import annotations

import json
import os
import socket


def socket_path(index_dir: str) -> str:
    """Canonical daemon socket path for an index directory."""
    return os.path.join(index_dir, "ask.sock")


def read_line(conn: socket.socket, max_bytes: int = 4_000_000) -> str | None:
    """Read one newline-terminated message from a connected socket.

    Returns the line (without the trailing newline) or None on clean EOF.
    Raises ValueError if the peer floods past `max_bytes` without a newline.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        b = conn.recv(65536)
        if not b:
            if not chunks:
                return None
            break
        nl = b.find(b"\n")
        if nl != -1:
            chunks.append(b[:nl])
            return b"".join(chunks).decode("utf-8", "replace")
        chunks.append(b)
        total += len(b)
        if total > max_bytes:
            raise ValueError("message exceeded max_bytes without newline")
    return b"".join(chunks).decode("utf-8", "replace")


def write_line(conn: socket.socket, obj: dict) -> None:
    """Send one JSON object followed by a newline."""
    conn.sendall((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))


def send_request(sock_path: str, req: dict, timeout: float = 30.0) -> dict:
    """Connect, send one request, return the decoded response.

    Raises OSError if the socket is absent/unreachable (no daemon) and the
    caller should fall back to in-process. Raises socket.timeout if the daemon
    accepted but did not answer within `timeout`.
    """
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(sock_path)
        write_line(s, req)
        line = read_line(s)
        if line is None:
            raise OSError("daemon closed the connection without a reply")
        return json.loads(line)
    finally:
        s.close()


def ping(sock_path: str, timeout: float = 1.0) -> dict | None:
    """Return the daemon's ping payload if it answers, else None."""
    try:
        resp = send_request(sock_path, {"op": "ping"}, timeout=timeout)
        return resp if resp.get("ok") else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None
