"""Panasonic autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_cull.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_cull.core.autofocus_points.utils import (
    apply_orientation_to_point,
    camera_make_startswith,
    coerce_number_list,
)
from easy_cull.core.records import PAIR_LENGTH


def extract(
        metadata: dict[str, Any], _width: int | None, _height: int | None
) -> FocusPointExtraction | None:
    """Extract a Panasonic AF point from normalized AFPointPosition data."""
    if not _is_panasonic_metadata(metadata):
        return None

    if 'AFPointPosition' not in metadata:
        return None

    values = coerce_number_list(metadata.get('AFPointPosition'))
    if len(values) < PAIR_LENGTH:
        return FocusPointExtraction(suppress_generic_fallback=True)

    x, y = values[:PAIR_LENGTH]
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        return FocusPointExtraction(suppress_generic_fallback=True)

    point = apply_orientation_to_point(x, y, metadata.get('Orientation'))
    return FocusPointExtraction(point=point)


def _is_panasonic_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Panasonic camera."""
    return camera_make_startswith(metadata, 'panasonic')
