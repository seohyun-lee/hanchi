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
from hanchi.units import (
    FINAL_ENDING,
    LOCATION_GUESS,
    MIXED_SCRIPT,
    NEGATIVE_PREDICATE,
    PROPER,
    QUANTITY,
    REQUEST_FORM,
    Unit,
    UnitKind,
)

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


def _slice(u: Unit, a: int, b: int, text: str, traits: frozenset[str]) -> Unit:
    """The part of unit ``u`` covering normalized range ``[a, b)``."""
    morphs = []
    for m in u.morphs:
        s, e = max(m.start, a), min(m.end, b)
        if s < e:
            morphs.append(m if (s, e) == (m.start, m.end) else Morph(text[s:e], m.tag, s, e))
    parts = tuple((max(s, a), min(e, b)) for s, e in u.parts if min(e, b) > max(s, a))
    piece = text[a:b]
    if len(parts) > 1 and _mixed_script(piece):
        traits = traits | {MIXED_SCRIPT}
    else:
        parts = ()
    word = u.word + text[u.start : a].count(" ")
    return Unit(a, b, tuple(morphs), u.kind, word, traits, parts, word + piece.count(" "))


def _mixed_script(piece: str) -> bool:
    has_ascii = any(ch.isascii() and ch.isalnum() for ch in piece)
    has_other = any(not ch.isascii() and ch.isalpha() for ch in piece)
    return has_ascii and has_other


def _offsets(u: Unit, text: str) -> list[int]:
    """Normalized offset of each non-space character of the unit."""
    return [i for i in range(u.start, u.end) if not text[i].isspace()]


def _cut(u: Unit, text: str, cuts: Sequence[int], traits: Sequence[frozenset[str]]) -> list[Unit]:
    """Split ``u`` at key positions ``cuts`` (indices into its space-free key)."""
    pos = _offsets(u, text)
    bounds = [u.start] + [pos[c] for c in cuts] + [u.end]
    return [_slice(u, bounds[k], bounds[k + 1], text, traits[k]) for k in range(len(bounds) - 1)]


_SPLIT_DROP = frozenset({MIXED_SCRIPT, QUANTITY, REQUEST_FORM, FINAL_ENDING, NEGATIVE_PREDICATE})


def refine_units(units: Sequence[Unit], text: str, res: Resources) -> list[Unit]:
    """Dictionary-driven corrections to the language pack's units (language-neutral).

    1. ``split`` overrides break a unit into the given parts.
    2. A unit that starts with a dictionary name is split after it ("gs25역삼점",
       "스타벅스강남r점"), unless a ``keep`` override protects it.
    3. LOCATION + QUALIFIER spelled as one unit is split ("역삼점", "강남r점").
    4. An unknown "X + QUALIFIER" right after a name becomes a guessed LOCATION X
       ("GLE어학원 목동점").
    """
    min_loc = int(res.setting("lattice", "min_location_guess_len"))
    out: list[Unit] = []
    for u in units:
        key = _key(res, text[u.start : u.end])
        keep = res.override_for(key, "keep") is not None
        split = res.override_for(key, "split")
        if split is not None:
            parts = split.value.split()
            if "".join(res.key(p) for p in parts) == key and len(parts) > 1:
                cuts, acc = [], 0
                for p in parts[:-1]:
                    acc += len(res.key(p))
                    cuts.append(acc)
                base = u.traits - _SPLIT_DROP
                out.extend(_cut(u, text, cuts, [base] * len(parts)))
                continue
        if keep or u.kind is not UnitKind.NOMINAL:
            out.append(u)
            continue
        pieces = [u]
        # 2. leading dictionary name
        if len(u.morphs) > 1 and key not in res.entities:
            bounds = {m.end for m in u.morphs[:-1]} | {e for _, e in u.parts[:-1]}
            pos = _offsets(u, text)
            for c in range(len(key) - 1, 0, -1):
                if key[:c] in res.entities and pos[c - 1] + 1 in bounds:
                    base = u.traits - _SPLIT_DROP
                    pieces = _cut(u, text, [c], [base, base])
                    break
        refined: list[Unit] = []
        for piece in pieces:
            refined.extend(_split_location_qualifier(piece, text, res))
        out.extend(refined)

    # 4. guessed locations: "<name> X점"
    result: list[Unit] = []
    for i, u in enumerate(out):
        if u.kind is UnitKind.NOMINAL and _is_namey(out, i - 1, text, res) and _starts_word(out, i):
            key = _key(res, text[u.start : u.end])
            nxt = out[i + 1] if i + 1 < len(out) else None
            if (
                nxt is not None
                and nxt.word == u.last_word
                and not res.in_lexicon("location", key)
                and res.in_lexicon("qualifier", _key(res, text[nxt.start : nxt.end]))
                and len(key) >= min_loc
            ):
                result.append(_with_trait(u, LOCATION_GUESS))
                continue
            for c in range(len(key) - 1, min_loc - 1, -1):
                if res.in_lexicon("qualifier", key[c:]) and not res.in_lexicon("location", key[:c]):
                    base = u.traits - _SPLIT_DROP
                    result.extend(_cut(u, text, [c], [base | {LOCATION_GUESS}, base]))
                    break
            else:
                result.append(u)
            continue
        result.append(u)
    return result


def _with_trait(u: Unit, trait: str) -> Unit:
    return Unit(u.start, u.end, u.morphs, u.kind, u.word, u.traits | {trait}, u.parts, u.word_end)


def _starts_word(units: Sequence[Unit], i: int) -> bool:
    return i == 0 or units[i - 1].last_word != units[i].word


def _is_namey(units: Sequence[Unit], j: int, text: str, res: Resources) -> bool:
    """Unit ``j`` ends the previous word and looks like a name."""
    if j < 0 or units[j].last_word == units[j + 1].word:
        return False
    u = units[j]
    key = _key(res, text[u.start : u.end])
    if res.in_lexicon("location", key):
        return False  # "강남 스포츠센터": a place, not a name, comes before
    return u.has(MIXED_SCRIPT) or u.has(PROPER) or key in res.entities


def _split_location_qualifier(u: Unit, text: str, res: Resources) -> list[Unit]:
    key = _key(res, text[u.start : u.end])
    if " " in text[u.start : u.end] or res.override_for(key, "keep") is not None:
        return [u]
    base = u.traits - _SPLIT_DROP
    for c in range(len(key) - 1, 0, -1):
        if res.in_lexicon("location", key[:c]) and res.in_lexicon("qualifier", key[c:]):
            return _cut(u, text, [c], [base, base - {PROPER}])
    # NAME + LOCATION + QUALIFIER in one word ("gle어학원대치점"): cut at morpheme
    # boundaries only, so the name keeps its own analysis.
    pos = _offsets(u, text)
    bounds = {m.start for m in u.morphs[1:]}
    for c1 in range(1, len(key) - 1):
        if pos[c1] not in bounds:
            continue
        for c2 in range(len(key) - 1, c1, -1):
            if res.in_lexicon("location", key[c1:c2]) and res.in_lexicon("qualifier", key[c2:]):
                return _cut(u, text, [c1, c2], [u.traits - {QUANTITY}, base, base - {PROPER}])
    return [u]


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
            if (
                any(res.in_lexicon(n, key) for n in PHRASE_LEXICONS)
                or key in res.aliases
                or res.override_for(key, "keep") is not None
            ):
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

    mixed_bonus = float(cfg["mixed_script_merge"])
    mixed = set(_spaced_mixed(spans, text, res))

    unsupported += [r for r in sorted(mixed) if r not in unsupported and r not in supported_set]

    candidates: list[tuple[list[tuple[int, int]], float]] = [([], 0.0)]
    for r in range(1, min(max_combo, len(supported)) + 1):
        for combo in itertools.combinations(supported, r):
            ranges = sorted(combo)
            if all(ranges[k][1] <= ranges[k + 1][0] for k in range(len(ranges) - 1)):
                candidates.append((ranges, len(ranges) * (merge_prior + full_bonus)))
    for rng in unsupported:
        candidates.append(([rng], merge_prior + (mixed_bonus if rng in mixed else 0.0)))

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
            if (a, b) in mixed:
                ws.traits = ws.traits | {MIXED_SCRIPT}
                ws.parts = tuple((s.start, s.end) for s in spans[a:b])
            merges.append(
                {
                    "range": (a, b),
                    "offsets": (ws.start, ws.end),
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


def _spaced_mixed(spans: Sequence[WorkSpan], text: str, res: Resources) -> list[tuple[int, int]]:
    """ "123 젤라또", "GLE 어학원": a lone number/letters word + a word starting with a
    category word may be one name written with a space (13.2-7)."""
    out = []
    for a in range(len(spans) - 1):
        first, nxt = spans[a], spans[a + 1]
        alone = (a == 0 or spans[a - 1].units[-1].last_word != first.units[0].word) and (
            nxt.units[0].word != first.units[-1].last_word
        )
        if (
            alone
            and first.kind in (UnitKind.FOREIGN.value, UnitKind.NUMBER.value)
            and not first.has(QUANTITY)
            and nxt.kind == UnitKind.NOMINAL.value
            and res.in_lexicon("head", nxt.key)
            and not res.in_lexicon("unit", nxt.key)
        ):
            b = a + 2
            while b < len(spans) and spans[b].units[0].word == spans[b - 1].units[-1].last_word:
                b += 1
            out.append((a, b) if not spans[b - 1].is_function else (a, a + 2))
    return out


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
