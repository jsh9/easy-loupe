"""Clipping-warning overlay generation for displayed viewer previews."""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image, ImageChops
from PySide6.QtGui import QImage, QPixmap

if TYPE_CHECKING:
    from pathlib import Path

HIGHLIGHT_CLIPPING_THRESHOLD = 250
SHADOW_CLIPPING_THRESHOLD = 5
HIGHLIGHT_CLIPPING_RGBA = (255, 59, 48, 156)
SHADOW_CLIPPING_RGBA = (0, 122, 255, 156)


def clipping_overlay_pixmap(
        image_path: Path,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
) -> QPixmap:
    """Return a cached clipping-warning pixmap for a displayed image path."""
    stat = image_path.stat()
    return _clipping_overlay_pixmap_cached(
        str(image_path),
        stat.st_mtime_ns,
        stat.st_size,
        highlight_threshold,
        shadow_threshold,
    )


def build_clipping_overlay_image(
        image: Image.Image,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
) -> Image.Image:
    """Return an RGBA overlay marking clipped highlights and shadows."""
    rgb_image = image.convert('RGB')
    red, green, blue = rgb_image.split()
    highlight_mask = _all_channels_mask((
        _threshold_channel_at_or_above(red, highlight_threshold),
        _threshold_channel_at_or_above(green, highlight_threshold),
        _threshold_channel_at_or_above(blue, highlight_threshold),
    ))
    shadow_mask = _all_channels_mask((
        _threshold_channel_at_or_below(red, shadow_threshold),
        _threshold_channel_at_or_below(green, shadow_threshold),
        _threshold_channel_at_or_below(blue, shadow_threshold),
    ))

    overlay = Image.new('RGBA', rgb_image.size, (0, 0, 0, 0))
    overlay.paste(
        Image.new('RGBA', rgb_image.size, HIGHLIGHT_CLIPPING_RGBA),
        (0, 0),
        highlight_mask,
    )
    overlay.paste(
        Image.new('RGBA', rgb_image.size, SHADOW_CLIPPING_RGBA),
        (0, 0),
        shadow_mask,
    )
    return overlay


@lru_cache(maxsize=128)
def _clipping_overlay_pixmap_cached(
        image_path: str,
        _mtime_ns: int,
        _size: int,
        highlight_threshold: int,
        shadow_threshold: int,
) -> QPixmap:
    with Image.open(image_path) as opened:
        overlay = build_clipping_overlay_image(
            opened,
            highlight_threshold=highlight_threshold,
            shadow_threshold=shadow_threshold,
        )

    return _pixmap_from_rgba_image(overlay)


def _all_channels_mask(channels: tuple[Image.Image, ...]) -> Image.Image:
    mask = channels[0]
    for channel in channels[1:]:
        mask = ImageChops.multiply(mask, channel)

    return mask


def _threshold_channel_at_or_above(
        channel: Image.Image, threshold: int
) -> Image.Image:
    return channel.point(lambda value: 255 if value >= threshold else 0)


def _threshold_channel_at_or_below(
        channel: Image.Image, threshold: int
) -> Image.Image:
    return channel.point(lambda value: 255 if value <= threshold else 0)


def _pixmap_from_rgba_image(image: Image.Image) -> QPixmap:
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    qimage = QImage()
    if not qimage.loadFromData(buffer.getvalue(), 'PNG'):
        return QPixmap()

    return QPixmap.fromImage(qimage)
