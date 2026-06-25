"""
Cursor provider — drives the Cursor agent CLI (`cursor-agent`) in non-interactive
print mode.

Caveat: Cursor is an agent runtime billed by Cursor *usage*, not a plain
per-token chat endpoint. Token usage here is ESTIMATED from text length
(chars/4), so cost figures are an upper-bound approximation, not exact billing.
Prefer ollama/openai/anthropic when token-exact accounting matters.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Provider, ProviderError, Usage


class CursorProvider(Provider):
    name = "cursor"

    def __init__(self, model: str = "", timeout: int = 300,
                 binary: str | None = None, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.binary = binary or os.environ.get("CURSOR_AGENT_BIN", "cursor-agent")

    def preflight(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None:
            return False, (f"'{self.binary}' not found on PATH. Install the Cursor "
                           f"CLI or set CURSOR_AGENT_BIN. (Cursor is usage-based, "
                           f"not token-exact.)")
        return True, "ok"

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        if shutil.which(self.binary) is None:
            raise ProviderError(f"'{self.binary}' not found on PATH")
        full = f"{system}\n\n{prompt}"
        if json_mode:
            full += "\n\nRespond with ONLY a single valid JSON object."
        # --trust: skip the interactive "Do you trust this directory?" prompt,
        # which otherwise blocks/fails every call in headless (--print) mode.
        cmd = [self.binary, "--print", "--output-format", "text", "--trust"]
        if self.model:
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(
                cmd, input=full, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"cursor: timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            raise ProviderError(
                f"cursor: exit {proc.returncode}: {(proc.stderr or '')[:300]}")
        text = (proc.stdout or "").strip()
        if not text:
            raise ProviderError("cursor: empty stdout")
        # Usage is not reported by the CLI; estimate from text length.
        usage = Usage(
            input_tokens=len(full) // 4,
            output_tokens=len(text) // 4,
        )
        return text, usage
