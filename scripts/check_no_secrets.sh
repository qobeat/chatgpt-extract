#!/usr/bin/env bash
# check_no_secrets.sh — block accidental commits of personal pipeline data.
# Usage: bash scripts/check_no_secrets.sh
# Hook:  cp scripts/check_no_secrets.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
    echo "[check] Not a git repo — skipping."
    exit 0
fi

STAGED="$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)"
if [[ -z "$STAGED" ]]; then
    exit 0
fi

FAIL=0
warn() { echo "[check] FAIL: $*"; FAIL=1; }

while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    case "$f" in
        .env|.env.*)
            [[ "$f" == ".env.example" ]] && continue
            warn "staged secrets file: $f"
            ;;
        output/*|data/*|**/transcripts/*|**/bundles/*)
            warn "staged personal pipeline path: $f"
            ;;
        *.zip)
            warn "staged export zip: $f"
            ;;
        config/reconstruct.config.local.json|config/*.local.json)
            warn "staged local config: $f"
            ;;
        reconstructed_projects.json)
            warn "staged full internal JSON (use published/projects.json): $f"
            ;;
    esac
done <<< "$STAGED"

# Content scan on staged JSON only (docs may mention field names in prose)
PATTERNS=(
    'source_conversation_ids'
    '/mnt/c/Users/'
    '/Users/[A-Za-z]'
)
while IFS= read -r f; do
    [[ -z "$f" ]] && continue
    [[ -f "$f" ]] || continue
    case "$f" in
        *.json) ;;
        *) continue ;;
    esac
    for pat in "${PATTERNS[@]}"; do
        if grep -qE "$pat" "$f" 2>/dev/null; then
            warn "staged file $f matches pattern: $pat"
        fi
    done
done <<< "$STAGED"

if [[ "$FAIL" -ne 0 ]]; then
    echo "[check] Aborting — remove personal data from the index before committing."
    exit 1
fi

echo "[check] OK — no obvious personal data in staged files."
exit 0
