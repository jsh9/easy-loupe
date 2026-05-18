"""Fujifilm autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_cull.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_cull.core.autofocus_points.utils import (
    apply_orientation_to_point,
    camera_make_startswith,
    clamp01,
    coerce_number_list,
    first_int,
)
from easy_cull.core.records import PAIR_LENGTH


def extract(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> FocusPointExtraction | None:
    """Extract a Fujifilm AF point from absolute FocusPixel coordinates."""
    if not _is_fujifilm_metadata(metadata):
        return None

    values = coerce_number_list(metadata.get('FocusPixel'))
    if len(values) < PAIR_LENGTH:
        return None

    image_width = width or first_int(
        metadata, ['ImageWidth', 'ExifImageWidth']
    )
    image_height = height or first_int(
        metadata, ['ImageHeight', 'ExifImageHeight']
    )
    if not image_width or not image_height:
        return FocusPointExtraction(suppress_generic_fallback=True)

    focus_x, focus_y = values[:PAIR_LENGTH]
    if not 0 <= focus_x <= image_width or not 0 <= focus_y <= image_height:
        return FocusPointExtraction(suppress_generic_fallback=True)

    x = clamp01(focus_x / image_width)
    y = clamp01(focus_y / image_height)
    point = apply_orientation_to_point(x, y, metadata.get('Orientation'))
    return FocusPointExtraction(point=point)


def _is_fujifilm_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Fujifilm camera."""
    return camera_make_startswith(metadata, 'fujifilm')
