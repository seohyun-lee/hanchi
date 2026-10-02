"""M7: replaceable resolver / weighter backends, learned weights, calibration from data."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from typing import Any

import pytest

from hanchi import Analyzer
from hanchi.backends import make_weighter, register_weighter
from hanchi.cli import main as cli_main
from hanchi.evaluation import compare
from hanchi.learn import (
    Click,
    RoleLabel,
    read_clicks,
    role_prior_suggestions,
    sense_prior_from_clicks,
    synonym_candidates,
    write_sense_prior,
    write_synonym_review,
)
from hanchi.neural import LexicalWeighter
from hanchi.neural.bge_m3 import INSTALL_HINT, BgeM3Encoder
from hanchi.weights import RuleWeighter
from helpers import HOMONYMS

ROOT = Path(__file__).parent.parent
HAS_FLAG = importlib.util.find_spec("FlagEmbedding") is not None


class FakeEncoder:
    """Gives every subword of ``favorite`` weight 1.0 and everything else 0.1."""

    def __init__(self, favorite: str) -> None:
        self.favorite = favorite

    def token_weights(self, text: str) -> list[tuple[int, int, float]]:
        out = []
        for i, ch in enumerate(text):
            if not ch.isspace():
                start = text.find(self.favorite)
                inside = start >= 0 and start <= i < start + len(self.favorite)
                out.append((i, i + 1, 1.0 if inside else 0.1))
        return out


# --- backends ---------------------------------------------------------------------------


@pytest.mark.skipif(HAS_FLAG, reason="FlagEmbedding is installed")
def test_neural_backend_without_extra_gives_install_hint() -> None:
    import hanchi.neural  # noqa: F401  (importing must work without the extra)

    with pytest.raises(ImportError, match="hanchi\\[neural\\]"):
        make_weighter("bge-m3")
    assert "pip install" in INSTALL_HINT
    # and the default analyzer works
    assert Analyzer().analyze("센터").spans[0].top.weight == 1.0


def test_unknown_backend_name() -> None:
    with pytest.raises(ValueError, match="unknown weighter"):
        Analyzer(weighter="nope")


def test_bge_m3_encoder_maps_lexical_weights_to_offsets() -> None:
    class FakeModel:
        def encode(self, texts: list[str], **kw: Any) -> dict[str, Any]:
            return {"lexical_weights": [{"11": 0.2, "12": 0.9}]}

        def tokenizer(self, text: str, **kw: Any) -> dict[str, Any]:
            return {"input_ids": [11, 12, 13], "offset_mapping": [(0, 2), (3, 6), (6, 6)]}

    enc = BgeM3Encoder(_model=FakeModel())
    assert enc.token_weights("강남 방탈출") == [(0, 2, 0.2), (3, 6, 0.9)]


def test_lexical_weighter_reweights_spans() -> None:
    q = "강남 카페 라떼"
    rule = Analyzer(["preset:local"]).analyze(q)
    neural = Analyzer(["preset:local"], weighter=LexicalWeighter(FakeEncoder("라떼"))).analyze(q)
    ratio = lambda r: r.span("라떼").top.weight / r.span("강남").top.weight  # noqa: E731
    assert ratio(neural) > ratio(rule)
    # roles and probabilities are untouched: only weights change
    assert [(s.text, s.top.role) for s in neural.spans] == [
        (s.text, s.top.role) for s in rule.spans
    ]


def test_rule_weighter_is_the_default() -> None:
    assert type(Analyzer().weighter) is RuleWeighter


def test_backend_from_config_and_compare(tmp_path: Path) -> None:
    register_weighter("fake-latte", lambda: LexicalWeighter(FakeEncoder("라떼")))
    (tmp_path / "cases.tsv").write_text(
        "강남 카페\t강남 카페 라떼｜홍대 카페\t강남 카페 라떼\tplace\n", encoding="utf-8"
    )
    cfg = tmp_path / "eval.yaml"
    cfg.write_text("plugins: [preset:local]\ncases: [cases.tsv]\nweighter: fake-latte\n", "utf-8")
    a = Analyzer.from_config(cfg)
    assert isinstance(a.weighter, LexicalWeighter)
    reports = compare(cfg, ["rule", "fake-latte"])
    assert set(reports) == {"rule", "fake-latte"}
    assert all(r.rank_cases == 1 for r in reports.values())
    out = io.StringIO()
    import contextlib

    with contextlib.redirect_stdout(out):
        assert (
            cli_main(["eval", "-c", str(cfg), "--weighter", "rule", "--weighter", "fake-latte"])
            == 0
        )
    assert "fake-latte" in out.getvalue()


# --- calibration from clicks ------------------------------------------------------------


def test_sense_prior_from_clicks(tmp_path: Path) -> None:
    a = Analyzer([HOMONYMS])
    clicks = [
        Click("애플", "애플 주가 전망", 9),
        Click("애플", "사과 농장", 1),
        Click("배 수리", "배 수리 업체", 3),
    ]
    priors = {(p.variant, p.sense_id): p.prior for p in sense_prior_from_clicks(a, clicks)}
    assert priors[("애플", "apple_inc")] > priors[("애플", "apple_fruit")]
    assert priors[("애플", "apple_inc")] == pytest.approx(10 / 12, abs=1e-3)
    assert ("배", "ship") not in priors  # resolved in context: not a homonym there

    # with enough evidence the bare word resolves (9:1 gives p≈0.83 < τ=0.9; 49:1 does)
    strong = [Click("애플", "애플 주가 전망", 49), Click("애플", "사과 농장", 1)]
    plugin = tmp_path / "learned"
    write_sense_prior(plugin / "sense_prior.tsv", list(sense_prior_from_clicks(a, strong)))
    calibrated = Analyzer([HOMONYMS, str(plugin)]).analyze("애플").spans[0]
    assert calibrated.resolved is not None and calibrated.resolved.sense_id == "apple_inc"


def test_read_clicks_and_cli(tmp_path: Path) -> None:
    f = tmp_path / "clicks.tsv"
    f.write_text(
        "# q\tclicked\tcount\tvertical\n애플\t애플 주가 전망\t5\tweb\n애플\t사과 농장\n", "utf-8"
    )
    rows = read_clicks(f)
    assert rows[0] == Click("애플", "애플 주가 전망", 5.0, "web") and rows[1].count == 1.0
    out = io.StringIO()
    code = cli_main(
        ["learn", "sense-prior", "-p", HOMONYMS, "--clicks", str(f), "-o", str(tmp_path / "p.tsv")],
        out=out,
    )
    assert code == 0 and "apple_inc" in (tmp_path / "p.tsv").read_text("utf-8")


def test_role_prior_suggestions_move_toward_labels() -> None:
    a = Analyzer()
    labels = [RoleLabel("센터", "센터", "ENTITY", 10)]
    suggested = role_prior_suggestions(a, labels)
    current = a.resources.rules["priors"]
    assert suggested["ENTITY"] > current["ENTITY"]
    assert suggested["HEAD"] < current["HEAD"]


# --- synonym candidates (§12.7) ----------------------------------------------------------


def test_synonym_candidates_review_queue(tmp_path: Path) -> None:
    vectors = {"식당": [1.0, 0.0], "음식점": [0.98, 0.05], "카페": [0.0, 1.0]}
    cands = synonym_candidates(list(vectors), lambda ts: [vectors[t] for t in ts], 0.9, 10)
    assert [(c.a, c.b) for c in cands] == [("식당", "음식점")]
    md = write_synonym_review(tmp_path / "review.md", cands, "lexicon:head").read_text("utf-8")
    assert "| 식당 | 음식점 |" in md and "Nothing here is applied automatically" in md
