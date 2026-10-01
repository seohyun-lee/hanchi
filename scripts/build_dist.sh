#!/usr/bin/env bash
# Build sdist + wheel into dist/ and list their contents (to confirm nothing local-only leaks in).
# Usage: scripts/build_dist.sh
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf dist
uv build -q
for f in dist/*; do
    echo "== $f"
    case "$f" in
        *.whl) .venv/bin/python -m zipfile -l "$f" | awk 'NR>1 {print "  " $1}' ;;
        *.tar.gz) tar -tzf "$f" | sed 's/^/  /' ;;
    esac
done
