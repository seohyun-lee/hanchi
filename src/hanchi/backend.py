"""Morphological backend interface (language-neutral).

A backend turns text into morphemes with fine-grained, language-specific tags. The core
never interprets those tags directly: each language pack also provides a tag table that
maps every tag to a coarse, language-neutral :class:`PosClass`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class PosClass(str, Enum):
    """Coarse part-of-speech classes shared by all languages."""

    NOUN = "noun"
    PROPN = "propn"
    PRON = "pron"
    NUM = "num"
    VERB = "verb"
    ADJ = "adj"
    AUX = "aux"
    COPULA = "copula"
    DET = "det"
    ADV = "adv"
    CONJ = "conj"
    INTJ = "intj"
    PARTICLE = "particle"
    ENDING = "ending"
    AFFIX = "affix"
    ROOT = "root"
    PUNCT = "punct"
    SYMBOL = "symbol"
    FOREIGN = "foreign"
    NUMBER = "number"
    SPECIAL = "special"
    UNKNOWN = "unknown"

    @property
    def is_function(self) -> bool:
        """Grammatical material with no lexical content of its own."""
        return self in _FUNCTION_CLASSES

    @property
    def is_nominal(self) -> bool:
        return self in _NOMINAL_CLASSES


_FUNCTION_CLASSES = frozenset({PosClass.PARTICLE, PosClass.ENDING, PosClass.PUNCT})
_NOMINAL_CLASSES = frozenset(
    {PosClass.NOUN, PosClass.PROPN, PosClass.PRON, PosClass.NUM, PosClass.FOREIGN}
)


@dataclass(frozen=True)
class TagInfo:
    tag: str
    pos_class: PosClass
    name: str
    """Human-readable name in the pack's language (e.g. "고유명사")."""


@dataclass(frozen=True)
class Morph:
    form: str
    tag: str
    start: int
    end: int
    """``[start, end)`` in the analyzed text. Contracted morphemes may overlap."""

    @property
    def pair(self) -> tuple[str, str]:
        return self.form, self.tag


@runtime_checkable
class Backend(Protocol):
    """What the core needs from a morphological analyzer."""

    def tokenize(self, text: str) -> list[Morph]: ...

    def add_user_word(self, word: str, tag: str, score: float | None = None) -> bool: ...

    @property
    def user_words(self) -> frozenset[str]:
        """Forms registered through :meth:`add_user_word`."""
        ...

    def tag_info(self, tag: str) -> TagInfo: ...


def coverage(morphs: Iterable[Morph], vocabulary: frozenset[str]) -> int:
    """Number of characters covered by morphemes whose form is in ``vocabulary``."""
    return sum(m.end - m.start for m in morphs if m.form in vocabulary)
