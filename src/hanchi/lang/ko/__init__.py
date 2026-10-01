"""Korean language pack (Kiwi backend, Korean normalization and patterns)."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path

from hanchi.lang.ko.backend import KiwiBackend, load_backend_config
from hanchi.lang.ko.normalize import korean_normalizer
from hanchi.lang.ko.spacing import segment as _segment
from hanchi.lang.ko.tags import tag_info
from hanchi.lang.ko.units import build_units, clause_breaks, load_patterns
from hanchi.normalize import NormalizedText
from hanchi.resources import Resources
from hanchi.segment import Segmentation
from hanchi.units import Unit

__all__ = ["KiwiBackend", "KoreanPack"]


class KoreanPack:
    code = "ko"

    def __init__(
        self, plugin_dirs: Iterable[str | Path] = (), backend: KiwiBackend | None = None
    ) -> None:
        dirs = tuple(plugin_dirs)
        self._normalizer = korean_normalizer(dirs)
        self._backend = backend if backend is not None else KiwiBackend(load_backend_config(dirs))
        self._patterns = load_patterns(dirs)

    @property
    def backend(self) -> KiwiBackend:
        return self._backend

    def normalize(self, text: str) -> NormalizedText:
        return self._normalizer(text)

    def segment(self, normalized: NormalizedText) -> Segmentation:
        return _segment(self._backend, normalized)

    def units(self, seg: Segmentation, res: Resources) -> list[Unit]:
        return build_units(seg, res, self._patterns)

    def clause_breaks(self, units: Sequence[Unit]) -> set[int]:
        return clause_breaks(units, self._patterns)

    def kind_label(self, kind: str) -> str:
        return str(self._patterns.get("kind_labels", {}).get(kind, kind))

    def register_names(self, names: Iterable[str]) -> None:
        """Register single-word, purely nominal names with Kiwi as proper nouns.

        Names Kiwi reads as predicates ("찾아줘", "안나와") or that mix scripts ("gs25")
        are left alone: the role layer handles them, and registering would hide their
        grammatical reading or their parts.
        """
        for raw in names:
            name = self.normalize(raw).text
            if " " in name or any(ch.isascii() and ch.isalnum() for ch in name):
                continue
            morphs = self._backend.tokenize(name)
            if morphs and all(tag_info(m.tag).pos_class.is_nominal for m in morphs):
                self._backend.add_user_word(name, "NNP")

    def pos_detail(self, morphs: Sequence[tuple[str, str]]) -> str:
        if len(morphs) == 1:
            tag = morphs[0][1]
            return f"{tag} {tag_info(tag).name}"
        return "+".join(tag for _, tag in morphs)
