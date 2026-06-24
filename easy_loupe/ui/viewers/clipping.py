"""Clipping-warning overlay generation for displayed viewer previews."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from threading import Lock
from typing import TYPE_CHECKING

from PIL import Image, ImageChops, ImageMath
from PySide6.QtGui import QImage, QPixmap

if TYPE_CHECKING:
    from pathlib import Path

HIGHLIGHT_CLIPPING_THRESHOLD = 250
SHADOW_CLIPPING_THRESHOLD = 5
HIGHLIGHT_CLIPPING_RGBA = (255, 59, 48, 156)
SHADOW_CLIPPING_RGBA = (0, 122, 255, 156)
CLIPPING_OVERLAY_MAX_LONG_EDGE = 2000
CLIPPING_OVERLAY_CACHE_SIZE = 24


@dataclass(frozen=True, slots=True)
class ClippingOverlayCacheKey:
    """Stable cache key for one displayed preview's clipping overlay."""

    image_path: str
    mtime_ns: int
    size: int
    highlight_threshold: int
    shadow_threshold: int
    max_long_edge: int


@dataclass(frozen=True, slots=True)
class ClippingOverlayPayload:
    """GUI-safe encoded clipping overlay data."""

    width: int
    height: int
    png_data: bytes


_CLIPPING_OVERLAY_CACHE_LOCK = Lock()
# Store encoded image bytes rather than QPixmaps so worker threads can fill
# the cache without touching GUI-thread-only Qt paint resources.
_CLIPPING_OVERLAY_CACHE: OrderedDict[
    ClippingOverlayCacheKey, ClippingOverlayPayload
] = OrderedDict()


def clipping_overlay_pixmap(
        image_path: Path,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
        max_long_edge: int = CLIPPING_OVERLAY_MAX_LONG_EDGE,
) -> QPixmap:
    """Return a cached clipping-warning pixmap for a displayed image path."""
    key = clipping_overlay_cache_key(
        image_path,
        highlight_threshold=highlight_threshold,
        shadow_threshold=shadow_threshold,
        max_long_edge=max_long_edge,
    )
    return clipping_overlay_pixmap_from_payload(
        clipping_overlay_payload_for_key(key)
    )


def clipping_overlay_cache_key(
        image_path: Path,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
        max_long_edge: int = CLIPPING_OVERLAY_MAX_LONG_EDGE,
) -> ClippingOverlayCacheKey:
    """Return the cache key for one displayed preview path."""
    stat = image_path.stat()
    return ClippingOverlayCacheKey(
        str(image_path),
        stat.st_mtime_ns,
        stat.st_size,
        highlight_threshold,
        shadow_threshold,
        max_long_edge,
    )


def get_cached_clipping_overlay_payload(
        key: ClippingOverlayCacheKey,
) -> ClippingOverlayPayload | None:
    """Return a cached clipping overlay payload without generating one."""
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        payload = _CLIPPING_OVERLAY_CACHE.get(key)
        if payload is None:
            return None

        _CLIPPING_OVERLAY_CACHE.move_to_end(key)
        return payload


def clipping_overlay_payload_for_key(
        key: ClippingOverlayCacheKey,
) -> ClippingOverlayPayload:
    """Return a cached clipping overlay payload, generating it on misses."""
    payload = get_cached_clipping_overlay_payload(key)
    if payload is not None:
        return payload

    payload = _build_clipping_overlay_payload(key)
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        cached_payload = _CLIPPING_OVERLAY_CACHE.get(key)
        if cached_payload is not None:
            _CLIPPING_OVERLAY_CACHE.move_to_end(key)
            return cached_payload

        _CLIPPING_OVERLAY_CACHE[key] = payload
        _CLIPPING_OVERLAY_CACHE.move_to_end(key)
        while len(_CLIPPING_OVERLAY_CACHE) > CLIPPING_OVERLAY_CACHE_SIZE:
            _CLIPPING_OVERLAY_CACHE.popitem(last=False)

    return payload


def clipping_overlay_pixmap_from_payload(
        payload: ClippingOverlayPayload,
) -> QPixmap:
    """Convert cached GUI-safe overlay bytes into a Qt pixmap."""
    qimage = QImage()
    if not qimage.loadFromData(payload.png_data, 'PNG'):
        return QPixmap()

    return QPixmap.fromImage(qimage)


def build_clipping_overlay_image(
        image: Image.Image,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
) -> Image.Image:
    """Return an RGBA overlay marking clipped highlights and shadows."""
    highlight_mask, shadow_mask = _clipping_masks(
        image,
        highlight_threshold=highlight_threshold,
        shadow_threshold=shadow_threshold,
    )
    return _overlay_image_from_masks(highlight_mask, shadow_mask)


def _build_clipping_overlay_payload(
        key: ClippingOverlayCacheKey,
) -> ClippingOverlayPayload:
    with Image.open(key.image_path) as opened:
        highlight_mask, shadow_mask = _clipping_masks(
            opened,
            highlight_threshold=key.highlight_threshold,
            shadow_threshold=key.shadow_threshold,
        )

    target_size = _bounded_size(
        highlight_mask.size,
        max_long_edge=key.max_long_edge,
    )
    # Resize binary masks, not RGB pixels, so tiny clipped regions cannot be
    # averaged below the warning thresholds while bounding large overlays.
    highlight_mask = _resize_hit_mask(highlight_mask, target_size)
    shadow_mask = _resize_hit_mask(shadow_mask, target_size)
    overlay = _overlay_image_from_masks(highlight_mask, shadow_mask)
    try:
        return _payload_from_rgba_image(overlay)
    finally:
        overlay.close()
        highlight_mask.close()
        shadow_mask.close()


def _clipping_masks(
        image: Image.Image,
        *,
        highlight_threshold: int,
        shadow_threshold: int,
) -> tuple[Image.Image, Image.Image]:
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
    rgb_image.close()
    red.close()
    green.close()
    blue.close()
    return highlight_mask, shadow_mask


def _overlay_image_from_masks(
        highlight_mask: Image.Image,
        shadow_mask: Image.Image,
) -> Image.Image:
    overlay = Image.new('RGBA', highlight_mask.size, (0, 0, 0, 0))
    overlay.paste(
        Image.new('RGBA', highlight_mask.size, HIGHLIGHT_CLIPPING_RGBA),
        (0, 0),
        highlight_mask,
    )
    overlay.paste(
        Image.new('RGBA', shadow_mask.size, SHADOW_CLIPPING_RGBA),
        (0, 0),
        shadow_mask,
    )
    return overlay


def _bounded_size(
        size: tuple[int, int],
        *,
        max_long_edge: int,
) -> tuple[int, int]:
    width, height = size
    long_edge = max(width, height)
    if max_long_edge <= 0 or long_edge <= max_long_edge:
        return size

    scale = max_long_edge / long_edge
    return (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )


def _resize_hit_mask(
        mask: Image.Image, target_size: tuple[int, int]
) -> Image.Image:
    """Resize a binary clipping mask without losing sub-byte hit averages."""
    if mask.size == target_size:
        return mask.copy()

    # Resize in float mode so a single clipped pixel still produces a positive
    # value after BOX filtering; 8-bit resizing can round that hit to zero.
    float_mask = mask.convert('F')
    resized = float_mask.resize(target_size, Image.Resampling.BOX)
    try:
        binary_mask = ImageMath.lambda_eval(
            lambda args: (
                ImageMath.imagemath_convert(args['resized'] > 0, 'L') * 255
            ),
            resized=resized,
        )
        try:
            return binary_mask.convert('L')
        finally:
            binary_mask.close()
    finally:
        float_mask.close()
        resized.close()


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


def _payload_from_rgba_image(image: Image.Image) -> ClippingOverlayPayload:
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return ClippingOverlayPayload(
        width=image.width,
        height=image.height,
        png_data=buffer.getvalue(),
    )
