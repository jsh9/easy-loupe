"""Top-level autofocus-point extraction flow."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from easy_photo_culling.core.autofocus_points.brands import (
    canon,
    fujifilm,
    nikon,
    olympus,
    panasonic,
    pentax,
    sony,
)
from easy_photo_culling.core.autofocus_points.generic import (
    extract_direct_focus_point,
    extract_paired_focus_point,
    extract_selected_array_point,
)
from easy_photo_culling.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_photo_culling.core.autofocus_points.utils import CENTER_FOCUS_POINT

AutofocusExtractor = Callable[
    [dict[str, Any], int | None, int | None],
    FocusPointExtraction | None,
]

EXTRACTORS: tuple[AutofocusExtractor, ...] = (
    canon.extract,
    sony.extract,
    panasonic.extract,
    fujifilm.extract,
    nikon.extract,
    olympus.extract,
    pentax.extract,
)


def extract_focus_point(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> tuple[float, float]:
    """Extract a normalized (x, y) focus point from EXIF metadata."""
    camera_brand_specific_result = _extract_focus_point_per_camera_brand(
        metadata, width, height
    )
    if camera_brand_specific_result is not None:
        if camera_brand_specific_result.point is not None:
            return camera_brand_specific_result.point

        if camera_brand_specific_result.suppress_generic_fallback:
            return CENTER_FOCUS_POINT

    direct_point = extract_direct_focus_point(metadata, width, height)
    if direct_point is not None:
        return direct_point

    paired_point = extract_paired_focus_point(metadata, width, height)
    if paired_point is not None:
        return paired_point

    array_point = extract_selected_array_point(metadata, width, height)
    if array_point is not None:
        return array_point

    return CENTER_FOCUS_POINT


def _extract_focus_point_per_camera_brand(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> FocusPointExtraction | None:
    """Try camera-brand-specific focus-point extraction paths."""
    for extractor in EXTRACTORS:
        result = extractor(metadata, width, height)
        if result is not None:
            return result

    return None
