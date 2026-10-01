"""Units: the contract between a language pack and the language-neutral core.

A language pack groups morphemes into units (a noun, a whole predicate with its
endings, a particle, …), labels each with a coarse :class:`UnitKind` and a set of
trait names. The core reasons only about kinds, traits and dictionary matches; it never
looks at language-specific tags or forms.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from hanchi.backend import Morph


class UnitKind(str, Enum):
    NOMINAL = "nominal"
    FOREIGN = "foreign"
    NUMBER = "number"
    PREDICATE = "predicate"
    ADVERB = "adverb"
    DETERMINER = "determiner"
    INTERJECTION = "interjection"
    FUNCTION = "function"
    SPECIAL = "special"
    OTHER = "other"

    @property
    def is_content(self) -> bool:
        return self is not UnitKind.FUNCTION

    @property
    def is_nominal_like(self) -> bool:
        return self in (UnitKind.NOMINAL, UnitKind.FOREIGN, UnitKind.NUMBER)


# Trait names a language pack may attach to a unit.
PROPER = "proper"
REQUEST_FORM = "request_form"
FINAL_ENDING = "final_ending"
NEGATIVE_PREDICATE = "negative_predicate"
INTERROGATIVE = "interrogative"
MIXED_SCRIPT = "mixed_script"
QUANTITY = "quantity"
LOCATION_GUESS = "location_guess"  # set by the core: unknown X in "<name> X점"


@dataclass(frozen=True)
class Unit:
    start: int
    end: int
    """``[start, end)`` in the normalized text."""
    morphs: tuple[Morph, ...]
    kind: UnitKind
    word: int
    """Index of the whitespace-delimited word the unit starts in."""
    traits: frozenset[str] = frozenset()
    parts: tuple[tuple[int, int], ...] = ()
    """Sub-ranges (normalized text) for units built from several pieces (e.g. 연세|365|의원)."""
    word_end: int = -1
    """Index of the word the unit ends in (defaults to :attr:`word`)."""
    meta: dict[str, str] = field(default_factory=dict, compare=False)

    @property
    def last_word(self) -> int:
        return self.word if self.word_end < 0 else self.word_end

    def has(self, trait: str) -> bool:
        return trait in self.traits
