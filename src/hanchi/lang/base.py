"""Language pack interface."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from hanchi.backend import Backend
from hanchi.normalize import NormalizedText
from hanchi.resources import Resources
from hanchi.segment import Segmentation
from hanchi.units import Unit


class LanguagePack(Protocol):
    code: str
    """ISO 639-1 language code (e.g. ``"ko"``)."""

    @property
    def backend(self) -> Backend: ...

    def normalize(self, text: str) -> NormalizedText: ...

    def segment(self, normalized: NormalizedText) -> Segmentation: ...

    def units(self, seg: Segmentation, res: Resources) -> list[Unit]:
        """Group morphemes into units with kinds and traits (see :mod:`hanchi.units`)."""
        ...

    def clause_breaks(self, units: Sequence[Unit]) -> set[int]:
        """Unit indices where a new clause starts, from grammar alone."""
        ...

    def register_names(self, names: Iterable[str]) -> None:
        """Tell the morphological backend about dictionary names (policy is per language)."""
        ...

    def kind_label(self, kind: str) -> str: ...

    def pos_detail(self, morphs: Sequence[tuple[str, str]]) -> str: ...
