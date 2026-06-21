"""Photo metadata filter state and popup UI helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from easy_loupe.core.records import (
    COLOR_LABEL_ORDER,
    FLAG_ORDER,
    MAX_RATING,
    MIN_RATING,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from easy_loupe.core.records import PhotoRecord

RatingFilterValue = int | None
ColorLabelFilterValue = str | None
FlagFilterValue = str | None


@dataclass(frozen=True, slots=True)
class PhotoFilterOption:
    """Display label and normalized value for one filter checkbox."""

    label: str
    value: Any
    object_suffix: str


def _metadata_value_label(value: str) -> str:
    """Return readable UI text for a slug-style metadata value."""
    return value.replace('_', ' ').title()


def _metadata_object_suffix(value: str) -> str:
    """Return a space-free Qt object suffix for stable widget lookup."""
    return ''.join(part.title() for part in value.split('_'))


RATING_FILTER_OPTIONS: tuple[PhotoFilterOption, ...] = (
    PhotoFilterOption('Not rated', None, 'None'),
    *(
        PhotoFilterOption(
            f'{rating} Star' if rating == 1 else f'{rating} Stars',
            rating,
            str(rating),
        )
        for rating in range(MIN_RATING, MAX_RATING + 1)
    ),
)
COLOR_LABEL_FILTER_OPTIONS: tuple[PhotoFilterOption, ...] = (
    PhotoFilterOption('No color label', None, 'None'),
    *(
        PhotoFilterOption(
            _metadata_value_label(color_label),
            color_label,
            _metadata_object_suffix(color_label),
        )
        for color_label in COLOR_LABEL_ORDER
    ),
)
FLAG_FILTER_OPTIONS: tuple[PhotoFilterOption, ...] = (
    PhotoFilterOption('Not flagged', None, 'None'),
    *(
        PhotoFilterOption(
            _metadata_value_label(flag), flag, _metadata_object_suffix(flag)
        )
        for flag in FLAG_ORDER
    ),
)

ALL_RATING_FILTER_VALUES = frozenset(
    cast('RatingFilterValue', option.value) for option in RATING_FILTER_OPTIONS
)
ALL_COLOR_LABEL_FILTER_VALUES = frozenset(
    cast('ColorLabelFilterValue', option.value)
    for option in COLOR_LABEL_FILTER_OPTIONS
)
ALL_FLAG_FILTER_VALUES = frozenset(
    cast('FlagFilterValue', option.value) for option in FLAG_FILTER_OPTIONS
)


@dataclass(frozen=True, slots=True)
class PhotoFilterSelection:
    """Selected metadata values that remain visible in the culling UI."""

    allowed_ratings: frozenset[RatingFilterValue] = ALL_RATING_FILTER_VALUES
    allowed_color_labels: frozenset[ColorLabelFilterValue] = (
        ALL_COLOR_LABEL_FILTER_VALUES
    )
    allowed_flags: frozenset[FlagFilterValue] = ALL_FLAG_FILTER_VALUES

    def __post_init__(self) -> None:
        ratings = frozenset(self.allowed_ratings)
        color_labels = frozenset(self.allowed_color_labels)
        flags = frozenset(self.allowed_flags)
        _validate_values(
            ratings,
            allowed_values=ALL_RATING_FILTER_VALUES,
            value_name='rating',
        )
        _validate_values(
            color_labels,
            allowed_values=ALL_COLOR_LABEL_FILTER_VALUES,
            value_name='color label',
        )
        _validate_values(
            flags,
            allowed_values=ALL_FLAG_FILTER_VALUES,
            value_name='flag',
        )
        object.__setattr__(self, 'allowed_ratings', ratings)
        object.__setattr__(self, 'allowed_color_labels', color_labels)
        object.__setattr__(self, 'allowed_flags', flags)

    @classmethod
    def default(cls) -> PhotoFilterSelection:
        """Return the all-values-selected filter state."""
        return cls()

    def is_default(self) -> bool:
        """Return whether this filter allows every metadata state."""
        return (
            self.allowed_ratings == ALL_RATING_FILTER_VALUES
            and self.allowed_color_labels == ALL_COLOR_LABEL_FILTER_VALUES
            and self.allowed_flags == ALL_FLAG_FILTER_VALUES
        )

    def matches(self, photo: PhotoRecord) -> bool:
        """Return whether ``photo`` should remain visible."""
        return (
            photo.rating in self.allowed_ratings
            and photo.color_label in self.allowed_color_labels
            and photo.flag in self.allowed_flags
        )


def create_photo_filter_menu(
        parent: QWidget | None,
        selection: PhotoFilterSelection,
        on_confirm: Callable[[PhotoFilterSelection], None],
) -> QMenu:
    """Build a one-shot filter popup initialized from ``selection``."""
    menu = QMenu(parent)
    menu.setObjectName('photoFilterMenu')
    panel = QWidget(menu)
    panel.setObjectName('photoFilterPanel')
    layout = QVBoxLayout(panel)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)

    rating_items = _add_checkbox_group(
        panel,
        layout,
        title='Rating',
        options=RATING_FILTER_OPTIONS,
        checked_values=selection.allowed_ratings,
        object_prefix='photoFilterRating',
        empty_button_label='Select not rated',
    )
    color_items = _add_checkbox_group(
        panel,
        layout,
        title='Color Label',
        options=COLOR_LABEL_FILTER_OPTIONS,
        checked_values=selection.allowed_color_labels,
        object_prefix='photoFilterColor',
        empty_button_label='Select no color label',
    )
    flag_items = _add_checkbox_group(
        panel,
        layout,
        title='Flag',
        options=FLAG_FILTER_OPTIONS,
        checked_values=selection.allowed_flags,
        object_prefix='photoFilterFlag',
        empty_button_label='Select not flagged',
    )

    button_row = QWidget(panel)
    button_layout = QHBoxLayout(button_row)
    button_layout.setContentsMargins(0, 0, 0, 0)
    button_layout.addStretch(1)
    confirm_button = QPushButton('Confirm', button_row)
    confirm_button.setObjectName('photoFilterConfirmButton')
    button_layout.addWidget(confirm_button)
    layout.addWidget(button_row)

    confirmed = False

    def confirm_filter() -> None:
        nonlocal confirmed
        if confirmed:
            return

        confirmed = True
        next_selection = PhotoFilterSelection(
            allowed_ratings=cast(
                'frozenset[RatingFilterValue]',
                _checked_values(rating_items),
            ),
            allowed_color_labels=cast(
                'frozenset[ColorLabelFilterValue]',
                _checked_values(color_items),
            ),
            allowed_flags=cast(
                'frozenset[FlagFilterValue]',
                _checked_values(flag_items),
            ),
        )
        on_confirm(next_selection)
        menu.close()

    confirm_button.clicked.connect(confirm_filter)
    key_filter = _ConfirmFilterKeyFilter(confirm_filter, panel)
    for widget in (menu, panel, *panel.findChildren(QWidget)):
        widget.installEventFilter(key_filter)

    action = QWidgetAction(menu)
    action.setDefaultWidget(panel)
    menu.addAction(action)
    return menu


def _validate_values(
        values: frozenset[Any],
        *,
        allowed_values: frozenset[Any],
        value_name: str,
) -> None:
    invalid_values = values - allowed_values
    if invalid_values:
        raise ValueError(f'Unknown {value_name} filter values')


class _ConfirmFilterKeyFilter(QObject):
    def __init__(
            self,
            on_confirm: Callable[[], None],
            parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._on_confirm = on_confirm

    def eventFilter(  # noqa: N802
            self, _watched: QObject, event: QEvent
    ) -> bool:
        if (
            isinstance(event, QKeyEvent)
            and event.type() == QEvent.KeyPress
            and event.key() in {Qt.Key_Return, Qt.Key_Enter}
        ):
            self._on_confirm()
            return True

        return super().eventFilter(_watched, event)


def _add_checkbox_group(
        parent: QWidget,
        layout: QVBoxLayout,
        *,
        title: str,
        options: Sequence[PhotoFilterOption],
        checked_values: frozenset[Any],
        object_prefix: str,
        empty_button_label: str,
) -> list[tuple[QCheckBox, Any]]:
    group = QGroupBox(title, parent)
    group.setObjectName(f'{object_prefix}Group')
    group_layout = QVBoxLayout(group)
    group_layout.setContentsMargins(10, 10, 10, 10)
    group_layout.setSpacing(4)
    checkbox_items: list[tuple[QCheckBox, Any]] = []
    select_row = QWidget(group)
    select_layout = QHBoxLayout(select_row)
    select_layout.setContentsMargins(0, 0, 0, 0)
    select_layout.setSpacing(6)
    select_all_button = QPushButton('Select all', select_row)
    select_all_button.setObjectName(f'{object_prefix}SelectAll')
    select_none_button = QPushButton('Select none', select_row)
    select_none_button.setObjectName(f'{object_prefix}SelectNone')
    select_empty_button = QPushButton(empty_button_label, select_row)
    select_empty_button.setObjectName(f'{object_prefix}SelectEmpty')
    select_layout.addWidget(select_all_button)
    select_layout.addWidget(select_none_button)
    select_layout.addWidget(select_empty_button)
    select_layout.addStretch(1)
    group_layout.addWidget(select_row)

    for option in options:
        checkbox = QCheckBox(option.label, group)
        checkbox.setObjectName(f'{object_prefix}{option.object_suffix}')
        checkbox.setChecked(option.value in checked_values)
        group_layout.addWidget(checkbox)
        checkbox_items.append((checkbox, option.value))

    layout.addWidget(group)
    select_all_button.clicked.connect(
        lambda _checked=False: _set_checkboxes_checked(
            checkbox_items, checked=True
        )
    )
    select_none_button.clicked.connect(
        lambda _checked=False: _set_checkboxes_checked(
            checkbox_items, checked=False
        )
    )
    select_empty_button.clicked.connect(
        lambda _checked=False: _set_empty_checkbox_checked(checkbox_items)
    )
    return checkbox_items


def _set_checkboxes_checked(
        checkbox_items: list[tuple[QCheckBox, Any]],
        *,
        checked: bool,
) -> None:
    for checkbox, _value in checkbox_items:
        checkbox.setChecked(checked)


def _set_empty_checkbox_checked(
        checkbox_items: list[tuple[QCheckBox, Any]],
) -> None:
    for checkbox, value in checkbox_items:
        checkbox.setChecked(value is None)


def _checked_values(
        checkbox_items: list[tuple[QCheckBox, Any]],
) -> frozenset[Any]:
    return frozenset(
        value for checkbox, value in checkbox_items if checkbox.isChecked()
    )
