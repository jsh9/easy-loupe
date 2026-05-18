from __future__ import annotations

from typing import Any

import pytest

import easy_photo_culling.core.autofocus_points as autofocus_points_module


@pytest.mark.parametrize(
    ('x_position', 'y_position', 'expected_focus'),
    [
        (0, -50, (0.5, 0.5 + (50 / 3648))),
        (-2264, 1608, (0.5 - (2264 / 5472), 0.5 - (1608 / 3648))),
        (2264, 1608, (0.5 + (2264 / 5472), 0.5 - (1608 / 3648))),
        (-2264, -1608, (0.5 - (2264 / 5472), 0.5 + (1608 / 3648))),
        (2264, -1608, (0.5 + (2264 / 5472), 0.5 + (1608 / 3648))),
    ],
)
def test_canon_af_area_positions_are_pixel_offsets_from_image_center(
        x_position: int,
        y_position: int,
        expected_focus: tuple[float, float],
) -> None:
    metadata: dict[str, Any] = {
        'Make': 'Canon',
        'AFAreaXPositions': f'{x_position} 0 0',
        'AFAreaYPositions': f'{y_position} 0 0',
        'AFPointsSelected': '1 0 0',
        'AFImageWidth': 5472,
        'AFImageHeight': 3648,
        'CanonImageWidth': 5472,
        'CanonImageHeight': 3648,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 5472, 3648
    ) == pytest.approx(expected_focus)


@pytest.mark.parametrize(
    ('x_position', 'y_position', 'expected_focus'),
    [
        (0, 0, (0.5, 0.5)),
        (2264, 1200, (0.5 - (1200 / 3648), 0.5 - (2264 / 5472))),
        (2264, -1608, (0.5 + (1608 / 3648), 0.5 - (2264 / 5472))),
        (-2264, 1608, (0.5 - (1608 / 3648), 0.5 + (2264 / 5472))),
        (-2264, -1608, (0.5 + (1608 / 3648), 0.5 + (2264 / 5472))),
    ],
)
def test_canon_af_area_positions_follow_orientation_for_portrait_display(
        x_position: int,
        y_position: int,
        expected_focus: tuple[float, float],
) -> None:
    metadata: dict[str, Any] = {
        'Make': 'Canon',
        'AFAreaXPositions': f'{x_position} 0 0',
        'AFAreaYPositions': f'{y_position} 0 0',
        'AFPointsSelected': '1 0 0',
        'AFImageWidth': 5472,
        'AFImageHeight': 3648,
        'CanonImageWidth': 5472,
        'CanonImageHeight': 3648,
        'Orientation': 8,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 5472, 3648
    ) == pytest.approx(expected_focus)


@pytest.mark.parametrize(
    'metadata',
    [
        pytest.param(
            {
                'Make': 'Canon',
                'AFAreaXPositions': '100 200',
                'AFAreaYPositions': '300',
                'FocusLocation': '1600 800',
                'ImageWidth': 4000,
                'ImageHeight': 2000,
            },
            id='mismatched-arrays',
        ),
        pytest.param(
            {
                'Make': 'Canon',
                'AFAreaXPositions': '100 200',
                'AFAreaYPositions': '300 400',
                'AFPointsSelected': '0 0',
                'FocusLocation': '1600 800',
                'ImageWidth': 4000,
                'ImageHeight': 2000,
            },
            id='no-selected-index',
        ),
    ],
)
def test_canon_unusable_arrays_suppress_generic_fallback(
        metadata: dict[str, Any],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata, 4000, 2000
    ) == (
        0.5,
        0.5,
    )
