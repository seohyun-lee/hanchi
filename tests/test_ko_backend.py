"""Kiwi backend: tag table, user words, typo option, and snapshots of known analyses.

The snapshots pin the behaviour of kiwipiepy 0.24.0's default model that the design
relies on. If a Kiwi upgrade changes them, review the role rules before updating.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from kiwipiepy import Kiwi

from hanchi.backend import Backend, PosClass
from hanchi.lang.ko import KiwiBackend
from hanchi.lang.ko.backend import load_backend_config
from hanchi.lang.ko.tags import KNOWN_TAGS, base_tag, tag_info

MakeBackend = Callable[..., KiwiBackend]


def fmt(backend: KiwiBackend, text: str) -> str:
    return " ".join(f"{m.form}/{m.tag}" for m in backend.tokenize(text))


def test_kiwi_backend_satisfies_protocol(make_backend: MakeBackend) -> None:
    assert isinstance(make_backend(), Backend)


def test_every_table_tag_is_accepted_by_kiwi() -> None:
    kiwi = Kiwi()
    for i, tag in enumerate(sorted(KNOWN_TAGS)):
        assert kiwi.add_user_word(f"태그검사{i}", tag) in (True, False), tag


def test_irregular_tags_share_base_entry() -> None:
    assert base_tag("VV-I") == "VV"
    assert tag_info("VA-R").pos_class is PosClass.ADJ
    assert tag_info("NNP").name == "고유명사"
    assert tag_info("XYZ").pos_class is PosClass.UNKNOWN


def test_all_tags_in_reference_analyses_are_known(make_backend: MakeBackend) -> None:
    backend = make_backend()
    texts = [*SNAPSHOT_PLAIN, "걸어서 가는 카페", "https://a.com #태그 3.5kg ㅋㅋ (괄호)!"]
    for text in texts:
        for m in backend.tokenize(text):
            assert base_tag(m.tag) in KNOWN_TAGS, (text, m)


def test_morph_offsets_index_the_text(make_backend: MakeBackend) -> None:
    text = "강남역 카페 찾아줘"
    morphs = make_backend().tokenize(text)
    assert [text[m.start : m.end] for m in morphs][:2] == ["강남역", "카페"]


def test_user_word_uses_configured_default_score(make_backend: MakeBackend) -> None:
    backend = make_backend("센터필드")
    assert backend.user_words == frozenset({"센터필드"})
    assert load_backend_config()["user_word_score"] > 0


def test_typo_option_is_passed_to_tokenize() -> None:
    cfg = load_backend_config()
    assert fmt(KiwiBackend(cfg), "맛잇는") == "맛/NNG 잇/VV-I 는/ETM"
    corrected = KiwiBackend({**cfg, "typos": "basic"})
    assert fmt(corrected, "맛잇는") == "맛있/VA 는/ETM"


# --- plan §4.1 measurements (kiwipiepy 0.24.0, default model) -----------------------

SNAPSHOT_PLAIN = {
    "건강센터": "건강/NNG 센터/NNG",
    "센터필드": "센터필드/NNG",
    "강남센터필드": "강남/NNP 센터/NNG 필드/NNG",
    "서울대병원 강남센터": "서울대병원/NNP 강남/NNP 센터/NNG",
    "강남 센터": "강남/NNP 센터/NNG",
    "강남구 건강센터": "강남구/NNP 건강/NNG 센터/NNG",
    "강남 센터필드": "강남/NNP 센터/NNG 필드/NNG",
}

SNAPSHOT_WITH_CENTERFIELD = {
    "강남센터필드": "강남/NNP 센터필드/NNP",
    "강남 센터필드": "강남/NNP 센터필드/NNP",
    "강남 센타필드": "강남/NNP 센타필드/NNG",
    "GS25역삼점": "GS/SL 25/SN 역삼점/NNG",
    "스타벅스강남R점": "스타벅스/NNP 강남/NNP R/SL 점/NNB",
}


@pytest.mark.parametrize(("text", "expected"), SNAPSHOT_PLAIN.items())
def test_snapshot_without_user_dictionary(
    make_backend: MakeBackend, text: str, expected: str
) -> None:
    assert fmt(make_backend(), text) == expected


@pytest.mark.parametrize(("text", "expected"), SNAPSHOT_WITH_CENTERFIELD.items())
def test_snapshot_with_user_dictionary(make_backend: MakeBackend, text: str, expected: str) -> None:
    assert fmt(make_backend("센터필드"), text) == expected


def test_space_snapshot(make_backend: MakeBackend) -> None:
    # space() splits 센터 필드 even though tokenize() keeps 강남센터필드 together here.
    assert make_backend().space("강남센터필드서울대병원") == "강남 센터 필드 서울대병원"
