"""RGB histogram helpers for viewer overlays."""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

if TYPE_CHECKING:
    from pathlib import Path

RGBHistogram = tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]
HISTOGRAM_CHANNEL_SIZE = 256


def compute_rgb_histogram(image_path: Path) -> RGBHistogram:
    """Return normalized R, G, and B histograms for an image path."""
    stat = image_path.stat()
    return _compute_rgb_histogram_cached(
        str(image_path), stat.st_mtime_ns, stat.st_size
    )


@lru_cache(maxsize=256)
def _compute_rgb_histogram_cached(
        image_path: str, _mtime_ns: int, _size: int
) -> RGBHistogram:
    with Image.open(image_path) as opened:
        image = ImageOps.exif_transpose(opened).convert('RGB')
        histogram = image.histogram()

    channels = (
        histogram[0:HISTOGRAM_CHANNEL_SIZE],
        histogram[HISTOGRAM_CHANNEL_SIZE : HISTOGRAM_CHANNEL_SIZE * 2],
        histogram[HISTOGRAM_CHANNEL_SIZE * 2 : HISTOGRAM_CHANNEL_SIZE * 3],
    )
    return (
        _normalize_channel(channels[0]),
        _normalize_channel(channels[1]),
        _normalize_channel(channels[2]),
    )


def _normalize_channel(channel: list[int]) -> tuple[float, ...]:
    max_count = max(channel, default=0)
    if max_count <= 0:
        return tuple(0.0 for _ in range(HISTOGRAM_CHANNEL_SIZE))

    return tuple(count / max_count for count in channel)
