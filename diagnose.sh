#!/usr/bin/env bash
# diagnose.sh — inspect an export's structure (read-only)
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/activate_env.sh
source "$REPO_DIR/scripts/lib/activate_env.sh"
exec "$PYTHON" "$REPO_DIR/scripts/diagnose.py" "$@"
