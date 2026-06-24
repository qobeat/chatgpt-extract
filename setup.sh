#!/usr/bin/env bash
# setup.sh — bootstrap the venv for chatgpt-extract
# Run once from the project root:  bash setup.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$SCRIPT_DIR/.env"
    set +a
fi

VENV_DIR="${VENV_DIR:-$HOME/.venvs/chatgpt-extract}"
PYTHON=""

# ── find python 3.10+ ──────────────────────────────────────────────────────
for candidate in python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" &>/dev/null; then
        if "$candidate" -c 'import sys; assert sys.version_info >= (3,10)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    fi
done
if [[ -z "$PYTHON" ]]; then
    echo "[error] Python 3.10+ not found. Install: sudo apt install python3.12"
    exit 1
fi
echo "[setup] Using $PYTHON ($("$PYTHON" --version))"

# ── create venv if absent ─────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    echo "[setup] Creating venv at $VENV_DIR ..."
    mkdir -p "$(dirname "$VENV_DIR")"
    "$PYTHON" -m venv "$VENV_DIR"
fi

PIP="$VENV_DIR/bin/pip"

# ── upgrade pip quietly ───────────────────────────────────────────────────
"$PIP" install --quiet --upgrade pip

# ── install deps (ijson recommended; jsonschema enforces archetype contracts) ─
echo "[setup] Installing ijson ..."
if ! "$PIP" install "ijson>=3.2" 2>/dev/null; then
    echo "[warn]  ijson build failed (no C compiler?). Falling back to stdlib mode."
    echo "        Large zips (>200 MB) will load fully into RAM."
else
    echo "[setup] ijson installed OK."
fi
echo "[setup] Installing jsonschema (optional output validation) ..."
"$PIP" install --quiet "jsonschema>=4.0" 2>/dev/null \
    && echo "[setup] jsonschema installed OK." \
    || echo "[warn]  jsonschema not installed; Stage 4 validation will be skipped."

# ── ensure .env exists ───────────────────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/.env" ]]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "[setup] Created .env from .env.example — edit paths if needed."
fi

# ── ensure local config template hint ─────────────────────────────────────
if [[ ! -f "$SCRIPT_DIR/config/reconstruct.config.local.json" ]]; then
    echo "[setup] Tip: copy config/reconstruct.config.example.json to"
    echo "        config/reconstruct.config.local.json for default_zips / data_root."
fi

echo ""
echo "[setup] Done. Venv: $VENV_DIR"
echo ""
echo "  Run the pipeline (deterministic Stages 1-3):"
echo "    ./run.sh --zip \"<path-to-export>.zip\""
echo "    ./run.sh --zip \"<export>.zip\" --verbose      # per-file logging"
echo ""
echo "  Stage 4 — LLM classify + summarize (local Ollama, free):"
echo "    ./ollama.sh --provider ollama --model gpt-oss:20b"
echo "    ./ollama.sh --provider openai --model gpt-5-mini --max-usd 2 --yes"
echo ""
echo "  Inspect an export if parsing yields 0 (read-only):"
echo "    ./diagnose.sh --zip \"<export>.zip\""
echo ""
echo "  Publish sanitized summaries to GitHub:"
echo "    ./run.sh ... && ./ollama.sh ... && python scripts/export_public.py --review"
