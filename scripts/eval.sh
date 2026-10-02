#!/usr/bin/env bash
# Run the public evaluation set (or pass another eval config / case files).
# Usage: scripts/eval.sh [-c config.yaml] [case files...]
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -eq 0 ]]; then set -- -c eval/hanchi.yaml; fi
.venv/bin/python -m hanchi.evaluation "$@"
