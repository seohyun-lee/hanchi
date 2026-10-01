"""Spacing-variant absorption for Korean.

Korean users space words inconsistently ("강남센터필드" / "강남 센터필드" / "센터 필드").
We analyze the text as typed and, optionally, with all spaces removed, then keep the
variant whose morphemes cover the most registered dictionary words. Offsets of the
despaced analysis are mapped back to the normalized text.
"""

from __future__ import annotations

from hanchi.backend import Morph, coverage
from hanchi.lang.ko.backend import KiwiBackend
from hanchi.normalize import NormalizedText
from hanchi.segment import Segmentation, Variant, choose_variant, split_words


def _despace(text: str) -> tuple[str, list[int]]:
    """Text without spaces, plus the index in ``text`` of every kept character."""
    keep = [i for i, ch in enumerate(text) if not ch.isspace()]
    return "".join(text[i] for i in keep), keep


def _remap(morphs: list[Morph], index: list[int], full_len: int) -> tuple[Morph, ...]:
    def pos(i: int) -> int:
        return index[i] if i < len(index) else full_len

    out = []
    for m in morphs:
        start = pos(m.start)
        end = index[m.end - 1] + 1 if m.end > m.start else start
        out.append(Morph(m.form, m.tag, start, end))
    return tuple(out)


def segment(backend: KiwiBackend, normalized: NormalizedText) -> Segmentation:
    text = normalized.text
    vocab = backend.user_words
    as_is = backend.tokenize(text)
    variants = [Variant("as_is", tuple(as_is), coverage(as_is, vocab))]

    if backend.despaced_variant and vocab and " " in text:
        despaced, index = _despace(text)
        morphs = backend.tokenize(despaced)
        variants.append(
            Variant("despaced", _remap(morphs, index, len(text)), coverage(morphs, vocab))
        )

    best = choose_variant(variants)
    return Segmentation(normalized, best.morphs, split_words(text), best.name, best.coverage)
