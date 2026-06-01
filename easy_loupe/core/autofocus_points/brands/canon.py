"""Canon autofocus-point extraction."""

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
    first_int,
    first_nonzero_index,
    has_af_area_arrays,
    selected_focus_index,
)


def extract(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> FocusPointExtraction | None:
    """Extract a Canon AF point from center-origin maker-note offsets."""
    if not _is_canon_metadata(metadata):
        return None

    if not has_af_area_arrays(metadata):
        return None

    x_values = coerce_number_list(metadata.get('AFAreaXPositions'))
    y_values = coerce_number_list(metadata.get('AFAreaYPositions'))
    if not x_values or not y_values or len(x_values) != len(y_values):
        return FocusPointExtraction(suppress_generic_fallback=True)

    selected_index = selected_focus_index(metadata)
    if selected_index is None:
        selected_index = first_nonzero_index(metadata.get('AFPointsSelected'))

    if selected_index is None:
        selected_index = first_nonzero_index(metadata.get('AFPointsInFocus'))

    if selected_index is None and len(x_values) == 1:
        selected_index = 0

    if selected_index is None or not 0 <= selected_index < len(x_values):
        return FocusPointExtraction(suppress_generic_fallback=True)

    af_width = (
        first_int(metadata, ['AFImageWidth'])
        or first_int(metadata, ['CanonImageWidth'])
        or width
    )
    af_height = (
        first_int(metadata, ['AFImageHeight'])
        or first_int(metadata, ['CanonImageHeight'])
        or height
    )
    if not af_width or not af_height:
        return FocusPointExtraction(suppress_generic_fallback=True)

    x = clamp01(0.5 + (x_values[selected_index] / af_width))
    y = clamp01(0.5 - (y_values[selected_index] / af_height))
    point = apply_orientation_to_point(x, y, metadata.get('Orientation'))
    return FocusPointExtraction(point=point)


def _is_canon_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Canon camera."""
    return camera_make_startswith(metadata, 'canon')
