from __future__ import annotations

from typing import Any

import pytest

import easy_loupe.core.autofocus_points as autofocus_points_module


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'Make': 'FUJIFILM',
                'FocusPixel': '2564 2491',
                'ImageWidth': 7728,
                'ImageHeight': 5152,
                'Orientation': 1,
            },
            (2564 / 7728, 2491 / 5152),
        ),
        (
            {
                'Make': 'FUJIFILM',
                'FocusPixel': '5053 2118',
                'ImageWidth': 7728,
                'ImageHeight': 5152,
                'Orientation': 6,
            },
            (1 - (2118 / 5152), 5053 / 7728),
        ),
        (
            {
                'Make': 'FUJIFILM',
                'FocusPixel': '4332 2069',
                'ImageWidth': 7728,
                'ImageHeight': 5152,
                'Orientation': 8,
            },
            (2069 / 5152, 1 - (4332 / 7728)),
        ),
        (
            {
                'Make': 'FUJIFILM',
                'ImageWidth': 7728,
                'ImageHeight': 5152,
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'FUJIFILM',
                'FocusPixel': '9000 2491',
                'ImageWidth': 7728,
                'ImageHeight': 5152,
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
    ],
)
def test_fujifilm_focus_pixel_uses_absolute_image_coordinates(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata, metadata.get('ImageWidth'), metadata.get('ImageHeight')
    ) == pytest.approx(expected_focus)
