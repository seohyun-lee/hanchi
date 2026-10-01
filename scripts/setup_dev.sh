#!/usr/bin/env bash
# Create a local virtualenv (.venv) and install hanchi in editable mode with dev extras.
# Usage: scripts/setup_dev.sh [python-version]   (default: 3.12)
set -euo pipefail
cd "$(dirname "$0")/.."

PY_VERSION="${1:-3.12}"

if command -v uv >/dev/null 2>&1; then
    uv venv --allow-existing --python "$PY_VERSION" .venv
    uv pip install --python .venv/bin/python -e ".[dev]"
else
    "python$PY_VERSION" -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e ".[dev]"
fi

.venv/bin/python -c "import hanchi, kiwipiepy; print('hanchi', hanchi.__version__, '| kiwipiepy', kiwipiepy.__version__)"
