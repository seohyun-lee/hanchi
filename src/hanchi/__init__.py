"""Hanchi (한치): Korean query understanding — per-word role & weight from context."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("hanchi")
except PackageNotFoundError:  # running from a source tree without installation
    __version__ = "0.0.0"

from hanchi.analyzer import Analyzer
from hanchi.schema import Analysis, Hypothesis, Interpretation, Span

__all__ = ["Analysis", "Analyzer", "Hypothesis", "Interpretation", "Span", "__version__"]
