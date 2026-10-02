"""Brand / business name clean-up: corporate markers, brackets, bilingual names."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CORP = re.compile(
    r"㈜|\(\s*(?:주|유|사|재|합|株)\s*\)|주식회사|유한회사|유한책임회사|합자회사|합명회사|사단법인|재단법인"
)
_PAREN = re.compile(r"[(\[{（［【]([^)\]}）］】]*)[)\]}）］】]")
_LATIN = re.compile(r"[A-Za-z]")
_HANGUL = re.compile(r"[가-힣]")
_SPACES = re.compile(r"\s+")


@dataclass
class CleanName:
    name: str
    aliases: list[str] = field(default_factory=list)


def _tidy(s: str) -> str:
    return _SPACES.sub(" ", s).strip(" -·,/")


def clean(raw: str) -> CleanName:
    """``"㈜스타벅스(STARBUCKS)"`` → name ``스타벅스``, aliases ``[STARBUCKS]``.

    Parenthesized Latin text is kept as an alias (bilingual names); other bracketed
    remarks are dropped. ``"한글 / LATIN"`` is split the same way.
    """
    text = _CORP.sub(" ", raw)
    aliases: list[str] = []
    for m in _PAREN.finditer(text):
        inner = _tidy(m.group(1))
        if inner and _LATIN.search(inner) and not _HANGUL.search(inner):
            aliases.append(inner)
    text = _tidy(_PAREN.sub(" ", text))
    if "/" in text:
        parts = [_tidy(p) for p in text.split("/") if _tidy(p)]
        hangul = [p for p in parts if _HANGUL.search(p)]
        latin = [p for p in parts if not _HANGUL.search(p)]
        if hangul and latin:
            text, aliases = hangul[0], aliases + latin + hangul[1:]
    if not text and aliases:
        text, aliases = aliases[0], aliases[1:]
    seen = {text}
    unique = [a for a in aliases if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]
    return CleanName(text, unique)
