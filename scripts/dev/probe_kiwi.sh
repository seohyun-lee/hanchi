#!/usr/bin/env bash
# Probe installed Kiwi (tags, reference analyses). Usage: scripts/dev/probe_kiwi.sh [outfile]
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ $# -ge 1 ]]; then .venv/bin/python scripts/dev/probe_kiwi.py > "$1"; else .venv/bin/python scripts/dev/probe_kiwi.py; fi
