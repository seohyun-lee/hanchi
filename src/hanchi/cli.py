"""Command-line interface (``hanchi``).

::

    hanchi analyze "강남 센터"                       # table: span | clause | POS | roles | …
    hanchi analyze --json "..."                      # JSON
    hanchi analyze --context prev.json "..."         # session context (prev_query, …)
    hanchi analyze -w 4 < queries.txt                # one query per line, JSON lines out
    hanchi rank "강남 센터" -c candidates.txt        # ranking + score breakdown
    hanchi expand "식당"                             # synonyms / hierarchy expansion
    hanchi eval -c eval.yaml                         # Hit@1, MRR, role accuracy
    hanchi repl                                      # interactive
    hanchi dict export --format kiwi|nori -o out/    # dictionary export
    hanchi dictgen run --sources ftc -o my_plugin/   # public-data dictionary update
    hanchi learn sense-prior --clicks c.tsv -o p.tsv # calibrate from click logs

Every command accepts ``--config FILE`` (see :meth:`hanchi.Analyzer.from_config`),
``-p/--plugin DIR|preset:NAME`` (repeatable, applied after the config's plugins) and
``--override FILE``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, TextIO

from hanchi import __version__


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", help="analyzer config YAML (plugins, overrides …)")
    p.add_argument("-p", "--plugin", action="append", default=[], help="plugin dir or preset:NAME")
    p.add_argument("--override", action="append", default=[], help="overrides.tsv file")
    p.add_argument("--weighter", help="weighter backend: rule (default), bge-m3, …")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hanchi",
        description="Korean query understanding: per-word role & weight from context.",
    )
    parser.add_argument("--version", action="version", version=f"hanchi {__version__}")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("analyze", help="analyze queries")
    _common(p)
    p.add_argument("text", nargs="*", help="queries (default: one per line from stdin)")
    p.add_argument("--json", action="store_true", help="JSON output (JSON lines for several)")
    p.add_argument("--explain", action="store_true", help="include feature contributions")
    p.add_argument("--context", help="JSON file with context (prev_query, prev_result_count …)")
    p.add_argument("-w", "--workers", type=int, default=1, help="threads for batch input")

    p = sub.add_parser("rank", help="rank candidate names for a query")
    _common(p)
    p.add_argument("query")
    p.add_argument("candidate", nargs="*", help="candidates (also see -c)")
    p.add_argument(
        "-c", "--candidates", help="file: one candidate per line (plain name or JSON object)"
    )
    p.add_argument("-k", type=int, help="relax until at least k candidates pass")
    p.add_argument("--json", action="store_true")
    p.add_argument("--context", help="JSON file with context")

    p = sub.add_parser("expand", help="synonym / hierarchy expansion")
    _common(p)
    p.add_argument("text")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("repl", help="interactive analysis")
    _common(p)

    p = sub.add_parser("dict", help="dictionary tools")
    _common(p)
    dsub = p.add_subparsers(dest="dict_command", required=True)
    e = dsub.add_parser("export", help="export dictionaries for Kiwi or nori")
    _common(e)
    e.add_argument("--format", choices=["kiwi", "nori"], required=True)
    e.add_argument("-o", "--out", default=".", help="output directory")

    p = sub.add_parser("dictgen", help="build entity dictionaries from public data")
    gsub = p.add_subparsers(dest="dictgen_command", required=True)
    g = gsub.add_parser("run", help="collect -> diff -> judge -> write plugin files + report")
    _common(g)
    g.add_argument("--sources", default="ftc", help="comma-separated sources (available: ftc)")
    g.add_argument("-o", "--out", required=True, help="plugin directory to update")
    g.add_argument("--since", choices=["last"], help="report entries not seen since the last run")
    g.add_argument("--no-stdict", action="store_true", help="skip the dictionary headword check")
    g.add_argument("--write-idf", action="store_true", help="write idf.tsv from collected names")
    g.add_argument("--dictgen-config", help="YAML overriding dictgen settings (API fields …)")

    p = sub.add_parser("learn", help="calibrate from user data / collect synonym candidates")
    lsub = p.add_subparsers(dest="learn_command", required=True)
    sp = lsub.add_parser("sense-prior", help="clicks.tsv -> sense_prior.tsv")
    _common(sp)
    sp.add_argument("--clicks", required=True, help="query ⇥ clicked ⇥ count ⇥ vertical")
    sp.add_argument("-o", "--out", required=True, help="output sense_prior.tsv")
    sp.add_argument("--smoothing", type=float, default=1.0)
    rp = lsub.add_parser("role-priors", help="role_feedback.tsv -> suggested rules.yaml priors")
    _common(rp)
    rp.add_argument("--labels", required=True, help="query ⇥ span ⇥ ROLE ⇥ count")
    rp.add_argument("--smoothing", type=float, default=1.0)
    sy = lsub.add_parser("synonyms", help="embedding-similar lexicon terms -> review markdown")
    _common(sy)
    sy.add_argument("--lexicon", default="head", help="lexicon name (default: head)")
    sy.add_argument("--threshold", type=float, default=0.8)
    sy.add_argument("--top", type=int, default=200)
    sy.add_argument("-o", "--out", required=True, help="output markdown file")

    sub.add_parser(
        "eval", help="evaluate ranking / role cases (see hanchi eval -h)", add_help=False
    )
    return parser


def _analyzer(args: argparse.Namespace) -> Any:
    from hanchi.analyzer import Analyzer

    plugins = list(args.plugin)
    options: dict[str, Any] = {"overrides": list(args.override)}
    if getattr(args, "weighter", None):
        options["weighter"] = args.weighter
    if args.config:
        return Analyzer.from_config(args.config, extra_plugins=plugins, **options)
    return Analyzer(plugins, **options)


def _context(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: context must be a JSON object")
    return data


# --- table output --------------------------------------------------------------------


def _width(s: str) -> int:
    import unicodedata

    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def _pad(s: str, w: int) -> str:
    return s + " " * max(0, w - _width(s))


def _table(rows: list[list[str]], out: TextIO) -> None:
    widths = [max(_width(r[i]) for r in rows) for i in range(len(rows[0]))]
    for n, row in enumerate(rows):
        print("  ".join(_pad(c, w) for c, w in zip(row, widths, strict=True)).rstrip(), file=out)
        if n == 0:
            print("  ".join("-" * w for w in widths), file=out)


def _fmt_attach(analysis: Any, attach: dict[str, Any] | None) -> str:
    if not attach:
        return ""
    anchor = attach.get("anchor")
    if isinstance(anchor, int):
        anchor = analysis.spans[anchor].text
    return f"{attach['type']}→{anchor}"


def print_analysis(analysis: Any, out: TextIO, max_hyps: int = 3) -> None:
    rows = [
        ["#", "span", "clause", "POS", "role (p)", "sense/type", "weight", "attach", "evidence"]
    ]
    for i, s in enumerate(analysis.spans):
        hyps = s.hypotheses[:max_hyps]
        roles = " ".join(f"{h.role}{'*' if s.resolved is h else ''}({h.p:.2f})" for h in hyps)
        top = s.top
        sense = "/".join(x for x in (top.sense_id, top.type) if x)
        rows.append(
            [
                str(i),
                s.text,
                str(s.clause_id),
                s.pos_detail,
                roles,
                sense,
                f"{top.weight:.2f}",
                _fmt_attach(analysis, s.attach),
                ", ".join(top.evidence[:3]),
            ]
        )
    _table(rows, out)
    flags = ["ambiguous" if analysis.ambiguous else "resolved"]
    if len(analysis.interpretations) > 1:
        alt = analysis.interpretations[1]
        merged = ", ".join(str(m["text"]) for m in alt.merges) or "(no merge)"
        flags.append(
            f"top reading p={analysis.interpretations[0].p:.2f}; next: {merged} p={alt.p:.2f}"
        )
    print("  ".join(flags), file=out)
    for sig in analysis.signals:
        print(f"signal: {sig['type']} '{sig['span']}' (clause {sig['clause_id']})", file=out)
    print("* = resolved", file=out)


# --- commands ---------------------------------------------------------------------------


def cmd_analyze(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    a = _analyzer(args)
    ctx = _context(args.context)
    texts = list(args.text) or [line.strip() for line in inp if line.strip()]
    results = a.analyze_batch(texts, workers=args.workers, context=ctx, explain=args.explain)
    for n, r in enumerate(results):
        if args.json:
            indent = 2 if len(results) == 1 else None
            print(r.to_json(indent=indent), file=out)
        else:
            if n:
                print(file=out)
            print(f"» {r.query}", file=out)
            print_analysis(r, out)
            if args.explain and r.explain:
                print(json.dumps(r.explain, ensure_ascii=False, indent=2), file=out)
    return 0


def _load_candidates(path: str) -> list[Any]:
    out: list[Any] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append(json.loads(line) if line.startswith("{") else line)
    return out


def cmd_rank(args: argparse.Namespace, out: TextIO) -> int:
    a = _analyzer(args)
    cands: list[Any] = [json.loads(c) if c.startswith("{") else c for c in args.candidate]
    if args.candidates:
        cands += _load_candidates(args.candidates)
    if not cands:
        raise SystemExit("no candidates (pass them as arguments or with -c FILE)")
    r = a.rank(args.query, cands, k=args.k, context=_context(args.context))
    if args.json:
        data = {
            "query": r.query,
            "mode": r.mode,
            "required": r.required,
            "dropped": r.dropped,
            "constraints": r.constraints,
            "signals": r.signals,
            "results": [
                {
                    "name": x.name,
                    "score": x.score,
                    "tier": x.tier,
                    "passed": x.passed,
                    "sense_id": x.sense_id,
                    "explain": x.explain,
                }
                for x in r
            ],
        }
        print(json.dumps(data, ensure_ascii=False, indent=2), file=out)
        return 0
    print(f"» {r.query}   mode={r.mode}  required={r.required}  dropped={r.dropped}", file=out)
    rows = [["rank", "score", "tier", "pass", "candidate", "matches", "bonus", "penalty"]]
    for n, x in enumerate(r, 1):
        matches = ", ".join(f"{m['span']}:{m['match']}" for m in x.explain["matches"])
        rows.append(
            [
                str(n),
                f"{x.score:.3f}",
                str(x.tier),
                "y" if x.passed else "-",
                x.name,
                matches,
                f"{x.explain['bonus']:g}",
                f"{x.explain['penalty']:g}",
            ]
        )
    _table(rows, out)
    for c in r.constraints:
        print(f"constraint: {c['span']} {c['type']}→{c['anchor']}", file=out)
    return 0


def cmd_expand(args: argparse.Namespace, out: TextIO) -> int:
    a = _analyzer(args)
    items = a.expand(a.analyze(args.text))
    if args.json:
        data = [vars(e) for e in items]
        print(json.dumps(data, ensure_ascii=False, indent=2), file=out)
        return 0
    if not items:
        print("(nothing to expand: no span with a resolved sense)", file=out)
        return 0
    rows = [["source", "term", "relation", "weight", "sense"]]
    rows += [[e.source, e.term, e.relation, f"{e.weight:.2f}", e.sense_id] for e in items]
    _table(rows, out)
    return 0


SEP = "\uff5c"  # FULLWIDTH VERTICAL LINE, as in evaluation case files

REPL_HELP = f"""commands:
  :json          toggle JSON output
  :explain       toggle feature contributions
  :context       toggle session context (previous line becomes prev_query)
  :rank A{SEP}B{SEP}C   rank candidates for the previous query
  :expand        expand the previous query
  :q             quit"""


def cmd_repl(args: argparse.Namespace, out: TextIO, inp: TextIO) -> int:
    a = _analyzer(args)
    as_json = explain = session = False
    prev: str | None = None
    print("hanchi repl — type a query, :help for commands", file=out)
    while True:
        print("hanchi> ", end="", file=out, flush=True)
        line = inp.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        if line in (":q", ":quit", ":exit"):
            break
        if line == ":help":
            print(REPL_HELP, file=out)
        elif line == ":json":
            as_json = not as_json
            print(f"json {'on' if as_json else 'off'}", file=out)
        elif line == ":explain":
            explain = not explain
            print(f"explain {'on' if explain else 'off'}", file=out)
        elif line == ":context":
            session = not session
            print(f"session context {'on' if session else 'off'}", file=out)
        elif line.startswith(":rank"):
            cands = [c.strip() for c in line[5:].split(SEP) if c.strip()]
            if prev is None or not cands:
                print(f"usage: :rank A{SEP}B{SEP}C (after a query)", file=out)
                continue
            for n, x in enumerate(a.rank(prev, cands), 1):
                print(f"{n}. {x.name}  {x.score:.3f}", file=out)
        elif line == ":expand":
            if prev is not None:
                for e in a.expand(a.analyze(prev)):
                    print(f"{e.term}  {e.relation}  {e.weight:.2f}", file=out)
        else:
            ctx = {"prev_query": prev} if session and prev else None
            r = a.analyze(line, context=ctx, explain=explain)
            if as_json:
                print(r.to_json(indent=2), file=out)
            else:
                print_analysis(r, out)
                if explain and r.explain:
                    print(json.dumps(r.explain["spans"], ensure_ascii=False, indent=2), file=out)
            prev = line
    return 0


def cmd_dict(args: argparse.Namespace, out: TextIO) -> int:
    from hanchi.lang.ko.export import export

    a = _analyzer(args)
    path = export(a, args.format, args.out)
    count = sum(
        1 for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("#")
    )
    print(f"wrote {count} entries to {path}", file=out)
    return 0


def cmd_dictgen(args: argparse.Namespace, out: TextIO) -> int:
    from hanchi.dictgen.pipeline import run
    from hanchi.dictgen.sources import MissingKeyError

    a = _analyzer(args)
    try:
        results = run(
            [s.strip() for s in args.sources.split(",") if s.strip()],
            args.out,
            a,
            config=args.dictgen_config,
            check_stdict=not args.no_stdict,
            since_last=args.since == "last",
            write_idf=args.write_idf,
        )
    except MissingKeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    for r in results:
        print(
            f"{r.source}: {len(r.candidates)} collected, {r.count('approved')} approved, "
            f"{r.count('review')} to review, {r.count('held')} held -> {r.report}",
            file=out,
        )
    return 0


def cmd_learn(args: argparse.Namespace, out: TextIO) -> int:
    from hanchi import learn

    a = _analyzer(args)
    if args.learn_command == "sense-prior":
        priors = learn.sense_prior_from_clicks(a, learn.read_clicks(args.clicks), args.smoothing)
        path = learn.write_sense_prior(args.out, priors)
        print(f"wrote {len(priors)} rows to {path}", file=out)
    elif args.learn_command == "role-priors":
        labels = learn.read_role_feedback(args.labels)
        suggested = learn.role_prior_suggestions(a, labels, args.smoothing)
        print("# suggested rules.yaml (review before use)", file=out)
        print("priors:", file=out)
        for role, value in suggested.items():
            print(f"  {role}: {value}", file=out)
    else:
        from hanchi.neural.bge_m3 import BgeM3Encoder

        terms = sorted(a.resources.lexicon.get(args.lexicon, {}))
        encoder = BgeM3Encoder()
        cands = learn.synonym_candidates(terms, encoder.dense, args.threshold, args.top)
        path = learn.write_synonym_review(args.out, cands, f"lexicon:{args.lexicon}")
        print(f"wrote {len(cands)} candidate pairs to {path}", file=out)
    return 0


def main(
    argv: Sequence[str] | None = None, out: TextIO | None = None, inp: TextIO | None = None
) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    out = sys.stdout if out is None else out
    inp = sys.stdin if inp is None else inp
    if args_list and args_list[0] == "eval":
        from hanchi.evaluation import main as eval_main

        return eval_main(args_list[1:])
    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command == "analyze":
        return cmd_analyze(args, out, inp)
    if args.command == "rank":
        return cmd_rank(args, out)
    if args.command == "expand":
        return cmd_expand(args, out)
    if args.command == "repl":
        return cmd_repl(args, out, inp)
    if args.command == "dict":
        return cmd_dict(args, out)
    if args.command == "dictgen":
        return cmd_dictgen(args, out)
    if args.command == "learn":
        return cmd_learn(args, out)
    parser.print_help(file=out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
