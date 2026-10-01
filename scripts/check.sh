#!/usr/bin/env bash
# Run the same checks as CI: lint, format check, type check, tests (network tests excluded).
# Usage: scripts/check.sh [extra pytest args]
set -euo pipefail
cd "$(dirname "$0")/.."

BIN=".venv/bin"
if [[ ! -x "$BIN/python" ]]; then
    echo "No .venv found. Run scripts/setup_dev.sh first." >&2
    exit 1
fi

echo "== ruff check"
"$BIN/ruff" check .
echo "== ruff format --check"
"$BIN/ruff" format --check .
echo "== mypy"
"$BIN/mypy" src
echo "== pytest"
"$BIN/pytest" "$@"
