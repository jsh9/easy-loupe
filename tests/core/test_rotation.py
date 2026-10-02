from __future__ import annotations

import pytest

from easy_loupe.core.autofocus_points.utils import apply_orientation_to_point
from easy_loupe.core.rotation import (
    normalize_rotation,
    rotate_normalized_point,
    step_rotation,
)


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        pytest.param(0, 0, id='no-rotation'),
        pytest.param(90, 90, id='quarter-turn'),
        pytest.param(180, 180, id='half-turn'),
        pytest.param(270, 270, id='three-quarter-turn'),
        pytest.param(True, None, id='bool-is-not-a-rotation'),
        pytest.param(45, None, id='not-a-quarter-turn'),
        pytest.param(-90, None, id='negative-degrees'),
        pytest.param(360, None, id='full-turn-is-not-stored'),
        pytest.param('90', None, id='string-degrees'),
        pytest.param(90.0, None, id='float-degrees'),
        pytest.param(None, None, id='missing'),
    ],
)
def test_normalize_rotation_accepts_only_quarter_turn_integers(
        value: object, expected: int | None
) -> None:
    """
    Verify persisted rotation values are strictly validated.

    ``easy-loupe.json`` can be hand-edited or written by another tool, so
    loading must ignore anything that is not an exact supported quarter turn.
    ``bool`` needs its own case because it subclasses ``int``.
    """
    assert normalize_rotation(value) == expected


@pytest.mark.parametrize(
    ('rotation', 'quarter_turns', 'expected'),
    [
        pytest.param(0, 1, 90, id='clockwise-from-zero'),
        pytest.param(270, 1, 0, id='clockwise-wraps-to-zero'),
        pytest.param(0, -1, 270, id='counterclockwise-wraps-to-270'),
        pytest.param(180, -1, 90, id='counterclockwise-step'),
        pytest.param(90, 4, 90, id='full-turn-is-identity'),
    ],
)
def test_step_rotation_wraps_in_both_directions(
        rotation: int, quarter_turns: int, expected: int
) -> None:
    """
    Verify ``]`` and ``[`` style quarter-turn steps always stay within 0..270.

    The UI derives undo snapshots from these values, so wrapping must be exact
    in both directions instead of producing 360 or negative degrees.
    """
    assert step_rotation(rotation, quarter_turns) == expected


@pytest.mark.parametrize(
    ('rotation', 'exif_orientation'),
    [
        pytest.param(0, 1, id='no-rotation'),
        pytest.param(90, 6, id='quarter-turn-matches-exif-6'),
        pytest.param(180, 3, id='half-turn-matches-exif-3'),
        pytest.param(270, 8, id='three-quarter-turn-matches-exif-8'),
    ],
)
@pytest.mark.parametrize(
    'point',
    [(0.25, 0.1), (0.9, 0.6), (0.5, 0.5), (0.0, 1.0)],
    ids=['top-left-area', 'right-lower-area', 'center', 'corner'],
)
def test_rotate_normalized_point_matches_exif_orientation_mapping(
        rotation: int,
        exif_orientation: int,
        point: tuple[float, float],
) -> None:
    """
    Verify view rotation maps AF points the same way EXIF orientation does.

    AF extraction already relies on ``apply_orientation_to_point`` for camera
    orientation; view rotation must use the same convention so AF markers stay
    on the same subject after ``]`` turns the photo.
    """
    assert rotate_normalized_point(point, rotation) == pytest.approx(
        apply_orientation_to_point(point[0], point[1], exif_orientation)
    )


def test_rotate_normalized_point_moves_left_edge_to_top() -> None:
    """
    Verify a clockwise quarter turn moves the left edge to the top edge.

    This pins the on-screen direction independently from the EXIF table so a
    swapped clockwise/counterclockwise mapping cannot pass unnoticed.
    """
    assert rotate_normalized_point((0.0, 0.5), 90) == pytest.approx((
        0.5,
        0.0,
    ))
