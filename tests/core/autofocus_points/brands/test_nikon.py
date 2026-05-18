from __future__ import annotations

from typing import Any

import pytest

import easy_cull.core.autofocus_points as autofocus_points_module
from tests.core.autofocus_points._helpers import first_int


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPosition': 2784,
                'AFAreaYPosition': 1856,
                'ImageWidth': 5600,
                'ImageHeight': 3728,
                'Orientation': 1,
            },
            (2784 / 5600, 1856 / 3728),
        ),
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPosition': 936,
                'AFAreaYPosition': 2446,
                'ImageWidth': 5600,
                'ImageHeight': 3728,
                'Orientation': 8,
            },
            (2446 / 3728, 1 - (936 / 5600)),
        ),
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPosition': 2784,
                'AFAreaYPosition': 1856,
                'ImageWidth': 5600,
                'ImageHeight': 3728,
                'Orientation': 8,
            },
            (1856 / 3728, 1 - (2784 / 5600)),
        ),
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPositions': [100, 700, 1900],
                'AFAreaYPositions': [200, 900, 1500],
                'AFPointsUsed': '2',
                'RawImageWidth': 2000,
                'RawImageHeight': 2000,
                'Orientation': 8,
            },
            (1500 / 2000, 1 - (1900 / 2000)),
        ),
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPosition': 9000,
                'AFAreaYPosition': 1856,
                'ImageWidth': 5600,
                'ImageHeight': 3728,
                'Orientation': 8,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'NIKON CORPORATION',
                'AFAreaXPosition': 2784,
                'ImageWidth': 5600,
                'ImageHeight': 3728,
                'Orientation': 8,
            },
            (0.5, 0.5),
        ),
    ],
)
def test_nikon_af_area_positions_use_dedicated_orientation_aware_path(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata,
        first_int(metadata, ['ImageWidth', 'RawImageWidth']),
        first_int(metadata, ['ImageHeight', 'RawImageHeight']),
    ) == pytest.approx(expected_focus)
