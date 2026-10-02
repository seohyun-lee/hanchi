"""Rank candidates for a query (calibration helper).

Usage: scripts/dev/rank.sh [-p PLUGIN]... [-e "name|type"]... query cand1 cand2 ...
A candidate may be JSON: '{"name": "찾아줘", "category": "방탈출", "location": "강남"}'.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from hanchi import Analyzer


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--plugin", action="append", default=[])
    ap.add_argument("-e", "--entity", action="append", default=[])
    ap.add_argument("query")
    ap.add_argument("candidates", nargs="+")
    args = ap.parse_args()
    plugins = list(args.plugin)
    if args.entity:
        d = Path(tempfile.mkdtemp())
        (d / "entities").mkdir()
        rows = []
        for e in args.entity:
            name, _, typ = e.partition("|")
            rows.append(f"{name}\t{name}\t{typ or 'name'}\tcli\t1.0")
        (d / "entities" / "cli.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
        plugins.append(str(d))
    a = Analyzer(plugins)
    cands = [json.loads(c) if c.startswith("{") else c for c in args.candidates]
    r = a.rank(args.query, cands)
    print(f"## {args.query}  mode={r.mode} required={r.required} dropped={r.dropped}")
    for x in r:
        m = ", ".join(f"{p['span']}:{p['role']}={p['match']}" for p in x.explain["matches"])
        print(
            f"  {x.score:7.3f} t{x.tier} {'P' if x.passed else '-'} {x.name:<22} "
            f"[{m}] bonus={x.explain['bonus']} pen={x.explain['penalty']} "
            f"reading={x.explain['reading']}({x.explain['reading_p']}) sense={x.sense_id}"
        )


if __name__ == "__main__":
    main()
