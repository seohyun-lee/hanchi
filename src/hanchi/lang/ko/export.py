"""Dictionary export for Korean tools: Kiwi user dictionaries and Elasticsearch /
OpenSearch ``nori`` user dictionaries.

nori format (one entry per line): ``<token> [<part 1> ... <part n>]``. The first token
is the dictionary word; the rest, when present, is its decomposition. Names are
exported **without** decomposition so nori never splits them; multi-noun category
words ("서비스센터") are exported with their parts so both the compound and its parts
are searchable (with ``decompound_mode: mixed``).
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hanchi.analyzer import Analyzer

KIWI_FILE = "kiwi_user_dict.txt"
NORI_FILE = "nori_user_dict.txt"

# Lexicons whose compound terms are exported to nori with their parts.
NORI_DECOMPOUND_LEXICONS = ("head", "qualifier", "location", "constraint")


def kiwi_entries(analyzer: Analyzer) -> list[tuple[str, str, float]]:
    """``(word, tag, score)`` rows that reproduce the analyzer's Kiwi registrations."""
    pack = analyzer.pack
    names = [e[0].name for e in analyzer.resources.entities.values()]
    score = pack.backend.user_word_score
    return [(name, "NNP", score) for name in sorted(pack.registrable_names(names))]


def nori_entries(analyzer: Analyzer) -> list[list[str]]:
    res = analyzer.resources
    backend = analyzer.pack.backend
    rows: dict[str, list[str]] = {}

    def token(text: str) -> str:
        return res.key(text)

    # Names: never decomposed.
    for key, entries in res.entities.items():
        if key and not key.startswith("re:"):
            rows.setdefault(token(entries[0].name), [token(entries[0].name)])
    # Words with dictionary senses ("애플파이"): kept whole, so a compound never
    # competes with the sense of its part ("애플").
    for sense in res.senses.values():
        k = token(sense.canonical)
        rows.setdefault(k, [k])

    # Compound category words: word + its noun parts.
    terms: set[str] = set()
    for name in NORI_DECOMPOUND_LEXICONS:
        terms |= set(res.lexicon.get(name, {}))
    for term in sorted(terms):
        if not term or term in rows:
            continue
        morphs = backend.tokenize(term)
        parts = [m.form for m in morphs if backend.tag_info(m.tag).pos_class.is_nominal]
        if len(morphs) > 1 and len(parts) == len(morphs) and "".join(parts) == term:
            rows[term] = [term, *parts]
    return [rows[k] for k in sorted(rows)]


def export(analyzer: Analyzer, fmt: str, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if fmt == "kiwi":
        path = out / KIWI_FILE
        lines = [f"{w}\t{t}\t{s:g}" for w, t, s in kiwi_entries(analyzer)]
        header = "# Kiwi user dictionary exported by hanchi (word\\tTAG\\tscore)\n"
    elif fmt == "nori":
        path = out / NORI_FILE
        lines = [" ".join(row) for row in nori_entries(analyzer)]
        header = "# nori user dictionary exported by hanchi\n"
    else:
        raise ValueError(f"unknown export format: {fmt!r} (kiwi, nori)")
    path.write_text(header + "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path
