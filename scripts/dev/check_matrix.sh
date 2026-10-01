#!/usr/bin/env bash
# Local stand-in for the CI matrix: for each Python version, create a throwaway venv,
# install with pip (as CI does) and run lint/type/tests. Requires uv to provide interpreters.
# Usage: scripts/dev/check_matrix.sh [versions...]   (default: 3.10 3.11 3.12 3.13)
set -euo pipefail
cd "$(dirname "$0")/../.."

VERSIONS=("$@")
[[ ${#VERSIONS[@]} -eq 0 ]] && VERSIONS=(3.10 3.11 3.12 3.13)
WORK="${TMPDIR:-/tmp}/hanchi-matrix"
mkdir -p "$WORK"

for v in "${VERSIONS[@]}"; do
    echo "===== Python $v"
    env="$WORK/py$v"
    uv venv --allow-existing --seed -q --python "$v" "$env"
    "$env/bin/python" -m pip install -q -e ".[dev]"
    "$env/bin/ruff" check -q .
    "$env/bin/ruff" format --check -q .
    "$env/bin/mypy" src
    "$env/bin/pytest" -q
done
echo "===== all versions passed: ${VERSIONS[*]}"
