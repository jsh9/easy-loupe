"""Shared helpers for autofocus-point extraction."""

from __future__ import annotations

import re
from typing import Any

from easy_cull.core.records import PAIR_LENGTH

CENTER_FOCUS_POINT = (0.5, 0.5)
MIN_EXIF_ORIENTATION = 1  # Normal top-left orientation.
MAX_EXIF_ORIENTATION = 8  # Last EXIF orientation value: 90 degrees CCW.


def camera_make_startswith(metadata: dict[str, Any], brand: str) -> bool:
    """Return whether the metadata Make field starts with the brand."""
    make = metadata.get('Make')
    return isinstance(make, str) and make.strip().lower().startswith(brand)


def apply_orientation_to_point(
        x: float, y: float, orientation_value: Any
) -> tuple[float, float]:
    """
    Rotate or mirror a normalized point to match EXIF display orientation.
    """
    orientation = parse_orientation(orientation_value)
    if orientation == 2:  # noqa: PLR2004 - EXIF orientation values are fixed.
        return (clamp01(1 - x), y)

    if orientation == 3:  # noqa: PLR2004
        return (clamp01(1 - x), clamp01(1 - y))

    if orientation == 4:  # noqa: PLR2004
        return (x, clamp01(1 - y))

    if orientation == 5:  # noqa: PLR2004
        return (y, x)

    if orientation == 6:  # noqa: PLR2004
        return (clamp01(1 - y), x)

    if orientation == 7:  # noqa: PLR2004
        return (clamp01(1 - y), clamp01(1 - x))

    if orientation == MAX_EXIF_ORIENTATION:
        return (y, clamp01(1 - x))

    return (x, y)


def parse_orientation(value: Any) -> int:
    """Parse an EXIF orientation value, defaulting to normal orientation."""
    number = coerce_float(value)
    if number is None:
        return MIN_EXIF_ORIENTATION

    orientation = int(number)
    if MIN_EXIF_ORIENTATION <= orientation <= MAX_EXIF_ORIENTATION:
        return orientation

    return MIN_EXIF_ORIENTATION


def has_af_area_arrays(metadata: dict[str, Any]) -> bool:
    """Return whether AF area coordinate arrays are present."""
    return 'AFAreaXPositions' in metadata and 'AFAreaYPositions' in metadata


def selected_focus_index(metadata: dict[str, Any]) -> int | None:
    """Return the first usable selected-focus index from known EXIF keys."""
    candidate_keys = [
        'AFPointSelected',
        'PrimaryAFPoint',
        'AFPointsUsed',
        'FocusPosition',
        'AFPointSelected2',
    ]
    for key in candidate_keys:
        value = metadata.get(key)
        parsed = parse_index(value)
        if parsed is not None:
            return parsed

    return None


def first_nonzero_index(value: Any) -> int | None:
    """Return the index of the first nonzero number in a numeric sequence."""
    for index, number in enumerate(coerce_number_list(value)):
        if number != 0:
            return index

    return None


def extract_point(
        value: Any, width: int | None, height: int | None
) -> tuple[float, float] | None:
    """Extract a normalized point from a dict, sequence, or numeric string."""
    if isinstance(value, dict):
        x = value.get('x') or value.get('X') or value.get('left')
        y = value.get('y') or value.get('Y') or value.get('top')
        return normalize_xy(x, y, width, height)

    if isinstance(value, (list, tuple)) and len(value) >= PAIR_LENGTH:
        return normalize_xy(value[0], value[1], width, height)

    if isinstance(value, str):
        numbers = re.findall(r'-?\d+(?:\.\d+)?', value)
        if len(numbers) >= PAIR_LENGTH:
            return normalize_xy(
                float(numbers[0]), float(numbers[1]), width, height
            )

    return None


def normalize_xy(
        x_value: Any, y_value: Any, width: int | None, height: int | None
) -> tuple[float, float] | None:
    """
    Normalize a coordinate pair using generic absolute-or-normalized rules.
    """
    x = normalize_coordinate(x_value, width)
    y = normalize_coordinate(y_value, height)
    if x is None or y is None:
        return None

    return (clamp01(x), clamp01(y))


def normalize_absolute_xy(
        x_value: Any, y_value: Any, width: int | None, height: int | None
) -> tuple[float, float] | None:
    """Normalize a coordinate pair that must be absolute pixel coordinates."""
    x = coerce_float(x_value)
    y = coerce_float(y_value)
    if x is None or y is None or not width or not height:
        return None

    if not 0 <= x <= width or not 0 <= y <= height:
        return None

    return (clamp01(x / width), clamp01(y / height))


def normalize_coordinate(value: Any, axis_size: int | None) -> float | None:
    """Normalize one coordinate that may already be fractional or absolute."""
    number = coerce_float(value)
    if number is None:
        return None

    if 0.0 <= number <= 1.0:
        return number

    if axis_size and axis_size > 0:
        return number / axis_size

    return None


def first_int(metadata: dict[str, Any], keys: list[str]) -> int | None:
    """
    Return the first integer-like metadata value found for the given keys.
    """
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, int):
            return value

        if isinstance(value, float):
            return int(value)

        if isinstance(value, str) and value.isdigit():
            return int(value)

    return None


def coerce_float(value: Any) -> float | None:
    """Convert a scalar value to float when possible."""
    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None

    return None


def coerce_number_list(value: Any) -> list[float]:
    """Convert a list-like or numeric string into a list of floats."""
    if isinstance(value, (list, tuple)):
        return [
            number
            for item in value
            if (number := coerce_float(item)) is not None
        ]

    if isinstance(value, str):
        return [
            float(match) for match in re.findall(r'-?\d+(?:\.\d+)?', value)
        ]

    return []


def parse_index(value: Any) -> int | None:
    """Parse a single integer index from common EXIF value shapes."""
    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return int(value)

    if isinstance(value, (list, tuple)) and len(value) == 1:
        return parse_index(value[0])

    if isinstance(value, str):
        match = re.search(r'\d+', value)
        if match:
            return int(match.group(0))

    return None


def clamp01(value: float) -> float:
    """Clamp a float into the inclusive 0..1 range."""
    return max(0.0, min(1.0, value))
