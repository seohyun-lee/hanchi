"""Evaluation harness: ranking (Hit@1, MRR) and role accuracy over case files.

Case files may live anywhere (including outside this repository), so domain teams can
keep private evaluation sets next to their private plugins.

Ranking cases
    ``*.tsv``   ``query ⇥ candidates ⇥ expected_top1 ⇥ note`` — candidates and
                acceptable answers are separated by ``｜`` (U+FF5C)
    ``*.jsonl`` one object per line: ``query``, ``candidates`` (strings or objects with
                ``name`` and optional ``category`` / ``location``), ``expected_top1``
                (string or list of acceptable names), optional ``note``, ``domain``,
                ``plugins`` (extra plugin dirs, relative to the file), ``entities``
                (``[name, type]`` pairs added for this case only), ``aliases``
                (``[variant, target]`` pairs) and ``context``

Role cases
    ``*.tsv``   ``query ⇥ span ⇥ expected ⇥ note``
    ``*.jsonl`` ``query``, ``span``, ``expected`` (+ the optional keys above)

``expected`` is a role (``HEAD``), a role and sense (``ENTITY/apple_inc``) or ``none``
(the span must stay unresolved). A role is checked against the span's top hypothesis.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hanchi.analyzer import Analyzer
from hanchi.config import load_yaml

SEP = "\uff5c"  # FULLWIDTH VERTICAL LINE


@dataclass
class Case:
    kind: str  # "rank" | "role"
    query: str
    candidates: list[Any] = field(default_factory=list)
    expected: list[str] = field(default_factory=list)
    span: str = ""
    note: str = ""
    domain: str = ""
    plugins: list[str] = field(default_factory=list)
    entities: list[tuple[str, str]] = field(default_factory=list)
    aliases: list[tuple[str, str]] = field(default_factory=list)
    context: dict[str, Any] | None = None
    source: str = ""


@dataclass
class Failure:
    case: Case
    got: Any


@dataclass
class Report:
    rank_cases: int = 0
    hits: int = 0
    reciprocal_ranks: float = 0.0
    role_cases: int = 0
    role_correct: int = 0
    failures: list[Failure] = field(default_factory=list)
    by_domain: dict[str, list[int]] = field(default_factory=dict)

    @property
    def hit_at_1(self) -> float:
        return self.hits / self.rank_cases if self.rank_cases else 0.0

    @property
    def mrr(self) -> float:
        return self.reciprocal_ranks / self.rank_cases if self.rank_cases else 0.0

    @property
    def role_accuracy(self) -> float:
        return self.role_correct / self.role_cases if self.role_cases else 0.0

    def metrics(self) -> dict[str, float]:
        return {
            "hit@1": round(self.hit_at_1, 4),
            "mrr": round(self.mrr, 4),
            "role_accuracy": round(self.role_accuracy, 4),
        }

    def summary(self) -> str:
        lines = [
            f"ranking cases: {self.rank_cases}  Hit@1 {self.hit_at_1:.3f}  MRR {self.mrr:.3f}",
            f"role cases:    {self.role_cases}  accuracy {self.role_accuracy:.3f}",
        ]
        for domain, (n, ok) in sorted(self.by_domain.items()):
            lines.append(f"  {domain or '-':<10} {ok}/{n}")
        for f in self.failures:
            c = f.case
            what = (
                f"span {c.span!r} expected {c.expected}"
                if c.kind == "role"
                else f"expected {c.expected}"
            )
            lines.append(f"FAIL [{c.kind}] {c.query!r}: {what}, got {f.got}  ({c.source})")
        return "\n".join(lines)


# --- loading -----------------------------------------------------------------------


def _split(cell: str) -> list[str]:
    return [x.strip() for x in cell.split(SEP) if x.strip()]


def load_cases(path: str | Path, kind: str) -> list[Case]:
    path = Path(path)
    cases: list[Case] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            src = f"{path.name}:{n}"
            if path.suffix == ".jsonl":
                cases.append(_from_json(json.loads(line), kind, path.parent, src))
            else:
                cols = [c.strip() for c in line.split("\t")]
                note = cols[3] if len(cols) > 3 else ""
                domain = note.split(":", 1)[0].strip() if ":" in note else ""
                if kind == "rank":
                    cases.append(
                        Case(
                            "rank",
                            cols[0],
                            _split(cols[1]),
                            _split(cols[2]),
                            note=note,
                            domain=domain,
                            source=src,
                        )
                    )
                else:
                    cases.append(
                        Case(
                            "role",
                            cols[0],
                            expected=[cols[2]],
                            span=cols[1],
                            note=note,
                            domain=domain,
                            source=src,
                        )
                    )
    return cases


def _from_json(obj: dict[str, Any], kind: str, base: Path, src: str) -> Case:
    expected = obj.get("expected_top1", obj.get("expected"))
    exp = [expected] if isinstance(expected, str) else list(expected or [])
    plugins = [
        p if p.startswith("preset:") else str((base / p).resolve()) for p in obj.get("plugins", [])
    ]
    return Case(
        kind=kind,
        query=obj["query"],
        candidates=list(obj.get("candidates", [])),
        expected=exp,
        span=obj.get("span", ""),
        note=obj.get("note", ""),
        domain=obj.get("domain", ""),
        plugins=plugins,
        entities=[tuple(e) for e in obj.get("entities", [])],
        aliases=[tuple(a) for a in obj.get("aliases", [])],
        context=obj.get("context"),
        source=src,
    )


# --- running -----------------------------------------------------------------------


class _Analyzers:
    """One analyzer per distinct (extra plugins, entities, aliases) combination."""

    def __init__(self, base_plugins: Sequence[str], overrides: Sequence[str]) -> None:
        self.base = list(base_plugins)
        self.overrides = list(overrides)
        self._cache: dict[tuple[Any, ...], Analyzer] = {}

    def get(self, case: Case) -> Analyzer:
        key = (tuple(case.plugins), tuple(case.entities), tuple(case.aliases))
        if key not in self._cache:
            extra = list(case.plugins)
            if case.entities or case.aliases:
                extra.append(_inline_plugin(case.entities, case.aliases))
            self._cache[key] = Analyzer(self.base + extra, overrides=self.overrides)
        return self._cache[key]


def _inline_plugin(entities: Iterable[tuple[str, str]], aliases: Iterable[tuple[str, str]]) -> str:
    d = Path(tempfile.mkdtemp(prefix="hanchi-eval-"))
    (d / "entities").mkdir()
    rows = [f"{name}\t{name}\t{typ}\teval\t1.0" for name, typ in entities]
    (d / "entities" / "eval.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    (d / "aliases.tsv").write_text("".join(f"{v}\t{t}\n" for v, t in aliases), encoding="utf-8")
    return str(d)


def evaluate(
    cases: Iterable[Case],
    plugins: Sequence[str] = (),
    overrides: Sequence[str] = (),
) -> Report:
    analyzers = _Analyzers(plugins, overrides)
    report = Report()
    for case in cases:
        a = analyzers.get(case)
        domain = report.by_domain.setdefault(case.domain, [0, 0])
        domain[0] += 1
        if case.kind == "rank":
            ranking = a.rank(case.query, case.candidates, context=case.context)
            names = ranking.names()
            report.rank_cases += 1
            rank_pos = next((i for i, n in enumerate(names) if n in case.expected), None)
            if rank_pos is not None:
                report.reciprocal_ranks += 1.0 / (rank_pos + 1)
            if rank_pos == 0:
                report.hits += 1
                domain[1] += 1
            else:
                report.failures.append(Failure(case, names[:3]))
        else:
            ok, got = _check_role(a, case)
            report.role_cases += 1
            if ok:
                report.role_correct += 1
                domain[1] += 1
            else:
                report.failures.append(Failure(case, got))
    return report


def _check_role(a: Analyzer, case: Case) -> tuple[bool, str]:
    analysis = a.analyze(case.query, context=case.context)
    try:
        span = analysis.span(case.span)
    except KeyError:
        return False, f"no span {case.span!r} in {[s.text for s in analysis.spans]}"
    expected = case.expected[0]
    top = span.top
    got = f"{top.role}/{top.sense_id}" if top.sense_id else top.role
    if expected.lower() == "none":
        return span.resolved is None, "resolved" if span.resolved else "none"
    role, _, sense = expected.partition("/")
    ok = top.role == role and (not sense or top.sense_id == sense)
    return ok, got


def run_config(config: str | Path, case_files: Sequence[str | Path] = ()) -> Report:
    """Evaluate with an eval config YAML::

    plugins: [preset:local, ./plugin]      # relative to the config file
    overrides: []
    cases: [cases.tsv, cases.jsonl]        # ranking cases
    roles: [roles.tsv, roles.jsonl]        # role cases
    """
    cfg_path = Path(config)
    cfg = load_yaml(cfg_path)
    base = cfg_path.parent

    def rel(p: str) -> str:
        return p if p.startswith("preset:") else str((base / p).resolve())

    cases: list[Case] = []
    if case_files:
        for f in case_files:
            kind = "role" if Path(f).stem.startswith("role") else "rank"
            cases += load_cases(f, kind)
    else:
        for f in cfg.get("cases", []):
            cases += load_cases(base / f, "rank")
        for f in cfg.get("roles", []):
            cases += load_cases(base / f, "role")
    return evaluate(
        cases,
        [rel(p) for p in cfg.get("plugins", [])],
        [rel(p) for p in cfg.get("overrides", [])],
    )


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="hanchi eval", description=__doc__.split("\n")[0])
    ap.add_argument("files", nargs="*", help="case files (default: those listed in --config)")
    ap.add_argument("-c", "--config", help="eval config YAML (plugins, overrides, case files)")
    ap.add_argument("-p", "--plugin", action="append", default=[], help="plugin dir or preset:name")
    ap.add_argument("--min-hit1", type=float, help="exit 1 if Hit@1 is below this")
    ap.add_argument("--min-mrr", type=float, help="exit 1 if MRR is below this")
    ap.add_argument("--min-role", type=float, help="exit 1 if role accuracy is below this")
    ap.add_argument("--json", action="store_true", help="print metrics as JSON")
    args = ap.parse_args(argv)

    if args.config:
        report = run_config(args.config, args.files)
    else:
        cases: list[Case] = []
        for f in args.files:
            kind = "role" if Path(f).stem.startswith("role") else "rank"
            cases += load_cases(f, kind)
        report = evaluate(cases, args.plugin)
    print(json.dumps(report.metrics()) if args.json else report.summary())
    m = report.metrics()
    below = (
        (args.min_hit1 is not None and m["hit@1"] < args.min_hit1)
        or (args.min_mrr is not None and m["mrr"] < args.min_mrr)
        or (args.min_role is not None and m["role_accuracy"] < args.min_role)
    )
    return 1 if below else 0


if __name__ == "__main__":
    sys.exit(main())
