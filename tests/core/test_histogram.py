from __future__ import annotations

from typing import TYPE_CHECKING

from PIL import Image

from easy_loupe.core.histogram import compute_rgb_histogram

if TYPE_CHECKING:
    from pathlib import Path


def test_compute_rgb_histogram_returns_normalized_rgb_channels(
        tmp_path: Path,
) -> None:
    image_path = tmp_path / 'histogram.jpg'
    image = Image.new('RGB', (2, 1))
    image.putdata([(128, 32, 32), (32, 128, 32)])
    image.save(image_path, format='PNG')

    red, green, blue = compute_rgb_histogram(image_path)

    assert len(red) == 256
    assert len(green) == 256
    assert len(blue) == 256
    assert red[128] == 1.0
    assert red[32] == 1.0
    assert green[128] == 1.0
    assert green[32] == 1.0
    assert blue[32] == 1.0
    assert max(blue[:32] + blue[33:]) == 0.0
