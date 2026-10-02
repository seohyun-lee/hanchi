#!/usr/bin/env bash
# Rank candidates for a query. See scripts/dev/rank.py.
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python scripts/dev/rank.py "$@"
