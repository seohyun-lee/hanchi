"""M6: dictgen pipeline with fixtures (no network), and a separate network test."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from hanchi import Analyzer
from hanchi.dictgen.names import clean
from hanchi.dictgen.pipeline import load_config, run
from hanchi.dictgen.sources import MissingKeyError, http_fetch
from hanchi.dictgen.sources.stdict import CACHE_MARKER, StdictChecker

FIX = Path(__file__).parent / "fixtures" / "dictgen"
ROOT = Path(__file__).parent.parent


class FakeFetch:
    """Serves fixture files; records every request."""

    def __init__(self, ftc_pages: list[str]) -> None:
        self.ftc_pages = ftc_pages
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, params: Mapping[str, str]) -> bytes:
        self.calls.append((url, dict(params)))
        if "stdict" in url:
            q = params["q"]
            f = FIX / f"stdict_{q}.json"
            return (f if f.is_file() else FIX / "stdict_empty.json").read_bytes()
        page = int(params["pageNo"])
        if page > len(self.ftc_pages):
            return b'{"totalCount": 0, "items": {"item": []}}'
        return (FIX / self.ftc_pages[page - 1]).read_bytes()


@pytest.fixture
def keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_GO_KR_KEY", "test-key")
    monkeypatch.setenv("STDICT_KEY", "test-key")


@pytest.fixture(scope="module")
def analyzer() -> Analyzer:
    return Analyzer()


def small_pages(tmp_path: Path) -> Path:
    cfg = tmp_path / "dictgen.yaml"
    cfg.write_text("ftc:\n  page_size: 3\n", encoding="utf-8")
    return cfg


# --- names -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "name", "aliases"),
    [
        ("㈜한빛치킨", "한빛치킨", []),
        ("주식회사 한빛치킨", "한빛치킨", []),
        ("별빛커피(STARLIGHT COFFEE)", "별빛커피", ["STARLIGHT COFFEE"]),
        ("누리 / NURI", "누리", ["NURI"]),
        ("한빛치킨(구 빛치킨)", "한빛치킨", []),
        ("(STARLIGHT)", "STARLIGHT", []),
    ],
)
def test_clean_names(raw: str, name: str, aliases: list[str]) -> None:
    c = clean(raw)
    assert (c.name, c.aliases) == (name, aliases)


# --- pipeline --------------------------------------------------------------------------


def test_diff_judge_write_report(tmp_path: Path, keys: None, analyzer: Analyzer) -> None:
    out = tmp_path / "plugin"
    (out / "entities").mkdir(parents=True)
    (out / "entities" / "manual.tsv").write_text("누리\t누리\tbrand\n", encoding="utf-8")
    fetch = FakeFetch(["ftc_page1.json", "ftc_page2.json"])
    [res] = run(
        ["ftc"],
        out,
        analyzer,
        config=small_pages(tmp_path),
        fetch=fetch,
        stdict_cache=tmp_path / "cache",
    )
    decisions = {c.name: c.decision for c in res.candidates}
    assert decisions == {
        "한빛치킨": "approved",  # FTC registered
        "별빛커피": "approved",
        "사과": "held",  # common dictionary noun
        "누리": "existing",  # already in the plugin
        "가": "review",  # too short
    }
    entities = (out / "entities" / "ftc_brands.tsv").read_text(encoding="utf-8")
    assert "한빛치킨\t한빛치킨\tbrand\tftc" in entities
    assert "STARLIGHT COFFEE\t별빛커피\tbrand\tftc" in entities  # bilingual alias
    assert "사과" not in entities
    assert "가\t" in (out / "review" / "ftc_review.tsv").read_text(encoding="utf-8")
    assert "사과" in (out / "review" / "ftc_held.tsv").read_text(encoding="utf-8")
    report = res.report.read_text(encoding="utf-8")
    assert "approved (written to entities): 2" in report and "## Review queue" in report
    # paging: two FTC pages requested
    assert sum("stdict" not in u for u, _ in fetch.calls) == 2

    # the generated plugin works as a plugin
    a = Analyzer([str(out)])
    assert a.analyze("한빛치킨 메뉴").span("한빛치킨").top.role == "ENTITY"
    assert a.analyze("starlight coffee").spans[0].top.sense_id == "별빛커피"


def test_second_run_since_last(tmp_path: Path, keys: None, analyzer: Analyzer) -> None:
    out = tmp_path / "plugin"
    cfg = small_pages(tmp_path)
    run(
        ["ftc"],
        out,
        analyzer,
        config=cfg,
        fetch=FakeFetch(["ftc_page1.json", "ftc_page2.json"]),
        stdict_cache=tmp_path / "cache",
    )
    [res] = run(
        ["ftc"],
        out,
        analyzer,
        config=cfg,
        fetch=FakeFetch(["ftc_page1_second_run.json"]),
        since_last=True,
        stdict_cache=tmp_path / "cache",
    )
    decisions = {c.name: c.decision for c in res.candidates}
    assert decisions["새봄베이커리"] == "approved"
    assert decisions["한빛치킨"] == "existing"  # approved in the earlier run
    assert set(res.removed) == {"별빛커피", "누리", "가"}
    entities = (out / "entities" / "ftc_brands.tsv").read_text(encoding="utf-8")
    assert "별빛커피" in entities  # never deleted automatically
    assert "No longer listed" in res.report.read_text(encoding="utf-8")


def test_stdict_cache_is_reused(tmp_path: Path) -> None:
    fetch = FakeFetch([])
    checker = StdictChecker(load_config()["stdict"], "k", fetch, tmp_path / "cache")
    assert checker.is_common_word("사과") and not checker.is_common_word("한빛치킨")
    assert checker.is_common_word("사과")
    assert sum("stdict" in u for u, _ in fetch.calls) == 2  # third call served from cache
    record = json.loads(next((tmp_path / "cache").glob("*.json")).read_text(encoding="utf-8"))
    assert record["marker"] == CACHE_MARKER
    assert record["license"] == "CC BY-SA 2.0 KR" and "stdict.korean.go.kr" in record["source"]


def test_missing_keys_give_a_helpful_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, analyzer: Analyzer
) -> None:
    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    monkeypatch.delenv("STDICT_KEY", raising=False)
    with pytest.raises(MissingKeyError, match="STDICT_KEY"):
        run(["ftc"], tmp_path, analyzer, fetch=FakeFetch([]))
    with pytest.raises(MissingKeyError, match="DATA_GO_KR_KEY"):
        run(["ftc"], tmp_path, analyzer, check_stdict=False, fetch=FakeFetch([]))
    with pytest.raises(ValueError, match="unknown or unavailable source"):
        monkeypatch.setenv("DATA_GO_KR_KEY", "k")
        run(["sbiz"], tmp_path, analyzer, check_stdict=False, fetch=FakeFetch([]))


def test_cli_reports_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from hanchi.cli import main

    monkeypatch.delenv("DATA_GO_KR_KEY", raising=False)
    assert main(["dictgen", "run", "--no-stdict", "-o", str(tmp_path)]) == 2
    assert "DATA_GO_KR_KEY" in capsys.readouterr().err


# --- NIKL dictionary data never reaches outputs or the repository ----------------------


def test_dictionary_text_does_not_leak_into_outputs(
    tmp_path: Path, keys: None, analyzer: Analyzer
) -> None:
    out = tmp_path / "plugin"
    run(
        ["ftc"],
        out,
        analyzer,
        config=small_pages(tmp_path),
        write_idf=True,
        fetch=FakeFetch(["ftc_page1.json", "ftc_page2.json"]),
        stdict_cache=tmp_path / "cache",
    )
    for f in out.rglob("*"):
        if f.is_file():
            text = f.read_text(encoding="utf-8")
            assert "LEAK_MARKER_DEFINITION" not in text, f
            assert CACHE_MARKER not in text, f
    assert not (out / "cache").exists()


def test_repository_contains_no_dictionary_cache() -> None:
    files = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.split()
    if not files:
        pytest.skip("not a git checkout")
    marker = CACHE_MARKER.encode()
    for name in files:
        path = ROOT / name
        if path.is_file() and path.suffix in (".json", ".tsv", ".txt", ".md", ".yaml"):
            assert marker not in path.read_bytes(), name


# --- live API (excluded by default; run with: pytest -m network) -----------------------


@pytest.mark.network
def test_live_ftc_and_stdict(tmp_path: Path, analyzer: Analyzer) -> None:
    if not os.environ.get("DATA_GO_KR_KEY") or not os.environ.get("STDICT_KEY"):
        pytest.skip("DATA_GO_KR_KEY / STDICT_KEY not set")
    cfg = tmp_path / "dictgen.yaml"
    cfg.write_text("ftc:\n  page_size: 20\n  max_pages: 1\n", encoding="utf-8")
    [res] = run(
        ["ftc"],
        tmp_path / "plugin",
        analyzer,
        config=cfg,
        fetch=http_fetch(20, 1, "hanchi-test"),
        stdict_cache=tmp_path / "cache",
    )
    assert res.candidates, "no items parsed: check ftc.url / items_path / fields in dictgen.yaml"
