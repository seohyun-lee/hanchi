"""Spacing-variant absorption (hanchi.lang.ko.spacing) through the Korean pack."""

from __future__ import annotations

from collections.abc import Callable

from hanchi.lang.ko import KoreanPack

MakePack = Callable[..., KoreanPack]


def seg_pairs(pack: KoreanPack, text: str) -> list[tuple[str, str]]:
    return pack.segment(pack.normalize(text)).pairs()


def test_spacing_variants_agree_with_user_word(make_pack: MakePack) -> None:
    pack = make_pack("센터필드")
    expected = [("강남", "NNP"), ("센터필드", "NNP")]
    assert seg_pairs(pack, "강남센터필드") == expected
    assert seg_pairs(pack, "강남 센터필드") == expected


def test_despaced_variant_wins_when_it_covers_more_dictionary(make_pack: MakePack) -> None:
    pack = make_pack("센터필드")
    seg = pack.segment(pack.normalize("강남 센터 필드"))
    assert seg.variant == "despaced"
    assert seg.pairs() == [("강남", "NNP"), ("센터필드", "NNP")]
    # Offsets are in the normalized text and span the original space.
    m = seg.morphs[1]
    assert seg.text[m.start : m.end] == "센터 필드"
    assert seg.words == ((0, 2), (3, 5), (6, 8))


def test_as_is_kept_without_user_dictionary(plain_pack: KoreanPack) -> None:
    seg = plain_pack.segment(plain_pack.normalize("강남 센터 필드"))
    assert seg.variant == "as_is"
    assert seg.coverage == 0


def test_as_is_preferred_on_tie(make_pack: MakePack) -> None:
    pack = make_pack("센터필드")
    seg = pack.segment(pack.normalize("강남 센터필드 카페"))
    assert seg.variant == "as_is"


def test_morph_offsets_map_back_to_original(plain_pack: KoreanPack) -> None:
    original = "㈜스타벅스 (강남R점)"
    nt = plain_pack.normalize(original)
    seg = plain_pack.segment(nt)
    starbucks = next(m for m in seg.morphs if m.form == "스타벅스")
    assert nt.original_slice(starbucks.start, starbucks.end) == "스타벅스"
    branch = [m for m in seg.morphs if m.start >= nt.text.index("강남")]
    s, e = nt.to_original(branch[0].start, branch[-1].end)
    assert original[s:e] == "강남R점"


def test_word_index(plain_pack: KoreanPack) -> None:
    seg = plain_pack.segment(plain_pack.normalize("강남역 카페 찾아줘"))
    assert [seg.word_index(m.start) for m in seg.morphs] == [0, 1, 2, 2, 2, 2]
