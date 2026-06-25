"""
Codex provider — drives the OpenAI Codex CLI (`codex exec`) in non-interactive
mode using your ChatGPT plan instead of the pay-per-token API.

When Codex is signed in with ChatGPT (`codex login`, "Sign in with ChatGPT"),
`codex exec` consumes your included ChatGPT plan usage — NOT separate API
billing. (Signing in with an API key instead would switch Codex to standard API
pricing; this provider deliberately relies on the ChatGPT account session.)

Caveat: usage is metered against your ChatGPT plan quota, not per-token billing,
so token counts here are ESTIMATED from text length (chars/4) and any USD figure
is a rough upper bound, not an invoice. Prefer ollama/openai when token-exact
accounting matters.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Provider, ProviderError, Usage


class CodexProvider(Provider):
    name = "codex"

    def __init__(self, model: str = "", timeout: int = 300,
                 binary: str | None = None, probe_timeout: int = 30, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.binary = binary or os.environ.get("CODEX_BIN", "codex")
        self.probe_timeout = probe_timeout

    def preflight(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None:
            return False, (
                f"'{self.binary}' not found on PATH. Install the Codex CLI and "
                f"run 'codex login' (Sign in with ChatGPT), or set CODEX_BIN. "
                f"(Codex uses your ChatGPT plan, not token-exact API billing.)")
        try:
            proc = subprocess.run(
                [self.binary, "login", "status"],
                capture_output=True, text=True, timeout=self.probe_timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"codex: could not check login status ({e})"
        if proc.returncode != 0:
            return False, (
                "codex: not signed in. Run 'codex login' (Sign in with ChatGPT) "
                "so runs draw on your ChatGPT plan, not API billing.")
        return True, "ok"

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        if shutil.which(self.binary) is None:
            raise ProviderError(f"'{self.binary}' not found on PATH")
        full = f"{system}\n\n{prompt}"
        if json_mode:
            full += "\n\nRespond with ONLY a single valid JSON object."
        # --skip-git-repo-check: run headless from any directory (e.g. the data
        # root), not only inside a trusted git repo. Without it `codex exec`
        # aborts with "Not inside a trusted directory", which the circuit breaker
        # reads as repeated provider failures.
        cmd = [self.binary, "exec", "--skip-git-repo-check"]
        if self.model:
            cmd += ["--model", self.model]
        try:
            proc = subprocess.run(
                cmd, input=full, capture_output=True, text=True,
                timeout=self.timeout, check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"codex: timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            raise ProviderError(
                f"codex: exit {proc.returncode}: {(proc.stderr or '')[:300]}")
        text = (proc.stdout or "").strip()
        if not text:
            raise ProviderError("codex: empty stdout")
        # The ChatGPT plan meters usage, not tokens; estimate from text length.
        usage = Usage(
            input_tokens=len(full) // 4,
            output_tokens=len(text) // 4,
        )
        return text, usage
