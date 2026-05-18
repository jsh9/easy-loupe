"""Shared internal types for autofocus-point extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FocusPointExtraction:
    """Represent one extractor's point and fallback policy."""

    point: tuple[float, float] | None = None
    suppress_generic_fallback: bool = False
