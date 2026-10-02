#!/usr/bin/env bash
# Compare weighter backends on the same evaluation (rule v1 vs learned).
# Usage: scripts/compare_backends.sh [eval-config] [weighters...]
#   default: eval/hanchi.yaml, rule bge-m3 (bge-m3 needs: pip install "hanchi[neural]")
set -euo pipefail
cd "$(dirname "$0")/.."
CONFIG="${1:-eval/hanchi.yaml}"; shift || true
WEIGHTERS=("$@"); [[ ${#WEIGHTERS[@]} -eq 0 ]] && WEIGHTERS=(rule bge-m3)
if [[ " ${WEIGHTERS[*]} " == *" bge-m3 "* ]] && ! .venv/bin/python -c "import FlagEmbedding" 2>/dev/null; then
    echo "FlagEmbedding not installed: comparing 'rule' only (pip install \"hanchi[neural]\" for bge-m3)" >&2
    WEIGHTERS=(rule)
fi
args=(); for w in "${WEIGHTERS[@]}"; do args+=(--weighter "$w"); done
[[ ${#WEIGHTERS[@]} -eq 1 ]] && args+=(--weighter "${WEIGHTERS[0]}")
.venv/bin/hanchi eval -c "$CONFIG" "${args[@]}"
