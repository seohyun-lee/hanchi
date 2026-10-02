"""Ranking helper: score candidate names against an analyzed query (plan §5.7, §11.7, §12.6).

Hanchi does not search. Given candidates that some search system already retrieved,
:func:`rank` orders them using the query's roles, weights and alternative readings:

- every reading of the query is tried: interpretations (segmentations) × the top
  hypotheses of up to ``rank.max_ambiguous_spans`` unresolved spans; a candidate's
  score is the best ``p(reading) × score(reading)``
- query spans match candidate spans exactly (1.0), through a canonical form (1.0),
  as a prefix (0.9) or only inside / at the tail (0.3); a name-like query span that
  only meets a category/branch/function part of the candidate counts as a weak match
- candidate spans that carry meaning (ENTITY, MODIFIER) but match nothing are penalized
- a candidate whose whole name equals a name-like query span ranks above partial
  matches: dictionary-backed multi-word names first, then single spans (``tier``)
- strict → relaxed: when fewer than ``k`` candidates match every important query span,
  the least important required spans are dropped one at a time
- when a span has several senses, results of the most likely sense come first and
  the best few of each other sense are mixed in

Every number comes from ``rules.yaml: rank``.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from hanchi.schema import (
    COMMAND,
    ENTITY,
    FUNC,
    HEAD,
    LOCATION,
    META,
    MODIFIER,
    QUALIFIER,
    Analysis,
    Hypothesis,
    Span,
)
from hanchi.weights import base_weight

if TYPE_CHECKING:
    from hanchi.analyzer import Analyzer

Candidate = str | Mapping[str, Any]

_COMMON_DOC_ROLES = (HEAD, QUALIFIER, FUNC, COMMAND)
_PENALIZED_DOC_ROLES = (ENTITY, MODIFIER)
_IGNORED_QUERY_ROLES = (META, FUNC)


@dataclass
class RankResult:
    candidate: Candidate
    name: str
    score: float
    tier: int
    passed: bool
    """Matched every required query span (see :attr:`Ranking.required`)."""
    sense_id: str | None
    explain: dict[str, Any]


@dataclass
class Ranking:
    query: str
    mode: str
    """``"strict"`` or ``"relaxed"``."""
    required: list[str]
    dropped: list[str]
    """Query spans no longer required in relaxed mode (least important first)."""
    results: list[RankResult]
    constraints: list[dict[str, Any]] = field(default_factory=list)
    """Attached constraints from the query (proximity, time …) for the caller to apply."""
    signals: list[dict[str, Any]] = field(default_factory=list)

    def __iter__(self) -> Iterator[RankResult]:
        return iter(self.results)

    def __len__(self) -> int:
        return len(self.results)

    def names(self) -> list[str]:
        return [r.name for r in self.results]


@dataclass
class _DocSpan:
    key: str
    canonical: str | None
    role: str
    weight: float
    senses: set[str]
    field: str = "name"
    parent: int | None = None
    """For ``field="part"``: index of the name span it is a piece of."""


@dataclass
class _Doc:
    candidate: Candidate
    name: str
    key: str
    canonicals: set[str]
    spans: list[_DocSpan]


@dataclass
class _QSpan:
    key: str
    canonical: str | None
    hyp: Hypothesis
    clause: int
    merged: bool
    text: str


@dataclass
class _Reading:
    p: float
    spans: list[_QSpan]
    interpretation: int


def rank(
    analyzer: Analyzer,
    query: str | Analysis,
    candidates: Sequence[Candidate],
    *,
    k: int | None = None,
    context: Mapping[str, Any] | None = None,
) -> Ranking:
    res = analyzer.resources
    cfg = res.setting("rank")
    k = int(cfg["min_results"]) if k is None else k
    analysis = query if isinstance(query, Analysis) else analyzer.analyze(query, context=context)
    readings = _readings(analysis, cfg, res)
    docs = [_doc(analyzer, c) for c in candidates]
    main_clause = _main_clause(analysis)

    min_match = float(cfg["strict_match"])
    scored: list[_Scored] = []
    for doc in docs:
        best: _Scored | None = None
        tier = 0
        for r in readings:
            sc = _score_reading(r, doc, cfg, res, main_clause)
            tier = max(tier, sc.tier)
            if best is None or sc.value > best.value:
                best = sc
        assert best is not None
        best.tier = tier
        scored.append(best)

    # strict -> relaxed: allow the n least important required spans to be missed
    def passes(sc: _Scored, n: int) -> bool:
        needed = sorted(sc.required, key=lambda kw: -kw[1])
        needed = needed[: max(0, len(needed) - n)]
        return all(sc.matched.get(key, 0.0) >= min_match for key, _ in needed)

    top_required = _required(readings[0], cfg, main_clause)
    n = 0
    max_n = max((len(sc.required) for sc in scored), default=0)
    while n < max_n and sum(passes(sc, n) for sc in scored) < k:
        n += 1
    dropped = [key for key, _ in sorted(top_required, key=lambda kw: kw[1])[:n]]

    # Senses of query words that have several (homonyms): results are diversified over them.
    homonym_senses: set[str | None] = set()
    for span in analysis.spans:
        ids = {h.sense_id for h in span.hypotheses if h.sense_id}
        if len(ids) > 1 and span.resolved is None:
            homonym_senses |= ids
    results = [
        RankResult(
            candidate=sc.doc.candidate,
            name=sc.doc.name,
            score=round(sc.value, 6),
            tier=sc.tier,
            passed=passes(sc, n),
            sense_id=next(
                (q.hyp.sense_id for q in sc.reading.spans if q.hyp.sense_id in homonym_senses),
                None,
            ),
            explain={
                "reading": sc.reading.interpretation,
                "reading_p": round(sc.reading.p, 6),
                **sc.detail,
            },
        )
        for sc in scored
    ]
    results.sort(key=lambda r: (-r.tier, not r.passed, -r.score))
    results = _diversify(results, analysis, cfg)
    constraints = [{"span": s.text, **s.attach} for s in analysis.spans if s.attach is not None]
    return Ranking(
        query=analysis.query,
        mode="strict" if n == 0 else "relaxed",
        required=[key for key, _ in top_required],
        dropped=dropped,
        results=results,
        constraints=constraints,
        signals=analysis.signals,
    )


# --- query side --------------------------------------------------------------------


def _main_clause(a: Analysis) -> int:
    for s in a.spans:
        if s.top.role == COMMAND:
            return s.clause_id
    return 0


def _qspan(s: Span, h: Hypothesis, merged: bool, res: Any) -> _QSpan:
    key = s.norm.replace(" ", "")
    canonical = None
    if h.sense_id:
        sense = res.senses.get(h.sense_id)
        canonical = sense.canonical if sense else h.sense_id
    return _QSpan(key, canonical and res.key(canonical), h, s.clause_id, merged, s.text)


def _readings(a: Analysis, cfg: Mapping[str, Any], res: Any) -> list[_Reading]:
    max_amb = int(cfg["max_ambiguous_spans"])
    per_span = int(cfg["hypotheses_per_span"])
    min_p = float(cfg["min_reading_p"])
    out: list[_Reading] = []
    for idx, it in enumerate(a.interpretations):
        supported = {str(m["text"]) for m in it.merges if m.get("supported")}
        options: list[list[tuple[Hypothesis, float]]] = []
        ambiguous = 0
        for s in it.spans:
            hyps = sorted(s.hypotheses, key=lambda h: -h.p)
            if s.resolved is None and ambiguous < max_amb and len(hyps) > 1:
                ambiguous += 1
                options.append([(h, h.p) for h in hyps[:per_span]])
            else:
                options.append([(hyps[0], 1.0)])
        for combo in itertools.product(*options):
            p = it.p
            for _, hp in combo:
                p *= hp
            if p < min_p:
                continue
            spans = [
                _qspan(s, h, s.text in supported, res)
                for s, (h, _) in zip(it.spans, combo, strict=True)
                if h.role not in _IGNORED_QUERY_ROLES and h.weight > 0
            ]
            out.append(_Reading(p, spans, idx))
    if not out:  # keep at least the best reading
        it = a.interpretations[0]
        spans = [
            _qspan(s, s.top, False, res) for s in it.spans if s.top.role not in _IGNORED_QUERY_ROLES
        ]
        out.append(_Reading(it.p, spans, 0))
    return out


def _required(r: _Reading, cfg: Mapping[str, Any], main_clause: int) -> list[tuple[str, float]]:
    """Query spans a strict match must contain: in the request clause, heavy enough and not
    a request word."""
    min_w = float(cfg["strict_min_weight"])
    return [
        (q.key, q.hyp.weight)
        for q in r.spans
        if q.clause == main_clause and q.hyp.role != COMMAND and q.hyp.weight >= min_w
    ]


# --- candidate side ----------------------------------------------------------------


def _doc(analyzer: Analyzer, c: Candidate) -> _Doc:
    res = analyzer.resources
    if isinstance(c, str):
        name, fields = c, {}
    else:
        name = str(c["name"])
        fields = {f: str(c[f]) for f in ("category", "location") if c.get(f)}
    a = analyzer.analyze(name)
    sense_ratio = float(res.setting("rank", "doc_sense_ratio"))
    part_factor = float(res.setting("rank", "part_match"))
    spans = []
    canonicals = set()
    for s in a.spans:
        h = s.top
        if h.role == FUNC:
            continue
        senses = {x.sense_id for x in s.hypotheses if x.sense_id and x.p >= h.p * sense_ratio}
        canonical = (s.canonical or h.sense_id or "").replace(" ", "") or None
        if canonical and len(a.spans) == 1:
            canonicals.add(canonical)
        weight = base_weight(res, h.role)
        spans.append(_DocSpan(s.norm.replace(" ", ""), canonical, h.role, weight, senses))
        if s.parts and len(s.parts) > 1:
            # "연세365의원": partial queries ("365의원", "연세의원") meet its pieces.
            pieces = [res.key(p.norm) for p in s.parts]
            seen = {spans[-1].key}
            parent = len(spans) - 1
            variants = [
                "".join(pieces[a:b])
                for a in range(len(pieces))
                for b in range(a + 1, len(pieces) + 1)
            ]
            variants.append("".join(p for p in pieces if not p.isdigit()))
            for v in variants:
                if v and v not in seen:
                    seen.add(v)
                    spans.append(
                        _DocSpan(v, None, h.role, weight * part_factor, senses, "part", parent)
                    )
    for f, role in (("category", HEAD), ("location", LOCATION)):
        if f in fields:
            spans.append(
                _DocSpan(res.key(fields[f]), None, role, base_weight(res, role), set(), field=f)
            )
    key = res.key(name)
    for entry in res.entities.get(key, []):
        canonicals.add(entry.canonical.replace(" ", ""))
    return _Doc(c, name, key, canonicals, spans)


# --- scoring -----------------------------------------------------------------------


def _match(q: _QSpan, d: _DocSpan, cfg: Mapping[str, Any], min_prefix: int) -> float:
    if q.key == d.key or (q.canonical and q.canonical in (d.key, d.canonical)):
        m = float(cfg["match_exact"])
    elif len(q.key) >= min_prefix and d.key.startswith(q.key):
        m = float(cfg["match_prefix"])
    elif len(q.key) >= min_prefix and q.key in d.key:
        m = float(cfg["match_partial"])
    else:
        return 0.0
    if q.hyp.role == ENTITY and d.role in _COMMON_DOC_ROLES and d.field == "name":
        m = min(m, float(cfg["match_partial"]))
    if q.hyp.sense_id and d.senses and q.hyp.sense_id not in d.senses:
        m *= float(cfg["sense_mismatch"])
    return m


@dataclass
class _Scored:
    doc: _Doc
    reading: _Reading
    value: float
    detail: dict[str, Any]
    matched: dict[str, float]
    required: list[tuple[str, float]]
    tier: int


def _score_reading(
    r: _Reading, doc: _Doc, cfg: Mapping[str, Any], res: Any, main_clause: int
) -> _Scored:
    min_prefix = int(res.setting("lattice", "min_prefix_len"))
    prefix = float(cfg["match_prefix"])
    total = 0.0
    used: set[int] = set()
    matched: dict[str, float] = {}
    parts = []
    whole = _DocSpan(doc.key, None, doc.spans[0].role if doc.spans else ENTITY, 1.0, set())
    for q in r.spans:
        best, best_i, best_m = 0.0, -1, 0.0
        for i, d in enumerate(doc.spans):
            m = _match(q, d, cfg, min_prefix)
            if m * d.weight > best:
                best, best_i, best_m = m * d.weight, i, m
        mw = _match(q, whole, cfg, min_prefix)
        if mw >= prefix:  # a query span covering several candidate spans
            first = doc.spans[0].weight if doc.spans else 1.0
            if mw * first > best:
                best, best_i, best_m = mw * first, -2, mw
        if best_i >= 0:
            used.add(best_i)
            parent = doc.spans[best_i].parent
            if parent is not None:
                used.add(parent)
        elif best_i == -2:
            used.update(i for i, d in enumerate(doc.spans) if d.field == "name" and d.key in q.key)
        if best_m:
            matched[q.key] = max(matched.get(q.key, 0.0), best_m)
        factor = 1.0 if q.clause == main_clause else float(cfg["other_clause_factor"])
        total += best * q.hyp.weight * factor
        parts.append({"span": q.text, "role": q.hyp.role, "match": round(best, 4)})

    # The whole candidate name is one of the query's spans (or the whole query), and
    # the candidate leaves no meaningful query span unmatched.
    cover_min = float(cfg["cover_min_weight"])
    covered = all(matched.get(q.key, 0.0) > 0 for q in r.spans if q.hyp.weight >= cover_min)
    content_key = "".join(q.key for q in r.spans if q.hyp.role != COMMAND)
    name_spans = [
        q for q in r.spans if q.key == doc.key or (q.canonical and q.canonical in doc.canonicals)
    ]
    full_name = bool(name_spans) or content_key == doc.key
    bonus = float(cfg["full_name_bonus"]) if full_name and covered else 0.0
    tier = 0
    if covered:
        min_p = float(cfg["tier_min_entity_p"])
        for q in name_spans:
            if q.clause == main_clause and q.hyp.role == ENTITY and q.hyp.p >= min_p:
                tier = max(tier, 2 if q.merged else 1)

    penalty = float(cfg["unmatched_penalty"]) * sum(
        d.weight
        for i, d in enumerate(doc.spans)
        if i not in used and d.field == "name" and d.role in _PENALIZED_DOC_ROLES
    )
    # Category conflict: the query asks for a category the candidate does not have,
    # while the candidate names a category of its own ("무선 이어폰" vs "무선 충전기").
    doc_has_head = any(d.role == HEAD and d.field in ("name", "category") for d in doc.spans)
    if doc_has_head:
        penalty += float(cfg["head_mismatch_penalty"]) * sum(
            q.hyp.weight
            for q in r.spans
            if q.hyp.role == HEAD and matched.get(q.key, 0.0) < float(cfg["match_prefix"])
        )
    score = total + bonus - penalty
    detail = {"matches": parts, "bonus": bonus, "penalty": round(penalty, 4)}
    return _Scored(doc, r, r.p * score, detail, matched, _required(r, cfg, main_clause), tier)


def _diversify(results: list[RankResult], a: Analysis, cfg: Mapping[str, Any]) -> list[RankResult]:
    senses = [r.sense_id for r in results if r.sense_id]
    if len(set(senses)) < 2:
        return results
    # main sense: most probable sense hypothesis in the query
    best: tuple[float, str] | None = None
    for s in a.spans:
        for h in s.hypotheses:
            if h.sense_id and h.sense_id in senses and (best is None or h.p > best[0]):
                best = (h.p, h.sense_id)
    if best is None:
        return results
    main = best[1]
    after = int(cfg["diversify_after"])
    per_sense = int(cfg["diversify_per_sense"])
    head = [r for r in results if r.sense_id in (main, None)]
    others: dict[str, list[RankResult]] = {}
    for r in results:
        if r.sense_id not in (main, None):
            others.setdefault(str(r.sense_id), []).append(r)
    mixed = head[:after]
    for sid in sorted(others, key=lambda s: -others[s][0].score):
        mixed.extend(others[sid][:per_sense])
    chosen = {id(r) for r in mixed}
    mixed.extend(r for r in results if id(r) not in chosen)
    return mixed
