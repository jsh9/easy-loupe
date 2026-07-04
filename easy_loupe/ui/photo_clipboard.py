"""Clipboard helpers for copying viewed photo pixels."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image, ImageOps
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

if TYPE_CHECKING:
    from pathlib import Path

    from easy_loupe.core.photo_library import PhotoLibrary


def copy_photo_pixels_to_clipboard(
        library: PhotoLibrary, photo_id: str
) -> bool:
    """Copy the whole photo image to the system clipboard as pixels."""
    try:
        image_path = _clipboard_image_path(library, photo_id)
        image = _qimage_for_path(image_path)
    except (KeyError, OSError, RuntimeError, ValueError):
        return False

    if image.isNull():
        return False

    QApplication.clipboard().setImage(image)
    return True


def _clipboard_image_path(library: PhotoLibrary, photo_id: str) -> Path:
    photo = library.get_photo(photo_id)
    if photo.has_jpeg:
        return photo.preview_source

    return library.get_preview_path(photo_id, 'viewer')


def _qimage_for_path(image_path: Path) -> QImage:
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGBA')

    try:
        width, height = image.size
        data = image.tobytes('raw', 'RGBA')
        qimage = QImage(
            data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        )
        return qimage.copy()
    finally:
        image.close()
