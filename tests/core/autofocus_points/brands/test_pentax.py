from __future__ import annotations

from typing import Any

import pytest

import easy_cull.core.autofocus_points as autofocus_points_module


@pytest.mark.parametrize(
    ('metadata', 'expected_focus'),
    [
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'ContrastDetectAFArea': '120 96 72 48',
                'Orientation': 1,
            },
            ((120 + 36) / 720, (96 + 24) / 480),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'ContrastDetectAFArea': '120 96 72 48',
                'Orientation': 8,
            },
            ((96 + 24) / 480, 1 - ((120 + 36) / 720)),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointsInFocus': '85 85 85 93 85 85 85 85 64',
                'AFPointSelected': '17 0',
                'Orientation': 1,
            },
            (0.40, 0.50),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointSelected': '15 5',
                'Orientation': 1,
            },
            (0.40, 0.50),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointSelected': '15 5',
                'Orientation': 8,
            },
            (0.50, 1 - 0.40),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointSelected': str(0xFFFE),
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointSelected': '273 5',
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'ContrastDetectAFArea': '0 0 0 0',
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
        (
            {
                'Make': 'RICOH IMAGING COMPANY, LTD.',
                'Model': 'PENTAX K-1 Mark II',
                'AFPointSelected': 'not a point',
                'FocusLocation': '1600 800',
                'ImageWidth': 4000,
                'ImageHeight': 2000,
                'Orientation': 1,
            },
            (0.5, 0.5),
        ),
    ],
)
def test_pentax_af_point_extraction_uses_documented_maker_note_fields(
        metadata: dict[str, Any],
        expected_focus: tuple[float, float],
) -> None:
    assert autofocus_points_module.extract_focus_point(
        metadata, metadata.get('ImageWidth'), metadata.get('ImageHeight')
    ) == pytest.approx(expected_focus)


def test_non_pentax_af_point_selected_is_not_a_focus_coordinate() -> None:
    metadata = {
        'Make': 'Generic Camera',
        'Model': 'Other',
        'AFPointSelected': '15 5',
        'ImageWidth': 4000,
        'ImageHeight': 2000,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 4000, 2000
    ) == (0.5, 0.5)
