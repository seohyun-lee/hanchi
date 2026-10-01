"""Kiwi (kiwipiepy >= 0.24.0) morphological backend."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from kiwipiepy import Kiwi

from hanchi.backend import Morph, TagInfo
from hanchi.config import layered
from hanchi.lang.ko.tags import tag_info

_DATA = "hanchi.lang.ko.data"


def load_backend_config(plugin_dirs: Iterable[str | Path] = ()) -> dict[str, Any]:
    return layered(_DATA, "backend.yaml", plugin_dirs)


class KiwiBackend:
    """Wraps :class:`kiwipiepy.Kiwi`.

    Typo correction is passed per call to ``Kiwi.tokenize`` (the constructor option is
    deprecated since kiwipiepy 0.23).
    """

    def __init__(self, config: Mapping[str, Any] | None = None, kiwi: Kiwi | None = None):
        cfg = dict(load_backend_config() if config is None else config)
        self._score: float = float(cfg["user_word_score"])
        self._typos: str | None = cfg.get("typos")
        self._typo_cost_threshold: float = float(cfg["typo_cost_threshold"])
        self.despaced_variant: bool = bool(cfg.get("despaced_variant", True))
        self._kiwi = kiwi if kiwi is not None else Kiwi()
        self._user_words: set[str] = set()

    @property
    def kiwi(self) -> Kiwi:
        return self._kiwi

    @property
    def user_words(self) -> frozenset[str]:
        return frozenset(self._user_words)

    def add_user_word(self, word: str, tag: str = "NNP", score: float | None = None) -> bool:
        added = bool(self._kiwi.add_user_word(word, tag, self._score if score is None else score))
        self._user_words.add(word)
        return added

    def tokenize(self, text: str) -> list[Morph]:
        kwargs: dict[str, Any] = {}
        if self._typos:
            kwargs["typos"] = self._typos
            kwargs["typo_cost_threshold"] = self._typo_cost_threshold
        return [
            Morph(t.form, t.tag, t.start, t.start + t.len)
            for t in self._kiwi.tokenize(text, **kwargs)
        ]

    def space(self, text: str) -> str:
        return str(self._kiwi.space(text))

    def tag_info(self, tag: str) -> TagInfo:
        return tag_info(tag)
