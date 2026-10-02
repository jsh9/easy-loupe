"""
View-only photo rotation values and normalized-coordinate helpers.

Rotation is a per-photo display preference stored in ``easy-loupe.json``. It
never changes original files or cached previews: viewers turn the photo only at
display time, so this module only owns the persisted value domain and the math
that maps unrotated sizes and normalized coordinates (such as AF points) into
the rotated on-screen frame.
"""

from __future__ import annotations

ROTATION_METADATA_FIELD = 'rotation'
"""Per-photo metadata field name used for the persisted view rotation."""
NO_ROTATION_DEGREES = 0
QUARTER_TURN_DEGREES = 90
HALF_TURN_DEGREES = 180
THREE_QUARTER_TURN_DEGREES = 270
FULL_TURN_DEGREES = 360
SUPPORTED_ROTATIONS = (
    NO_ROTATION_DEGREES,
    QUARTER_TURN_DEGREES,
    HALF_TURN_DEGREES,
    THREE_QUARTER_TURN_DEGREES,
)
"""Clockwise display rotations in degrees; 0 means the preview as rendered."""


def normalize_rotation(value: object) -> int | None:
    """
    Return a supported clockwise rotation in degrees, or None when invalid.

    Only exact quarter-turn integers are accepted. ``bool`` is rejected
    explicitly because it is an ``int`` subclass, and a hand-edited ``true``
    must not turn into a 1-degree or 90-degree rotation.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        return None

    return value if value in SUPPORTED_ROTATIONS else None


def step_rotation(rotation: int, quarter_turns: int) -> int:
    """
    Return the rotation after turning by whole quarter turns.

    Positive ``quarter_turns`` turn clockwise and negative values turn
    counterclockwise; the result always wraps back into ``0..270``.
    """
    return (
        rotation + (quarter_turns * QUARTER_TURN_DEGREES)
    ) % FULL_TURN_DEGREES


def rotate_size(size: tuple[int, int], rotation: int) -> tuple[int, int]:
    """
    Return the ``(width, height)`` an image occupies after rotation.

    Quarter and three-quarter turns swap the axes; half turns keep them.
    """
    width, height = size
    if rotation in {QUARTER_TURN_DEGREES, THREE_QUARTER_TURN_DEGREES}:
        return (height, width)

    return (width, height)


def rotate_normalized_point(
        point: tuple[float, float], rotation: int
) -> tuple[float, float]:
    """
    Map a normalized point from the unrotated frame into a rotated frame.

    ``point`` is an ``(x, y)`` pair in ``0..1`` image coordinates with the
    origin at the top-left. A clockwise quarter turn moves the left edge to the
    top, so ``(x, y)`` becomes ``(1 - y, x)``. These are the same mappings EXIF
    orientations 6, 3, and 8 use for AF points.
    """
    x, y = point
    if rotation == QUARTER_TURN_DEGREES:
        return (1.0 - y, x)

    if rotation == HALF_TURN_DEGREES:
        return (1.0 - x, 1.0 - y)

    if rotation == THREE_QUARTER_TURN_DEGREES:
        return (y, 1.0 - x)

    return (x, y)
