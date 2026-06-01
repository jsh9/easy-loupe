"""Sony autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_loupe.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_loupe.core.autofocus_points.utils import (
    apply_orientation_to_point,
    camera_make_startswith,
    clamp01,
    coerce_number_list,
)

SONY_FOCUS_LOCATION_VALUE_COUNT = 4


def extract(
        metadata: dict[str, Any], _width: int | None, _height: int | None
) -> FocusPointExtraction | None:
    """Extract a Sony AF point from FocusLocation-style maker-note fields."""
    if not _is_sony_metadata(metadata):
        return None

    if 'FocusLocation2' not in metadata and 'FocusLocation' not in metadata:
        return None

    for key in ['FocusLocation2', 'FocusLocation']:
        values = coerce_number_list(metadata.get(key))
        if len(values) < SONY_FOCUS_LOCATION_VALUE_COUNT:
            continue

        coord_width, coord_height, focus_x, focus_y = values[
            :SONY_FOCUS_LOCATION_VALUE_COUNT
        ]
        if coord_width <= 0 or coord_height <= 0:
            continue

        x = clamp01(focus_x / coord_width)
        y = clamp01(focus_y / coord_height)
        point = apply_orientation_to_point(x, y, metadata.get('Orientation'))
        return FocusPointExtraction(point=point)

    return FocusPointExtraction(suppress_generic_fallback=True)


def _is_sony_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Sony camera."""
    return camera_make_startswith(metadata, 'sony')
