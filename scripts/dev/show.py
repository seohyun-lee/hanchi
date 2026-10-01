"""Print compact analyses for calibration.

Usage: scripts/dev/show.sh [-p PLUGIN]... [-e "name|type"]... [-c JSON] query...
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
    ap.add_argument("-c", "--context")
    ap.add_argument("-x", "--explain", action="store_true")
    ap.add_argument("queries", nargs="+")
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
    ctx = json.loads(args.context) if args.context else None
    for q in args.queries:
        r = a.analyze(q, context=ctx, explain=args.explain)
        print(f"\n## {q}   ambiguous={r.ambiguous} clauses={r.clauses} signals={r.signals}")
        for it in r.interpretations[:5]:
            merges = [m["text"] for m in it.merges]
            print(f"   interp p={it.p:.3f} score={it.score:.2f} merges={merges}")
        for i, s in enumerate(r.spans):
            hyps = " ".join(
                f"{h.role}{'/' + h.sense_id if h.sense_id else ''}:{h.p:.2f}(w{h.weight:.2f})"
                for h in s.hypotheses
            )
            res = s.resolved.role if s.resolved else "-"
            att = f" attach={s.attach}" if s.attach else ""
            print(
                f"  [{i}] c{s.clause_id} {s.text!r:<16} {s.pos_detail:<22} R={res:<10} {hyps}{att}"
            )
        if args.explain and r.explain:
            for sp in r.explain["spans"]:
                for h in sp["hypotheses"][:3]:
                    contrib = ", ".join(f"{c['feature']}={c['value']}" for c in h["contributions"])
                    print(f"      {sp['text']} {h['role']} logit={h['logit']}: {contrib}")


if __name__ == "__main__":
    main()
