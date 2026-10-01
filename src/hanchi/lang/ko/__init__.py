"""Korean language pack (Kiwi backend, Korean normalization and patterns)."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from hanchi.lang.ko.backend import KiwiBackend, load_backend_config
from hanchi.lang.ko.normalize import korean_normalizer
from hanchi.lang.ko.spacing import segment as _segment
from hanchi.normalize import NormalizedText
from hanchi.segment import Segmentation

__all__ = ["KiwiBackend", "KoreanPack"]


class KoreanPack:
    code = "ko"

    def __init__(
        self, plugin_dirs: Iterable[str | Path] = (), backend: KiwiBackend | None = None
    ) -> None:
        dirs = tuple(plugin_dirs)
        self._normalizer = korean_normalizer(dirs)
        self._backend = backend if backend is not None else KiwiBackend(load_backend_config(dirs))

    @property
    def backend(self) -> KiwiBackend:
        return self._backend

    def normalize(self, text: str) -> NormalizedText:
        return self._normalizer(text)

    def segment(self, normalized: NormalizedText) -> Segmentation:
        return _segment(self._backend, normalized)
