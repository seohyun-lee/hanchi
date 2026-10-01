from __future__ import annotations

from collections.abc import Callable

import pytest

from hanchi.lang.ko import KiwiBackend, KoreanPack


@pytest.fixture(scope="session")
def plain_pack() -> KoreanPack:
    """Korean pack with no user dictionary (shared; do not add words to it)."""
    return KoreanPack()


@pytest.fixture
def make_pack() -> Callable[..., KoreanPack]:
    """Fresh Korean pack with the given NNP user words registered."""

    def make(*words: str) -> KoreanPack:
        pack = KoreanPack()
        for w in words:
            pack.backend.add_user_word(w, "NNP")
        return pack

    return make


@pytest.fixture(scope="session")
def plain_backend() -> KiwiBackend:
    """Backend with no user dictionary (shared; do not add words to it)."""
    return KiwiBackend()


@pytest.fixture
def make_backend(plain_backend: KiwiBackend) -> Callable[..., KiwiBackend]:
    """Backend with the given NNP user words (the shared plain one when none are given)."""

    def make(*words: str) -> KiwiBackend:
        if not words:
            return plain_backend
        backend = KiwiBackend()
        for w in words:
            backend.add_user_word(w, "NNP")
        return backend

    return make
