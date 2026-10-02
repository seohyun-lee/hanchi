"""Weighting with learned lexical (sparse) term weights.

An encoder returns ``(start, end, weight)`` for each subword of the normalized query.
Subword weights are pooled into each span by character offsets, normalized within the
query, and turned into a factor exactly like the idf term:
``raw = base[role] × idf factor × (alpha + (1 − alpha) × neural_norm)``.
Settings: ``rules.yaml: neural``.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Protocol

from hanchi.lattice import WorkSpan
from hanchi.resources import Resources
from hanchi.weights import RuleWeighter


class LexicalEncoder(Protocol):
    def token_weights(self, text: str) -> list[tuple[int, int, float]]:
        """``(start, end, weight)`` per subword token, offsets into ``text``."""
        ...


class LexicalWeighter(RuleWeighter):
    def __init__(self, encoder: LexicalEncoder, cache_size: int = 1024) -> None:
        self.encoder = encoder
        self._cache: OrderedDict[str, list[tuple[int, int, float]]] = OrderedDict()
        self._cache_size = cache_size

    def _weights(self, text: str) -> list[tuple[int, int, float]]:
        if text in self._cache:
            self._cache.move_to_end(text)
            return self._cache[text]
        w = self.encoder.token_weights(text)
        self._cache[text] = w
        if len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return w

    def span_importance(self, spans: list[WorkSpan], res: Resources, text: str) -> list[float]:
        pool = str(res.setting("neural", "pool"))
        tokens = self._weights(text) if text else []
        out = []
        for s in spans:
            ws = [w for a, b, w in tokens if a < s.end and b > s.start]
            if not ws:
                out.append(0.0)
            elif pool == "sum":
                out.append(sum(ws))
            else:
                out.append(max(ws))
        top = max(out, default=0.0)
        return [x / top if top > 0 else 0.0 for x in out]

    def span_factors(self, spans: list[WorkSpan], res: Resources, text: str) -> list[float]:
        alpha = float(res.setting("neural", "alpha"))
        base = super().span_factors(spans, res, text)
        neural = self.span_importance(spans, res, text)
        return [b * (alpha + (1 - alpha) * n) for b, n in zip(base, neural, strict=True)]
