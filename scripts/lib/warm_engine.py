#!/usr/bin/env python3
"""
Warm engine wrappers — keep a plan-covered CLI model resident across calls.

`gpt ask`'s latency floor on the CLI providers is *process boot* (codex/claude
cold-start ~2-12s). A warm engine pays that once and amortises it: the daemon
([scripts/ask_daemon.py](scripts/ask_daemon.py)) holds one of these open and
routes every question through it, so per-question latency drops to the model's
own round-trip.

Two backends, both driven over a persistent stdio pipe (measured warm latency on
a trivial prompt):

  - claude  `claude -p --input-format stream-json` ............ ~2.2s/call
            One growing session (turns share context), so we (a) make each
            request fully self-contained and (b) RECYCLE the process every
            `recycle_after` turns to bound context growth and cross-question
            bleed. This is the only CLI that meets the ~2s SLA.
  - codex   `codex mcp-server` -> `codex` tool ................. ~5s/call
            Each `codex` tool call is a FRESH conversation (stateless, clean),
            but agent overhead keeps it ~5s -> usable (<15s) but not 2s.

Security: both run in a throwaway temp cwd with tools/sandbox locked down
(codex sandbox=read-only, approval=never; claude dangerous tools disallowed) so
an answer call can never edit files or run commands.

Pure stdlib. `complete(system, prompt, timeout)` mirrors the provider contract
and raises WarmEngineError on timeout/crash (the caller reports the model
UNUSABLE). A timed-out engine is killed and lazily restarted on the next call.
"""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time

# Tools we never want an "answer this question" call to touch.
_CLAUDE_DISALLOWED = ["Bash", "Edit", "Write", "NotebookEdit", "WebFetch",
                      "WebSearch", "Read", "Glob", "Grep", "Task"]


class WarmEngineError(RuntimeError):
    """Raised on engine timeout, crash, or protocol failure."""


class WarmEngine:
    """Base: a persistent subprocess with a background stdout reader."""

    name = "base"

    def __init__(self, model: str | None = None, recycle_after: int = 0,
                 cwd: str | None = None):
        self.model = model or None
        self.recycle_after = recycle_after
        self._cwd = cwd or tempfile.mkdtemp(prefix=f"warm-{self.name}-")
        self._proc: subprocess.Popen | None = None
        self._q: "queue.Queue[str | None]" = queue.Queue()
        self._lock = threading.Lock()
        self._turns = 0

    # --- lifecycle ---------------------------------------------------------
    def _spawn_cmd(self) -> list[str]:
        raise NotImplementedError

    def _handshake(self) -> None:
        """Optional post-spawn protocol setup (e.g. MCP initialize)."""

    def start(self) -> None:
        if self.alive():
            return
        cmd = self._spawn_cmd()
        self._proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, cwd=self._cwd)
        self._q = queue.Queue()
        threading.Thread(target=self._reader, args=(self._proc.stdout,),
                         daemon=True).start()
        self._turns = 0
        self._handshake()

    def _reader(self, pipe) -> None:
        try:
            for line in pipe:
                self._q.put(line)
        finally:
            self._q.put(None)

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                self._proc.stdin.close()
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass
        finally:
            self._proc = None

    def restart(self) -> None:
        self.close()
        self.start()

    def __del__(self):
        try:
            self.close()
            if self._cwd and os.path.isdir(self._cwd):
                shutil.rmtree(self._cwd, ignore_errors=True)
        except Exception:
            pass

    # --- request helpers ---------------------------------------------------
    def _send_line(self, obj: dict) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write(json.dumps(obj) + "\n")
        self._proc.stdin.flush()

    def _drain_until(self, match, deadline: float):
        """Pull stdout JSON objects until `match(obj)` is truthy or deadline.

        Returns match(obj)'s truthy value, or raises WarmEngineError on
        timeout / EOF. Non-JSON lines are ignored (CLIs print stray logs).
        """
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise WarmEngineError(f"{self.name}: timed out")
            try:
                line = self._q.get(timeout=remaining)
            except queue.Empty:
                raise WarmEngineError(f"{self.name}: timed out")
            if line is None:
                raise WarmEngineError(f"{self.name}: engine exited")
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            hit = match(obj)
            if hit is not None:
                return hit

    def complete(self, system: str, prompt: str, timeout: float = 15.0
                 ) -> tuple[str, dict]:
        """Run one request; return (text, info). Thread-safe (single-flight).

        On timeout or engine death, kills the engine (lazily restarted next
        call) and raises WarmEngineError so the caller marks it UNUSABLE.
        """
        with self._lock:
            if self.recycle_after and self._turns >= self.recycle_after:
                self.restart()
            if not self.alive():
                self.start()
            t0 = time.monotonic()
            deadline = t0 + timeout
            try:
                text = self._exchange(system, prompt, deadline)
            except WarmEngineError:
                self.close()  # poison -> fresh process next time
                raise
            self._turns += 1
            return text, {"engine": self.name, "elapsed_ms": round((time.monotonic() - t0) * 1000, 1)}

    def _exchange(self, system: str, prompt: str, deadline: float) -> str:
        raise NotImplementedError

    def preflight(self) -> tuple[bool, str]:
        return True, "ok"


class ClaudeWarmEngine(WarmEngine):
    """`claude -p` stream-json: warm, fast (~2.2s), shared session (recycled)."""

    name = "claude"

    def __init__(self, model: str | None = None, recycle_after: int = 6,
                 binary: str | None = None, **kw):
        super().__init__(model=model, recycle_after=recycle_after, **kw)
        self.binary = binary or os.environ.get("CLAUDE_BIN", "claude")

    def preflight(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None:
            return False, f"'{self.binary}' not on PATH"
        return True, "ok"

    def _spawn_cmd(self) -> list[str]:
        cmd = [self.binary, "-p", "--input-format", "stream-json",
               "--output-format", "stream-json", "--verbose",
               "--disallowed-tools", *_CLAUDE_DISALLOWED]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def _exchange(self, system: str, prompt: str, deadline: float) -> str:
        content = f"{system}\n\n{prompt}" if system else prompt
        self._send_line({"type": "user",
                         "message": {"role": "user", "content": content}})

        def match(ev):
            if ev.get("type") == "result":
                if ev.get("is_error"):
                    raise WarmEngineError(
                        f"claude: {ev.get('result') or ev.get('subtype')}")
                return ev.get("result", "")
            return None

        return self._drain_until(match, deadline)


class CodexWarmEngine(WarmEngine):
    """`codex mcp-server`: warm, stateless per call (~5s), agent locked down."""

    name = "codex"

    def __init__(self, model: str | None = None, binary: str | None = None, **kw):
        # Stateless per call, so no recycling needed.
        super().__init__(model=model, recycle_after=0, **kw)
        self.binary = binary or os.environ.get("CODEX_BIN", "codex")
        self._id = 0

    def preflight(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None:
            return False, f"'{self.binary}' not on PATH"
        return True, "ok"

    def _spawn_cmd(self) -> list[str]:
        return [self.binary, "mcp-server"]

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _handshake(self) -> None:
        rid = self._next_id()
        self._send_line({"jsonrpc": "2.0", "id": rid, "method": "initialize",
                         "params": {"protocolVersion": "2025-06-18",
                                    "capabilities": {},
                                    "clientInfo": {"name": "gpt-ask", "version": "1"}}})
        deadline = time.monotonic() + 30
        self._drain_until(
            lambda ev: True if ev.get("id") == rid and "result" in ev else None,
            deadline)
        self._send_line({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _exchange(self, system: str, prompt: str, deadline: float) -> str:
        rid = self._next_id()
        args = {
            "prompt": prompt,
            "sandbox": "read-only",
            "approval-policy": "never",
            "cwd": self._cwd,
            "base-instructions": system or
            "You are a concise question-answering assistant. Answer directly "
            "and do not use tools or run commands.",
        }
        if self.model:
            args["model"] = self.model
        self._send_line({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                         "params": {"name": "codex", "arguments": args}})

        def match(ev):
            if ev.get("id") != rid:
                return None
            if "error" in ev:
                raise WarmEngineError(f"codex: {ev['error']}")
            result = ev.get("result") or {}
            blocks = result.get("content") or []
            text = " ".join(b.get("text", "") for b in blocks
                            if isinstance(b, dict)).strip()
            return text or ""

        return self._drain_until(match, deadline)


ENGINES = {"claude": ClaudeWarmEngine, "codex": CodexWarmEngine}


def get_engine(name: str, **kwargs) -> WarmEngine:
    name = (name or "claude").lower()
    if name not in ENGINES:
        raise WarmEngineError(f"unknown engine '{name}'. Choose: {', '.join(ENGINES)}")
    return ENGINES[name](**kwargs)


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Smoke-test a warm engine.")
    ap.add_argument("--engine", default="claude", choices=list(ENGINES))
    ap.add_argument("--model", default=None)
    ap.add_argument("--timeout", type=float, default=20.0)
    ap.add_argument("--n", type=int, default=2, help="Number of warm calls.")
    ap.add_argument("prompt", nargs="*", default=["What does the acronym API stand for?"])
    args = ap.parse_args()
    eng = get_engine(args.engine, model=args.model)
    ok, msg = eng.preflight()
    if not ok:
        print(f"[preflight] {msg}", file=sys.stderr)
        raise SystemExit(2)
    q = " ".join(args.prompt) if args.prompt else "What does the acronym API stand for?"
    try:
        for i in range(args.n):
            text, info = eng.complete("Answer in one short sentence.", q, timeout=args.timeout)
            tag = "cold" if i == 0 else f"warm#{i}"
            print(f"[{tag}] {info['elapsed_ms']}ms -> {text[:80]!r}")
    finally:
        eng.close()
