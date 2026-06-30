"""pytest configuration: the default suite is hermetic and skip-free.

`tests/test_ask_live.py` talks to a REAL local Ollama (embeddings + a small
generation model), so it is opt-in rather than skipped: it is not collected at
all unless `GPT_ASK_LIVE=1`. That keeps the default run — and CI (NFR-Q6) —
green with **zero skips**, while the live lane stays one env var away:

    GPT_ASK_LIVE=1 pytest -q tests/test_ask_live.py
"""
import os

# `collect_ignore` paths are resolved relative to this conftest's directory.
collect_ignore = []
if os.environ.get("GPT_ASK_LIVE") != "1":
    collect_ignore.append("test_ask_live.py")
