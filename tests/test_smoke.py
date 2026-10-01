from __future__ import annotations

import re
from importlib.metadata import version

import pytest

import hanchi
from hanchi.cli import main


def _release_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def test_package_imports_with_version() -> None:
    assert hanchi.__version__ == version("hanchi")


def test_kiwipiepy_is_apache_licensed_release() -> None:
    # kiwipiepy <= 0.23.2 is LGPL; only >= 0.24.0 may be used.
    assert _release_tuple(version("kiwipiepy")) >= (0, 24, 0)


def test_kiwi_backend_loads() -> None:
    from kiwipiepy import Kiwi

    tokens = Kiwi().tokenize("한국어 검색어")
    assert [t.form for t in tokens]


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"hanchi {hanchi.__version__}"


def test_cli_without_args_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "usage: hanchi" in capsys.readouterr().out
