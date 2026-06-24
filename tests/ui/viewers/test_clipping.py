from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtWidgets import QApplication

from easy_loupe.ui.viewers.clipping import (
    HIGHLIGHT_CLIPPING_RGBA,
    SHADOW_CLIPPING_RGBA,
    build_clipping_overlay_image,
    clipping_overlay_pixmap,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_clipping_overlay_marks_highlights_shadows_and_midtones() -> None:
    """
    Verify clipping masks distinguish blown highlights, shadows, and midtones.

    The viewer overlay is an inspection aid, so mixed-channel or midtone pixels
    must remain transparent instead of producing false warnings.
    """
    image = Image.new('RGB', (5, 1))
    image.putdata([
        (255, 255, 255),
        (0, 0, 0),
        (128, 128, 128),
        (255, 255, 200),
        (0, 0, 8),
    ])

    overlay = build_clipping_overlay_image(image)

    assert overlay.getpixel((0, 0)) == HIGHLIGHT_CLIPPING_RGBA
    assert overlay.getpixel((1, 0)) == SHADOW_CLIPPING_RGBA
    assert overlay.getpixel((2, 0)) == (0, 0, 0, 0)
    assert overlay.getpixel((3, 0)) == (0, 0, 0, 0)
    assert overlay.getpixel((4, 0)) == (0, 0, 0, 0)


def test_clipping_overlay_pixmap_uses_displayed_image_path(
        tmp_path: Path,
) -> None:
    """
    Verify the Qt overlay pixmap matches the supplied displayed preview file.

    This protects the feature boundary: clipping is derived from the image
    loaded into the viewer, not from source metadata or a separate render path.
    """
    image_path = tmp_path / 'preview.png'
    image = Image.new('RGB', (2, 1))
    image.putdata([(255, 255, 255), (0, 0, 0)])
    image.save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)
    rendered = pixmap.toImage()

    assert pixmap.width() == 2
    assert pixmap.height() == 1
    assert rendered.pixelColor(0, 0).red() == HIGHLIGHT_CLIPPING_RGBA[0]
    assert rendered.pixelColor(0, 0).alpha() == HIGHLIGHT_CLIPPING_RGBA[3]
    assert rendered.pixelColor(1, 0).blue() == SHADOW_CLIPPING_RGBA[2]
    assert rendered.pixelColor(1, 0).alpha() == SHADOW_CLIPPING_RGBA[3]
    del app
