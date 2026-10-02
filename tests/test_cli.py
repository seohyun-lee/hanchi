"""M5: CLI, batch analysis, dictionary export."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from hanchi import Analyzer
from hanchi.cli import main
from hanchi.lang.ko import KiwiBackend
from hanchi.lang.ko.export import NORI_FILE, export, nori_entries
from helpers import FIXTURES, analyzer

LOCAL = "preset:local"
EVAL_PLUGIN = str(Path(__file__).parent.parent / "eval" / "plugin")


def run(*args: str, stdin: str = "") -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(args), out=out, inp=io.StringIO(stdin))
    return code, out.getvalue()


# --- smoke tests ---------------------------------------------------------------------


def test_analyze_table_has_clause_attach_and_signal_columns() -> None:
    code, out = run("analyze", "-p", LOCAL, "주변 강남 방탈출 찾아줘 왜 안나와")
    assert code == 0
    header = out.splitlines()[1]
    for col in ("clause", "role (p)", "sense/type", "weight", "attach"):
        assert col in header
    assert "proximity→강남" in out
    assert "signal: dissatisfaction '왜 안나와'" in out
    assert "COMMAND*" in out


def test_analyze_json() -> None:
    code, out = run("analyze", "--json", "-p", LOCAL, "지금 영업중인 식당 찾아줘")
    data = json.loads(out)
    assert code == 0 and data["spans"][-1]["resolved"]["role"] == "COMMAND"


def test_analyze_context_file(tmp_path: Path) -> None:
    ctx = tmp_path / "prev.json"
    ctx.write_text(
        json.dumps({"prev_query": "강남 방탈출 찾아줘", "prev_result_count": 0}), encoding="utf-8"
    )
    _, out = run(
        "analyze",
        "--json",
        "--explain",
        "-p",
        LOCAL,
        "--context",
        str(ctx),
        "강남 방탈출 찾아줘 왜 안나와",
    )
    assert "context:prev_query_no_result" in out


def test_analyze_stdin_batch_json_lines() -> None:
    code, out = run("analyze", "--json", "-w", "2", stdin="강남 카페\n\n아이폰 케이스\n")
    lines = out.strip().splitlines()
    assert code == 0 and [json.loads(x)["query"] for x in lines] == ["강남 카페", "아이폰 케이스"]


def test_analyze_with_config(tmp_path: Path) -> None:
    (tmp_path / "hanchi.yaml").write_text("plugins: [preset:local]\n", encoding="utf-8")
    _, out = run("analyze", "--config", str(tmp_path / "hanchi.yaml"), "--json", "강남 카페")
    assert json.loads(out)["spans"][0]["hypotheses"][0]["role"] == "LOCATION"


def test_rank_with_candidate_file(tmp_path: Path) -> None:
    f = tmp_path / "cands.txt"
    f.write_text(
        '홍대 카페\n# comment\n{"name": "강남 카페 라떼", "category": "카페"}\n', encoding="utf-8"
    )
    code, out = run("rank", "-p", LOCAL, "강남 카페", "-c", str(f))
    assert code == 0
    first = next(line for line in out.splitlines() if line.startswith("1 "))
    assert "강남 카페 라떼" in first and "mode=strict" in out
    _, js = run("rank", "-p", LOCAL, "강남 카페", "-c", str(f), "--json")
    assert json.loads(js)["results"][0]["name"] == "강남 카페 라떼"


def test_expand() -> None:
    _, out = run("expand", "-p", str(FIXTURES / "food"), "식당")
    assert "음식점" in out and "synonym" in out


def test_repl_session() -> None:
    script = ":help\n강남 카페\n:rank 강남 카페 라떼｜홍대 카페\n:json\n찾아줘\n:q\n"
    code, out = run("repl", "-p", LOCAL, stdin=script)
    assert code == 0
    assert ":rank" in out and "1. 강남 카페 라떼" in out
    assert '"query": "찾아줘"' in out


def test_no_command_prints_help() -> None:
    code, out = run()
    assert code == 0 and "usage: hanchi" in out


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--version"])
    assert "hanchi" in capsys.readouterr().out


# --- batch ---------------------------------------------------------------------------


def test_analyze_batch_matches_sequential() -> None:
    a = analyzer(LOCAL, EVAL_PLUGIN)
    texts = [
        "강남 방탈출 찾아줘",
        "아이유 노래 틀어줘",
        "애플 매장",
        "GS25역삼점",
        "지금 영업중인 식당 찾아줘",
        "배 1박스",
        "연세365의원",
        "서울 날씨 어때",
        "나를 찾아줘",
        "젤라또 2개",
    ] * 3
    seq = [r.to_dict() for r in a.analyze_batch(texts, workers=1)]
    par = [r.to_dict() for r in a.analyze_batch(texts, workers=4)]
    assert par == seq


# --- dictionary export -----------------------------------------------------------------


def test_nori_export_format(tmp_path: Path) -> None:
    a = analyzer(LOCAL, EVAL_PLUGIN)
    path = export(a, "nori", tmp_path)
    assert path.name == NORI_FILE
    rows = {
        line.split()[0]: line.split()[1:]
        for line in path.read_text("utf-8").splitlines()
        if line and not line.startswith("#")
    }
    # compound proper names: no decomposition
    for name in ("센터필드", "서울대병원", "롯데월드타워", "gs25", "나를찾아줘", "애플파이"):
        assert rows[name] == [], name
    # compound category words: word + parts
    assert rows["서비스센터"] == ["서비스", "센터"]
    assert all(" " not in r[0] for r in nori_entries(a))


def test_kiwi_export_reloads_to_identical_analysis(tmp_path: Path) -> None:
    a = Analyzer([LOCAL, EVAL_PLUGIN])
    path = export(a, "kiwi", tmp_path)
    fresh = KiwiBackend()
    assert fresh.load_user_dictionary(path) == len(a.pack.backend.user_words)
    assert fresh.user_words == a.pack.backend.user_words
    for q in (
        "강남 센터필드",
        "서울대병원 강남센터",
        "롯데월드타워 전망대",
        "아이유 콘서트",
        "스벅",
    ):
        got = [(m.form, m.tag) for m in fresh.tokenize(q)]
        want = [(m.form, m.tag) for m in a.pack.backend.tokenize(q)]
        assert got == want, q


def test_dict_export_cli(tmp_path: Path) -> None:
    code, out = run("dict", "export", "--format", "nori", "-o", str(tmp_path), "-p", EVAL_PLUGIN)
    assert code == 0 and "wrote" in out and (tmp_path / NORI_FILE).is_file()
