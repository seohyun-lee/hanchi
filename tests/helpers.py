"""Shared helpers: analyzers with ad-hoc entity dictionaries, cached per configuration."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hanchi import Analyzer

FIXTURES = Path(__file__).parent / "fixtures" / "plugins"
HOMONYMS = str(FIXTURES / "homonyms")
WEB_PRIOR = str(FIXTURES / "web_prior")

_cache: dict[tuple[tuple[str, ...], tuple[tuple[str, str], ...]], Analyzer] = {}


def entity_plugin(entities: tuple[tuple[str, str], ...]) -> str:
    """A throwaway plugin directory holding ``(name, type)`` entities."""
    d = Path(tempfile.mkdtemp(prefix="hanchi-test-"))
    (d / "entities").mkdir()
    rows = [f"{name}\t{name}\t{typ}\ttest\t1.0" for name, typ in entities]
    (d / "entities" / "test.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return str(d)


def analyzer(*plugins: str, entities: tuple[tuple[str, str], ...] = ()) -> Analyzer:
    key = (plugins, entities)
    if key not in _cache:
        specs = list(plugins) + ([entity_plugin(entities)] if entities else [])
        _cache[key] = Analyzer(specs)
    return _cache[key]
