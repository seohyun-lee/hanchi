"""M4: ranking helper and query relaxation (plan §1.3, §5.7, §11.7, §12.6)."""

from __future__ import annotations

from typing import Any

import pytest

from helpers import HOMONYMS, analyzer

LOCAL = "preset:local"
A: dict[str, Any] = {"name": "강남 방탈출카페 미로", "category": "방탈출", "location": "강남"}
H2 = {"name": "강남 방탈출", "category": "방탈출", "location": "강남"}
H3 = {"name": "찾아줘", "category": "방탈출", "location": "강남"}
H4 = {"name": "방탈출 찾아줘", "category": "카페", "location": "강남"}


# --- plan §1.3 representative cases -------------------------------------------------


def test_center_prefix_beats_category_and_branch() -> None:
    a = analyzer(LOCAL, entities=(("센터필드", "building"),))
    names = a.rank(
        "강남 센터", ["서울대병원 강남센터", "강남구 건강센터", "강남 센터필드", "강남 스포츠센터"]
    ).names()
    assert names[0] == "강남 센터필드"
    assert names[-1] == "서울대병원 강남센터"
    assert set(names[1:3]) == {"강남구 건강센터", "강남 스포츠센터"}


def test_region_beats_name_sharing_a_common_tail() -> None:
    a = analyzer(LOCAL, entities=(("열쇠를찾아줘", "store"),))
    r = a.rank("강남 찾아줘", ["열쇠를찾아줘 강남점", {"name": "강남", "category": "지역"}])
    assert r.names()[0] == "강남"


def test_h1_default_reading_lists_category_results() -> None:
    tail = {"name": "열쇠를찾아줘 강남점", "category": "방탈출", "location": "강남"}
    r = analyzer(LOCAL).rank("강남 방탈출 찾아줘", [tail, A])
    assert r.names() == ["강남 방탈출카페 미로", "열쇠를찾아줘 강남점"]
    assert r.mode == "strict"


@pytest.mark.parametrize(
    ("entities", "candidates", "top"),
    [
        ((("강남 방탈출", "store"),), [A, H2], "강남 방탈출"),
        ((("찾아줘", "store"),), [A, H3], "찾아줘"),
        ((("방탈출 찾아줘", "cafe"),), [A, H4], "방탈출 찾아줘"),
    ],
)
def test_h2_h3_h4(entities: tuple[tuple[str, str], ...], candidates: list[Any], top: str) -> None:
    r = analyzer(LOCAL, entities=entities).rank("강남 방탈출 찾아줘", candidates)
    assert r.names()[0] == top


def test_all_readings_merged_in_fixed_order() -> None:
    ents = (("강남 방탈출", "store"), ("찾아줘", "store"), ("방탈출 찾아줘", "cafe"))
    a = analyzer(LOCAL, entities=ents)
    assert a.analyze("강남 방탈출 찾아줘").ambiguous
    names = a.rank("강남 방탈출 찾아줘", [A, H3, H4, H2]).names()
    assert set(names[:2]) == {"강남 방탈출", "방탈출 찾아줘"}  # full names (H2/H4)
    assert names[2:] == ["찾아줘", "강남 방탈출카페 미로"]  # then H3, then the H1 list
    tiers = [r.tier for r in a.rank("강남 방탈출 찾아줘", [A, H3, H4, H2])]
    assert tiers == [2, 2, 1, 0]


def test_title_full_match() -> None:
    a = analyzer(entities=(("나를 찾아줘", "title"),))
    assert (
        a.rank("나를 찾아줘 예매", ["찾아줘 앱 사용법", "나를 찾아줘"]).names()[0] == "나를 찾아줘"
    )


def test_entity_plus_category_beats_entity_alone() -> None:
    a = analyzer("preset:commerce", entities=(("아이폰 15", "product"),))
    names = a.rank(
        "아이폰 15 케이스 찾아줘", ["아이폰 15", "갤럭시 케이스", "아이폰 15 케이스"]
    ).names()
    assert names[0] == "아이폰 15 케이스"


# --- relaxation -----------------------------------------------------------------------


def test_relaxed_mode_when_nothing_matches_everything() -> None:
    a = analyzer(LOCAL)
    strict = a.rank("강남 카페", ["강남 카페 라떼", "홍대 카페"])
    assert strict.mode == "strict" and strict.results[0].passed
    relaxed = a.rank("강남 카페", ["홍대 카페", "부산 카페"])
    assert relaxed.mode == "relaxed"
    assert relaxed.dropped == ["강남"] or relaxed.dropped  # least important span first
    assert all(r.passed for r in relaxed)


def test_k_controls_relaxation() -> None:
    a = analyzer(LOCAL)
    r = a.rank("강남 카페", ["강남 카페 라떼", "홍대 카페"], k=2)
    assert r.mode == "relaxed"


# --- §11.7 ------------------------------------------------------------------------------


def test_meta_clause_is_not_matched() -> None:
    r = analyzer(LOCAL).rank("강남 방탈출 찾아줘 왜 안나와", ["왜 안나와 노래 가사", A])
    assert r.names()[0] == "강남 방탈출카페 미로"
    assert r.signals and r.signals[0]["type"] == "dissatisfaction"


def test_request_clause_first_entity_reading_still_listed() -> None:
    a = analyzer(LOCAL, entities=(("안나와", "store"),))
    other = {"name": "안나와", "category": "주점", "location": "강남"}
    r = a.rank("강남 방탈출 찾아줘 안나와", [other, A])
    assert r.names() == ["강남 방탈출카페 미로", "안나와"]
    assert r.results[1].score > 0


def test_constraints_are_passed_to_the_caller() -> None:
    r = analyzer(LOCAL).rank("주변 방탈출 찾아줘", [A])
    assert r.constraints == [{"span": "주변", "type": "proximity", "anchor": "user_location"}]


# --- §12.6 senses ------------------------------------------------------------------------


def test_homonym_results_are_diversified() -> None:
    a = analyzer(HOMONYMS)
    cands = [
        "애플 주가",
        "애플 서비스센터",
        "애플 가로수길 매장",
        "애플 신제품",
        "사과 농장",
        "애플파이",
    ]
    r = a.rank("애플", cands)
    senses = [x.sense_id for x in r]
    assert senses[0] == "apple_inc"
    # the other sense shows up early instead of only after every company result
    assert "apple_fruit" in senses[:5]


def test_resolved_sense_matches_its_own_results() -> None:
    a = analyzer(HOMONYMS)
    assert a.rank("애플 매장", ["사과 매장", "애플 매장 위치"]).names()[0] == "애플 매장 위치"


# --- mixed-script names (§13.5) ---------------------------------------------------------


@pytest.mark.parametrize("query", ["365의원", "연세의원"])
def test_partial_queries_meet_mixed_script_name_parts(query: str) -> None:
    r = analyzer(LOCAL).rank(query, ["서울의원", "연세치과", "연세365의원"])
    assert r.names()[0] == "연세365의원"
