"""Plugin directories → in-memory resources (dictionaries, lexicons, settings).

Priority: **overrides > user plugins > package defaults.** Plugins load in the order
given, after the package default plugin; a later plugin wins on conflicts.
``overrides.tsv`` rules (from any plugin, or extra override files) are applied after
everything else in the pipeline. A plugin is a directory or ``preset:<name>``.

Plugin layout (every file optional)::

    roles.yaml            role base weights                        (mappings merge)
    rules.yaml            feature weights, thresholds, settings     (mappings merge)
    normalize.yaml, patterns.yaml, backend.yaml                    (language pack)
    entities/*.tsv        name \\t canonical \\t type \\t source \\t score
    lexicon/<name>.txt    term                                      (name: head, qualifier,
    lexicon/<name>.tsv    term \\t type                               command, constraint,
                                                                    location, meta, unit)
    senses.tsv            sense_id \\t canonical \\t role \\t type \\t note
    aliases.tsv           variant \\t target \\t score   (target: sense_id, entity name,
                                                          or another unambiguous variant)
    synonyms.tsv          sense_id \\t sense_id          (same meaning, both directions)
    hypernyms.tsv         child_sense \\t parent_sense   (directed: 식당 → 맛집)
    compat.tsv            type_a \\t type_b \\t score
    sense_prior.tsv       variant \\t sense_id \\t prior [\\t vertical]
    idf.tsv               token \\t idf
    overrides.tsv         pattern \\t action \\t value \\t note
                          action: role (value ROLE or ROLE/sense_id) | keep | split
                          (value: the parts, space-separated)

In lexicon, entity, alias and sense files a line starting with ``-`` removes an entry
loaded earlier (``-센터`` in ``qualifier.txt``). Lexicon terms starting with ``re:``
are regular expressions matched against the whole normalized term (``re:[a-z]?점``).
"""

from __future__ import annotations

import math
import re
import warnings
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from pathlib import Path
from typing import Any

from hanchi.config import deep_merge, load_yaml

PRESET_PREFIX = "preset:"
REGEX_PREFIX = "re:"
REMOVE_PREFIX = "-"


class AliasWarning(UserWarning):
    """An alias row was ignored (e.g. it would merge senses through an ambiguous variant)."""


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


@dataclass(frozen=True)
class Override:
    pattern: str
    action: str
    value: str
    note: str
    source: str
    regex: re.Pattern[str] | None = None

    def matches(self, key: str) -> bool:
        return bool(self.regex.fullmatch(key)) if self.regex else key == self.pattern


OVERRIDE_ACTIONS = ("role", "keep", "split")


@dataclass
class Resources:
    key: Callable[[str], str]
    """Normalizes a dictionary term into a lookup key (same rules as queries, no spaces)."""
    roles: dict[str, Any] = field(default_factory=dict)
    rules: dict[str, Any] = field(default_factory=dict)
    lexicon: dict[str, dict[str, str | None]] = field(default_factory=lambda: defaultdict(dict))
    lexicon_patterns: dict[str, list[tuple[re.Pattern[str], str | None]]] = field(
        default_factory=lambda: defaultdict(list)
    )
    entities: dict[str, list[EntityEntry]] = field(default_factory=lambda: defaultdict(list))
    senses: dict[str, Sense] = field(default_factory=dict)
    aliases: dict[str, dict[str, float]] = field(default_factory=lambda: defaultdict(dict))
    synonyms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    hypernyms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    hyponyms: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    compat: dict[tuple[str, str], float] = field(default_factory=dict)
    sense_prior: dict[tuple[str, str, str], float] = field(default_factory=dict)
    idf: dict[str, float] = field(default_factory=dict)
    overrides: list[Override] = field(default_factory=list)
    plugin_dirs: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    _index: _EntityIndex | None = None

    # --- lexicons ----------------------------------------------------------------

    def in_lexicon(self, name: str, key: str) -> bool:
        if key in self.lexicon.get(name, {}):
            return True
        return any(p.fullmatch(key) for p, _ in self.lexicon_patterns.get(name, ()))

    def lexicon_type(self, name: str, key: str) -> str | None:
        terms = self.lexicon.get(name, {})
        if key in terms:
            return terms[key]
        for p, t in self.lexicon_patterns.get(name, ()):
            if p.fullmatch(key):
                return t
        return None

    def lexicons_of(self, key: str) -> list[str]:
        names = set(self.lexicon) | set(self.lexicon_patterns)
        return sorted(n for n in names if self.in_lexicon(n, key))

    # --- entities ----------------------------------------------------------------

    @property
    def index(self) -> _EntityIndex:
        if self._index is None:
            lat = self.rules.get("lattice", {})
            self._index = _EntityIndex(
                self.entities, int(lat.get("max_infix_len", 8)), int(lat.get("max_infix_keys", 64))
            )
        return self._index

    def entity_keys_with_prefix(self, key: str) -> set[str]:
        """Entity keys strictly longer than ``key`` that start with it."""
        return self.index.with_prefix(key)

    def entity_keys_containing(self, key: str) -> Iterator[str]:
        """Entity keys containing ``key`` somewhere other than at the start."""
        return iter(self.index.containing(key))

    # --- senses ------------------------------------------------------------------

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

    # --- overrides ---------------------------------------------------------------

    def override_for(self, key: str, action: str) -> Override | None:
        for o in reversed(self.overrides):  # later wins
            if o.action == action and o.matches(key):
                return o
        return None

    # --- settings ----------------------------------------------------------------

    def setting(self, *path: str) -> Any:
        node: Any = self.rules
        for p in path:
            if not isinstance(node, dict) or p not in node:
                raise KeyError("rules.yaml: missing setting " + ".".join(path))
            node = node[p]
        return node

    def feature(self, role: str, name: str) -> float:
        return float(self.rules.get("features", {}).get(role, {}).get(name, 0.0))


class _EntityIndex:
    """Prefix and infix lookups over entity keys (built lazily, capped per substring)."""

    def __init__(self, entities: dict[str, list[EntityEntry]], max_infix: int, cap: int) -> None:
        self._prefix: dict[str, set[str]] = defaultdict(set)
        self._infix: dict[str, set[str]] = defaultdict(set)
        for k in entities:
            for i in range(1, len(k)):
                self._prefix[k[:i]].add(k)
            for start in range(1, len(k)):
                for end in range(start + 1, min(len(k), start + max_infix) + 1):
                    bucket = self._infix[k[start:end]]
                    if len(bucket) < cap:
                        bucket.add(k)

    def with_prefix(self, key: str) -> set[str]:
        return self._prefix.get(key, set())

    def containing(self, key: str) -> set[str]:
        return self._infix.get(key, set())


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


@dataclass
class _Pending:
    aliases: list[tuple[str, str, float, str]] = field(default_factory=list)
    removed_aliases: list[tuple[str, str | None]] = field(default_factory=list)


def load_resources(
    plugins: Iterable[str | Path],
    key: Callable[[str], str],
    include_default: bool = True,
    override_files: Iterable[str | Path] = (),
) -> Resources:
    res = Resources(key=key)
    pending = _Pending()
    dirs = [default_plugin_dir()] if include_default else []
    dirs += [resolve_plugin(p) for p in plugins]
    for d in dirs:
        _load_dir(res, d, pending)
    for f in override_files:
        _load_overrides(res, Path(f))
    _resolve_aliases(res, pending)
    res.plugin_dirs = dirs
    return res


def _load_dir(res: Resources, d: Path, pending: _Pending) -> None:
    key = res.key
    for name, target in (("roles.yaml", "roles"), ("rules.yaml", "rules")):
        if (d / name).is_file():
            setattr(res, target, deep_merge(getattr(res, target), load_yaml(d / name)))

    lex_dir = d / "lexicon"
    if lex_dir.is_dir():
        for path in sorted(lex_dir.iterdir()):
            if path.suffix in (".txt", ".tsv"):
                _load_lexicon(res, path)

    ent_dir = d / "entities"
    if ent_dir.is_dir():
        for path in sorted(ent_dir.glob("*.tsv")):
            for row in _rows(path):
                name = row[0]
                if name.startswith(REMOVE_PREFIX):
                    res.entities.pop(key(name[1:]), None)
                    continue
                entry = EntityEntry(
                    name=name,
                    canonical=_col(row, 1) or name,
                    type=_col(row, 2),
                    source=_col(row, 3) or path.stem,
                    score=float(_col(row, 4) or 1.0),
                )
                res.entities[key(name)].append(entry)

    if (d / "senses.tsv").is_file():
        for row in _rows(d / "senses.tsv"):
            sid = row[0]
            if sid.startswith(REMOVE_PREFIX):
                res.senses.pop(sid[1:], None)
                continue
            res.senses[sid] = Sense(
                sid, _col(row, 1) or sid, _col(row, 2) or "ENTITY", _col(row, 3)
            )
    if (d / "aliases.tsv").is_file():
        src = str(d / "aliases.tsv")
        for row in _rows(d / "aliases.tsv"):
            if row[0].startswith(REMOVE_PREFIX):
                pending.removed_aliases.append((key(row[0][1:]), _col(row, 1)))
                continue
            if len(row) < 2:
                raise ValueError(f"{src}: alias row needs a target: {row}")
            pending.aliases.append((key(row[0]), row[1], float(_col(row, 2) or 1.0), src))
    if (d / "synonyms.tsv").is_file():
        for row in _rows(d / "synonyms.tsv"):
            res.synonyms[row[0]].add(row[1])
            res.synonyms[row[1]].add(row[0])
    if (d / "hypernyms.tsv").is_file():
        for row in _rows(d / "hypernyms.tsv"):
            res.hypernyms[row[0]].add(row[1])
            res.hyponyms[row[1]].add(row[0])
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
    if (d / "overrides.tsv").is_file():
        _load_overrides(res, d / "overrides.tsv")
    res._index = None


def _load_lexicon(res: Resources, path: Path) -> None:
    name = path.stem.lower()
    terms = res.lexicon[name]
    patterns = res.lexicon_patterns[name]
    for row in _rows(path):
        term, typ = row[0], _col(row, 1)
        if term.startswith(REMOVE_PREFIX):
            term = term[1:]
            if term.startswith(REGEX_PREFIX):
                patterns[:] = [
                    (p, t) for p, t in patterns if p.pattern != term[len(REGEX_PREFIX) :]
                ]
            else:
                terms.pop(res.key(term), None)
        elif term.startswith(REGEX_PREFIX):
            patterns.append((re.compile(term[len(REGEX_PREFIX) :]), typ))
        else:
            terms[res.key(term)] = typ


def _load_overrides(res: Resources, path: Path) -> None:
    for row in _rows(path):
        pattern, action = row[0], (_col(row, 1) or "").lower()
        if action not in OVERRIDE_ACTIONS:
            raise ValueError(f"{path}: unknown override action {action!r} in {row}")
        value, note = _col(row, 2) or "", _col(row, 3) or ""
        if pattern.startswith(REGEX_PREFIX):
            regex = re.compile(pattern[len(REGEX_PREFIX) :])
            res.overrides.append(Override(pattern, action, value, note, str(path), regex))
        else:
            res.overrides.append(Override(res.key(pattern), action, value, note, str(path)))


def _warn(res: Resources, message: str) -> None:
    res.warnings.append(message)
    warnings.warn(message, AliasWarning, stacklevel=3)


def _resolve_aliases(res: Resources, pending: _Pending) -> None:
    """Link variants to senses (many-to-many) without ever merging two senses.

    - target is a sense id → direct link
    - target is an entity name → the variant becomes another name of that entity
    - target is another variant → follow it only if that variant has exactly one
      sense; through an ambiguous variant ("배" → pear/ship) nothing is merged and a
      warning is issued (this replaces union-find, which would join the groups)
    """
    key = res.key
    removed = set(pending.removed_aliases)
    chained: list[tuple[str, str, float, str]] = []
    for variant, target, score, src in pending.aliases:
        if (variant, target) in removed or (variant, None) in removed:
            continue
        if target in res.senses:
            res.aliases[variant][target] = score
        elif key(target) in res.entities:
            for e in res.entities[key(target)]:
                alias = EntityEntry(
                    variant, e.canonical, e.type, f"alias:{e.source}", e.score * score
                )
                if alias not in res.entities[variant]:
                    res.entities[variant].append(alias)
        else:
            chained.append((variant, key(target), score, src))

    for _ in range(len(chained) + 1):
        progress = False
        rest = []
        for variant, tkey, score, src in chained:
            links = res.aliases.get(tkey)
            if not links:
                rest.append((variant, tkey, score, src))
                continue
            if len(links) > 1:
                _warn(
                    res,
                    f"{src}: alias '{variant}' -> '{tkey}' ignored: '{tkey}' is ambiguous "
                    f"({', '.join(sorted(links))}); senses are never merged through it",
                )
                progress = True
                continue
            sid = next(iter(links))
            res.aliases[variant][sid] = score
            progress = True
        chained = rest
        if not progress:
            break
    for variant, tkey, _, src in chained:
        raise ValueError(f"{src}: alias '{variant}' -> '{tkey}': unknown sense, entity or variant")

    # A sense's canonical spelling is a variant of it unless a plugin says otherwise.
    for sense in res.senses.values():
        k = key(sense.canonical)
        if sense.sense_id not in res.aliases.get(k, {}) and (k, None) not in removed:
            res.aliases[k][sense.sense_id] = 1.0
    res._index = None
