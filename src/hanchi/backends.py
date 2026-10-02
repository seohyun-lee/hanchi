"""Named resolver / weighter backends, so configs and the CLI can switch them.

Built in: resolver ``rule``; weighters ``rule`` and ``bge-m3`` (needs the ``[neural]``
extra). Register your own with :func:`register_weighter` / :func:`register_resolver`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from hanchi.resolver import Resolver, RuleResolver
from hanchi.weights import RuleWeighter, Weighter

WeighterFactory = Callable[..., Weighter]
ResolverFactory = Callable[..., Resolver]


def _bge_m3(**options: Any) -> Weighter:
    from hanchi.neural.bge_m3 import BgeM3Encoder
    from hanchi.neural.lexical import LexicalWeighter

    return LexicalWeighter(BgeM3Encoder(**options))


_WEIGHTERS: dict[str, WeighterFactory] = {"rule": RuleWeighter, "bge-m3": _bge_m3}
_RESOLVERS: dict[str, ResolverFactory] = {"rule": RuleResolver}


def register_weighter(name: str, factory: WeighterFactory) -> None:
    _WEIGHTERS[name] = factory


def register_resolver(name: str, factory: ResolverFactory) -> None:
    _RESOLVERS[name] = factory


def make_weighter(name: str, **options: Any) -> Weighter:
    if name not in _WEIGHTERS:
        raise ValueError(f"unknown weighter {name!r} (available: {', '.join(sorted(_WEIGHTERS))})")
    return _WEIGHTERS[name](**options)


def make_resolver(name: str, **options: Any) -> Resolver:
    if name not in _RESOLVERS:
        raise ValueError(f"unknown resolver {name!r} (available: {', '.join(sorted(_RESOLVERS))})")
    return _RESOLVERS[name](**options)
