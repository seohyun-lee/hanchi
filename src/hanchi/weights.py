"""Weighting v1 (language-neutral).

``raw(span, role) = base[role] × (α + (1 − α) × idf_norm(span))`` — the idf term is
dropped when no ``idf.tsv`` is loaded or the span is not in it. Weights are then
normalized inside the query: every hypothesis is divided by the largest expected
span weight ``E[w] = Σ p × raw`` (capped at 1.0). A query with a single content span
gets weight 1.0 for every hypothesis whose role has a positive base weight.

The :class:`Weighter` protocol lets a learned weighter replace this one.
"""

from __future__ import annotations

from typing import Protocol

from hanchi.lattice import WorkSpan
from hanchi.resources import Resources


class Weighter(Protocol):
    def weigh(
        self, spans: list[WorkSpan], res: Resources, text: str = ""
    ) -> dict[int, list[float]]:
        """Weight of each hypothesis, per span index. ``text`` is the normalized query
        the span offsets refer to."""
        ...


def base_weight(res: Resources, role: str) -> float:
    weights = res.roles.get("weights", {})
    if role not in weights:
        raise KeyError(f"roles.yaml: no weight for role {role}")
    return float(weights[role])


class RuleWeighter:
    """``raw = base[role] × factor(span)``, normalized within the query.

    The default factor is the idf term. Subclasses replace :meth:`span_factors` to
    bring in other evidence (e.g. learned term importance) and keep everything else.
    """

    def span_factors(self, spans: list[WorkSpan], res: Resources, text: str) -> list[float]:
        alpha = float(res.setting("weights", "alpha"))
        out = []
        for s in spans:
            idf = res.idf_norm(s.key)
            out.append(1.0 if idf is None else alpha + (1 - alpha) * idf)
        return out

    def weigh(
        self, spans: list[WorkSpan], res: Resources, text: str = ""
    ) -> dict[int, list[float]]:
        cap = float(res.setting("weights", "cap"))
        factors = self.span_factors(spans, res, text)
        raw: dict[int, list[float]] = {
            i: [base_weight(res, h.role) * factors[i] for h in s.hyps] for i, s in enumerate(spans)
        }

        content = [i for i, s in enumerate(spans) if not s.is_function]
        if len(content) == 1:
            i = content[0]
            out = {k: [0.0] * len(v) for k, v in raw.items()}
            out[i] = [cap if r > 0 else 0.0 for r in raw[i]]
            return out

        expected = [
            sum(h.p * r for h, r in zip(spans[i].hyps, raw[i], strict=True)) for i in content
        ]
        top = max(expected, default=0.0)
        if top <= 0:
            return {k: [0.0] * len(v) for k, v in raw.items()}
        return {k: [min(cap, r / top) for r in v] for k, v in raw.items()}
