"""
Qt pixel helpers for view-only photo rotation.

Viewers rotate decoded pixels at display time instead of rotating the
``QGraphicsView`` or the cached preview files. Rotating by a quarter-turn
multiple is lossless, and keeping the rotated pixels as the displayed image
lets fit, zoom, pan, and minimap math keep treating screen axes as image axes.
"""

from __future__ import annotations

from PySide6.QtGui import QImage, QPixmap, QTransform

from easy_loupe.core.rotation import NO_ROTATION_DEGREES


def rotate_pixmap(pixmap: QPixmap, rotation: int) -> QPixmap:
    """
    Return ``pixmap`` turned clockwise by ``rotation`` degrees.

    Qt treats positive angles as clockwise on screen and drops the
    translation from the result, so a quarter turn yields a pixmap whose left
    edge is now the top edge. Unrotated and null pixmaps are returned as-is.
    """
    if rotation == NO_ROTATION_DEGREES or pixmap.isNull():
        return pixmap

    return pixmap.transformed(QTransform().rotate(rotation))


def rotate_image(image: QImage, rotation: int) -> QImage:
    """
    Return ``image`` turned clockwise by ``rotation`` degrees.

    ``QImage`` is safe off the GUI thread, so this suits clipboard and
    overlay images. PIL's ``Image.rotate`` turns counterclockwise, so use
    this helper wherever the result must match the on-screen view.
    """
    if rotation == NO_ROTATION_DEGREES or image.isNull():
        return image

    return image.transformed(QTransform().rotate(rotation))
