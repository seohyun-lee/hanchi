"""M3: plugins, aliases (§12.2), overrides, priority, mixed-script names (§13)."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from hanchi import Analyzer
from hanchi.resources import AliasWarning
from helpers import FIXTURES, HOMONYMS, analyzer

LOCAL = "preset:local"
FOOD = str(FIXTURES / "food")


def write_plugin(root: Path, files: dict[str, str]) -> str:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return str(root)


def roles_of(r: object) -> list[tuple[str, str]]:
    return [(s.norm, s.top.role) for s in r.spans]  # type: ignore[attr-defined]


# --- M3 completion criteria --------------------------------------------------------


def test_alias_maps_variant_spelling_to_entity(tmp_path: Path) -> None:
    plugin = write_plugin(
        tmp_path,
        {
            "entities/places.tsv": "센터필드\t센터필드\tbuilding\n",
            "aliases.tsv": "센타필드\t센터필드\n",
        },
    )
    r = Analyzer([LOCAL, plugin]).analyze("강남 센타필드")
    span = r.span("센타필드")
    assert span.canonical == "센터필드"
    assert span.resolved is not None and span.resolved.role == "ENTITY"
    assert any(e.startswith("entity_dict:alias") for e in span.resolved.evidence)


def test_mixed_script_brand_with_branch(tmp_path: Path) -> None:
    plugin = write_plugin(tmp_path, {"entities/brands.tsv": "GS25\tGS25\tbrand\n"})
    r = Analyzer([LOCAL, plugin]).analyze("GS25역삼점")
    assert [s.text for s in r.spans] == ["GS25", "역삼", "점"]
    assert roles_of(r) == [("gs25", "ENTITY"), ("역삼", "LOCATION"), ("점", "QUALIFIER")]
    assert r.spans[0].resolved is not None


def test_variant_branch_marker(tmp_path: Path) -> None:
    plugin = write_plugin(tmp_path, {"entities/brands.tsv": "스타벅스\t스타벅스\tbrand\n"})
    r = Analyzer([LOCAL, plugin]).analyze("스타벅스강남R점")
    assert [s.text for s in r.spans] == ["스타벅스", "강남", "R점"]
    assert roles_of(r) == [("스타벅스", "ENTITY"), ("강남", "LOCATION"), ("r점", "QUALIFIER")]


def test_role_override_beats_resolver(tmp_path: Path) -> None:
    plugin = write_plugin(tmp_path, {"overrides.tsv": "찾아줘\trole\tENTITY\tstore name\n"})
    r = Analyzer([plugin]).analyze("강남역 카페 찾아줘")
    span = r.span("찾아줘")
    assert span.resolved is not None and span.resolved.role == "ENTITY"
    assert span.resolved.p == 1.0
    assert span.resolved.evidence == ["override:store name"]


def test_override_file_given_to_analyzer(tmp_path: Path) -> None:
    f = tmp_path / "hotfix.tsv"
    f.write_text("강남\trole\tENTITY\thotfix\n", encoding="utf-8")
    r = Analyzer([LOCAL], overrides=[f]).analyze("강남 카페")
    assert r.span("강남").resolved is not None
    assert r.span("강남").resolved.role == "ENTITY"  # type: ignore[union-attr]


def test_split_and_keep_overrides(tmp_path: Path) -> None:
    plugin = write_plugin(
        tmp_path, {"overrides.tsv": "센터필드\tsplit\t센터 필드\n방탈출\tkeep\t\n"}
    )
    a = Analyzer([plugin])
    assert [s.norm for s in a.analyze("센터필드").spans] == ["센터", "필드"]
    assert [s.norm for s in a.analyze("방탈출").spans] == ["방탈출"]
    assert [s.norm for s in Analyzer().analyze("방탈출").spans] == ["방", "탈출"]


def test_regex_override(tmp_path: Path) -> None:
    plugin = write_plugin(tmp_path, {"overrides.tsv": "re:\\d+호선\trole\tLOCATION\tsubway\n"})
    r = Analyzer([plugin]).analyze("2호선 막차")
    assert r.span("2호선").top.role == "LOCATION"


# --- priority: overrides > user plugin > preset > package default -------------------


def test_priority_of_yaml_settings(tmp_path: Path) -> None:
    user = write_plugin(
        tmp_path,
        {"roles.yaml": "weights:\n  HEAD: 0.9\n", "rules.yaml": "threshold: 0.5\n"},
    )
    a = Analyzer([LOCAL, user])
    weights = a.resources.roles["weights"]
    assert weights["HEAD"] == 0.9  # user plugin
    assert weights["LOCATION"] == 0.7  # preset (untouched by user)
    assert weights["ENTITY"] == 1.0  # package default
    assert a.resources.setting("threshold") == 0.5
    assert a.resources.feature("COMMAND", "request_clause_final") == 3.0  # default kept
    assert a.analyze("강남 카페").span("강남").resolved is not None


def test_later_plugin_wins(tmp_path: Path) -> None:
    first = write_plugin(tmp_path / "a", {"roles.yaml": "weights:\n  HEAD: 0.2\n"})
    second = write_plugin(tmp_path / "b", {"roles.yaml": "weights:\n  HEAD: 0.4\n"})
    assert Analyzer([first, second]).resources.roles["weights"]["HEAD"] == 0.4
    assert Analyzer([second, first]).resources.roles["weights"]["HEAD"] == 0.2


def test_user_plugin_removes_preset_entries(tmp_path: Path) -> None:
    user = write_plugin(
        tmp_path,
        {
            "lexicon/qualifier.txt": "-센터\n",
            "lexicon/location.txt": "-강남\n목동\n",
        },
    )
    res = Analyzer([LOCAL, user]).resources
    assert not res.in_lexicon("qualifier", "센터")
    assert res.in_lexicon("qualifier", "점")
    assert not res.in_lexicon("location", "강남")
    assert res.in_lexicon("location", "목동")


def test_entity_removal_and_sense_prior_override(tmp_path: Path) -> None:
    base = write_plugin(
        tmp_path / "base",
        {
            "entities/x.tsv": "센터필드\t센터필드\tbuilding\n",
            "sense_prior.tsv": "애플\tapple_inc\t0.9\n",
        },
    )
    user = write_plugin(
        tmp_path / "user",
        {"entities/x.tsv": "-센터필드\n", "sense_prior.tsv": "애플\tapple_inc\t0.2\n"},
    )
    res = Analyzer([HOMONYMS, base, user]).resources
    assert "센터필드" not in res.entities
    assert res.prior_of("애플", "apple_inc", None) == 0.2


def test_override_beats_user_plugin_lexicon(tmp_path: Path) -> None:
    user = write_plugin(
        tmp_path / "u", {"lexicon/location.txt": "카페\n", "overrides.tsv": "카페\trole\tHEAD\t\n"}
    )
    r = Analyzer([user]).analyze("강남 카페")
    assert r.span("카페").resolved is not None and r.span("카페").resolved.role == "HEAD"  # type: ignore[union-attr]


def test_from_config(tmp_path: Path) -> None:
    write_plugin(tmp_path / "my_domain", {"entities/e.tsv": "센터필드\t센터필드\tbuilding\n"})
    (tmp_path / "hotfix.tsv").write_text("카페\trole\tENTITY\t\n", encoding="utf-8")
    cfg = tmp_path / "hanchi.yaml"
    cfg.write_text(
        "plugins: [preset:local, ./my_domain]\noverrides: [./hotfix.tsv]\nexplain: true\n",
        encoding="utf-8",
    )
    a = Analyzer.from_config(cfg)
    r = a.analyze("강남 센터필드 카페")
    assert r.explain is not None
    assert r.span("센터필드").top.role == "ENTITY"
    assert r.span("카페").top.role == "ENTITY"
    assert r.span("강남").top.role == "LOCATION"


# --- §12.2 alias model --------------------------------------------------------------


def test_ambiguous_variant_never_bridges_senses(tmp_path: Path) -> None:
    user = write_plugin(tmp_path, {"aliases.tsv": "배즙\t배\n"})
    with pytest.warns(AliasWarning, match="ambiguous"):
        res = Analyzer([HOMONYMS, user]).resources
    assert set(res.aliases["배"]) == {"pear", "ship", "belly"}
    assert "배즙" not in res.aliases
    assert res.warnings


def test_unambiguous_variant_chain(tmp_path: Path) -> None:
    user = write_plugin(
        tmp_path,
        {
            "senses.tsv": "starbucks\t스타벅스\tENTITY\tcafe_brand\n",
            "aliases.tsv": "스타벅스\tstarbucks\n스벅\t스타벅스\n",
        },
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", AliasWarning)
        res = Analyzer([user]).resources
    assert set(res.aliases["스벅"]) == {"starbucks"}
    r = Analyzer([user]).analyze("스벅")
    assert r.spans[0].canonical == "스타벅스"


def test_one_variant_many_senses_is_allowed() -> None:
    res = Analyzer([HOMONYMS]).resources
    assert set(res.aliases["애플"]) == {"apple_inc", "apple_fruit"}
    assert res.senses["apple_inc"].canonical == "애플"


def test_unknown_alias_target_is_an_error(tmp_path: Path) -> None:
    user = write_plugin(tmp_path, {"aliases.tsv": "뭔가\t없는대상\n"})
    with pytest.raises(ValueError, match="unknown"):
        Analyzer([user])


# --- §12.5 expansion ----------------------------------------------------------------


def test_expand_synonym_and_hierarchy() -> None:
    a = analyzer(FOOD)
    restaurant = {e.term: e for e in a.expand(a.analyze("식당"))}
    assert restaurant["음식점"].relation == "synonym" and restaurant["음식점"].weight == 0.95
    assert restaurant["맛집"].relation == "hypernym" and restaurant["맛집"].weight == 0.4
    hot = {e.term: e for e in a.expand(a.analyze("맛집"))}
    assert hot["식당"].relation == "hyponym" and hot["식당"].weight == 0.7


def test_ambiguous_span_is_not_expanded() -> None:
    a = analyzer(HOMONYMS)
    assert a.expand(a.analyze("배")) == []


# --- §13 mixed-script names, with and without a dictionary ---------------------------

MIXED = (("연세365의원", "clinic"), ("123젤라또", "store"), ("GLE어학원", "academy"))


@pytest.fixture(params=["no_dict", "dict"])
def mixed(request: pytest.FixtureRequest) -> Analyzer:
    return analyzer(LOCAL, entities=MIXED if request.param == "dict" else ())


def test_13_5_single_word_names(mixed: Analyzer) -> None:
    for q in ("연세365의원", "123젤라또", "GLE어학원", "gle어학원", "365의원"):
        r = mixed.analyze(q)
        assert len(r.spans) == 1, q
        assert r.spans[0].top.role == "ENTITY", q
    s = mixed.analyze("연세365의원").spans[0]
    assert s.parts is not None and [p.norm for p in s.parts] == ["연세", "365", "의원"]
    assert mixed.analyze("gle어학원").spans[0].text == "gle어학원"


@pytest.mark.parametrize("query", ["123 젤라또", "GLE 어학원"])
def test_13_5_spaced_names_keep_both_readings(mixed: Analyzer, query: str) -> None:
    r = mixed.analyze(query)
    merged = [it for it in r.interpretations if [m["text"] for m in it.merges] == [query]]
    split = [it for it in r.interpretations if not it.merges]
    assert merged and split
    assert merged[0].spans[0].top.role == "ENTITY"


def test_13_5_quantity_and_general_term(mixed: Analyzer) -> None:
    r = mixed.analyze("젤라또 2개")
    assert roles_of(r) == [("젤라또", "HEAD"), ("2개", "CONSTRAINT")]
    b2b = mixed.analyze("B2B마케팅").spans[0]
    assert b2b.resolved is None and "ENTITY" in b2b.roles()


@pytest.mark.parametrize("query", ["GLE어학원 대치점", "GLE어학원대치점"])
def test_13_3_branch_after_name(mixed: Analyzer, query: str) -> None:
    r = mixed.analyze(query)
    assert roles_of(r) == [("gle어학원", "ENTITY"), ("대치", "LOCATION"), ("점", "QUALIFIER")]


def test_13_3_unknown_branch_location_is_guessed() -> None:
    r = analyzer(LOCAL).analyze("GLE어학원 목동점")
    loc = r.span("목동").hypothesis("LOCATION")
    assert loc is not None and "rule:name+X+qualifier" in loc.evidence
    assert r.span("점").top.role == "QUALIFIER"


def test_names_that_read_as_predicates_are_not_registered_with_kiwi() -> None:
    a = analyzer(entities=(("안나와", "store"), ("센터필드", "building"), ("GLE어학원", "academy")))
    assert a.pack.backend.user_words == frozenset({"센터필드"})


def test_example_config_and_template_load() -> None:
    root = Path(__file__).parent.parent / "examples"
    a = Analyzer.from_config(root / "hanchi.yaml")
    r = a.analyze("충전 어댑터")
    assert r.spans[0].canonical == "충전기"
    assert not a.resources.in_lexicon("head", "필름")  # removed by the template
