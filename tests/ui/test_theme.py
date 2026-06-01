from __future__ import annotations

import pytest

import easy_loupe.ui.theme as theme_module
from tests.ui._helpers import make_photo_record


def test_metadata_markup_includes_color_label_indicator() -> None:
    photo = make_photo_record(
        'IMG_7200', rating=3, color_label='green', flag='picked'
    )

    markup = theme_module.metadata_markup(photo)

    assert '★★★☆☆' in markup
    assert '●' in markup
    assert theme_module.COLOR_LABEL_SWATCHES['green'] in markup
    assert '✅' in markup

    assert (
        theme_module.metadata_markup(
            make_photo_record(
                'IMG_7201', rating=None, color_label=None, flag=None
            )
        )
        == ''
    )


@pytest.mark.parametrize(
    ('rating', 'color_label', 'flag', 'expected_fragments'),
    [
        pytest.param(3, None, None, ['★★★☆☆'], id='rating-only'),
        pytest.param(None, 'red', None, ['●'], id='color-label-only'),
        pytest.param(None, None, 'rejected', ['❌'], id='rejected-flag'),
        pytest.param(None, None, 'picked', ['✅'], id='picked-flag'),
        pytest.param(
            5,
            'blue',
            'rejected',
            ['★★★★★', '●', '❌'],
            id='all-fields-rejected',
        ),
    ],
)
def test_metadata_markup_covers_partial_field_combinations(
        rating: int | None,
        color_label: str | None,
        flag: str | None,
        expected_fragments: list[str],
) -> None:
    photo = make_photo_record(
        'IMG_9040', rating=rating, color_label=color_label, flag=flag
    )
    markup = theme_module.metadata_markup(photo)

    for fragment in expected_fragments:
        assert fragment in markup


@pytest.mark.parametrize(
    ('rating', 'expected'),
    [
        (None, ''),
        (1, '★☆☆☆☆'),
        (3, '★★★☆☆'),
        (5, '★★★★★'),
    ],
)
def test_rating_symbols_returns_correct_star_pattern(
        rating: int | None, expected: str
) -> None:
    assert theme_module.rating_symbols(rating) == expected


@pytest.mark.parametrize(
    ('flag', 'expected'),
    [('picked', '✅'), ('rejected', '❌'), (None, '')],
)
def test_flag_symbol_returns_correct_indicator(
        flag: str | None, expected: str
) -> None:
    assert theme_module.flag_symbol(flag) == expected


@pytest.mark.parametrize(
    ('label', 'has_dot'),
    [
        ('red', True),
        ('yellow', True),
        ('green', True),
        ('blue', True),
        ('purple', True),
        (None, False),
        ('invalid', False),
    ],
)
def test_color_label_markup_returns_dot_for_valid_labels(
        label: str | None, has_dot: bool
) -> None:
    result = theme_module.color_label_markup(label)

    if has_dot:
        assert '●' in result
        assert theme_module.COLOR_LABEL_SWATCHES[label] in result
    else:
        assert result == ''
