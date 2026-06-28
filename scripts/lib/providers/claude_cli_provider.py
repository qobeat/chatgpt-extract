"""
Claude CLI provider — drives Claude Code (`claude -p`) in print mode using your
Claude Pro/Max subscription instead of the pay-per-token Anthropic API.

Subscription auth comes from a long-lived OAuth token generated once on a
machine with a browser via `claude setup-token`, then exported as
CLAUDE_CODE_OAUTH_TOKEN. If ANTHROPIC_API_KEY is also present, Claude Code lets
it take precedence and bills at API rates — so this provider explicitly removes
ANTHROPIC_API_KEY from the child process environment.

Caveats (as of 2026-06-15):
  - Headless `claude -p` usage draws from a SEPARATE monthly "Agent SDK credit"
    pool, distinct from your interactive chat limits.
  - Usage is quota-metered, not per-token billed here; token counts are
    ESTIMATED from text length (chars/4) and any USD figure is a rough upper
    bound, not an invoice.
This is distinct from the `anthropic` provider, which calls the API directly with
ANTHROPIC_API_KEY (token-exact, separate billing).
"""
from __future__ import annotations

import os
import shutil
import subprocess

from .base import Provider, ProviderError, Usage


class ClaudeCliProvider(Provider):
    name = "claude"

    # Network/agentic tools denied for a benchmark run: the model must answer
    # from the prompt alone, never from a live web lookup (FR-B3 integrity).
    _NO_WEB_TOOLS = ("WebSearch", "WebFetch")

    def __init__(self, model: str = "", timeout: int = 300,
                 binary: str | None = None, allow_web: bool = False, **kw):
        super().__init__(model=model, timeout=timeout, **kw)
        self.binary = binary or os.environ.get("CLAUDE_BIN", "claude")
        self.oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
        self.allow_web = allow_web

    def _child_env(self) -> dict[str, str]:
        """Child env forcing subscription auth: keep the OAuth token, drop the
        API key so Claude Code does not silently fall back to API billing."""
        env = dict(os.environ)
        env.pop("ANTHROPIC_API_KEY", None)
        return env

    def preflight(self) -> tuple[bool, str]:
        if shutil.which(self.binary) is None:
            return False, (
                f"'{self.binary}' not found on PATH. Install Claude Code and run "
                f"'claude setup-token', or set CLAUDE_BIN. (Uses your Claude plan, "
                f"not token-exact API billing.)")
        if not self.oauth_token:
            return False, (
                "CLAUDE_CODE_OAUTH_TOKEN is not set. Run 'claude setup-token' on a "
                "machine with a browser and export it so runs use your Claude plan. "
                "Note: headless -p draws a separate monthly Agent SDK credit pool.")
        return True, "ok"

    def _build_cmd(self) -> list[str]:
        cmd = [self.binary, "-p"]
        if not self.allow_web:
            cmd += ["--disallowedTools", *self._NO_WEB_TOOLS]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def complete(self, system: str, prompt: str, json_mode: bool = True
                 ) -> tuple[str, Usage]:
        if shutil.which(self.binary) is None:
            raise ProviderError(f"'{self.binary}' not found on PATH")
        full = f"{system}\n\n{prompt}"
        if json_mode:
            full += "\n\nRespond with ONLY a single valid JSON object."
        cmd = self._build_cmd()
        try:
            proc = subprocess.run(
                cmd, input=full, capture_output=True, text=True,
                timeout=self.timeout, check=False, env=self._child_env(),
            )
        except subprocess.TimeoutExpired as e:
            raise ProviderError(f"claude: timed out after {self.timeout}s") from e
        if proc.returncode != 0:
            raise ProviderError(
                f"claude: exit {proc.returncode}: {(proc.stderr or '')[:300]}")
        text = (proc.stdout or "").strip()
        if not text:
            raise ProviderError("claude: empty stdout")
        # The Claude plan meters usage, not tokens; estimate from text length.
        usage = Usage(
            input_tokens=len(full) // 4,
            output_tokens=len(text) // 4,
        )
        return text, usage
