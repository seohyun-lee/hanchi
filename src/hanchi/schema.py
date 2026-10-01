"""Output schema: hypotheses, spans, interpretations and the analysis result."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

# Built-in role names. Roles are plain strings so configuration can add new ones.
ENTITY = "ENTITY"
MODIFIER = "MODIFIER"
LOCATION = "LOCATION"
HEAD = "HEAD"
CONSTRAINT = "CONSTRAINT"
QUALIFIER = "QUALIFIER"
COMMAND = "COMMAND"
META = "META"
FUNC = "FUNC"

ROLES = (ENTITY, MODIFIER, LOCATION, HEAD, CONSTRAINT, QUALIFIER, COMMAND, META, FUNC)


@dataclass
class Hypothesis:
    role: str
    p: float
    weight: float
    evidence: list[str]
    sense_id: str | None = None
    type: str | None = None


@dataclass
class Span:
    text: str
    """As typed by the user (original offsets)."""
    norm: str
    canonical: str | None
    start: int
    end: int
    """``[start, end)`` in the original query."""
    morphs: list[tuple[str, str]]
    pos: str
    pos_detail: str
    hypotheses: list[Hypothesis]
    resolved: Hypothesis | None
    clause_id: int = 0
    attach: dict[str, Any] | None = None
    parts: list[Span] | None = None

    @property
    def top(self) -> Hypothesis:
        return max(self.hypotheses, key=lambda h: h.p)

    def hypothesis(self, role: str, sense_id: str | None = None) -> Hypothesis | None:
        for h in self.hypotheses:
            if h.role == role and (sense_id is None or h.sense_id == sense_id):
                return h
        return None

    def roles(self) -> set[str]:
        return {h.role for h in self.hypotheses}


@dataclass
class Interpretation:
    p: float
    score: float
    spans: list[Span]
    merges: list[dict[str, Any]] = field(default_factory=list)
    """Multi-unit spans that define this segmentation, with their evidence."""


@dataclass
class Analysis:
    query: str
    normalized: str
    spans: list[Span]
    ambiguous: bool
    clauses: list[tuple[int, int]]
    """Span index range ``[first, last + 1)`` of each clause."""
    signals: list[dict[str, Any]]
    interpretations: list[Interpretation]
    explain: dict[str, Any] | None = None

    def span(self, text: str) -> Span:
        """First span whose original text (or normalized text) equals ``text``."""
        for s in self.spans:
            if text in (s.text, s.norm):
                return s
        raise KeyError(text)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, **kwargs: Any) -> str:
        kwargs.setdefault("ensure_ascii", False)
        return json.dumps(self.to_dict(), **kwargs)
