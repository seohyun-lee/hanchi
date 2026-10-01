#!/usr/bin/env bash
# Compact analysis dump for calibration. See scripts/dev/show.py for options.
set -euo pipefail
cd "$(dirname "$0")/../.."
.venv/bin/python scripts/dev/show.py "$@"
