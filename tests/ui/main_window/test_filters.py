from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QPushButton

from easy_loupe.core.records import (
    COLOR_LABELS,
    FLAGS,
    MAX_RATING,
    MIN_RATING,
)
from easy_loupe.ui.main_window.filters import (
    PhotoFilterSelection,
    _metadata_object_suffix,
    _metadata_value_label,
    create_photo_filter_menu,
)
from tests.ui._helpers import (
    create_jpeg,
    create_main_window_with_library,
    make_photo_record,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _collect_photo_ids_from_list(list_widget: Any) -> list[str]:
    return [
        str(list_widget.item(index).data(Qt.UserRole))
        for index in range(list_widget.count())
    ]


def _checkbox(menu: Any, object_name: str) -> QCheckBox:
    checkbox = menu.findChild(QCheckBox, object_name)
    assert checkbox is not None
    return checkbox


def _button(menu: Any, object_name: str) -> QPushButton:
    button = menu.findChild(QPushButton, object_name)
    assert button is not None
    return button


def _group_checkboxes(menu: Any, object_prefix: str) -> list[QCheckBox]:
    checkboxes = [
        checkbox
        for checkbox in menu.findChildren(QCheckBox)
        if checkbox.objectName().startswith(object_prefix)
    ]
    assert checkboxes
    return checkboxes


def _set_only_checked(menu: Any, object_names: set[str]) -> None:
    checkboxes = menu.findChildren(QCheckBox)
    assert checkboxes
    for checkbox in checkboxes:
        checkbox.setChecked(checkbox.objectName() in object_names)


def _set_metadata(
        window: Any,
        photo_id: str,
        *,
        rating: int | None,
        color_label: str | None,
        flag: str | None,
) -> None:
    photo = window.library.get_photo(photo_id)
    photo.rating = rating
    photo.color_label = color_label
    photo.flag = flag


def test_photo_filter_selection_matches_metadata_values() -> None:
    """Verify filtering handles tagged values and explicit empty states."""
    selection = PhotoFilterSelection(
        allowed_ratings=frozenset({None, 3, 4, 5}),
        allowed_color_labels=frozenset({None, 'red', 'green'}),
        allowed_flags=frozenset({'picked'}),
    )

    assert selection.matches(make_photo_record('IMG_1000', 3, 'red', 'picked'))
    assert selection.matches(
        make_photo_record('IMG_1001', None, None, 'picked')
    )
    assert not selection.matches(
        make_photo_record('IMG_1002', 2, 'red', 'picked')
    )
    assert not selection.matches(
        make_photo_record('IMG_1003', 5, 'blue', 'picked')
    )
    assert not selection.matches(
        make_photo_record('IMG_1004', 5, 'green', None)
    )

    assert PhotoFilterSelection.default().is_default() is True


def test_photo_filter_default_covers_core_metadata_domains() -> None:
    """
    Verify default filtering remains aligned with valid metadata values.

    The all-selected state is the no-filter state, so it must include every
    core metadata value to avoid hiding future valid labels or flags by
    default.
    """
    selection = PhotoFilterSelection.default()

    assert selection.allowed_ratings == frozenset({
        None,
        *range(MIN_RATING, MAX_RATING + 1),
    })
    assert selection.allowed_color_labels == frozenset({None, *COLOR_LABELS})
    assert selection.allowed_flags == frozenset({None, *FLAGS})


def test_photo_filter_value_labels_and_object_suffixes_are_distinct() -> None:
    """
    Verify future multi-word metadata values keep stable object names.

    Display labels should be readable, while Qt object suffixes must avoid
    spaces so tests and object-name lookups remain predictable.
    """
    assert _metadata_value_label('dark_orange') == 'Dark Orange'
    assert _metadata_object_suffix('dark_orange') == 'DarkOrange'
    assert _metadata_value_label('green') == 'Green'
    assert _metadata_object_suffix('green') == 'Green'


def test_photo_filter_menu_defaults_to_all_options_checked() -> None:
    """Verify the popup starts as a non-filtering all-values selection."""
    app = QApplication.instance() or QApplication([])
    captured: list[PhotoFilterSelection] = []
    menu = create_photo_filter_menu(
        None, PhotoFilterSelection.default(), captured.append
    )

    assert all(
        checkbox.isChecked() for checkbox in menu.findChildren(QCheckBox)
    )
    assert _checkbox(menu, 'photoFilterRatingNone').text() == 'Not rated'
    assert _checkbox(menu, 'photoFilterColorNone').text() == 'No color label'
    assert _checkbox(menu, 'photoFilterFlagNone').text() == 'Not flagged'

    confirm_button = menu.findChild(QPushButton, 'photoFilterConfirmButton')
    assert confirm_button is not None
    confirm_button.click()

    assert captured == [PhotoFilterSelection.default()]
    del app


def test_photo_filter_group_bulk_buttons_update_only_their_group() -> None:
    """
    Verify each group can select or clear all pending checkbox values.

    Bulk controls should help users edit the open popup without applying the
    filter until Confirm is clicked, and each pair must leave other groups
    unchanged.
    """
    app = QApplication.instance() or QApplication([])
    captured: list[PhotoFilterSelection] = []
    menu = create_photo_filter_menu(
        None, PhotoFilterSelection.default(), captured.append
    )

    group_prefixes = (
        'photoFilterRating',
        'photoFilterColor',
        'photoFilterFlag',
    )
    for target_prefix in group_prefixes:
        _button(menu, f'{target_prefix}SelectNone').click()
        for prefix in group_prefixes:
            expected_checked = prefix != target_prefix
            assert all(
                checkbox.isChecked() is expected_checked
                for checkbox in _group_checkboxes(menu, prefix)
            )

        _button(menu, f'{target_prefix}SelectAll').click()
        assert all(
            checkbox.isChecked() for checkbox in menu.findChildren(QCheckBox)
        )

    _button(menu, 'photoFilterRatingSelectNone').click()
    _button(menu, 'photoFilterFlagSelectNone').click()
    _button(menu, 'photoFilterConfirmButton').click()

    assert captured == [
        PhotoFilterSelection(
            allowed_ratings=frozenset(),
            allowed_color_labels=frozenset({
                None,
                'red',
                'yellow',
                'green',
                'blue',
                'purple',
            }),
            allowed_flags=frozenset(),
        )
    ]
    del app


def test_photo_filter_empty_buttons_update_only_their_group() -> None:
    """
    Verify empty-state shortcuts select only the group's explicit None value.

    These controls reduce repetitive checkbox edits while preserving the
    popup's pending-state contract until the user confirms the selection.
    """
    app = QApplication.instance() or QApplication([])
    captured: list[PhotoFilterSelection] = []
    menu = create_photo_filter_menu(
        None, PhotoFilterSelection.default(), captured.append
    )

    group_prefixes = (
        'photoFilterRating',
        'photoFilterColor',
        'photoFilterFlag',
    )
    none_checkboxes = {
        'photoFilterRating': 'photoFilterRatingNone',
        'photoFilterColor': 'photoFilterColorNone',
        'photoFilterFlag': 'photoFilterFlagNone',
    }
    for target_prefix in group_prefixes:
        other_states = {
            prefix: [
                checkbox.isChecked()
                for checkbox in _group_checkboxes(menu, prefix)
            ]
            for prefix in group_prefixes
            if prefix != target_prefix
        }

        _button(menu, f'{target_prefix}SelectEmpty').click()
        assert [
            checkbox.objectName()
            for checkbox in _group_checkboxes(menu, target_prefix)
            if checkbox.isChecked()
        ] == [none_checkboxes[target_prefix]]
        for prefix, expected_states in other_states.items():
            assert [
                checkbox.isChecked()
                for checkbox in _group_checkboxes(menu, prefix)
            ] == expected_states

        _button(menu, f'{target_prefix}SelectAll').click()
        assert all(
            checkbox.isChecked() for checkbox in menu.findChildren(QCheckBox)
        )

    _button(menu, 'photoFilterRatingSelectEmpty').click()
    _button(menu, 'photoFilterColorSelectEmpty').click()
    _button(menu, 'photoFilterFlagSelectEmpty').click()
    _button(menu, 'photoFilterConfirmButton').click()

    assert captured == [
        PhotoFilterSelection(
            allowed_ratings=frozenset({None}),
            allowed_color_labels=frozenset({None}),
            allowed_flags=frozenset({None}),
        )
    ]
    del app


def test_photo_filter_menu_enter_confirms_pending_selection() -> None:
    """
    Verify Return/Enter uses the same confirmation path as the button.

    The popup is edited through pending checkbox state, so keyboard confirm
    must emit exactly one selection and close without applying intermediate
    changes.
    """
    app = QApplication.instance() or QApplication([])
    captured: list[PhotoFilterSelection] = []
    menu = create_photo_filter_menu(
        None, PhotoFilterSelection.default(), captured.append
    )
    _set_only_checked(
        menu,
        {
            'photoFilterRating3',
            'photoFilterColorGreen',
            'photoFilterFlagPicked',
        },
    )

    menu.show()
    app.processEvents()
    focused_checkbox = _checkbox(menu, 'photoFilterColorGreen')
    focused_checkbox.setFocus()
    app.processEvents()
    QTest.keyClick(focused_checkbox, Qt.Key_Return)
    app.processEvents()

    assert captured == [
        PhotoFilterSelection(
            allowed_ratings=frozenset({3}),
            allowed_color_labels=frozenset({'green'}),
            allowed_flags=frozenset({'picked'}),
        )
    ]
    menu.close()
    del app


def test_filter_button_is_push_button(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify the top-bar Filter control matches neighboring button widgets."""
    _, _app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_1900', 'red')],
    )

    assert isinstance(window.filter_button, QPushButton)
    assert window.filter_button.objectName() == 'photoFilterButton'
    assert window.filter_button.text() == 'Filter'

    window.close()


def test_filter_popup_applies_rating_color_and_flag_criteria(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify confirmed filter choices hide non-matching photos in both lists.

    This covers the requested rating 3-5, red/green, picked workflow through
    the popup control rather than only calling the filter setter directly.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_2000', 'red'),
            ('IMG_2001', 'green'),
            ('IMG_2002', 'blue'),
            ('IMG_2003', 'yellow'),
            ('IMG_2004', 'purple'),
        ],
    )
    _set_metadata(
        window, 'IMG_2000', rating=3, color_label='red', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2001', rating=5, color_label='green', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2002', rating=2, color_label='red', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2003', rating=4, color_label='blue', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2004', rating=4, color_label='green', flag='rejected'
    )

    menu = window._build_photo_filter_menu()
    _set_only_checked(
        menu,
        {
            'photoFilterRating3',
            'photoFilterRating4',
            'photoFilterRating5',
            'photoFilterColorRed',
            'photoFilterColorGreen',
            'photoFilterFlagPicked',
        },
    )
    confirm_button = menu.findChild(QPushButton, 'photoFilterConfirmButton')
    assert confirm_button is not None
    confirm_button.click()
    app.processEvents()

    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2000',
        'IMG_2001',
    ]
    assert _collect_photo_ids_from_list(window.browse_list) == [
        'IMG_2000',
        'IMG_2001',
    ]
    assert len(window.library.photos) == 5
    assert window.filter_button.text() == 'Filter (2/5)'
    assert window.current_photo_id == 'IMG_2000'

    window.close()


def test_filter_empty_result_clears_current_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify an active filter can show an empty but still loaded workspace."""
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_2100', 'red'), ('IMG_2101', 'green')],
    )
    _set_metadata(
        window, 'IMG_2100', rating=3, color_label='red', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2101', rating=4, color_label='green', flag='picked'
    )

    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({5}),
            allowed_color_labels=frozenset({'purple'}),
            allowed_flags=frozenset({'rejected'}),
        )
    )
    app.processEvents()

    assert window.current_photo_id is None
    assert window.viewer._current_image_path is None
    assert window.thumbnail_list.count() == 0
    assert window.browse_list.count() == 0
    assert window.selection_label.text() == (
        'Selection: No photos match filter'
    )
    assert window.filter_button.text() == 'Filter (0/2)'
    assert window.browse_mode_shortcut.isEnabled() is False
    assert window.compare_mode_shortcut.isEnabled() is False

    window.close()


def test_filter_resets_on_folder_load(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify filter state is session-only and clears on a new folder load."""
    first_folder = tmp_path / 'first'
    first_folder.mkdir()
    _, app, window = create_main_window_with_library(
        first_folder,
        monkeypatch,
        photo_specs=[('IMG_2200', 'red'), ('IMG_2201', 'green')],
    )
    _set_metadata(
        window, 'IMG_2200', rating=3, color_label='red', flag='picked'
    )
    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({3}),
            allowed_color_labels=frozenset({'red'}),
            allowed_flags=frozenset({'picked'}),
        )
    )
    assert window.filter_button.text() == 'Filter (1/2)'

    next_folder = tmp_path / 'next'
    next_folder.mkdir()
    create_jpeg(next_folder / 'IMG_2300.JPG', 'blue')
    create_jpeg(next_folder / 'IMG_2301.JPG', 'purple')
    monkeypatch.setattr(
        QFileDialog,
        'getExistingDirectory',
        lambda *_args, **_kwargs: str(next_folder),
    )

    window.choose_folder()
    app.processEvents()

    assert window._photo_filter_selection.is_default() is True
    assert window.filter_button.text() == 'Filter'
    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2300',
        'IMG_2301',
    ]

    window.close()


def test_filter_scene_mode_shows_only_matching_exact_photos(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify scene stacks and scene strips are rebuilt from visible photos."""
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_2400', 'red'),
            ('IMG_2401', 'green'),
            ('IMG_2402', 'blue'),
        ],
        scene_groups=[['IMG_2400', 'IMG_2401', 'IMG_2402']],
    )
    _set_metadata(
        window, 'IMG_2400', rating=3, color_label='red', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2401', rating=2, color_label='blue', flag='rejected'
    )
    _set_metadata(
        window, 'IMG_2402', rating=5, color_label='green', flag='picked'
    )

    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({3, 5}),
            allowed_color_labels=frozenset({'red', 'green'}),
            allowed_flags=frozenset({'picked'}),
        )
    )
    app.processEvents()

    assert _collect_photo_ids_from_list(window.thumbnail_list) == ['IMG_2400']
    assert window.thumbnail_list.item(0).data(Qt.UserRole + 1) == 2
    assert _collect_photo_ids_from_list(window.scene_list) == [
        'IMG_2400',
        'IMG_2402',
    ]
    assert window.merge_scene_action.isEnabled() is False
    context_position = window.thumbnail_list.visualItemRect(
        window.thumbnail_list.item(0)
    ).center()
    assert (
        window._context_scene_from_thumbnail_position(context_position) is None
    )
    before_groups = window.library.scene_group_photo_ids()
    window._merge_selected_photos_into_scene()
    window._break_scene_into_singletons(window.library.scenes[0].scene_id)
    assert window.library.scene_group_photo_ids() == before_groups

    window.close()


def test_filter_metadata_change_hides_newly_non_matching_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify metadata edits under an active filter rebuild visible rows."""
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_2500', 'red'), ('IMG_2501', 'green')],
    )
    _set_metadata(
        window, 'IMG_2500', rating=3, color_label='red', flag='picked'
    )
    _set_metadata(
        window, 'IMG_2501', rating=5, color_label='green', flag='picked'
    )
    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({3, 5}),
            allowed_color_labels=frozenset({'red', 'green'}),
            allowed_flags=frozenset({'picked'}),
        )
    )
    app.processEvents()

    window.flag_actions[None].trigger()
    app.processEvents()

    assert _collect_photo_ids_from_list(window.thumbnail_list) == ['IMG_2501']
    assert _collect_photo_ids_from_list(window.browse_list) == ['IMG_2501']
    assert window.current_photo_id == 'IMG_2501'
    assert window.filter_button.text() == 'Filter (1/2)'

    window.close()


def test_filter_compare_metadata_change_prunes_hidden_active_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered compare mode drops photos hidden by metadata edits.

    Compare mode keeps a separate active-photo grid, so metadata changes must
    reconcile that grid with active filters before Esc can restore normal view.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_2600', 'red'),
            ('IMG_2601', 'green'),
            ('IMG_2602', 'blue'),
        ],
    )
    for photo_id in ('IMG_2600', 'IMG_2601', 'IMG_2602'):
        _set_metadata(
            window, photo_id, rating=3, color_label='red', flag='picked'
        )

    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({3}),
            allowed_color_labels=frozenset({'red'}),
            allowed_flags=frozenset({'picked'}),
        )
    )
    window._restore_photo_selection(['IMG_2600', 'IMG_2601', 'IMG_2602'])
    window._enter_compare_mode()
    app.processEvents()
    assert window._compare_mode is True
    assert window.compare_viewer.active_photo_id() == 'IMG_2600'

    window.flag_actions[None].trigger()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == ['IMG_2601', 'IMG_2602']
    assert window.compare_viewer.active_photo_id() == 'IMG_2601'
    assert _collect_photo_ids_from_list(window.thumbnail_list) == [
        'IMG_2601',
        'IMG_2602',
    ]

    window._exit_compare_mode()
    app.processEvents()

    assert window.current_photo_id == 'IMG_2601'
    assert window.thumbnail_list.currentItem().data(Qt.UserRole) == 'IMG_2601'
    assert window.viewer._current_image_path == (
        window.library.get_preview_path('IMG_2601', 'viewer')
    )

    window.close()


def test_filter_compare_metadata_change_exits_when_too_few_photos_remain(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify filtered compare mode returns to normal view below compare minimum.

    If a metadata edit leaves only one compared photo visible, compare cannot
    stay open and must avoid restoring the newly hidden active photo.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_2700', 'red'), ('IMG_2701', 'green')],
    )
    for photo_id in ('IMG_2700', 'IMG_2701'):
        _set_metadata(
            window, photo_id, rating=3, color_label='red', flag='picked'
        )

    window._apply_photo_filter(
        PhotoFilterSelection(
            allowed_ratings=frozenset({3}),
            allowed_color_labels=frozenset({'red'}),
            allowed_flags=frozenset({'picked'}),
        )
    )
    window._restore_photo_selection(['IMG_2700', 'IMG_2701'])
    window._enter_compare_mode()
    app.processEvents()
    assert window._compare_mode is True

    window.flag_actions[None].trigger()
    app.processEvents()

    assert window._compare_mode is False
    assert window.compare_viewer.photo_ids() == []
    assert window.current_photo_id == 'IMG_2701'
    assert _collect_photo_ids_from_list(window.thumbnail_list) == ['IMG_2701']
    assert window.thumbnail_list.currentItem().data(Qt.UserRole) == 'IMG_2701'
    assert window.viewer._current_image_path == (
        window.library.get_preview_path('IMG_2701', 'viewer')
    )

    window.close()
