"""
Qt helpers for view-only photo rotation.

Viewers never rotate the ``QGraphicsView`` itself or the cached preview files.
The main photo item gets a quarter-turn item transform instead, which turns it
without copying full-resolution pixels and keeps scene coordinates in the
rotated on-screen frame, so fit, zoom, pan, and minimap math keep treating
screen axes as image axes. Small images (thumbnails, minimaps, and one-off
clipboard copies) are turned as pixels.
"""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap, QTransform

from easy_loupe.core.rotation import (
    HALF_TURN_DEGREES,
    NO_ROTATION_DEGREES,
    QUARTER_TURN_DEGREES,
    THREE_QUARTER_TURN_DEGREES,
)


def build_rotation_transform(
        width: int, height: int, rotation: int
) -> QTransform:
    """
    Return the item transform that turns a ``width`` x ``height`` image.

    The transform maps unrotated image pixels into a scene rectangle that
    starts at the origin, so the rotated item covers ``(0, 0)`` to the rotated
    size. A clockwise quarter turn maps ``(x, y)`` to ``(height - y, x)``: the
    left edge becomes the top edge.
    """
    if rotation == QUARTER_TURN_DEGREES:
        return QTransform(0, 1, -1, 0, height, 0)

    if rotation == HALF_TURN_DEGREES:
        return QTransform(-1, 0, 0, -1, width, height)

    if rotation == THREE_QUARTER_TURN_DEGREES:
        return QTransform(0, -1, 1, 0, 0, width)

    return QTransform()


def rotate_pixels[PixelsT: (QImage, QPixmap)](
        pixels: PixelsT, rotation: int
) -> PixelsT:
    """
    Return ``pixels`` turned clockwise by ``rotation`` degrees.

    Qt treats positive angles as clockwise on screen and drops the translation
    from the result, so a quarter turn yields an image whose left edge is now
    the top edge. Unrotated and null images are returned as-is. PIL's
    ``Image.rotate`` turns counterclockwise, so use this helper wherever the
    result must match the on-screen view.
    """
    if rotation == NO_ROTATION_DEGREES or pixels.isNull():
        return pixels

    return pixels.transformed(QTransform().rotate(rotation))
