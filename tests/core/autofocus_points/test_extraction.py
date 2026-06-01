from __future__ import annotations

from typing import Any

import pytest

import easy_loupe.core.autofocus_points as autofocus_points_module
from tests.core.autofocus_points._helpers import first_int


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'FocusLocation': {'x': 1600, 'y': 800},
                'ExifImageWidth': '4000',
                'ExifImageHeight': '2000',
            },
            (0.4, 0.4),
        ),
        (
            {
                'AFAreaCenter': '3000, 1000',
                'ImageWidth': 4000,
                'ImageHeight': 2000,
            },
            (0.75, 0.5),
        ),
        ({'AFPointPosition': [0.2, 0.8]}, (0.2, 0.8)),
        (
            {
                'Make': 'Generic Camera',
                'AFAreaXPositions': [100, 700, 1900],
                'AFAreaYPositions': [200, 900, 1500],
                'AFPointsUsed': '2',
                'RawImageWidth': 2000,
                'RawImageHeight': 2000,
            },
            (0.95, 0.75),
        ),
        (
            {
                'AFImagePosition': {'left': 4500, 'top': -50},
                'ImageWidth': 4000,
                'ImageHeight': 2000,
            },
            (1.0, 0.0),
        ),
        (
            {
                'Make': 'SONY',
                'FocusLocation': '7008 4672 1 1',
                'FocusLocation2': '7008 4672 3504 2336',
                'ImageWidth': 7008,
                'ImageHeight': 4672,
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'SONY',
                'FocusLocation2': '7008 4672 4774 2822',
                'ImageWidth': 7008,
                'ImageHeight': 4672,
                'Orientation': 8,
            },
            (2822 / 4672, 1 - (4774 / 7008)),
        ),
    ],
)
def test_extract_focus_point_from_supported_exif_shapes(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata,
        first_int(metadata, ['ImageWidth', 'ExifImageWidth', 'RawImageWidth']),
        first_int(
            metadata, ['ImageHeight', 'ExifImageHeight', 'RawImageHeight']
        ),
    ) == pytest.approx(expected_focus)


def test_missing_focus_metadata_falls_back_to_image_center() -> None:
    assert autofocus_points_module.extract_focus_point(
        {'ImageWidth': 4000, 'ImageHeight': 3000}, 4000, 3000
    ) == (0.5, 0.5)


def test_non_sony_two_value_focus_location_uses_generic_parser() -> None:
    metadata = {
        'Make': 'NIKON CORPORATION',
        'FocusLocation': '1600 800',
        'ImageWidth': 4000,
        'ImageHeight': 2000,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 4000, 2000
    ) == pytest.approx((0.4, 0.4))


def test_non_panasonic_af_point_position_uses_generic_parser() -> None:
    metadata = {
        'Make': 'NIKON CORPORATION',
        'AFPointPosition': '1600 800',
        'ImageWidth': 4000,
        'ImageHeight': 2000,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 4000, 2000
    ) == pytest.approx((0.4, 0.4))


def test_non_nikon_paired_af_area_position_uses_generic_parser() -> None:
    metadata = {
        'Make': 'Generic Camera',
        'AFAreaXPosition': 936,
        'AFAreaYPosition': 2446,
        'ImageWidth': 5600,
        'ImageHeight': 3728,
        'Orientation': 8,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 5600, 3728
    ) == pytest.approx((936 / 5600, 2446 / 3728))
