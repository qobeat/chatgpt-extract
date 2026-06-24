"""
Provider abstraction for the summarizer.

A Provider turns (system, prompt) into (text, usage) regardless of backend:
  - ollama     local, $0 marginal cost (default)
  - openai     Chat Completions, JSON mode
  - anthropic  Messages API, JSON via prefill
  - cursor     Cursor CLI/agent (usage-based, not token-exact)

Keys come from the environment (loaded from .env by the shell wrappers):
  OPENAI_API_KEY, ANTHROPIC_API_KEY, CURSOR_API_KEY
"""
from __future__ import annotations

from .base import Provider, ProviderError, Usage

PROVIDERS = ("ollama", "openai", "anthropic", "cursor")


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
    raise ProviderError(f"unknown provider '{name}'. Choose one of: {', '.join(PROVIDERS)}")


__all__ = ["Provider", "ProviderError", "Usage", "get_provider", "PROVIDERS"]
