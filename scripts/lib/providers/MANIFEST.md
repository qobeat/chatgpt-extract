# scripts/lib/providers/ — MANIFEST

Provider backends. Each turns `(system, prompt)` into `(text, usage)` behind one
interface, so `gpt summarize`/`gpt ask` work across local and cloud backends.

## How an agent EXECUTES this folder
- Not run directly. Callers do `from providers import get_provider; p =
  get_provider(name, **kwargs); text, usage = p.complete(system, prompt,
  json_mode=...)`.
- `ollama` is the local, $0 default. `openai`/`anthropic` read API keys from the
  environment (`.env`). `cursor`/`codex`/`claude` use the signed-in local CLI's
  plan (no API key). Anything that is not in `ask.LOCAL_PROVIDERS` is treated as
  off-box egress and is gated (`--scrub-cloud`).

## How an agent CHANGES this folder
- Add a backend by subclassing `Provider` in `base.py` and registering it in
  `__init__.py`'s `get_provider` + the `PROVIDERS` tuple. Reuse `base.Provider`'s
  HTTP retry/backoff (`_post_json`) rather than rolling your own.
- Preserve the `complete()` signature and return a `Usage`. Keep billing facts in
  `config/models.json` / `config/plans.json`, not in code.
- A new cloud provider MUST be excluded from `LOCAL_PROVIDERS` so the privacy
  gate covers it. Add/adjust `tests/test_providers.py`.

## Files
- `__init__.py` — `get_provider(name)` factory + `PROVIDERS` registry.
- `base.py` — `Provider` base (HTTP, retry/backoff), `ProviderError`, `Usage`.
- `ollama_provider.py` — local Ollama (`/api/chat`), $0, structured-output retry.
- `openai_provider.py` — OpenAI Chat Completions (JSON mode; token billing).
- `anthropic_provider.py` — Anthropic Messages (JSON via prefill; token billing).
- `cursor_provider.py` — Cursor agent CLI (plan-billed).
- `codex_provider.py` — Codex CLI `codex exec` (ChatGPT plan, quota-metered).
- `claude_cli_provider.py` — Claude Code `claude -p` (Claude plan, quota-metered).
