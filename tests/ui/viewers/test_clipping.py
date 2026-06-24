from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image
from PySide6.QtWidgets import QApplication

from easy_loupe.ui.viewers.clipping import (
    CLIPPING_OVERLAY_MAX_LONG_EDGE,
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


def test_clipping_overlay_pixmap_caps_long_edge(
        tmp_path: Path,
) -> None:
    """
    Verify cached clipping overlays are bounded for large viewer previews.

    The app may show full-size JPEG previews, so clipping overlays need their
    own size cap to avoid retaining native-resolution pixmaps in the cache.
    """
    image_path = tmp_path / 'large_preview.jpg'
    Image.new('RGB', (4000, 1000), color='white').save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)

    assert pixmap.width() == CLIPPING_OVERLAY_MAX_LONG_EDGE
    assert pixmap.height() == 500
    del app


def test_clipping_overlay_pixmap_preserves_small_highlight_after_cap(
        tmp_path: Path,
) -> None:
    """
    Verify bounded overlays do not average away tiny highlight warnings.

    The overlay is generated from full preview masks before downsampling so a
    single clipped source pixel should still be visible in the cached overlay.
    """
    image_path = tmp_path / 'large_highlight_preview.png'
    image = Image.new('RGB', (4000, 1000), color=(128, 128, 128))
    image.putpixel((0, 0), (255, 255, 255))
    image.save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)
    rendered = pixmap.toImage()

    assert pixmap.width() == CLIPPING_OVERLAY_MAX_LONG_EDGE
    assert pixmap.height() == 500
    assert rendered.pixelColor(0, 0).red() == HIGHLIGHT_CLIPPING_RGBA[0]
    assert rendered.pixelColor(0, 0).alpha() == HIGHLIGHT_CLIPPING_RGBA[3]
    del app


def test_clipping_overlay_pixmap_preserves_small_shadow_after_cap(
        tmp_path: Path,
) -> None:
    """
    Verify bounded overlays do not average away tiny shadow warnings.

    Shadows use the same hit-preserving mask resize path as highlights.
    """
    image_path = tmp_path / 'large_shadow_preview.png'
    image = Image.new('RGB', (4000, 1000), color=(128, 128, 128))
    image.putpixel((0, 0), (0, 0, 0))
    image.save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)
    rendered = pixmap.toImage()

    assert pixmap.width() == CLIPPING_OVERLAY_MAX_LONG_EDGE
    assert pixmap.height() == 500
    assert rendered.pixelColor(0, 0).blue() == SHADOW_CLIPPING_RGBA[2]
    assert rendered.pixelColor(0, 0).alpha() == SHADOW_CLIPPING_RGBA[3]
    del app
