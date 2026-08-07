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
  --html         Regenerate HTML report without scanning RSS feeds
  --test-parser  Test the title parser without API calls
  --parse-only   Download/parse RSS only and print parsed titles/years
  --help         Show this help message

Examples:
  ./scripts/run_scanner.sh
  ./scripts/run_scanner.sh --html
  ./scripts/run_scanner.sh --test-parser
  ./scripts/run_scanner.sh --parse-only
EOF
}

if [[ "${1:-}" == "--help" ]]; then
    show_help
    exit 0
fi

if [[ -x "./venv/bin/python" ]]; then
    PYTHON_BIN="./venv/bin/python"
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

"${PYTHON_BIN}" movie_scanner.py "$@"
