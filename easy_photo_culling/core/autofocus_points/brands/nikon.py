"""Nikon autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_photo_culling.core.autofocus_points.generic import (
    extract_selected_array_point,
)
from easy_photo_culling.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_photo_culling.core.autofocus_points.utils import (
    apply_orientation_to_point,
    camera_make_startswith,
    has_af_area_arrays,
    normalize_absolute_xy,
)


def extract(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> FocusPointExtraction | None:
    """Extract a Nikon AF point from scalar or selected-array coordinates."""
    if not _is_nikon_metadata(metadata):
        return None

    if not _has_nikon_af_metadata(metadata):
        return None

    scalar_point = normalize_absolute_xy(
        metadata.get('AFAreaXPosition'),
        metadata.get('AFAreaYPosition'),
        width,
        height,
    )
    if scalar_point is not None:
        point = apply_orientation_to_point(
            scalar_point[0], scalar_point[1], metadata.get('Orientation')
        )
        return FocusPointExtraction(point=point)

    array_point = extract_selected_array_point(metadata, width, height)
    if array_point is not None:
        point = apply_orientation_to_point(
            array_point[0], array_point[1], metadata.get('Orientation')
        )
        return FocusPointExtraction(point=point)

    return FocusPointExtraction(suppress_generic_fallback=True)


def _is_nikon_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Nikon camera."""
    return camera_make_startswith(metadata, 'nikon')


def _has_nikon_af_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether Nikon-specific AF coordinate fields are present."""
    return (
        'AFAreaXPosition' in metadata
        or 'AFAreaYPosition' in metadata
        or has_af_area_arrays(metadata)
    )
