#!/usr/bin/env bash
# run.sh — activate venv then delegate to run.py (Stages 1-3)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/activate_env.sh
source "$REPO_DIR/scripts/lib/activate_env.sh"
exec "$PYTHON" "$REPO_DIR/run.py" "$@"
