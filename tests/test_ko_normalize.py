"""Korean normalization rules (hanchi.lang.ko.normalize)."""

from __future__ import annotations

from pathlib import Path

import pytest

from hanchi.lang.ko.normalize import korean_normalizer

normalize = korean_normalizer()


def test_reference_case_text() -> None:
    assert normalize("㈜스타벅스 (강남R점)").text == "스타벅스 강남r점"


def test_reference_case_offsets_map_back_to_original() -> None:
    original = "㈜스타벅스 (강남R점)"
    nt = normalize(original)
    i = nt.text.index("스타벅스")
    assert nt.original_slice(i, i + 4) == "스타벅스"
    j = nt.text.index("강남r점")
    assert nt.original_slice(j, j + 4) == "강남R점"
    assert nt.to_original(j, j + 4) == (original.index("강남R점"), original.index("강남R점") + 4)
    assert len(nt.spans) == len(nt.text)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ＧＳ２５　역삼점", "gs25 역삼점"),  # full-width -> half-width, lowercase
        ("주식회사 한빛상사", "한빛상사"),
        ("한빛상사 주식회사", "한빛상사"),
        ("한빛상사(유)", "한빛상사"),
        ("(주) 한빛상사", "한빛상사"),
        ("떡볶이·순대", "떡볶이 순대"),
        ("떡볶이ㆍ순대", "떡볶이 순대"),
        ("7-Eleven", "7 eleven"),
        ("010-1234-5678", "010-1234-5678"),  # dash between digits kept
        ("「나를 찾아줘」 예매", "나를 찾아줘 예매"),
        ("ㅋㅋ 웃긴 영상", "ㅋㅋ 웃긴 영상"),  # compatibility jamo protected from NFKC
        ("아이폰  15\t케이스 ", "아이폰 15 케이스"),
        ("주식회사", ""),
    ],
)
def test_rules(raw: str, expected: str) -> None:
    assert normalize(raw).text == expected


def test_marker_inside_word_is_kept() -> None:
    # "주식회사" only removed as a whole word or at a word edge.
    assert normalize("가주식회사나").text == "가주식회사나"


def test_every_char_maps_into_original() -> None:
    raw = "㈜한빛 (본점)·ＡＢＣ-마트"
    nt = normalize(raw)
    for i, ch in enumerate(nt.text):
        s, e = nt.to_original(i, i + 1)
        assert 0 <= s < e <= len(raw), (ch, s, e)


def test_plugin_normalize_yaml_overrides_defaults(tmp_path: Path) -> None:
    (tmp_path / "normalize.yaml").write_text(
        "company_markers:\n  words: [협동조합]\nmiddle_dots: ''\n", encoding="utf-8"
    )
    custom = korean_normalizer([tmp_path])
    assert custom("협동조합 한빛").text == "한빛"
    assert custom("떡볶이·순대").text == "떡볶이·순대"
    assert custom("(주)한빛").text == "한빛"  # untouched keys keep defaults
