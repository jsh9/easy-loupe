"""Pentax autofocus-point extraction."""

from __future__ import annotations

from typing import Any

from easy_cull.core.autofocus_points.types import (
    FocusPointExtraction,
)
from easy_cull.core.autofocus_points.utils import (
    CENTER_FOCUS_POINT,
    apply_orientation_to_point,
    clamp01,
    coerce_number_list,
)

PENTAX_CONTRAST_AF_FRAME_WIDTH = 720
PENTAX_CONTRAST_AF_FRAME_HEIGHT = 480
# Pentax K-1/K-1 II are DSLRs with a dedicated phase-detect AF module. Their
# maker notes usually identify one of a few dozen viewfinder AF points, not a
# pixel coordinate. Those AF points occupy a central cluster rather than the
# whole image area, so map the documented point ids into this conservative box.
PENTAX_K1_AF_POINT_MIN_X = 0.30
PENTAX_K1_AF_POINT_MAX_X = 0.70
PENTAX_K1_AF_POINT_MIN_Y = 0.35
PENTAX_K1_AF_POINT_MAX_Y = 0.65

# Row-to-column layout from ExifTool's K-1 AFPointSelected documentation.
# Point ids are assigned left-to-right, top-to-bottom over this 33-point shape.
_PENTAX_K1_AF_POINT_COLUMNS: dict[int, tuple[int, ...]] = {
    0: (3, 4, 5, 6, 7),
    1: (2, 3, 4, 5, 6, 7, 8),
    2: (1, 2, 3, 4, 5, 6, 7, 8, 9),
    3: (2, 3, 4, 5, 6, 7, 8),
    4: (3, 4, 5, 6, 7),
}
# Zone ids name groups of individual DSLR AF points. Use each zone's centroid
# as the best available marker location because Pentax does not provide a more
# precise image-coordinate point for these phase-detect modes.
_PENTAX_K1_ZONE_POINTS: dict[int, tuple[int, ...]] = {
    263: (1, 2, 6, 7, 8, 14, 15, 16),
    264: (1, 2, 3, 7, 8, 9, 15, 16, 17),
    265: (2, 3, 4, 8, 9, 10, 16, 17, 18),
    266: (3, 4, 5, 9, 10, 11, 17, 18, 19),
    267: (4, 5, 10, 11, 12, 18, 19, 20),
    270: (6, 7, 13, 14, 15, 22, 23),
    271: (6, 7, 8, 14, 15, 16, 22, 23, 24),
    272: (7, 8, 9, 15, 16, 17, 23, 24, 25),
    273: (8, 9, 10, 16, 17, 18, 24, 25, 26),
    274: (9, 10, 11, 17, 18, 19, 25, 26, 27),
    275: (10, 11, 12, 18, 19, 20, 26, 27, 28),
    276: (11, 12, 19, 20, 21, 27, 28),
    279: (14, 15, 16, 22, 23, 24, 29, 30),
    280: (15, 16, 17, 23, 24, 25, 29, 30, 31),
    281: (16, 17, 18, 24, 25, 26, 30, 31, 32),
    282: (17, 18, 19, 25, 26, 27, 31, 32, 33),
    283: (18, 19, 20, 26, 27, 28, 32, 33),
}
PENTAX_K1_FIXED_CENTER_POINT_ID = 0xFFFE


def extract(
        metadata: dict[str, Any], _width: int | None, _height: int | None
) -> FocusPointExtraction | None:
    """
    Extract a Pentax AF point from maker-note AF area metadata.

    Pentax DSLR files often expose phase-detect AF point ids instead of image
    coordinates. For K-1 style bodies, convert those ids through the documented
    central 33-point viewfinder layout. Contrast-detect rectangles are already
    coordinates and are preferred when present.
    """
    if not _is_pentax_metadata(metadata):
        return None

    if not _has_pentax_af_metadata(metadata):
        return None

    contrast_point = _extract_pentax_contrast_detect_af_area(metadata)
    if contrast_point is not None:
        point = apply_orientation_to_point(
            contrast_point[0], contrast_point[1], metadata.get('Orientation')
        )
        return FocusPointExtraction(point=point)

    if not _is_pentax_k1_model(metadata):
        return FocusPointExtraction(suppress_generic_fallback=True)

    point_id = _pentax_k1_selected_af_point_id(metadata)
    point = _pentax_k1_af_point_position(point_id)
    if point is None:
        return FocusPointExtraction(suppress_generic_fallback=True)

    oriented_point = apply_orientation_to_point(
        point[0], point[1], metadata.get('Orientation')
    )
    return FocusPointExtraction(point=oriented_point)


def _is_pentax_metadata(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Pentax camera."""
    make = metadata.get('Make')
    model = metadata.get('Model')
    if isinstance(make, str) and make.strip().lower().startswith('pentax'):
        return True

    return (
        isinstance(make, str)
        and make.strip().lower().startswith('ricoh')
        and isinstance(model, str)
        and model.strip().lower().startswith('pentax')
    )


def _is_pentax_k1_model(metadata: dict[str, Any]) -> bool:
    """Return whether metadata appears to come from a Pentax K-1 DSLR."""
    model = metadata.get('Model')
    return isinstance(model, str) and 'k-1' in model.strip().lower()


def _has_pentax_af_metadata(metadata: dict[str, Any]) -> bool:
    """
    Return whether Pentax AF point or AF-area metadata fields are present.
    """
    return any(
        key in metadata
        for key in [
            'ContrastDetectAFArea',
            'AFPointsInFocus',
            'AFPointsSpecial',
            'AFPointSelected',
        ]
    )


def _extract_pentax_contrast_detect_af_area(
        metadata: dict[str, Any],
) -> tuple[float, float] | None:
    """
    Return a Pentax contrast-detect AF rectangle center if usable.

    ExifTool documents this field as left, top, width, and height in a 720x480
    frame. It is a real coordinate field, unlike the DSLR phase-detect point-id
    fields, but many K-1 II photos report an all-zero rectangle.
    """
    values = coerce_number_list(metadata.get('ContrastDetectAFArea'))
    if len(values) < 4:  # noqa: PLR2004 - Pentax stores left, top, width, height.
        return None

    left, top, rect_width, rect_height = values[:4]
    if rect_width <= 0 or rect_height <= 0:
        return None

    center_x = left + (rect_width / 2)
    center_y = top + (rect_height / 2)
    if (
        not 0 <= center_x <= PENTAX_CONTRAST_AF_FRAME_WIDTH
        or not 0 <= center_y <= PENTAX_CONTRAST_AF_FRAME_HEIGHT
    ):
        return None

    return (
        clamp01(center_x / PENTAX_CONTRAST_AF_FRAME_WIDTH),
        clamp01(center_y / PENTAX_CONTRAST_AF_FRAME_HEIGHT),
    )


def _pentax_k1_selected_af_point_id(
        metadata: dict[str, Any],
) -> int | None:
    """
    Return the best Pentax K-1 AF point id from maker-note fields.

    Prefer the in-focus/special bitmasks because they represent the actual
    chosen DSLR AF point. Fall back to the first value of AFPointSelected; the
    second value is the AF area mode, such as expanded 33-point selection.
    """
    for key in ['AFPointsInFocus', 'AFPointsSpecial']:
        point_id = _decode_pentax_k1_af_point_mask(metadata.get(key))
        if point_id is not None:
            return point_id

    values = coerce_number_list(metadata.get('AFPointSelected'))
    if values:
        return int(values[0])

    return None


def _decode_pentax_k1_af_point_mask(value: Any) -> int | None:
    """
    Decode ExifTool's numeric Pentax K-1 2-bit AF point mask.

    The mask stores state for the few dozen physical DSLR AF points, ordered
    from point 1 through point 33. A set 0x02 bit marks a selected/in-focus
    point in ExifTool's decoded numeric output.
    """
    bytes_ = [int(number) for number in coerce_number_list(value)]
    if not bytes_:
        return None

    point_id = 1
    for byte in bytes_:
        for shift in [6, 4, 2, 0]:
            if point_id > 33:  # noqa: PLR2004 - Pentax K-1 has 33 AF points.
                return None

            if (byte >> shift) & 0x02:
                return point_id

            point_id += 1

    return None


def _pentax_k1_af_point_position(
        point_id: int | None,
) -> tuple[float, float] | None:
    """
    Return an approximate normalized Pentax K-1 AF point position.

    K-1 point ids describe positions in the DSLR viewfinder AF module rather
    than image pixels. The returned point is therefore an intentional layout
    approximation inside the central AF coverage area.
    """
    if point_id is None or point_id == 0:
        return None

    if point_id == PENTAX_K1_FIXED_CENTER_POINT_ID:
        return CENTER_FOCUS_POINT

    if point_id in _PENTAX_K1_ZONE_POINTS:
        points = [
            _pentax_k1_af_point_position(zone_point_id)
            for zone_point_id in _PENTAX_K1_ZONE_POINTS[point_id]
        ]
        valid_points = [point for point in points if point is not None]
        if not valid_points:
            return None

        return (
            sum(point[0] for point in valid_points) / len(valid_points),
            sum(point[1] for point in valid_points) / len(valid_points),
        )

    point_positions = _pentax_k1_af_point_positions()
    return point_positions.get(point_id)


def _pentax_k1_af_point_positions() -> dict[int, tuple[float, float]]:
    """
    Return approximate normalized positions for the K-1 33-point AF layout.

    The Pentax DSLR AF grid has only 33 selectable points concentrated near the
    middle of the frame. Spread the documented shape across the conservative
    central coverage box instead of the full image.
    """
    positions: dict[int, tuple[float, float]] = {}
    point_id = 1
    for row_index, columns in _PENTAX_K1_AF_POINT_COLUMNS.items():
        y = _interpolate_pentax_k1_af_axis(
            row_index,
            max(_PENTAX_K1_AF_POINT_COLUMNS),
            PENTAX_K1_AF_POINT_MIN_Y,
            PENTAX_K1_AF_POINT_MAX_Y,
        )
        for column in columns:
            x = _interpolate_pentax_k1_af_axis(
                column - 1,
                8,
                PENTAX_K1_AF_POINT_MIN_X,
                PENTAX_K1_AF_POINT_MAX_X,
            )
            positions[point_id] = (x, y)
            point_id += 1

    return positions


def _interpolate_pentax_k1_af_axis(
        index: int, max_index: int, minimum: float, maximum: float
) -> float:
    """Linearly interpolate one axis within the Pentax central AF box."""
    if max_index <= 0:
        return minimum

    return minimum + ((maximum - minimum) * (index / max_index))
