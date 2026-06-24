#!/usr/bin/env bash
# ollama.sh — activate venv then run Stage 4 (multi-provider LLM summarizer).
# Defaults to the local Ollama provider; pass --provider openai|anthropic|cursor
# to use a cloud provider (keys come from .env).
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/activate_env.sh
source "$REPO_DIR/scripts/lib/activate_env.sh"
exec "$PYTHON" "$REPO_DIR/scripts/summarize.py" "$@"
