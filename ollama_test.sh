#!/usr/bin/env bash
# ollama_test.sh — invoke the polished ollama-test CLI (host/model diagnostics)
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

if [[ -z "${OLLAMA_TEST_HOME:-}" ]]; then
    for cfg in "$SCRIPT_DIR/config/reconstruct.config.local.json" \
               "$SCRIPT_DIR/config/reconstruct.config.json"; do
        if [[ -f "$cfg" ]]; then
            OLLAMA_TEST_HOME="$(python3 -c "
import json, os
with open('${cfg}', encoding='utf-8') as f:
    v = json.load(f).get('ollama_test_home')
if v:
    print(os.path.expanduser(v))
" 2>/dev/null || true)"
            if [[ -n "${OLLAMA_TEST_HOME:-}" ]]; then
                break
            fi
        fi
    done
fi

OLLAMA_TEST_HOME="${OLLAMA_TEST_HOME:-$HOME/dev/WSL/ollama/ollama-test}"
OLLAMA_TEST_HOME="$(python3 -c "import os; print(os.path.expanduser('${OLLAMA_TEST_HOME}'))")"

if [[ ! -d "$OLLAMA_TEST_HOME" ]]; then
    echo "[ollama_test] OLLAMA_TEST_HOME not found: $OLLAMA_TEST_HOME" >&2
    echo "  Set OLLAMA_TEST_HOME or add ollama_test_home to config/reconstruct.config.local.json" >&2
    exit 1
fi

export OLLAMA_TEST_HOME
export PYTHONPATH="${OLLAMA_TEST_HOME}${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m ollama_test.cli "$@"
