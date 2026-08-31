#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${PROJECT_ROOT}"

show_help() {
    cat <<'EOF'
=== Movie Scanner - Help ===

Usage: ./scripts/run_scanner.sh [OPTIONS]

Options:
  --config PATH      Path to configuration JSON file (default: legacy/config.json)
  --mode MODE        Scanner mode (rss, recheck-existing, reparse-unfound, all, apply-proposals)
  --dry-run          Run without writing to Firestore
  --parse-only       Download/parse RSS only, no external APIs (requires --mode rss)
  --feed-file PATH   Path to local feed file (requires --mode rss --parse-only)
  --force-days N     Force scan N days back (0-30)
  --audit-days N     Audit N days back (0-30)
    --proposal-id ID   Explicit ID of the single proposal to plan/apply
  --reject-proposal  Reject proposal instead of applying
  --fake-repos       Use fake repositories (no Firebase)
  --help             Show this help message

Examples:
  ./scripts/run_scanner.sh --mode rss
  ./scripts/run_scanner.sh --mode rss --parse-only --feed-file backend/tests/fixtures/movies_feed.atom
  ./scripts/run_scanner.sh --mode recheck-existing --dry-run
    ./scripts/run_scanner.sh --mode apply-proposals --proposal-id prop-123 --dry-run

Notes:
    --mode all never applies proposals; there is no bulk proposal application mode.
    Non-dry-run application also requires MEDIADOCK_ENABLE_PROPOSAL_APPLICATION=true.
EOF
}

if [[ "${1:-}" == "--help" ]]; then
    show_help
    exit 0
fi

if [[ -x "./.venv/bin/python" ]]; then
    PYTHON_BIN="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: Python was not found." >&2
    exit 1
fi

echo "=== Movie Scanner ==="
echo "Using Python: ${PYTHON_BIN}"
echo "Note: Legacy movie_scanner.py execution is unsupported."

"${PYTHON_BIN}" -m movies_feed.cli "$@"
