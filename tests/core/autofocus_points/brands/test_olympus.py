from __future__ import annotations

from typing import Any

import pytest

import easy_loupe.core.autofocus_points as autofocus_points_module


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'Make': 'OLYMPUS IMAGING CORP.',
                'AFPointSelected': (
                    '0.634375 0.3958333333 0.634375 0.3958333333'
                ),
                'Orientation': 1,
            },
            (0.634375, 0.3958333333),
        ),
        (
            {
                'Make': 'OLYMPUS IMAGING CORP.',
                'AFPointSelected': (
                    '0.2484375 0.4770833333 0.2484375 0.4770833333'
                ),
                'Orientation': 6,
            },
            (1 - 0.4770833333, 0.2484375),
        ),
        (
            {
                'Make': 'OLYMPUS IMAGING CORP.',
                'AFPointSelected': (
                    '0.3203125 0.4979166667 0.3203125 0.4979166667'
                ),
                'Orientation': 8,
            },
            (0.4979166667, 1 - 0.3203125),
        ),
        (
            {
                'Make': 'OLYMPUS IMAGING CORP.',
                'AFPointSelected': 'undef undef undef undef',
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'OLYMPUS IMAGING CORP.',
                'AFPointSelected': '1.2 0.5 1.2 0.5',
                'FocusLocation': '1600 800',
                'ImageWidth': 4000,
                'ImageHeight': 2000,
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
    ],
)
def test_olympus_af_point_selected_uses_normalized_coordinates(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata, metadata.get('ImageWidth'), metadata.get('ImageHeight')
    ) == pytest.approx(expected_focus)


def test_non_olympus_af_point_selected_is_not_a_generic_focus_point() -> None:
    metadata = {
        'Make': 'Generic Camera',
        'AFPointSelected': '0.2 0.8 0.2 0.8',
        'ImageWidth': 4000,
        'ImageHeight': 2000,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 4000, 2000
    ) == (0.5, 0.5)
