"""Offset-preserving text normalization (language-neutral engine).

A :class:`NormalizedText` keeps, for every character of the normalized string, the
``[start, end)`` range of the original text it came from, so analysis results on the
normalized text can always be mapped back to what the user typed.

Language packs assemble a :class:`Normalizer` from the generic steps defined here
(plus their own language-specific steps and data).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class NormalizedText:
    original: str
    text: str
    spans: tuple[tuple[int, int], ...]
    """``spans[i]`` is the original ``[start, end)`` range that produced ``text[i]``."""

    @classmethod
    def identity(cls, text: str) -> NormalizedText:
        return cls(text, text, tuple((i, i + 1) for i in range(len(text))))

    def to_original(self, start: int, end: int) -> tuple[int, int]:
        """Map a ``[start, end)`` range of :attr:`text` to a range of :attr:`original`."""
        if not 0 <= start <= end <= len(self.text):
            raise ValueError(f"range [{start}, {end}) outside normalized text")
        if start == end:
            if start < len(self.spans):
                pos = self.spans[start][0]
            elif self.spans:
                pos = self.spans[-1][1]
            else:
                pos = 0
            return pos, pos
        return self.spans[start][0], max(s[1] for s in self.spans[start:end])

    def original_slice(self, start: int, end: int) -> str:
        ostart, oend = self.to_original(start, end)
        return self.original[ostart:oend]

    def replace_ranges(self, edits: Iterable[tuple[int, int, str]]) -> NormalizedText:
        """Replace non-overlapping ``[start, end)`` ranges of :attr:`text`.

        Every character of a replacement inherits the original span of the whole
        replaced range; a deletion simply drops the characters.
        """
        out: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        for start, end, repl in sorted(edits):
            if start < cursor:
                raise ValueError("overlapping edits")
            out.append(self.text[cursor:start])
            spans.extend(self.spans[cursor:start])
            if repl:
                span = self.to_original(start, end)
                out.append(repl)
                spans.extend([span] * len(repl))
            cursor = end
        out.append(self.text[cursor:])
        spans.extend(self.spans[cursor:])
        return NormalizedText(self.original, "".join(out), tuple(spans))


Step = Callable[[NormalizedText], NormalizedText]


class Normalizer:
    """A sequence of offset-preserving normalization steps."""

    def __init__(self, steps: Sequence[Step]) -> None:
        self.steps = tuple(steps)

    def __call__(self, text: str) -> NormalizedText:
        nt = NormalizedText.identity(text)
        for step in self.steps:
            nt = step(nt)
        return nt


# --- generic steps -----------------------------------------------------------------


def _is_cluster_start(ch: str) -> bool:
    # Conjoining Hangul medials/finals and combining marks attach to the previous char.
    cp = ord(ch)
    if 0x1160 <= cp <= 0x11FF or 0xD7B0 <= cp <= 0xD7FF:
        return False
    return unicodedata.combining(ch) == 0


@dataclass(frozen=True)
class UnicodeNormalize:
    """Apply a Unicode normalization form cluster by cluster.

    ``protect`` lists code point ranges left untouched (e.g. scripts whose
    compatibility decomposition would hurt downstream analysis).
    """

    form: str = "NFKC"
    protect: tuple[tuple[int, int], ...] = ()

    def _protected(self, ch: str) -> bool:
        cp = ord(ch)
        return any(lo <= cp <= hi for lo, hi in self.protect)

    def __call__(self, nt: NormalizedText) -> NormalizedText:
        edits: list[tuple[int, int, str]] = []
        text = nt.text
        i = 0
        while i < len(text):
            j = i + 1
            while j < len(text) and not _is_cluster_start(text[j]):
                j += 1
            chunk = text[i:j]
            if not any(self._protected(c) for c in chunk):
                norm = unicodedata.normalize(self.form, chunk)  # type: ignore[arg-type]
                if norm != chunk:
                    edits.append((i, j, norm))
            i = j
        return nt.replace_ranges(edits) if edits else nt


@dataclass(frozen=True)
class RegexReplace:
    """Replace every match of ``pattern`` with ``repl`` (a literal string)."""

    pattern: re.Pattern[str]
    repl: str

    @classmethod
    def compile(cls, pattern: str, repl: str) -> RegexReplace:
        return cls(re.compile(pattern), repl)

    def __call__(self, nt: NormalizedText) -> NormalizedText:
        edits = [(m.start(), m.end(), self.repl) for m in self.pattern.finditer(nt.text)]
        return nt.replace_ranges(edits) if edits else nt


def lowercase_latin(nt: NormalizedText) -> NormalizedText:
    """Lowercase Latin letters only, one character at a time (offsets stay 1:1)."""
    edits = []
    for i, ch in enumerate(nt.text):
        if ch.isupper() and unicodedata.name(ch, "").startswith("LATIN"):
            low = ch.lower()
            if len(low) == 1:
                edits.append((i, i + 1, low))
    return nt.replace_ranges(edits) if edits else nt


_WHITESPACE = re.compile(r"\s+")


def collapse_whitespace(nt: NormalizedText) -> NormalizedText:
    """Collapse whitespace runs to a single space and strip both ends."""
    text = nt.text
    edits: list[tuple[int, int, str]] = []
    for m in _WHITESPACE.finditer(text):
        at_edge = m.start() == 0 or m.end() == len(text)
        if at_edge:
            edits.append((m.start(), m.end(), ""))
        elif m.group() != " ":
            edits.append((m.start(), m.end(), " "))
    return nt.replace_ranges(edits) if edits else nt
