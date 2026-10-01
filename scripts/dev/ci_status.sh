#!/usr/bin/env bash
# Show the latest GitHub Actions runs for the `origin` remote (public API, no auth needed for public repos).
# Usage: scripts/dev/ci_status.sh [count]
set -euo pipefail
cd "$(dirname "$0")/../.."
repo=$(git remote get-url origin | sed -E 's#(git@github.com:|https://github.com/)##; s#\.git$##')
curl -fsSL "https://api.github.com/repos/$repo/actions/runs?per_page=${1:-3}" |
    python3 -c '
import json, sys
for r in json.load(sys.stdin).get("workflow_runs", []):
    print(r["head_sha"][:7], r["name"], r["status"], r["conclusion"] or "-", r["html_url"], sep="  ")'
