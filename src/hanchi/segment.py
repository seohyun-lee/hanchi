"""Segmentation result and variant selection (language-neutral).

A language pack may analyze several *variants* of the normalized text (for example,
with and without spaces) and keep the one whose morphemes cover the most dictionary
material. All morpheme offsets are expressed in the normalized text.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from hanchi.backend import Morph
from hanchi.normalize import NormalizedText

_NON_SPACE = re.compile(r"\S+")


@dataclass(frozen=True)
class Segmentation:
    normalized: NormalizedText
    morphs: tuple[Morph, ...]
    words: tuple[tuple[int, int], ...]
    """Whitespace-delimited units of the normalized text, as ``[start, end)``."""
    variant: str
    """Which text variant produced :attr:`morphs` (e.g. ``"as_is"``)."""
    coverage: int

    @property
    def text(self) -> str:
        return self.normalized.text

    def word_index(self, offset: int) -> int:
        """Index of the word containing ``offset`` (or the next word, if on a space)."""
        for i, (_, end) in enumerate(self.words):
            if offset < end:
                return i
        return len(self.words) - 1

    def pairs(self) -> list[tuple[str, str]]:
        return [m.pair for m in self.morphs]


def split_words(text: str) -> tuple[tuple[int, int], ...]:
    return tuple((m.start(), m.end()) for m in _NON_SPACE.finditer(text))


@dataclass(frozen=True)
class Variant:
    name: str
    morphs: tuple[Morph, ...]
    coverage: int


def choose_variant(variants: Sequence[Variant]) -> Variant:
    """Highest coverage wins; ties go to the earliest variant (the as-typed text first)."""
    if not variants:
        raise ValueError("no variants to choose from")
    best = variants[0]
    for v in variants[1:]:
        if v.coverage > best.coverage:
            best = v
    return best
