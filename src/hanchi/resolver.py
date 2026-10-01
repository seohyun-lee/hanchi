"""Role hypotheses and rule-based resolution (v1). Language-neutral.

For every span of an interpretation: generate candidate (role, sense) hypotheses,
score each with ``prior(role) + Σ feature weights`` and normalize per span with a
softmax. Every weight comes from ``rules.yaml``; the code only decides *whether* a
feature fires. Feature names double as evidence keys in the output.

The :class:`Resolver` protocol lets a learned resolver replace this one.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from hanchi.lattice import WorkHypothesis, WorkSpan
from hanchi.resources import Resources
from hanchi.schema import (
    COMMAND,
    CONSTRAINT,
    ENTITY,
    FUNC,
    HEAD,
    LOCATION,
    META,
    MODIFIER,
    QUALIFIER,
)
from hanchi.units import (
    INTERROGATIVE,
    LOCATION_GUESS,
    MIXED_SCRIPT,
    NEGATIVE_PREDICATE,
    PROPER,
    QUANTITY,
    REQUEST_FORM,
)

_DEFAULT_ROLES = (ENTITY, MODIFIER, HEAD, LOCATION)
_ROLE_LEXICONS = ("head", "qualifier", "command", "constraint", "location", "meta")


@dataclass
class ResolveContext:
    """Information from outside the query (all optional)."""

    vertical: str | None = None
    prev_types: set[str] = field(default_factory=set)
    retry_after_clause: int | None = None
    """When set, META hypotheses in clauses after this one get the retry feature."""
    inside_entities: dict[int, str] = field(default_factory=dict)
    """Base-span index → name of a multi-span entity it is strictly inside of."""


class Resolver(Protocol):
    def resolve(self, spans: list[WorkSpan], res: Resources, ctx: ResolveContext) -> None:
        """Fill ``span.hyps`` (with ``p``) for every span."""
        ...


class RuleResolver:
    def resolve(self, spans: list[WorkSpan], res: Resources, ctx: ResolveContext) -> None:
        view = _View(spans, res)
        for i, span in enumerate(spans):
            span.hyps = _candidates(span, res)
            for h in span.hyps:
                h.add(
                    "prior", float(res.rules.get("priors", {}).get(h.role, 0.0)), f"prior:{h.role}"
                )
                _score(i, span, h, view, res, ctx)
            _softmax(span.hyps)


# --- structure helpers ----------------------------------------------------------


class _View:
    """Neighbourhood queries over the spans of one interpretation."""

    def __init__(self, spans: list[WorkSpan], res: Resources) -> None:
        self.spans = spans
        self.res = res
        self.lex = [set(res.lexicons_of(s.key)) & set(_ROLE_LEXICONS) for s in spans]

    def content_neighbor(self, i: int, step: int) -> int | None:
        j = i + step
        while 0 <= j < len(self.spans):
            if self.spans[j].clause != self.spans[i].clause:
                return None
            if not self.spans[j].is_function:
                return j
            j += step
        return None

    def np_next(self, i: int) -> int | None:
        j = i + 1
        s = self.spans
        if (
            j < len(s)
            and s[j].clause == s[i].clause
            and s[i].is_nominal_like
            and s[j].is_nominal_like
            and not s[i].has(QUANTITY)
            and not s[j].has(QUANTITY)
        ):
            return j
        return None

    def is_np_final(self, i: int) -> bool:
        return self.spans[i].is_nominal_like and self.np_next(i) is None

    def is_last_content_in_clause(self, i: int) -> bool:
        return self.content_neighbor(i, +1) is None

    def word_final(self, i: int) -> bool:
        s = self.spans
        return i + 1 >= len(s) or s[i + 1].units[0].word != s[i].units[-1].last_word

    def whole_words(self, i: int) -> bool:
        """The span starts and ends at word boundaries."""
        return self.same_word_prev(i) is None and self.word_final(i)

    def same_word_prev(self, i: int) -> int | None:
        s = self.spans
        if i > 0 and s[i - 1].units[-1].last_word == s[i].units[0].word:
            return i - 1
        return None

    def has_entity_full(self, i: int) -> bool:
        s = self.spans[i]
        return s.entity_merge is not None or s.key in self.res.entities

    def is_request(self, i: int) -> bool:
        return self.spans[i].has(REQUEST_FORM) or "command" in self.lex[i]

    def types_of(self, i: int) -> set[str]:
        s = self.spans[i]
        res = self.res
        types = {sense.type for sense, _ in res.senses_of(s.key) if sense.type}
        types |= {e.type for e in res.entities.get(s.key, []) if e.type}
        ctype = res.lexicon_type("constraint", s.key)
        if ctype:
            types.add(ctype)
        if s.has(QUANTITY):
            types.add("quantity")
        return types


# --- candidates -------------------------------------------------------------------


def _candidates(span: WorkSpan, res: Resources) -> list[WorkHypothesis]:
    if span.is_function:
        return [WorkHypothesis(FUNC)]
    roles: set[str] = set(res.rules.get("candidates", {}).get(span.kind, [ENTITY]))
    lexicon_roles = res.rules.get("lexicon_roles", {})
    for name in res.lexicons_of(span.key):
        if name in lexicon_roles:
            roles.add(lexicon_roles[name])
    trait_roles = res.rules.get("trait_roles", {})
    for trait in span.traits:
        if trait in trait_roles:
            roles.add(trait_roles[trait])

    hyps: list[WorkHypothesis] = []
    senses = res.senses_of(span.key)
    if senses:
        roles -= set(_DEFAULT_ROLES)
        for sense, _ in senses:
            hyps.append(WorkHypothesis(sense.role, sense.sense_id, sense.type))

    entries = span.entity_merge or res.entities.get(span.key, [])
    seen: set[tuple[str, str | None]] = set()
    for e in entries:
        if (e.canonical, e.type) not in seen and not any(h.sense_id == e.canonical for h in hyps):
            seen.add((e.canonical, e.type))
            hyps.append(WorkHypothesis(ENTITY, e.canonical, e.type))
    if entries:
        roles.discard(ENTITY)

    hyps.extend(WorkHypothesis(r) for r in sorted(roles))
    return hyps


# --- features ---------------------------------------------------------------------


def _score(
    i: int, span: WorkSpan, h: WorkHypothesis, v: _View, res: Resources, ctx: ResolveContext
) -> None:
    def fire(name: str, evidence: str) -> None:
        h.add(name, res.feature(h.role, name), evidence)

    lex = v.lex[i]
    prev = v.content_neighbor(i, -1)
    nxt = v.content_neighbor(i, +1)
    role = h.role

    if role == ENTITY:
        _entity_features(i, span, h, v, res, fire, prev, nxt)
    elif role == COMMAND:
        if v.is_request(i):
            if v.is_last_content_in_clause(i):
                fire("request_clause_final", "rule:sentence_final_request")
            else:
                fire("request_not_final", "rule:request_form(not_final)")
        if prev is not None and v.spans[prev].is_nominal_like:
            fire("after_nominal", "context:after_nominal")
        inside = ctx.inside_entities.get(span.base_range[0])
        if inside is not None and span.base_range[1] - span.base_range[0] == 1:
            fire("in_entity_full", f"entity_dict(inside:{inside})")
    elif role == QUALIFIER:
        if "qualifier" in lex and v.word_final(i):
            p = v.same_word_prev(i)
            if p is not None and (
                "location" in v.lex[p] or v.spans[p].has(LOCATION_GUESS) or v.has_entity_full(p)
            ):
                fire("qualifier_after_location", "rule:location+qualifier")
    elif role == HEAD:
        if "head" in lex:
            if v.is_np_final(i):
                fire("head_lexicon_np_final", "lexicon:head(np_final)")
            else:
                fire("head_lexicon", "lexicon:head")
        elif not lex and v.is_np_final(i) and h.sense_id is None:
            fire("np_final_noun", "position:np_final")
    elif role == LOCATION:
        if "location" in lex:
            fire("location_lexicon", "lexicon:location")
        elif span.has(LOCATION_GUESS):
            fire("location_guess", "rule:name+X+qualifier")
    elif role == CONSTRAINT:
        if "constraint" in lex:
            ctype = res.lexicon_type("constraint", span.key) or "constraint"
            fire("constraint_lexicon", f"lexicon:constraint({ctype})")
        if span.has(QUANTITY):
            fire("quantity", "rule:number+unit")
    elif role == MODIFIER:
        n = v.np_next(i)
        if n is not None and not lex and not span.has(PROPER) and "head" in v.lex[n]:
            fire("before_head", "position:before_head")
    elif role == FUNC:
        fire("function_form", "pos:function")
    elif role == META:
        _meta_features(i, span, v, res, fire, prev, ctx)

    if h.type or h.sense_id:
        _sense_features(i, span, h, v, res, ctx)


Fire = Callable[[str, str], None]


def _entity_features(
    i: int,
    span: WorkSpan,
    h: WorkHypothesis,
    v: _View,
    res: Resources,
    fire: Fire,
    prev: int | None,
    nxt: int | None,
) -> None:
    key = span.key
    min_prefix = int(res.setting("lattice", "min_prefix_len"))
    full = span.entity_merge or res.entities.get(key, [])
    if full:
        fire("entity_full", f"entity_dict:{full[0].source}(full)")
        if (prev is not None and "location" in v.lex[prev]) or (
            nxt is not None and "location" in v.lex[nxt]
        ):
            fire("adjacent_location", "context:adjacent_location")
        if nxt is not None and v.is_request(nxt):
            fire("before_command", "context:before_command")
    else:
        longer = res.entity_keys_with_prefix(key) if len(key) >= min_prefix else set()
        if longer:
            name = min(longer, key=len)
            fire("entity_prefix", f"entity_dict:{res.entities[name][0].source}(prefix:{name})")
        elif any(True for _ in res.entity_keys_containing(key)):
            name = next(iter(res.entity_keys_containing(key)))
            fire("entity_common_part", f"entity_dict(common_part:{name})")
    if span.has(PROPER) and h.sense_id not in res.senses:
        # A word sense defined in senses.tsv already says what the word is.
        fire("proper_noun", "pos:proper")
    if span.has(MIXED_SCRIPT):
        fire("mixed_script", "rule:mixed_script_eojeol")
        if span.parts:
            s, e = span.parts[-1]
            if res.in_lexicon("head", key[s - span.start : e - span.start]):
                fire("mixed_ends_with_head", "rule:mixed_ends_with_head")
    if nxt is not None and "location" in v.lex[nxt] and v.whole_words(i):
        q = nxt + 1
        if q < len(v.spans) and "qualifier" in v.lex[q] and v.same_word_prev(q) == nxt:
            fire("next_location_qualifier", "context:location+qualifier_follows")


def _meta_features(
    i: int,
    span: WorkSpan,
    v: _View,
    res: Resources,
    fire: Fire,
    prev: int | None,
    ctx: ResolveContext,
) -> None:
    if span.has(INTERROGATIVE):
        fire("interrogative", "rule:interrogative_adverb")
    if prev is not None and v.spans[prev].has(INTERROGATIVE):
        fire("after_interrogative", "context:after_interrogative")
    if span.has(NEGATIVE_PREDICATE):
        fire("negative_predicate", "rule:negative_predicate")
    mtype = res.lexicon_type("meta", span.key) if "meta" in v.lex[i] else None
    if mtype == "correction":
        fire("correction_marker", "lexicon:meta(correction)")
    elif "meta" in v.lex[i]:
        fire("meta_lexicon", f"lexicon:meta({mtype or 'meta'})")
    if span.clause > 0:
        last_prev_clause = max(
            (k for k, s in enumerate(v.spans) if s.clause == span.clause - 1 and not s.is_function),
            default=None,
        )
        if last_prev_clause is not None and v.is_request(last_prev_clause):
            fire("after_complete_request", "context:after_complete_request")
    if ctx.retry_after_clause is not None and span.clause > ctx.retry_after_clause:
        fire("context_retry", "context:prev_query_no_result")


def _sense_features(
    i: int, span: WorkSpan, h: WorkHypothesis, v: _View, res: Resources, ctx: ResolveContext
) -> None:
    def add(name: str, scale: float, evidence: str) -> None:
        h.add(name, res.feature("SENSE", name) * scale, evidence)

    if h.type:
        for j, other in enumerate(v.spans):
            if j == i or other.clause != span.clause or other.is_function:
                continue
            scores = [(res.compat_score(h.type, t), t) for t in v.types_of(j)]
            scores = [s for s in scores if s[0] != 0.0]
            if scores:
                score, t = max(scores, key=lambda s: abs(s[0]))
                add("compat", score, f"compat:{h.type}+{t}")
        if h.type in ctx.prev_types:
            add("context_same_type", 1.0, f"context:prev_query_type({h.type})")
        prev_scores = [(res.compat_score(h.type, t), t) for t in ctx.prev_types if t != h.type]
        prev_scores = [s for s in prev_scores if s[0] != 0.0]
        if prev_scores:
            score, t = max(prev_scores, key=lambda s: abs(s[0]))
            add("context_compat", score, f"context:prev_query_compat({h.type}+{t})")
    if h.sense_id:
        prior = _sense_prior(span, h.sense_id, res, ctx)
        if prior is not None:
            add("sense_prior", math.log(prior), f"sense_prior:{prior:g}")
        if res.has_vertical_prior(span.key, h.sense_id, ctx.vertical):
            add("vertical_match", 1.0, f"context:vertical({ctx.vertical})")
        alias = res.aliases.get(span.key, {}).get(h.sense_id)
        if alias is not None and alias > 0:
            add("alias_score", math.log(alias), f"alias:{alias:g}")


def _sense_prior(
    span: WorkSpan, sense_id: str, res: Resources, ctx: ResolveContext
) -> float | None:
    """Prior of ``sense_id`` for this spelling; senses without a row share what is left."""
    given = {
        h.sense_id: res.prior_of(span.key, h.sense_id, ctx.vertical)
        for h in span.hyps
        if h.sense_id
    }
    known = {k: v for k, v in given.items() if v is not None}
    if not known:
        return None
    if sense_id in known:
        return known[sense_id]
    missing = len(given) - len(known)
    floor = float(res.setting("senses", "prior_floor"))
    return max(floor, (1.0 - sum(known.values())) / missing)


def _softmax(hyps: Sequence[WorkHypothesis]) -> None:
    top = max(h.logit for h in hyps)
    exps = [math.exp(h.logit - top) for h in hyps]
    z = sum(exps)
    for h, e in zip(hyps, exps, strict=True):
        h.p = e / z
