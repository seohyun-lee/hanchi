"""M4: evaluation harness, external case files, CI regression against the baseline."""

from __future__ import annotations

import json
from pathlib import Path

from hanchi.cli import main as cli_main
from hanchi.config import load_yaml
from hanchi.evaluation import evaluate, load_cases, run_config

ROOT = Path(__file__).parent.parent
EVAL = ROOT / "eval"


def test_tsv_and_jsonl_loaders(tmp_path: Path) -> None:
    (tmp_path / "cases.tsv").write_text(
        "# comment\n강남 센터\t강남 센터필드｜강남 스포츠센터\t강남 센터필드\tplace: x\n",
        encoding="utf-8",
    )
    (tmp_path / "cases.jsonl").write_text(
        json.dumps(
            {
                "query": "q",
                "candidates": [{"name": "a"}],
                "expected_top1": ["a", "b"],
                "entities": [["a", "store"]],
                "plugins": ["preset:local", "./p"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    tsv = load_cases(tmp_path / "cases.tsv", "rank")
    assert tsv[0].candidates == ["강남 센터필드", "강남 스포츠센터"]
    assert tsv[0].domain == "place"
    js = load_cases(tmp_path / "cases.jsonl", "rank")[0]
    assert js.expected == ["a", "b"] and js.entities == [("a", "store")]
    assert js.plugins[0] == "preset:local" and js.plugins[1] == str((tmp_path / "p").resolve())


def test_metrics_on_a_small_set(tmp_path: Path) -> None:
    (tmp_path / "cases.tsv").write_text(
        "아이폰 케이스\t아이폰 케이스｜갤럭시 케이스\t아이폰 케이스\tcommerce\n"
        "아이폰 케이스\t아이폰 케이스｜갤럭시 케이스\t갤럭시 케이스\tcommerce: wrong on purpose\n",
        encoding="utf-8",
    )
    (tmp_path / "roles.tsv").write_text("강남역 카페 찾아줘\t찾아줘\tCOMMAND\t\n", encoding="utf-8")
    cases = load_cases(tmp_path / "cases.tsv", "rank") + load_cases(tmp_path / "roles.tsv", "role")
    report = evaluate(cases, ["preset:commerce"])
    assert report.rank_cases == 2 and report.hit_at_1 == 0.5
    assert report.mrr == 0.75
    assert report.role_accuracy == 1.0
    assert len(report.failures) == 1


def test_external_eval_config_through_cli(tmp_path: Path, capsys: object) -> None:
    plugin = tmp_path / "my_plugin"
    (plugin / "entities").mkdir(parents=True)
    (plugin / "entities" / "e.tsv").write_text("센터필드\t센터필드\tbuilding\n", encoding="utf-8")
    (tmp_path / "cases.tsv").write_text(
        "강남 센터\t강남 스포츠센터｜강남 센터필드\t강남 센터필드\tplace\n", encoding="utf-8"
    )
    (tmp_path / "hanchi.yaml").write_text(
        "plugins: [preset:local, ./my_plugin]\ncases: [cases.tsv]\n", encoding="utf-8"
    )
    code = cli_main(["eval", "-c", str(tmp_path / "hanchi.yaml"), "--json", "--min-hit1", "1.0"])
    assert code == 0
    assert json.loads(capsys.readouterr().out)["hit@1"] == 1.0  # type: ignore[attr-defined]
    assert cli_main(["eval", "-c", str(tmp_path / "hanchi.yaml"), "--min-hit1", "1.1"]) == 1


def test_public_eval_set_meets_baseline() -> None:
    cases = load_cases(EVAL / "cases.tsv", "rank") + load_cases(EVAL / "cases.jsonl", "rank")
    assert len(cases) >= 50
    domains = {c.domain for c in cases}
    assert {"web", "commerce", "place", "person", "command"} <= domains

    report = run_config(EVAL / "hanchi.yaml")
    baseline = load_yaml(EVAL / "baseline.yaml")
    metrics = report.metrics()
    for name, minimum in baseline.items():
        assert metrics[name] >= minimum, (
            f"{name} {metrics[name]} < baseline {minimum}\n{report.summary()}"
        )
