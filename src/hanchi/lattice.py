"""From units to segmentation hypotheses (interpretations). Language-neutral.

1. ``split_location_qualifier``: a single nominal unit spelled LOCATION + QUALIFIER
   ("역삼점", "대치점") is split back into two units.
2. ``base_spans``: lexicon phrases spanning several units are merged deterministically
   (longest match): "영업 중" → 영업중, "방 탈출" → 방탈출, "애플 파이" → 애플파이.
3. ``interpretations``: the base segmentation plus alternatives in which several base
   spans form one name — supported ones (entity dictionary full match) and, for recall,
   unsupported ones (adjacent words within a clause) that score low unless evidence
   appears later.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from hanchi.backend import Morph
from hanchi.resources import EntityEntry, Resources
from hanchi.units import FINAL_ENDING, NEGATIVE_PREDICATE, PROPER, REQUEST_FORM, Unit, UnitKind

PHRASE = "phrase"

# Lexicons whose multi-unit entries are merged into one span.
PHRASE_LEXICONS = ("head", "qualifier", "command", "constraint", "location", "meta")


@dataclass
class WorkSpan:
    """A span under analysis: one or more consecutive units."""

    units: tuple[Unit, ...]
    key: str
    start: int
    end: int
    kind: str
    traits: frozenset[str]
    parts: tuple[tuple[int, int], ...] = ()
    clause: int = 0
    base_range: tuple[int, int] = (0, 0)
    """Range of base spans covered (``[first, last + 1)``)."""
    entity_merge: list[EntityEntry] | None = None
    hyps: list[WorkHypothesis] = field(default_factory=list)

    @property
    def morphs(self) -> list[Morph]:
        return [m for u in self.units for m in u.morphs]

    @property
    def is_function(self) -> bool:
        return self.kind == UnitKind.FUNCTION.value

    @property
    def is_nominal_like(self) -> bool:
        return self.kind in (UnitKind.NOMINAL.value, UnitKind.FOREIGN.value, UnitKind.NUMBER.value)

    def has(self, trait: str) -> bool:
        return trait in self.traits


@dataclass
class WorkHypothesis:
    role: str
    sense_id: str | None = None
    type: str | None = None
    logit: float = 0.0
    contributions: list[tuple[str, float, str]] = field(default_factory=list)
    p: float = 0.0

    def add(self, name: str, value: float, evidence: str) -> None:
        self.logit += value
        self.contributions.append((name, value, evidence))


@dataclass
class Interpretation:
    spans: list[WorkSpan]
    score: float
    merges: list[dict[str, object]]
    p: float = 0.0


def _key(res: Resources, text: str) -> str:
    return text.replace(" ", "")


def split_location_qualifier(units: Sequence[Unit], text: str, res: Resources) -> list[Unit]:
    out: list[Unit] = []
    for u in units:
        key = _key(res, text[u.start : u.end])
        if u.kind is UnitKind.NOMINAL and len(u.morphs) == 1 and " " not in text[u.start : u.end]:
            for cut in range(len(key) - 1, 0, -1):
                if res.in_lexicon("location", key[:cut]) and res.in_lexicon("qualifier", key[cut:]):
                    m = u.morphs[0]
                    mid = u.start + cut
                    loc = Morph(key[:cut], m.tag, u.start, mid)
                    qual = Morph(key[cut:], m.tag, mid, u.end)
                    out.append(Unit(u.start, mid, (loc,), u.kind, u.word, u.traits, (), u.word_end))
                    out.append(
                        Unit(mid, u.end, (qual,), u.kind, u.word, frozenset(), (), u.word_end)
                    )
                    break
            else:
                out.append(u)
        else:
            out.append(u)
    return out


def _span(units: Sequence[Unit], text: str, res: Resources, rng: tuple[int, int]) -> WorkSpan:
    start, end = units[0].start, max(u.end for u in units)
    key = _key(res, text[start:end])
    if len(units) == 1:
        u = units[0]
        return WorkSpan(
            tuple(units), key, start, end, u.kind.value, u.traits, u.parts, base_range=rng
        )
    last = units[-1]
    traits = set(last.traits & {REQUEST_FORM, FINAL_ENDING, NEGATIVE_PREDICATE})
    if any(u.has(PROPER) for u in units):
        traits.add(PROPER)
    kinds = {u.kind for u in units if u.kind is not UnitKind.FUNCTION}
    kind = kinds.pop().value if len(kinds) == 1 else PHRASE
    parts = tuple((u.start, u.end) for u in units if u.kind is not UnitKind.FUNCTION)
    return WorkSpan(tuple(units), key, start, end, kind, frozenset(traits), parts, base_range=rng)


def base_spans(units: Sequence[Unit], text: str, res: Resources) -> list[WorkSpan]:
    max_units = int(res.setting("lattice", "max_phrase_units"))
    spans: list[WorkSpan] = []
    i = 0
    while i < len(units):
        best = i + 1
        for j in range(min(len(units), i + max_units), i + 1, -1):
            group = units[i:j]
            if any(u.kind is UnitKind.FUNCTION for u in group):
                continue
            key = _key(res, text[group[0].start : group[-1].end])
            if any(res.in_lexicon(n, key) for n in PHRASE_LEXICONS) or key in res.aliases:
                best = j
                break
        spans.append(_span(units[i:best], text, res, (len(spans), len(spans) + 1)))
        i = best
    return spans


def entity_matches(spans: Sequence[WorkSpan], text: str, res: Resources) -> list[tuple[int, int]]:
    """Base-span ranges (length ≥ 2) whose text exactly equals an entity name."""
    max_spans = int(res.setting("lattice", "max_entity_spans"))
    found = []
    for a in range(len(spans)):
        for b in range(a + 2, min(len(spans), a + max_spans) + 1):
            key = _key(res, text[spans[a].start : spans[b - 1].end])
            if key in res.entities:
                found.append((a, b))
    return found


def _words(spans: Sequence[WorkSpan], a: int, b: int) -> int:
    return spans[b - 1].units[-1].last_word - spans[a].units[0].word + 1


def _merged(spans: Sequence[WorkSpan], a: int, b: int, text: str, res: Resources) -> WorkSpan:
    units = [u for s in spans[a:b] for u in s.units]
    ws = _span(units, text, res, (a, b))
    if ws.kind != PHRASE and b - a > 1:
        ws.kind = PHRASE
    return ws


def interpretations(
    spans: list[WorkSpan],
    breaks: set[int],
    text: str,
    res: Resources,
) -> list[Interpretation]:
    """All segmentation hypotheses, scored and normalized (best first)."""
    cfg = res.setting("interpretation")
    merge_prior = float(cfg["merge_prior"])
    full_bonus = float(cfg["entity_full_match"])
    max_words = int(cfg["max_merge_words"])
    max_interp = int(cfg["max_interpretations"])
    max_combo = int(cfg["max_supported_merges"])

    supported = entity_matches(spans, text, res)
    supported_set = set(supported)

    def clause_ok(a: int, b: int) -> bool:
        return not any(a < k < b for k in breaks)

    unsupported = []
    for a in range(len(spans)):
        if spans[a].is_function or (
            a > 0 and spans[a - 1].units[-1].last_word == spans[a].units[0].word
        ):
            continue  # must start at a word boundary with content
        for b in range(a + 2, len(spans) + 1):
            if b < len(spans) and spans[b].units[0].word == spans[b - 1].units[-1].last_word:
                continue  # must end at a word boundary
            words = _words(spans, a, b)
            if words > max_words:
                break
            content = [s for s in spans[a:b] if not s.is_function]
            if words < 2 or len(content) < 2 or not clause_ok(a, b) or (a, b) in supported_set:
                continue
            if spans[b - 1].is_function:
                continue
            unsupported.append((a, b))

    candidates: list[tuple[list[tuple[int, int]], float]] = [([], 0.0)]
    for r in range(1, min(max_combo, len(supported)) + 1):
        for combo in itertools.combinations(supported, r):
            ranges = sorted(combo)
            if all(ranges[k][1] <= ranges[k + 1][0] for k in range(len(ranges) - 1)):
                candidates.append((ranges, len(ranges) * (merge_prior + full_bonus)))
    for rng in unsupported:
        candidates.append(([rng], merge_prior))

    out = []
    for ranges, score in candidates:
        built: list[WorkSpan] = []
        merges = []
        k = 0
        for a, b in ranges:
            built.extend(spans[k:a])
            ws = _merged(spans, a, b, text, res)
            if (a, b) in supported_set:
                ws.entity_merge = res.entities[ws.key]
            merges.append(
                {
                    "range": (a, b),
                    "text": text[ws.start : ws.end],
                    "supported": (a, b) in supported_set,
                }
            )
            built.append(ws)
            k = b
        built.extend(spans[k:])
        out.append(Interpretation([_copy(s) for s in built], score, merges))

    out.sort(key=lambda it: -it.score)
    base = next(it for it in out if not it.merges)
    kept = out[:max_interp]
    if base not in kept:
        kept[-1] = base
    z = sum(math.exp(it.score) for it in kept)
    for it in kept:
        it.p = math.exp(it.score) / z
    return kept


def _copy(s: WorkSpan) -> WorkSpan:
    return WorkSpan(
        s.units,
        s.key,
        s.start,
        s.end,
        s.kind,
        s.traits,
        s.parts,
        s.clause,
        s.base_range,
        s.entity_merge,
    )


def assign_clauses(
    spans: list[WorkSpan], base_breaks: set[int], correction_starts: set[int]
) -> None:
    """Set ``clause`` on spans of one interpretation. Breaks are base-span indices."""
    clause = 0
    for i, s in enumerate(spans):
        a = s.base_range[0]
        if i > 0 and (a in base_breaks or a in correction_starts):
            clause += 1
        s.clause = clause
