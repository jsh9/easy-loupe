from __future__ import annotations

from typing import Any

import pytest

import easy_cull.core.autofocus_points as autofocus_points_module


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'Make': 'Panasonic',
                'AFPointPosition': '0.4931640625 0.3330078125',
                'Orientation': 1,
            },
            (0.4931640625, 0.3330078125),
        ),
        (
            {
                'Make': 'Panasonic',
                'AFPointPosition': '0.6591796875 0.60546875',
                'Orientation': 8,
            },
            (0.60546875, 1 - 0.6591796875),
        ),
        (
            {
                'Make': 'Panasonic',
                'AFPointPosition': '4194303.999 4194303.999',
                'Orientation': 8,
            },
            (0.5, 0.5),
        ),
    ],
)
def test_panasonic_af_point_position_uses_normalized_coordinates(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata, 6000, 4000
    ) == pytest.approx(expected_focus)
