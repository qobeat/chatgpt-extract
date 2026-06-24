# shellcheck shell=bash
# activate_env.sh — shared .env + venv activation for the shell wrappers.
# Source this (do not execute). The caller must set REPO_DIR to the repo root.
# On return, $PYTHON points at the interpreter to use.
# shellcheck disable=SC2034  # PYTHON is consumed by the sourcing wrapper.

if [[ -f "$REPO_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO_DIR/.env"
    set +a
fi

VENV_DIR="${VENV_DIR:-$HOME/.venvs/chatgpt-project-reconstructor}"

if [[ -f "$VENV_DIR/bin/activate" ]]; then
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"
    PYTHON="python"
else
    echo "[warn] venv not found at $VENV_DIR — run 'bash setup.sh' to install ijson" >&2
    echo "       (faster + lower RAM on large exports). Falling back to python3." >&2
    if command -v python3 >/dev/null 2>&1; then
        PYTHON="python3"
    else
        echo "[error] python3 not found. Install Python 3.10+ then run: bash setup.sh" >&2
        exit 1
    fi
fi
