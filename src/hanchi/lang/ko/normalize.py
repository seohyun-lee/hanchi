"""Korean normalization pipeline.

Rules, in order (all offset-preserving):

1. NFKC per character cluster, except Hangul compatibility / halfwidth jamo.
   Full-width → half-width, ``㈜`` → ``(주)``, ``①`` → ``1``.
2. Corporate-form markers removed: ``(주)``, ``(유)`` … anywhere; ``주식회사`` … as a
   whole word or at the start/end of a word.
3. Brackets and quotes → space.
4. Middle dots → space.
5. Hyphens/dashes → space, except between two digits.
6. Latin letters lowercased.
7. Whitespace collapsed to single spaces, stripped.

Example: ``"㈜스타벅스 (강남R점)"`` → ``"스타벅스 강남r점"``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hanchi.config import layered
from hanchi.normalize import (
    Normalizer,
    RegexReplace,
    Step,
    UnicodeNormalize,
    collapse_whitespace,
    lowercase_latin,
)

_DATA = "hanchi.lang.ko.data"


def _char_class(chars: str) -> str:
    return "[" + "".join(re.escape(c) for c in chars) + "]"


def build_steps(config: Mapping[str, Any]) -> list[Step]:
    protect = tuple((int(lo), int(hi)) for lo, hi in config.get("nfkc_protect", []))
    steps: list[Step] = [UnicodeNormalize("NFKC", protect)]

    markers = config.get("company_markers", {})
    paren = markers.get("parenthesized", [])
    if paren:
        alt = "|".join(re.escape(m) for m in paren)
        steps.append(RegexReplace.compile(rf"\(\s*(?:{alt})\s*\)", " "))
    words = markers.get("words", [])
    if words:
        alt = "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))
        steps.append(RegexReplace.compile(rf"(?:(?<=\s)|^)(?:{alt})|(?:{alt})(?=\s|$)", " "))

    for key in ("separators", "middle_dots"):
        chars = config.get(key, "")
        if chars:
            steps.append(RegexReplace.compile(_char_class(chars), " "))
    dashes = config.get("dashes", "")
    if dashes:
        steps.append(
            RegexReplace.compile(rf"(?<!\d){_char_class(dashes)}|{_char_class(dashes)}(?!\d)", " ")
        )

    steps += [lowercase_latin, collapse_whitespace]
    return steps


def korean_normalizer(plugin_dirs: Iterable[str | Path] = ()) -> Normalizer:
    return Normalizer(build_steps(layered(_DATA, "normalize.yaml", plugin_dirs)))
