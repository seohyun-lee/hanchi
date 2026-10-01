"""Plugin directories → in-memory resources (dictionaries, lexicons, settings).

Load order is the priority order: the package default plugin first, then each plugin
given by the caller (later wins on conflicts). A plugin is a directory, or
``preset:<name>`` for one of the presets shipped in :mod:`hanchi.presets`.

Plugin layout (every file optional)::

    roles.yaml            role base weights
    rules.yaml            resolver feature weights, thresholds, interpretation settings
    entities/*.tsv        name \\t canonical \\t type \\t source \\t score
    lexicon/<name>.txt    one term per line            (name: head, qualifier, command,
    lexicon/<name>.tsv    term \\t type                  constraint, location, meta, unit)
    senses.tsv            sense_id \\t canonical \\t role \\t type \\t note
    aliases.tsv           variant \\t sense_id \\t score
    compat.tsv            type_a \\t type_b \\t score
    sense_prior.tsv       variant \\t sense_id \\t prior [\\t vertical]
    idf.tsv               token \\t idf
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from hanchi.config import deep_merge, load_yaml

PRESET_PREFIX = "preset:"


@dataclass(frozen=True)
class EntityEntry:
    name: str
    canonical: str
    type: str | None
    source: str
    score: float


@dataclass(frozen=True)
class Sense:
    sense_id: str
    canonical: str
    role: str
    type: str | None


@dataclass
class Resources:
    key: Callable[[str], str]
    """Normalizes a dictionary term into a lookup key (same rules as queries, no spaces)."""
    roles: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    lexicon: dict[str, dict[str, str | None]] = field(default_factory=lambda: defaultdict(dict))
    entities: dict[str, list[EntityEntry]] = field(default_factory=lambda: defaultdict(list))
    senses: dict[str, Sense] = field(default_factory=dict)
    aliases: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    compat: dict[tuple[str, str], float] = field(default_factory=dict)
    sense_prior: dict[tuple[str, str, str], float] = field(default_factory=dict)
    idf: dict[str, float] = field(default_factory=dict)
    plugin_dirs: list[Path] = field(default_factory=list)
    _prefixes: dict[str, set[str]] | None = None

    # --- lookups -----------------------------------------------------------------

    def in_lexicon(self, name: str, key: str) -> bool:
        return key in self.lexicon.get(name, {})

    def lexicon_type(self, name: str, key: str) -> str | None:
        return self.lexicon.get(name, {}).get(key)

    def lexicons_of(self, key: str) -> list[str]:
        return [name for name, terms in self.lexicon.items() if key in terms]

    def entity_keys_with_prefix(self, key: str) -> set[str]:
        if self._prefixes is None:
            index: dict[str, set[str]] = defaultdict(set)
            for k in self.entities:
                for i in range(1, len(k)):
                    index[k[:i]].add(k)
            self._prefixes = dict(index)
        return self._prefixes.get(key, set())

    def entity_keys_containing(self, key: str) -> Iterator[str]:
        """Entity keys containing ``key`` somewhere other than at the start."""
        for k in self.entities:
            if len(k) > len(key) and key in k[1:]:
                yield k

    def senses_of(self, key: str) -> list[tuple[Sense, float]]:
        return [(self.senses[sid], s) for sid, s in self.aliases.get(key, {}).items()]

    def compat_score(self, a: str, b: str) -> float:
        return self.compat.get((a, b), self.compat.get((b, a), 0.0))

    def prior_of(self, key: str, sense_id: str, vertical: str | None) -> float | None:
        if vertical:
            hit = self.sense_prior.get((key, sense_id, vertical))
            if hit is not None:
                return hit
        return self.sense_prior.get((key, sense_id, ""))

    def has_vertical_prior(self, key: str, sense_id: str, vertical: str | None) -> bool:
        return bool(vertical) and (key, sense_id, vertical) in self.sense_prior

    def idf_norm(self, key: str) -> float | None:
        if not self.idf or key not in self.idf:
            return None
        top = max(self.idf.values())
        return self.idf[key] / top if top > 0 else None

    def setting(self, *path: str) -> Any:
        node: Any = self.rules
        for p in path:
            if not isinstance(node, dict) or p not in node:
                raise KeyError("rules.yaml: missing setting " + ".".join(path))
            node = node[p]
        return node

    def feature(self, role: str, name: str) -> float:
        return float(self.rules.get("features", {}).get(role, {}).get(name, 0.0))


# --- loading -------------------------------------------------------------------


def default_plugin_dir() -> Path:
    return Path(str(importlib_resources.files("hanchi") / "data" / "default"))


def resolve_plugin(spec: str | Path) -> Path:
    s = str(spec)
    if s.startswith(PRESET_PREFIX):
        name = s[len(PRESET_PREFIX) :]
        path = Path(str(importlib_resources.files("hanchi") / "presets" / name))
    else:
        path = Path(s).expanduser()
    if not path.is_dir():
        raise FileNotFoundError(f"plugin directory not found: {spec}")
    return path


def _rows(path: Path) -> Iterator[list[str]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            yield [c.strip() for c in line.split("\t")]


def _col(row: Sequence[str], i: int) -> str | None:
    return row[i] if len(row) > i and row[i] else None


def load_resources(
    plugins: Iterable[str | Path], key: Callable[[str], str], include_default: bool = True
) -> Resources:
    res = Resources(key=key)
    dirs = [default_plugin_dir()] if include_default else []
    dirs += [resolve_plugin(p) for p in plugins]
    for d in dirs:
        _load_dir(res, d)
    for variant, links in res.aliases.items():
        unknown = [sid for sid in links if sid not in res.senses]
        if unknown:
            raise ValueError(f"aliases: '{variant}' links to unknown sense(s) {unknown}")
    res.plugin_dirs = dirs
    return res


def _load_dir(res: Resources, d: Path) -> None:
    key = res.key
    for name, target in (("roles.yaml", "roles"), ("rules.yaml", "rules")):
        if (d / name).is_file():
            setattr(res, target, deep_merge(getattr(res, target), load_yaml(d / name)))

    lex_dir = d / "lexicon"
    if lex_dir.is_dir():
        for path in sorted(lex_dir.iterdir()):
            if path.suffix not in (".txt", ".tsv"):
                continue
            terms = res.lexicon[path.stem.lower()]
            for row in _rows(path):
                terms[key(row[0])] = _col(row, 1)

    ent_dir = d / "entities"
    if ent_dir.is_dir():
        for path in sorted(ent_dir.glob("*.tsv")):
            for row in _rows(path):
                name = row[0]
                entry = EntityEntry(
                    name=name,
                    canonical=_col(row, 1) or name,
                    type=_col(row, 2),
                    source=_col(row, 3) or path.stem,
                    score=float(_col(row, 4) or 1.0),
                )
                res.entities[key(name)].append(entry)
        res._prefixes = None

    if (d / "senses.tsv").is_file():
        for row in _rows(d / "senses.tsv"):
            sid = row[0]
            res.senses[sid] = Sense(
                sid, _col(row, 1) or sid, _col(row, 2) or "ENTITY", _col(row, 3)
            )
    if (d / "aliases.tsv").is_file():
        for row in _rows(d / "aliases.tsv"):
            res.aliases[key(row[0])][row[1]] = float(_col(row, 2) or 1.0)
    if (d / "compat.tsv").is_file():
        for row in _rows(d / "compat.tsv"):
            res.compat[(row[0], row[1])] = float(row[2])
    if (d / "sense_prior.tsv").is_file():
        for row in _rows(d / "sense_prior.tsv"):
            prior = float(row[2])
            if prior <= 0 or math.isnan(prior):
                raise ValueError(f"{d / 'sense_prior.tsv'}: prior must be > 0: {row}")
            res.sense_prior[(key(row[0]), row[1], _col(row, 3) or "")] = prior
    if (d / "idf.tsv").is_file():
        for row in _rows(d / "idf.tsv"):
            res.idf[key(row[0])] = float(row[1])
