from __future__ import annotations

import easy_cull.core.autofocus_points as autofocus_points_module


def test_sony_malformed_focus_location_does_not_use_dimension_values() -> None:
    metadata = {
        'Make': 'SONY',
        'FocusLocation': '7008 4672',
        'ImageWidth': 7008,
        'ImageHeight': 4672,
        'Orientation': 1,
    }

    assert autofocus_points_module.extract_focus_point(
        metadata, 7008, 4672
    ) == (
        0.5,
        0.5,
    )
