"""What a constraint (or a corrected location) applies to. Language-neutral.

``Span.attach = {"type": <constraint type>, "anchor": <anchor>}`` where the anchor is a span
index, ``"user_location"``, ``"now"`` or ``None``.

- proximity constraints ("주변", "근처") anchor to a LOCATION span of the same clause
  (word order does not matter), else of a neighbouring clause, else ``"user_location"``
  (the caller knows where the user is; the library does not).
- time/status constraints anchor to ``"now"``.
- quantities anchor to the nearest noun-like span they count.
- a LOCATION in a later clause without its own request ("… 찾아줘 아니 강남") anchors
  to the request span of an earlier clause (type ``"location"``).

Which constraint type uses which strategy is configured in ``rules.yaml: attach``.
"""

from __future__ import annotations

from typing import Any

from hanchi.lattice import WorkHypothesis, WorkSpan
from hanchi.resources import Resources
from hanchi.schema import COMMAND, CONSTRAINT, ENTITY, HEAD, LOCATION, MODIFIER
from hanchi.units import QUANTITY

_COUNTABLE = (HEAD, ENTITY, MODIFIER)


def _top(s: WorkSpan) -> WorkHypothesis:
    return max(s.hyps, key=lambda h: h.p)


def attach(spans: list[WorkSpan], res: Resources) -> dict[int, dict[str, Any]]:
    strategies: dict[str, str] = res.setting("attach")
    tops = [_top(s).role for s in spans]
    out: dict[int, dict[str, Any]] = {}

    def nearest(i: int, roles: tuple[str, ...], clauses: set[int]) -> int | None:
        cands = [
            j for j, s in enumerate(spans) if j != i and s.clause in clauses and tops[j] in roles
        ]
        return min(cands, key=lambda j: abs(j - i)) if cands else None

    for i, s in enumerate(spans):
        if tops[i] == CONSTRAINT:
            ctype = res.lexicon_type("constraint", s.key) or (
                "quantity" if s.has(QUANTITY) else None
            )
            if ctype is None:
                continue
            strategy = strategies.get(ctype, "none")
            anchor: int | str | None = None
            if strategy == "location":
                anchor = nearest(i, (LOCATION,), {s.clause})
                if anchor is None:
                    anchor = nearest(i, (LOCATION,), {s.clause - 1, s.clause + 1})
                if anchor is None:
                    anchor = "user_location"
            elif strategy == "now":
                anchor = "now"
            elif strategy == "nominal":
                before = [
                    j for j in range(i) if spans[j].clause == s.clause and tops[j] in _COUNTABLE
                ]
                after = [
                    j
                    for j in range(i + 1, len(spans))
                    if spans[j].clause == s.clause and tops[j] in _COUNTABLE
                ]
                anchor = before[-1] if before else (after[0] if after else None)
            out[i] = {"type": ctype, "anchor": anchor}
        elif tops[i] == LOCATION and s.clause > 0:
            own_request = any(
                tops[j] == COMMAND and spans[j].clause == s.clause for j in range(len(spans))
            )
            earlier = [j for j in range(i) if tops[j] == COMMAND and spans[j].clause < s.clause]
            if not own_request and earlier:
                out[i] = {"type": "location", "anchor": earlier[-1]}
    return out
