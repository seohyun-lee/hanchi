#!/usr/bin/env bash
# Run the test suite on a fresh clone of HEAD (catches files that exist locally but are
# not committed). Usage: scripts/dev/check_clean_clone.sh [workdir]
set -euo pipefail
cd "$(dirname "$0")/../.."
WORK="${1:-${TMPDIR:-/tmp}/hanchi-clean-clone}"
rm -rf "$WORK"
git clone -q . "$WORK"
cd "$WORK"
uv venv -q --python 3.12 .venv
uv pip install -q --python .venv/bin/python -e ".[dev]"
.venv/bin/ruff check -q . && .venv/bin/ruff format --check -q . && .venv/bin/mypy src
.venv/bin/pytest -q
