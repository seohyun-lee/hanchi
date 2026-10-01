"""Language pack interface."""

from __future__ import annotations

from typing import Protocol

from hanchi.backend import Backend
from hanchi.normalize import NormalizedText
from hanchi.segment import Segmentation


class LanguagePack(Protocol):
    code: str
    """ISO 639-1 language code (e.g. ``"ko"``)."""

    @property
    def backend(self) -> Backend: ...

    def normalize(self, text: str) -> NormalizedText: ...

    def segment(self, normalized: NormalizedText) -> Segmentation: ...
