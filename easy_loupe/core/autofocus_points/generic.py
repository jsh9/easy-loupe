"""Generic fallback autofocus-point extractors."""

from __future__ import annotations

from typing import Any

from easy_loupe.core.autofocus_points.utils import (
    coerce_number_list,
    extract_point,
    normalize_xy,
    selected_focus_index,
)


def extract_direct_focus_point(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> tuple[float, float] | None:
    """Try generic direct-point EXIF fields in precedence order."""
    for key in [
        'FocusLocation',
        'AFAreaCenter',
        'AFPointPosition',
        'AFImagePosition',
    ]:
        point = extract_point(metadata.get(key), width, height)
        if point is not None:
            return point

    return None


def extract_paired_focus_point(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> tuple[float, float] | None:
    """Try generic paired-coordinate EXIF fields in precedence order."""
    paired_keys = [
        ('AFAreaXPosition', 'AFAreaYPosition'),
        ('AFAreaX', 'AFAreaY'),
        ('AFAreaCenterX', 'AFAreaCenterY'),
        ('FocusPointX', 'FocusPointY'),
        ('AFPointX', 'AFPointY'),
    ]
    for x_key, y_key in paired_keys:
        point = normalize_xy(
            metadata.get(x_key), metadata.get(y_key), width, height
        )
        if point is not None:
            return point

    return None


def extract_selected_array_point(
        metadata: dict[str, Any], width: int | None, height: int | None
) -> tuple[float, float] | None:
    """
    Return a point from selected AF coordinate arrays using generic rules.
    """
    x_values = coerce_number_list(metadata.get('AFAreaXPositions'))
    y_values = coerce_number_list(metadata.get('AFAreaYPositions'))
    if not x_values or not y_values or len(x_values) != len(y_values):
        return None

    selected_index = selected_focus_index(metadata)
    if selected_index is None:
        if len(x_values) == 1:
            selected_index = 0
        else:
            return None

    if 0 <= selected_index < len(x_values):
        return normalize_xy(
            x_values[selected_index], y_values[selected_index], width, height
        )

    return None
