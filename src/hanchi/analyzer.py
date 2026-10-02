"""The public entry point: :class:`Analyzer`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from hanchi.attach import attach
from hanchi.config import load_yaml
from hanchi.lang.ko import KoreanPack
from hanchi.lattice import (
    Interpretation as WorkInterpretation,
)
from hanchi.lattice import (
    WorkHypothesis,
    WorkSpan,
    assign_clauses,
    base_spans,
    entity_matches,
    interpretations,
    refine_units,
)
from hanchi.normalize import NormalizedText
from hanchi.rank import Candidate, Ranking
from hanchi.rank import rank as rank_candidates
from hanchi.resolver import ResolveContext, Resolver, RuleResolver
from hanchi.resources import Resources, load_resources, resolve_plugin
from hanchi.schema import FUNC, META, Analysis, Hypothesis, Interpretation, Span
from hanchi.weights import RuleWeighter, Weighter

PluginSpec = str | Path


@dataclass(frozen=True)
class Expansion:
    term: str
    sense_id: str
    weight: float
    relation: str
    """synonym | hyponym (narrower than the query word) | hypernym (broader)."""
    source: str
    """The query span it expands."""


class Analyzer:
    """Analyze short queries into spans with role hypotheses and weights.

    Priority: ``overrides`` > ``plugins`` (in order, later wins) > package defaults.
    Each plugin is a directory or ``"preset:<name>"``; ``overrides`` are extra
    ``overrides.tsv``-format files applied last. See :meth:`from_config` to set all of
    this from one YAML file.
    """

    def __init__(
        self,
        plugins: Iterable[PluginSpec] = (),
        *,
        overrides: Iterable[PluginSpec] = (),
        lang: str = "ko",
        explain: bool = False,
        include_default: bool = True,
        resolver: Resolver | None = None,
        weighter: Weighter | None = None,
    ) -> None:
        if lang != "ko":
            raise ValueError(f"unsupported language: {lang!r} (available: 'ko')")
        specs = list(plugins)
        dirs = [resolve_plugin(p) for p in specs]
        self.pack = KoreanPack(dirs)
        self.explain = explain
        self.resources: Resources = load_resources(
            specs, self._key, include_default=include_default, override_files=overrides
        )
        self.resolver: Resolver = resolver or RuleResolver()
        self.weighter: Weighter = weighter or RuleWeighter()
        self._inject_user_words()

    @classmethod
    def from_config(cls, path: PluginSpec, **kwargs: Any) -> Analyzer:
        """Build an analyzer from a YAML file::

            plugins: [preset:local, ./my_domain]   # relative to this file
            overrides: [./hotfix/overrides.tsv]
            include_default: true
            explain: false

        Switching domains then needs no code change: point to another config file.
        ``extra_plugins=[...]`` are applied after the configured ones.
        """
        cfg_path = Path(path).expanduser()
        cfg = load_yaml(cfg_path)
        base = cfg_path.parent

        def resolve(p: str) -> str:
            if p.startswith("preset:") or Path(p).expanduser().is_absolute():
                return p
            return str((base / p).resolve())

        options: dict[str, Any] = {
            "plugins": [resolve(str(p)) for p in cfg.get("plugins", [])],
            "overrides": [resolve(str(p)) for p in cfg.get("overrides", [])],
            "include_default": bool(cfg.get("include_default", True)),
            "explain": bool(cfg.get("explain", False)),
            "lang": str(cfg.get("lang", "ko")),
        }
        extra = list(kwargs.pop("extra_plugins", ()))
        options.update(kwargs)
        plugins = list(options.pop("plugins")) + extra
        return cls(plugins, **options)

    # --- setup --------------------------------------------------------------------

    def _key(self, text: str) -> str:
        return self.pack.normalize(text).text.replace(" ", "")

    def _inject_user_words(self) -> None:
        names = [entries[0].name for entries in self.resources.entities.values()]
        self.pack.register_names(names)

    # --- analysis -----------------------------------------------------------------

    def analyze(
        self,
        text: str,
        context: Mapping[str, Any] | None = None,
        explain: bool | None = None,
    ) -> Analysis:
        explain = self.explain if explain is None else explain
        res = self.resources
        nt = self.pack.normalize(text)
        seg = self.pack.segment(nt)
        units = self.pack.units(seg, res)
        units = refine_units(units, nt.text, res)
        spans = base_spans(units, nt.text, res)

        breaks = self._breaks(spans, units)
        correction = {
            i for i, s in enumerate(spans) if res.lexicon_type("meta", s.key) == "correction"
        }
        ctx = self._context(context, spans, breaks | correction, nt)
        for a, b in entity_matches(spans, nt.text, res):
            name = nt.text[spans[a].start : spans[b - 1].end]
            for k in range(a, b):
                ctx.inside_entities.setdefault(k, name)

        interps = interpretations(spans, breaks, nt.text, res)
        for it in interps:
            assign_clauses(it.spans, breaks, correction)
            self.resolver.resolve(it.spans, res, ctx)
            self._apply_role_overrides(it.spans)

        built = [self._build(it, nt) for it in interps]
        top = built[0]
        tau = float(res.setting("threshold"))
        ambiguous = top.p < tau or any(s.resolved is None for s in top.spans if s.top.role != FUNC)
        clauses = _clause_ranges(top.spans)
        return Analysis(
            query=text,
            normalized=nt.text,
            spans=top.spans,
            ambiguous=ambiguous,
            clauses=clauses,
            signals=_signals(top.spans, nt),
            interpretations=built,
            explain=self._explain(interps[0], built) if explain else None,
        )

    def analyze_batch(
        self,
        texts: Iterable[str],
        workers: int = 1,
        context: Mapping[str, Any] | None = None,
        explain: bool | None = None,
    ) -> list[Analysis]:
        """Analyze many texts, in order, using up to ``workers`` threads."""
        items = list(texts)
        if workers <= 1 or len(items) <= 1:
            return [self.analyze(t, context=context, explain=explain) for t in items]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(
                pool.map(lambda t: self.analyze(t, context=context, explain=explain), items)
            )

    @staticmethod
    def to_dict(analysis: Analysis) -> dict[str, Any]:
        return analysis.to_dict()

    @staticmethod
    def to_json(analysis: Analysis, **kwargs: Any) -> str:
        return analysis.to_json(**kwargs)

    def _breaks(self, spans: list[WorkSpan], units: list[Any]) -> set[int]:
        unit_breaks = self.pack.clause_breaks(units)
        starts = {s.units[0].start: i for i, s in enumerate(spans)}
        return {starts[units[k].start] for k in unit_breaks if units[k].start in starts}

    def _context(
        self,
        context: Mapping[str, Any] | None,
        spans: list[WorkSpan],
        breaks: set[int],
        nt: NormalizedText,
    ) -> ResolveContext:
        ctx = ResolveContext()
        if not context:
            return ctx
        ctx.vertical = context.get("vertical")
        prev = context.get("prev_query")
        if prev:
            prev_analysis = self.analyze(str(prev))
            ctx.prev_types = {s.top.type for s in prev_analysis.spans if s.top.type}
            count = context.get("prev_result_count")
            if count is not None and int(count) == 0:
                end = min((spans[k].start for k in breaks if k > 0), default=len(nt.text))
                first_clause = nt.text[:end].replace(" ", "")
                ratio = _similarity(prev_analysis.normalized.replace(" ", ""), first_clause)
                if ratio >= float(self.resources.setting("context", "retry_similarity")):
                    ctx.retry_after_clause = 0
        return ctx

    def _apply_role_overrides(self, spans: list[WorkSpan]) -> None:
        """``role`` overrides replace whatever the resolver decided."""
        for s in spans:
            o = self.resources.override_for(s.key, "role")
            if o is None:
                continue
            role, _, sense_id = o.value.partition("/")
            sense = self.resources.senses.get(sense_id) if sense_id else None
            h = WorkHypothesis(role.upper(), sense_id or None, sense.type if sense else None)
            h.add("override", 0.0, f"override:{o.note or o.source}")
            h.p = 1.0
            s.hyps = [h]

    # --- ranking ------------------------------------------------------------------

    def rank(
        self,
        query: str | Analysis,
        candidates: Sequence[Candidate],
        *,
        k: int | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> Ranking:
        """Order candidate names for a query (see :mod:`hanchi.rank`)."""
        return rank_candidates(self, query, candidates, k=k, context=context)

    # --- expansion ----------------------------------------------------------------

    def expand(self, analysis: Analysis) -> list[Expansion]:
        """Synonym / hierarchy expansion for spans whose sense is resolved.

        Ambiguous spans are never expanded (a wrong sense would add wrong terms).
        """
        res = self.resources
        coef = res.setting("expand")
        out: list[Expansion] = []
        for s in analysis.spans:
            h = s.resolved
            if h is None or not h.sense_id or h.sense_id not in res.senses:
                continue
            relations = (
                ("synonym", res.synonyms.get(h.sense_id, set())),
                ("hyponym", res.hyponyms.get(h.sense_id, set())),
                ("hypernym", res.hypernyms.get(h.sense_id, set())),
            )
            for relation, targets in relations:
                for sid in sorted(targets):
                    target = res.senses.get(sid)
                    if target is None:
                        continue
                    weight = round(h.weight * float(coef[relation]), 6)
                    out.append(Expansion(target.canonical, sid, weight, relation, s.text))
        out.sort(key=lambda e: -e.weight)
        return out

    # --- output -------------------------------------------------------------------

    def _build(self, it: WorkInterpretation, nt: NormalizedText) -> Interpretation:
        res = self.resources
        tau = float(res.setting("threshold"))
        weights = self.weighter.weigh(it.spans, res)
        attached = attach(it.spans, res)
        out: list[Span] = []
        for i, ws in enumerate(it.spans):
            hyps = []
            for h, w in zip(ws.hyps, weights[i], strict=True):
                evidence = [e for name, _, e in h.contributions if name != "prior"]
                hyps.append(
                    Hypothesis(
                        role=h.role,
                        p=round(h.p, 6),
                        weight=round(w, 6),
                        evidence=evidence or [f"prior:{h.role}"],
                        sense_id=h.sense_id,
                        type=h.type,
                    )
                )
            hyps.sort(key=lambda h: -h.p)
            best = hyps[0]
            span = self._span(ws, nt, hyps, best if best.p >= tau else None)
            span.attach = attached.get(i)
            out.append(span)
        merges = []
        for m in it.merges:
            start, end = cast("tuple[int, int]", m["offsets"])
            s, e = nt.to_original(start, end)
            merges.append(
                {k: v for k, v in m.items() if k != "offsets"} | {"text": nt.original[s:e]}
            )
        return Interpretation(p=round(it.p, 6), score=it.score, spans=out, merges=merges)

    def _span(
        self, ws: WorkSpan, nt: NormalizedText, hyps: list[Hypothesis], resolved: Hypothesis | None
    ) -> Span:
        s, e = nt.to_original(ws.start, ws.end)
        morphs = [m.pair for m in ws.morphs]
        canonical = None
        top = hyps[0] if hyps else None
        if top is not None and top.sense_id:
            sense = self.resources.senses.get(top.sense_id)
            canonical = sense.canonical if sense else top.sense_id
        parts = None
        if len(ws.parts) > 1:
            parts = [self._part(nt, a, b) for a, b in ws.parts]
        return Span(
            text=nt.original[s:e],
            norm=nt.text[ws.start : ws.end],
            canonical=canonical,
            start=s,
            end=e,
            morphs=morphs,
            pos=self.pack.kind_label(ws.kind),
            pos_detail=self.pack.pos_detail(morphs),
            hypotheses=hyps,
            resolved=resolved,
            clause_id=ws.clause,
            parts=parts,
        )

    def _part(self, nt: NormalizedText, a: int, b: int) -> Span:
        s, e = nt.to_original(a, b)
        return Span(
            text=nt.original[s:e],
            norm=nt.text[a:b],
            canonical=None,
            start=s,
            end=e,
            morphs=[],
            pos="",
            pos_detail="",
            hypotheses=[],
            resolved=None,
        )

    def _explain(self, top: WorkInterpretation, built: list[Interpretation]) -> dict[str, Any]:
        return {
            "interpretations": [
                {"p": it.p, "score": it.score, "merges": it.merges} for it in built
            ],
            "spans": [
                {
                    "text": nt_span.norm,
                    "hypotheses": [
                        {
                            "role": h.role,
                            "sense_id": h.sense_id,
                            "logit": round(h.logit, 4),
                            "p": round(h.p, 6),
                            "contributions": [
                                {"feature": n, "value": v, "evidence": ev}
                                for n, v, ev in h.contributions
                            ],
                        }
                        for h in sorted(ws.hyps, key=lambda h: -h.p)
                    ],
                }
                for ws, nt_span in zip(top.spans, built[0].spans, strict=True)
            ],
        }


def _clause_ranges(spans: list[Span]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for i, s in enumerate(spans):
        if not ranges or s.clause_id != spans[ranges[-1][0]].clause_id:
            ranges.append((i, i + 1))
        else:
            ranges[-1] = (ranges[-1][0], i + 1)
    return ranges


def _signals(spans: list[Span], nt: NormalizedText) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    run: list[Span] = []

    def flush() -> None:
        if not run:
            return
        correction = any(
            "lexicon:meta(correction)" in (s.resolved.evidence if s.resolved else []) for s in run
        )
        signals.append(
            {
                "type": "correction" if correction else "dissatisfaction",
                "span": nt.original[run[0].start : run[-1].end],
                "clause_id": run[0].clause_id,
            }
        )
        run.clear()

    for s in spans:
        if s.resolved is not None and s.resolved.role == META:
            if run and run[-1].clause_id != s.clause_id:
                flush()
            run.append(s)
        elif s.top.role != FUNC:
            flush()
    flush()
    return signals


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return 1.0 - prev[-1] / max(len(a), len(b))
