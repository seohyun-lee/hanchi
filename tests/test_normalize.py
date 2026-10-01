"""Language-neutral normalization engine."""

from __future__ import annotations

import pytest

from hanchi.normalize import (
    NormalizedText,
    Normalizer,
    RegexReplace,
    UnicodeNormalize,
    collapse_whitespace,
    lowercase_latin,
)


def test_identity_maps_each_char_to_itself() -> None:
    nt = NormalizedText.identity("abc")
    assert nt.to_original(0, 3) == (0, 3)
    assert nt.original_slice(1, 2) == "b"


def test_replacement_inherits_span_of_replaced_range() -> None:
    nt = NormalizedText.identity("a(b)c").replace_ranges([(1, 2, " "), (3, 4, "")])
    assert nt.text == "a bc"
    assert nt.to_original(1, 2) == (1, 2)
    assert nt.original_slice(2, 4) == "b)c"


def test_expanding_replacement_maps_all_chars_to_source() -> None:
    nt = NormalizedText.identity("x㈜y").replace_ranges([(1, 2, "(주)")])
    assert nt.text == "x(주)y"
    assert all(nt.to_original(i, i + 1) == (1, 2) for i in range(1, 4))
    assert nt.original_slice(4, 5) == "y"


def test_empty_range_maps_to_position() -> None:
    nt = NormalizedText.identity("ab")
    assert nt.to_original(1, 1) == (1, 1)
    assert nt.to_original(2, 2) == (2, 2)
    with pytest.raises(ValueError):
        nt.to_original(0, 3)


def test_overlapping_edits_rejected() -> None:
    with pytest.raises(ValueError):
        NormalizedText.identity("abcd").replace_ranges([(0, 2, "x"), (1, 3, "y")])


def test_unicode_normalize_respects_protected_ranges() -> None:
    step = UnicodeNormalize("NFKC", protect=((0x3130, 0x318F),))
    nt = step(NormalizedText.identity("ＡＢ１ㅋㅋ"))
    assert nt.text == "AB1ㅋㅋ"


def test_unicode_normalize_composes_conjoining_jamo_cluster() -> None:
    decomposed = "가"  # ᄀ + ᅡ
    nt = UnicodeNormalize("NFKC")(NormalizedText.identity(decomposed + "x"))
    assert nt.text == "가x"
    assert nt.to_original(0, 1) == (0, 2)


def test_lowercase_latin_only() -> None:
    nt = lowercase_latin(NormalizedText.identity("GS25 Ä Ω"))
    assert nt.text == "gs25 ä Ω"


def test_collapse_whitespace() -> None:
    nt = collapse_whitespace(NormalizedText.identity("  a \t\n b  "))
    assert nt.text == "a b"
    assert nt.original_slice(0, 1) == "a"
    assert nt.original_slice(2, 3) == "b"


def test_normalizer_composes_steps() -> None:
    norm = Normalizer([RegexReplace.compile(r"-", " "), collapse_whitespace])
    nt = norm("a-b")
    assert nt.text == "a b"
    assert nt.original == "a-b"
