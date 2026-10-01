#!/usr/bin/env bash
# Audit licenses of hanchi's runtime dependencies (optionally with extras).
# Usage: scripts/license_audit.sh [extra ...]
set -euo pipefail
cd "$(dirname "$0")/.."
.venv/bin/python scripts/license_audit.py "$@"
