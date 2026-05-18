from __future__ import annotations

import pytest

import easy_cull.core.autofocus_points.utils as autofocus_utils_module


@pytest.mark.parametrize(
    ('orientation', 'expected'),
    [
        (1, (0.25, 0.75)),
        (2, (0.75, 0.75)),
        (3, (0.75, 0.25)),
        (4, (0.25, 0.25)),
        (5, (0.75, 0.25)),
        (6, (0.25, 0.25)),
        (7, (0.25, 0.75)),
        (8, (0.75, 0.75)),
        (99, (0.25, 0.75)),
    ],
)
def test_apply_orientation_to_point_handles_exif_orientations(
        orientation: int,
        expected: tuple[float, float],
) -> None:
    assert autofocus_utils_module.apply_orientation_to_point(
        0.25, 0.75, orientation
    ) == pytest.approx(expected)


def test_coerce_number_list_parses_from_strings_and_lists() -> None:
    assert autofocus_utils_module.coerce_number_list('100, 200, 300') == [
        100.0,
        200.0,
        300.0,
    ]
    assert autofocus_utils_module.coerce_number_list('1.5 -2.5') == [
        1.5,
        -2.5,
    ]
    assert autofocus_utils_module.coerce_number_list([
        10,
        '20',
        'bad',
        30.5,
    ]) == [
        10.0,
        20.0,
        30.5,
    ]
    assert autofocus_utils_module.coerce_number_list(42) == []


def test_parse_index_handles_int_float_list_and_string() -> None:
    assert autofocus_utils_module.parse_index(3) == 3
    assert autofocus_utils_module.parse_index(2.7) == 2
    assert autofocus_utils_module.parse_index([5]) == 5
    assert autofocus_utils_module.parse_index('Point 7') == 7
    assert autofocus_utils_module.parse_index(None) is None
    assert autofocus_utils_module.parse_index([]) is None
    assert autofocus_utils_module.parse_index([1, 2]) is None
    assert autofocus_utils_module.parse_index('no digits') is None
