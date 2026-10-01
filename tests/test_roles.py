"""M2: role candidates, resolver v1, weights, explain (plan §1.3, §5, §11, §12, §13)."""

from __future__ import annotations

import json

import pytest

from hanchi import Analysis, Analyzer, Span
from helpers import HOMONYMS, WEB_PRIOR, analyzer

LOCAL = "preset:local"
TITLES = (("나를 찾아줘", "title"),)


def top_role(span: Span) -> str:
    return span.top.role


def resolved_role(span: Span) -> str | None:
    return span.resolved.role if span.resolved else None


def check_invariants(r: Analysis) -> None:
    for s in r.spans:
        assert abs(sum(h.p for h in s.hypotheses) - 1.0) < 1e-4
        assert r.query[s.start : s.end] == s.text
        assert all(0.0 <= h.weight <= 1.0 for h in s.hypotheses)
    assert abs(sum(it.p for it in r.interpretations) - 1.0) < 1e-4


# --- M2 completion criteria --------------------------------------------------------


@pytest.mark.parametrize("plugins", [(), (LOCAL,)])
def test_sentence_final_request_is_command(plugins: tuple[str, ...]) -> None:
    r = analyzer(*plugins).analyze("강남역 카페 찾아줘")
    check_invariants(r)
    cmd = r.span("찾아줘")
    assert resolved_role(cmd) == "COMMAND"
    assert cmd.resolved is not None and cmd.resolved.p >= 0.9
    assert "ENTITY" in cmd.roles()  # never deleted, just unlikely


def test_natural_language_request() -> None:
    r = analyzer(LOCAL).analyze("지금 영업중인 식당 찾아줘")
    check_invariants(r)
    assert top_role(r.span("지금")) == "CONSTRAINT"
    assert top_role(r.span("영업중")) == "CONSTRAINT"
    assert top_role(r.span("식당")) == "HEAD"
    assert resolved_role(r.span("찾아줘")) == "COMMAND"
    assert r.span("지금").attach == {"type": "time", "anchor": "now"}
    assert r.span("영업중").attach == {"type": "status", "anchor": "now"}


def test_title_followed_by_noun_is_entity() -> None:
    r = analyzer(entities=TITLES).analyze("나를 찾아줘 예매")
    span = r.span("나를 찾아줘")
    assert resolved_role(span) == "ENTITY"
    assert span.resolved is not None and span.resolved.sense_id == "나를 찾아줘"


def test_title_alone_stays_ambiguous() -> None:
    r = analyzer(entities=TITLES).analyze("나를 찾아줘")
    span = r.span("나를 찾아줘")
    assert span.resolved is None
    assert {"ENTITY", "COMMAND"} <= span.roles()
    assert r.ambiguous


def test_compound_modifier_and_head() -> None:
    r = analyzer(LOCAL).analyze("건강센터")
    assert top_role(r.span("건강")) == "MODIFIER"
    assert top_role(r.span("센터")) == "HEAD"


def test_registered_name_is_single_entity_span() -> None:
    r = analyzer(LOCAL, entities=(("센터필드", "building"),)).analyze("센터필드")
    assert len(r.spans) == 1
    assert resolved_role(r.spans[0]) == "ENTITY"


def test_branch_marker_is_qualifier() -> None:
    r = analyzer(LOCAL).analyze("메가스터디학원 강남센터")
    assert [s.norm for s in r.spans][-2:] == ["강남", "센터"]
    assert top_role(r.spans[-1]) == "QUALIFIER"


@pytest.mark.parametrize("plugins", [(), (LOCAL,)])
def test_single_word_query_has_full_weight(plugins: tuple[str, ...]) -> None:
    r = analyzer(*plugins).analyze("센터")
    assert len(r.spans) == 1
    assert r.spans[0].top.weight == 1.0


def test_explain_gives_evidence_for_every_hypothesis() -> None:
    r = analyzer(LOCAL, entities=TITLES).analyze("지금 영업중인 식당 찾아줘", explain=True)
    assert r.explain is not None
    for s in r.spans:
        for h in s.hypotheses:
            assert h.evidence, (s.text, h.role)
    contributions = [
        c for sp in r.explain["spans"] for h in sp["hypotheses"] for c in h["contributions"]
    ]
    assert any(c["feature"] == "request_clause_final" for c in contributions)


def test_explain_off_by_default() -> None:
    assert analyzer().analyze("찾아줘").explain is None


# --- §1.3 "강남 방탈출 찾아줘": four readings ----------------------------------------


def merges(r: Analysis) -> list[list[str]]:
    return [[str(m["text"]) for m in it.merges] for it in r.interpretations]


def test_all_four_readings_are_generated_without_entities() -> None:
    r = analyzer(LOCAL).analyze("강남 방탈출 찾아줘")
    ms = merges(r)
    assert [] in ms  # H1 / H3 (base segmentation)
    assert ["강남 방탈출"] in ms  # H2
    assert ["방탈출 찾아줘"] in ms  # H4
    assert "ENTITY" in r.span("찾아줘").roles()  # H3 hypothesis exists
    # H1 wins: 강남=LOCATION, 방탈출=HEAD, 찾아줘=COMMAND
    assert r.interpretations[0].merges == []
    assert r.interpretations[0].p >= 0.9
    assert top_role(r.span("강남")) == "LOCATION"
    assert top_role(r.span("방탈출")) == "HEAD"
    assert resolved_role(r.span("찾아줘")) == "COMMAND"


def test_h2_full_name_wins() -> None:
    r = analyzer(LOCAL, entities=(("강남 방탈출", "store"),)).analyze("강남 방탈출 찾아줘")
    assert [m["text"] for m in r.interpretations[0].merges] == ["강남 방탈출"]
    assert resolved_role(r.span("강남 방탈출")) == "ENTITY"
    assert resolved_role(r.span("찾아줘")) == "COMMAND"


def test_h3_name_matches_command_word() -> None:
    r = analyzer(LOCAL, entities=(("찾아줘", "store"),)).analyze("강남 방탈출 찾아줘")
    span = r.span("찾아줘")
    assert span.resolved is None
    assert {"ENTITY", "COMMAND"} <= span.roles()
    assert any("(full)" in e for e in span.hypothesis("ENTITY").evidence)  # type: ignore[union-attr]


def test_h4_full_name_wins() -> None:
    r = analyzer(LOCAL, entities=(("방탈출 찾아줘", "cafe"),)).analyze("강남 방탈출 찾아줘")
    assert [m["text"] for m in r.interpretations[0].merges] == ["방탈출 찾아줘"]
    # The whole name could still be read as "find escape rooms" (also kept as reading H1).
    assert top_role(r.span("방탈출 찾아줘")) == "ENTITY"
    assert top_role(r.span("강남")) == "LOCATION"


def test_several_names_leave_the_query_ambiguous() -> None:
    ents = (("강남 방탈출", "store"), ("방탈출 찾아줘", "cafe"), ("찾아줘", "store"))
    r = analyzer(LOCAL, entities=ents).analyze("강남 방탈출 찾아줘")
    assert r.ambiguous
    assert r.interpretations[0].p < 0.9
    supported = {m["text"] for it in r.interpretations for m in it.merges if m["supported"]}
    assert supported == {"강남 방탈출", "방탈출 찾아줘"}


def test_common_tail_of_a_name_is_not_evidence() -> None:
    r = analyzer(LOCAL, entities=(("열쇠를찾아줘", "store"),)).analyze("강남 찾아줘")
    cmd = r.span("찾아줘")
    assert resolved_role(cmd) == "COMMAND"
    entity = cmd.hypothesis("ENTITY")
    assert entity is not None and any("common_part" in e for e in entity.evidence)


# --- §11 conversational / voice input ---------------------------------------------


def test_dissatisfaction_clause() -> None:
    r = analyzer(LOCAL).analyze("강남 방탈출 찾아줘 왜 안나와")
    assert len(r.clauses) == 2
    assert {s.clause_id for s in r.spans[:3]} == {0}
    assert resolved_role(r.span("왜")) == "META"
    assert resolved_role(r.span("안나와")) == "META"
    assert r.signals == [{"type": "dissatisfaction", "span": "왜 안나와", "clause_id": 1}]
    assert r.span("안나와").top.weight == 0.0


ANNAWA = (("안나와", "store"),)


def test_trailing_name_like_complaint_is_ambiguous() -> None:
    r = analyzer(LOCAL, entities=ANNAWA).analyze("강남 방탈출 찾아줘 안나와")
    span = r.span("안나와")
    assert span.resolved is None
    assert {"META", "ENTITY"} <= span.roles()


def test_location_plus_name_is_entity() -> None:
    r = analyzer(LOCAL, entities=ANNAWA).analyze("강남 안나와")
    assert resolved_role(r.span("안나와")) == "ENTITY"


def test_name_with_branch_is_entity() -> None:
    r = analyzer(LOCAL, entities=(("안나오네", "store"),)).analyze("안나오네 강남점")
    assert resolved_role(r.span("안나오네")) == "ENTITY"
    assert top_role(r.span("강남")) == "LOCATION"
    assert top_role(r.span("점")) == "QUALIFIER"


def test_name_before_request_is_entity() -> None:
    r = analyzer(LOCAL, entities=ANNAWA).analyze("강남 안나와 찾아줘")
    assert resolved_role(r.span("안나와")) == "ENTITY"
    assert resolved_role(r.span("찾아줘")) == "COMMAND"


def test_session_context_strengthens_meta() -> None:
    a = analyzer(LOCAL, entities=ANNAWA)
    q = "강남 방탈출 찾아줘 왜 안나와"
    plain = a.analyze(q).span("안나와").hypothesis("META")
    ctx = {"prev_query": "강남 방탈출 찾아줘", "prev_result_count": 0}
    with_ctx = a.analyze(q, context=ctx).span("안나와").hypothesis("META")
    assert plain is not None and with_ctx is not None
    assert with_ctx.p > plain.p
    assert "context:prev_query_no_result" in with_ctx.evidence
    assert resolved_role(a.analyze(q, context=ctx).span("안나와")) == "META"


@pytest.mark.parametrize("query", ["주변 강남 방탈출 찾아줘", "강남 주변 방탈출 찾아줘"])
def test_proximity_attaches_to_location_regardless_of_order(query: str) -> None:
    r = analyzer(LOCAL).analyze(query)
    near = r.span("주변")
    assert top_role(near) == "CONSTRAINT"
    assert near.attach is not None
    anchor = near.attach["anchor"]
    assert near.attach["type"] == "proximity"
    assert isinstance(anchor, int) and r.spans[anchor].norm == "강남"


def test_proximity_without_location_uses_user_location() -> None:
    r = analyzer(LOCAL).analyze("주변 방탈출 찾아줘")
    assert r.span("주변").attach == {"type": "proximity", "anchor": "user_location"}


def test_correction_clause() -> None:
    r = analyzer(LOCAL).analyze("방탈출 찾아줘 아니 강남")
    assert len(r.clauses) == 2
    assert resolved_role(r.span("아니")) == "META"
    assert r.signals[0]["type"] == "correction"
    gangnam = r.span("강남")
    assert top_role(gangnam) == "LOCATION"
    assert gangnam.attach is not None and r.spans[gangnam.attach["anchor"]].norm == "찾아줘"


# --- §12 homonyms -------------------------------------------------------------------


@pytest.mark.parametrize("query", ["애플 매장", "애플 서비스센터"])
def test_company_sense_from_co_occurring_word(query: str) -> None:
    r = analyzer(HOMONYMS).analyze(query)
    apple = r.span("애플")
    assert apple.resolved is not None
    assert (apple.resolved.role, apple.resolved.sense_id) == ("ENTITY", "apple_inc")
    assert apple.canonical == "애플"


def test_compound_wins_over_part() -> None:
    r = analyzer(HOMONYMS).analyze("애플파이")
    assert len(r.spans) == 1
    assert r.spans[0].resolved is not None and r.spans[0].resolved.sense_id == "apple_pie"


def test_bare_homonym_without_prior_is_uniform() -> None:
    r = analyzer(HOMONYMS).analyze("애플")
    apple = r.spans[0]
    assert apple.resolved is None
    ps = [h.p for h in apple.hypotheses]
    assert max(ps) - min(ps) < 1e-6


def test_domain_prior_resolves_bare_homonym() -> None:
    r = analyzer(HOMONYMS, WEB_PRIOR).analyze("애플")
    assert r.spans[0].resolved is not None and r.spans[0].resolved.sense_id == "apple_inc"


def test_previous_query_raises_related_sense() -> None:
    a = analyzer(HOMONYMS)
    plain = a.analyze("애플").spans[0].hypothesis("ENTITY", "apple_inc")
    ctx = (
        a.analyze("애플", context={"prev_query": "아이폰 15"})
        .spans[0]
        .hypothesis("ENTITY", "apple_inc")
    )
    assert plain is not None and ctx is not None and ctx.p > plain.p


@pytest.mark.parametrize(("query", "sense"), [("배 수리", "ship"), ("배 1박스", "pear")])
def test_homonym_sense_from_context(query: str, sense: str) -> None:
    r = analyzer(HOMONYMS).analyze(query)
    assert r.span("배").top.sense_id == sense


def test_bare_homonym_three_ways() -> None:
    r = analyzer(HOMONYMS).analyze("배")
    assert r.spans[0].resolved is None
    assert {h.sense_id for h in r.spans[0].hypotheses} == {"pear", "ship", "belly"}


# --- §13 mixed-script names without a dictionary ----------------------------------


def test_mixed_script_name_with_parts() -> None:
    r = analyzer(LOCAL).analyze("연세365의원")
    assert len(r.spans) == 1
    s = r.spans[0]
    assert resolved_role(s) == "ENTITY"
    assert s.parts is not None and [p.norm for p in s.parts] == ["연세", "365", "의원"]
    assert "rule:mixed_script_eojeol" in s.top.evidence


@pytest.mark.parametrize("query", ["365의원", "123젤라또", "GLE어학원"])
def test_mixed_script_names(query: str) -> None:
    r = analyzer(LOCAL).analyze(query)
    assert len(r.spans) == 1
    assert top_role(r.spans[0]) == "ENTITY"
    assert "CONSTRAINT" not in r.spans[0].roles()  # 123 is not a quantity


def test_case_insensitive_but_original_text_kept() -> None:
    a = analyzer(LOCAL)
    upper, lower = a.analyze("GLE어학원").spans[0], a.analyze("gle어학원").spans[0]
    assert lower.text == "gle어학원" and upper.text == "GLE어학원"
    assert upper.norm == lower.norm
    assert [(h.role, round(h.p, 4)) for h in upper.hypotheses] == [
        (h.role, round(h.p, 4)) for h in lower.hypotheses
    ]


def test_quantity_is_not_a_name() -> None:
    r = analyzer(LOCAL).analyze("젤라또 2개")
    assert top_role(r.span("젤라또")) == "HEAD"
    qty = r.span("2개")
    assert top_role(qty) == "CONSTRAINT"
    assert qty.attach == {"type": "quantity", "anchor": 0}


def test_mixed_script_general_term_stays_ambiguous() -> None:
    r = analyzer(LOCAL).analyze("B2B마케팅")
    s = r.spans[0]
    assert s.resolved is None
    assert "ENTITY" in s.roles() and len(s.roles()) > 1


# --- schema / defaults ------------------------------------------------------------


def test_json_round_trip() -> None:
    r = analyzer(LOCAL).analyze("지금 영업중인 식당 찾아줘")
    data = json.loads(r.to_json())
    assert data["query"] == "지금 영업중인 식당 찾아줘"
    assert data["spans"][-1]["resolved"]["role"] == "COMMAND"
    assert data["spans"][0]["attach"] == {"type": "time", "anchor": "now"}


def test_package_defaults_are_domain_neutral() -> None:
    res = Analyzer().resources
    assert not res.lexicon.get("location")
    assert "점" not in res.lexicon.get("qualifier", {})
    assert not res.entities
