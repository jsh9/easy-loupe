"""Olympus autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_photo_culling.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_photo_culling.core.autofocus_points.utils import (
    apply_orientation_to_point,
    camera_make_startswith,
    coerce_number_list,
)
from easy_photo_culling.core.records import PAIR_LENGTH


def extract(
        metadata: dict[str, Any], _width: int | None, _height: int | None
) -> FocusPointExtraction | None:
    """Extract an Olympus AF point from normalized AFPointSelected data."""
    if not _is_olympus_metadata(metadata):
        return None

    if 'AFPointSelected' not in metadata:
        return None

    values = coerce_number_list(metadata.get('AFPointSelected'))
    if len(values) < PAIR_LENGTH:
        return FocusPointExtraction(suppress_generic_fallback=True)

    x, y = values[:PAIR_LENGTH]
    if not 0 <= x <= 1 or not 0 <= y <= 1:
        return FocusPointExtraction(suppress_generic_fallback=True)

    point = apply_orientation_to_point(x, y, metadata.get('Orientation'))
    return FocusPointExtraction(point=point)


def _is_olympus_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from an Olympus camera."""
    return camera_make_startswith(metadata, 'olympus')
