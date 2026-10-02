"""Korean unit builder: Kiwi morphemes → :class:`~hanchi.units.Unit`.

Grouping rules (per whitespace word):

- particles (J*), punctuation (S* except SW→function too) → one function unit each
- copula + endings after a noun ("영업중**인**") → function unit
- predicate stem + endings/auxiliaries ("찾아줘", "가까운") → one predicate unit;
  a noun directly before XSV/XSA joins it ("검색해줘")
- nouns, foreign words, numbers → one unit each; XSN/Z_* attach to the previous unit,
  XPN to the next
- number + unit noun in the same word → quantity unit ("2개", "1박스")
- letters + digits in the same word → one foreign unit ("gs25", "b2b")
- letters/digits glued to a noun in the same word → one nominal unit with
  ``mixed_script`` and parts ("연세365의원" → 연세|365|의원)
- negation adverb + following predicate → one negative predicate unit ("안 나와")
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from hanchi.backend import Morph, PosClass
from hanchi.config import layered
from hanchi.lang.ko.tags import base_tag, tag_info
from hanchi.resources import Resources
from hanchi.segment import Segmentation
from hanchi.units import (
    ADNOMINAL,
    FINAL_ENDING,
    INTERROGATIVE,
    MIXED_SCRIPT,
    NEGATIVE_PREDICATE,
    PROPER,
    QUANTITY,
    QUESTION_FORM,
    REQUEST_FORM,
    Unit,
    UnitKind,
)

_DATA = "hanchi.lang.ko.data"
P = PosClass

_PREDICATE_STEMS = {P.VERB, P.ADJ, P.AUX}
_PREDICATE_TAIL = {P.ENDING, P.AUX, P.VERB, P.ADJ, P.COPULA}
_NOMINAL_CLASSES = {P.NOUN, P.PROPN, P.PRON, P.NUM, P.ROOT}


def load_patterns(plugin_dirs: Iterable[str | Path] = ()) -> dict[str, Any]:
    return layered(_DATA, "patterns.yaml", plugin_dirs)


def _cls(m: Morph) -> PosClass:
    return tag_info(m.tag).pos_class


def _kind_of(m: Morph) -> UnitKind:
    c = _cls(m)
    if c in _NOMINAL_CLASSES:
        return UnitKind.NOMINAL
    return {
        P.FOREIGN: UnitKind.FOREIGN,
        P.NUMBER: UnitKind.NUMBER,
        P.ADV: UnitKind.ADVERB,
        P.CONJ: UnitKind.ADVERB,
        P.DET: UnitKind.DETERMINER,
        P.INTJ: UnitKind.INTERJECTION,
        P.SPECIAL: UnitKind.SPECIAL,
        P.UNKNOWN: UnitKind.OTHER,
    }.get(c, UnitKind.FUNCTION)


class _Draft:
    __slots__ = ("kind", "morphs", "parts", "traits")

    def __init__(self, kind: UnitKind, morphs: list[Morph]) -> None:
        self.kind = kind
        self.morphs = morphs
        self.traits: set[str] = set()
        self.parts: list[tuple[int, int]] = []

    @property
    def start(self) -> int:
        return min(m.start for m in self.morphs)

    @property
    def end(self) -> int:
        return max(m.end for m in self.morphs)


def _group_word(morphs: Sequence[Morph]) -> list[_Draft]:
    drafts: list[_Draft] = []
    i = 0
    n = len(morphs)
    while i < n:
        m = morphs[i]
        c = _cls(m)
        tag = base_tag(m.tag)
        if c in _PREDICATE_STEMS or tag in ("VCN", "XSV", "XSA"):
            group = [m]
            # A noun right before a verb/adjective-forming suffix belongs to the predicate.
            if tag in ("XSV", "XSA") and drafts and drafts[-1].kind is UnitKind.NOMINAL:
                group = drafts.pop().morphs + group
            j = i + 1
            while j < n and (
                _cls(morphs[j]) in _PREDICATE_TAIL or base_tag(morphs[j].tag) in ("XSV", "XSA")
            ):
                group.append(morphs[j])
                j += 1
            drafts.append(_Draft(UnitKind.PREDICATE, group))
            i = j
            continue
        if c is P.COPULA:  # VCP after a noun: grammatical, with its endings
            group = [m]
            j = i + 1
            while j < n and _cls(morphs[j]) is P.ENDING:
                group.append(morphs[j])
                j += 1
            drafts.append(_Draft(UnitKind.FUNCTION, group))
            i = j
            continue
        if c is P.AFFIX:
            if tag == "XPN" and i + 1 < n:
                nxt = morphs[i + 1]
                drafts.append(_Draft(_kind_of(nxt), [m, nxt]))
                i += 2
                continue
            if drafts and drafts[-1].kind is not UnitKind.FUNCTION:
                drafts[-1].morphs.append(m)
                i += 1
                continue
        if c is P.SYMBOL:
            drafts.append(_Draft(UnitKind.FUNCTION, [m]))
        else:
            drafts.append(_Draft(_kind_of(m), [m]))
        i += 1
    return drafts


def _text(norm: str, d: _Draft) -> str:
    return norm[d.start : d.end].replace(" ", "")


def _merge_word(drafts: list[_Draft], norm: str, res: Resources) -> list[_Draft]:
    # number + unit noun -> quantity
    out: list[_Draft] = []
    for d in drafts:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.kind is UnitKind.NUMBER
            and QUANTITY not in prev.traits
            and d.kind in (UnitKind.NOMINAL, UnitKind.FOREIGN)
            and res.in_lexicon("unit", res.key(_text(norm, d)))
        ):
            prev.morphs += d.morphs
            prev.traits.add(QUANTITY)
            continue
        out.append(d)

    # letters + digits -> one foreign token
    merged: list[_Draft] = []
    for d in out:
        prev = merged[-1] if merged else None
        alnum = (UnitKind.FOREIGN, UnitKind.NUMBER)
        if (
            prev is not None
            and prev.kind in alnum
            and d.kind in alnum
            and QUANTITY not in prev.traits | d.traits
            and UnitKind.FOREIGN in (prev.kind, d.kind)
        ):
            prev.morphs += d.morphs
            prev.kind = UnitKind.FOREIGN
            continue
        merged.append(d)

    # letters/digits glued to nouns -> mixed-script nominal with parts
    result: list[_Draft] = []
    i = 0
    while i < len(merged):
        j = i
        while (
            j < len(merged)
            and merged[j].kind in (UnitKind.NOMINAL, UnitKind.FOREIGN, UnitKind.NUMBER)
            and QUANTITY not in merged[j].traits
        ):
            j += 1
        run = merged[i:j]
        kinds = {d.kind for d in run}
        if (
            len(run) >= 2
            and UnitKind.NOMINAL in kinds
            and kinds & {UnitKind.FOREIGN, UnitKind.NUMBER}
        ):
            mixed = _Draft(UnitKind.NOMINAL, [m for d in run for m in d.morphs])
            mixed.traits.add(MIXED_SCRIPT)
            mixed.parts = [(d.start, d.end) for d in run]
            result.append(mixed)
            i = j
        elif run:
            result.extend(run)
            i = j
        else:
            result.append(merged[i])
            i += 1
    return result


def _traits(d: _Draft, pat: Mapping[str, Any]) -> None:
    if any(base_tag(m.tag) == "NNP" for m in d.morphs):
        d.traits.add(PROPER)
    if d.kind is UnitKind.PREDICATE:
        tags = [base_tag(m.tag) for m in d.morphs]
        if tags and tags[-1] == "EF":
            d.traits.add(FINAL_ENDING)
        aux = set(pat.get("request_auxiliaries", []))
        aux_endings = set(pat.get("request_aux_endings", []))
        endings = set(pat.get("request_endings", []))
        last = d.morphs[-1]
        last_is_ending = tag_info(last.tag).pos_class is P.ENDING
        has_aux = any(base_tag(m.tag) in ("VX", "VV") and m.form in aux for m in d.morphs[:-1])
        if last_is_ending and has_aux and last.form in aux_endings:
            d.traits.add(REQUEST_FORM)
        if base_tag(last.tag) == "EF" and last.form in endings:
            d.traits.add(REQUEST_FORM)
        q_stems = set(pat.get("question_stems", []))
        q_endings = set(pat.get("question_endings", []))
        if any(m.form in q_stems for m in d.morphs) or (
            base_tag(last.tag) == "EF" and last.form in q_endings
        ):
            d.traits.add(QUESTION_FORM)
        if base_tag(last.tag) == "ETM":
            d.traits.add(ADNOMINAL)
        negative = set(pat.get("negative_stems", []))
        if any(m.form in negative and base_tag(m.tag) in ("VA", "VCN") for m in d.morphs):
            d.traits.add(NEGATIVE_PREDICATE)
    if d.kind is UnitKind.ADVERB and d.morphs[0].form in set(pat.get("interrogatives", [])):
        d.traits.add(INTERROGATIVE)


def _merge_negation(drafts: list[_Draft], pat: Mapping[str, Any]) -> list[_Draft]:
    neg = set(pat.get("negation_adverbs", []))
    out: list[_Draft] = []
    for d in drafts:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.kind is UnitKind.PREDICATE
            and d.kind is UnitKind.PREDICATE
            and base_tag(prev.morphs[-1].tag) == "EC"
            and base_tag(d.morphs[0].tag) == "VX"
        ):
            prev.morphs += d.morphs
            prev.traits = (prev.traits | d.traits) - {FINAL_ENDING} | (d.traits & {FINAL_ENDING})
            continue
        if (
            prev is not None
            and prev.kind is UnitKind.ADVERB
            and len(prev.morphs) == 1
            and prev.morphs[0].form in neg
            and d.kind is UnitKind.PREDICATE
        ):
            d.morphs = prev.morphs + d.morphs
            d.traits.add(NEGATIVE_PREDICATE)
            out[-1] = d
            continue
        out.append(d)
    return out


def build_units(seg: Segmentation, res: Resources, pat: Mapping[str, Any]) -> list[Unit]:
    norm = seg.text
    by_word: dict[int, list[Morph]] = {}
    for m in seg.morphs:
        by_word.setdefault(seg.word_index(m.start), []).append(m)

    drafts: list[_Draft] = []
    for w in sorted(by_word):
        word_drafts = _merge_word(_group_word(by_word[w]), norm, res)
        drafts.extend(word_drafts)
    for d in drafts:
        _traits(d, pat)
    drafts = _merge_negation(drafts, pat)

    units = []
    for d in drafts:
        units.append(
            Unit(
                start=d.start,
                end=d.end,
                morphs=tuple(d.morphs),
                kind=d.kind,
                word=seg.word_index(d.start),
                word_end=seg.word_index(max(d.end - 1, d.start)),
                traits=frozenset(d.traits),
                parts=tuple(d.parts),
            )
        )
    return units


def clause_breaks(units: Sequence[Unit], pat: Mapping[str, Any]) -> set[int]:
    """Indices ``i`` such that a new clause starts at ``units[i]`` (grammar-based)."""
    cfg = pat.get("clause_break", {})
    always = set(cfg.get("always_after_tags", []))
    next_kinds = {UnitKind(k) for k in cfg.get("next_kinds", [])}
    after_request = bool(cfg.get("predicate_after_request", False))
    breaks: set[int] = set()
    for i in range(1, len(units)):
        prev, cur = units[i - 1], units[i]
        if any(base_tag(m.tag) in always for m in prev.morphs) or (
            prev.has(FINAL_ENDING)
            and (
                cur.kind in next_kinds
                or (after_request and prev.has(REQUEST_FORM) and cur.kind is UnitKind.PREDICATE)
            )
        ):
            breaks.add(i)
    return breaks
