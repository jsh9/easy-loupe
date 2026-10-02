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
    """Return the source path that matches the clipboard copy contract."""
    photo = library.get_photo(photo_id)
    # JPEG-backed records should copy the original file pixels, not a cached
    # viewer render, so paste targets receive the folder's JPEG image.
    if photo.has_jpeg:
        return photo.preview_source

    # RAW, HEIC/HEIF, JPEG XL, and PNG-only records use EasyLoupe's rendered
    # viewer preview. RAW, HEIF, and JXL originals are not generally pasteable
    # raster images, and sharing one path keeps PNG orientation and
    # transparency flattening consistent with what the viewer shows.
    return library.get_preview_path(photo_id, 'viewer')


def _qimage_for_path(image_path: Path) -> QImage:
    """Return a detached, EXIF-oriented image for clipboard ownership."""
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
        # ``QImage`` wraps ``data`` above, so detach it before the local
        # buffer and PIL image go out of scope.
        return qimage.copy()
    finally:
        image.close()
