"""
Provider abstraction for the summarizer.

A Provider turns (system, prompt) into (text, usage) regardless of backend:
  - ollama     local, $0 marginal cost (default)
  - openai     Chat Completions, JSON mode (API key, token-exact billing)
  - anthropic  Messages API, JSON via prefill (API key, token-exact billing)
  - cursor     Cursor CLI/agent (Cursor plan; usage-based, not token-exact)
  - codex      Codex CLI `codex exec` (ChatGPT plan; quota-metered, not token-exact)
  - claude     Claude Code `claude -p` (Claude plan; quota-metered, not token-exact)

API providers read keys from the environment (loaded from .env by the shell
wrappers): OPENAI_API_KEY, ANTHROPIC_API_KEY, CURSOR_API_KEY. The CLI providers
(cursor/codex/claude) use their local CLI's signed-in session/plan instead.
"""
from __future__ import annotations

from .base import Provider, ProviderError, Usage

PROVIDERS = ("ollama", "openai", "anthropic", "cursor", "codex", "claude")


def get_provider(name: str, **kwargs) -> Provider:
    name = (name or "ollama").lower()
    if name == "ollama":
        from .ollama_provider import OllamaProvider
        return OllamaProvider(**kwargs)
    if name == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(**kwargs)
    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(**kwargs)
    if name == "cursor":
        from .cursor_provider import CursorProvider
        return CursorProvider(**kwargs)
    if name == "codex":
        from .codex_provider import CodexProvider
        return CodexProvider(**kwargs)
    if name == "claude":
        from .claude_cli_provider import ClaudeCliProvider
        return ClaudeCliProvider(**kwargs)
    raise ProviderError(f"unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}")


__all__ = ["Provider", "ProviderError", "Usage", "get_provider", "PROVIDERS"]
