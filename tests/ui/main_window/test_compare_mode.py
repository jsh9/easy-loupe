from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from easy_cull.core.records import METADATA_FILENAME
from easy_cull.ui.main_window.build import VIEWER_KEYBOARD_PAN_STEP
from tests.ui._helpers import create_main_window_with_library

if TYPE_CHECKING:
    from pathlib import Path


def _select_rows(list_widget: object, rows: range | list[int]) -> None:
    list_widget.clearSelection()
    first_item = list_widget.item(rows[0])
    assert first_item is not None
    list_widget.setCurrentItem(first_item)
    for row in rows:
        item = list_widget.item(row)
        assert item is not None
        item.setSelected(True)

    list_widget.setFocus(Qt.OtherFocusReason)


def test_compare_mode_opens_first_eight_selected_photos_and_esc_restores_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that compare mode limits selection and returns to normal view.

    This guards the main compare entry/exit contract: users can over-select,
    compare only the first configured batch, then leave compare without losing
    the surrounding view-mode chrome.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_{index:04d}', 'dimgray') for index in range(10)],
    )

    _select_rows(window.thumbnail_list, range(9))
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.content_splitter.isVisible() is True
    assert window.thumbnail_list.isVisible() is False
    assert window.scene_list.isVisible() is False
    assert window.viewer_stack.currentWidget() is window.compare_viewer
    assert window.compare_viewer.photo_ids() == [
        f'IMG_{index:04d}' for index in range(8)
    ]

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False
    assert window.viewer_stack.currentWidget() is window.viewer
    assert window.content_splitter.isVisible() is True
    assert window.thumbnail_list.isVisible() is True

    window.close()


def test_compare_mode_keyboard_pan_step_scales_with_zoom(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that keyboard panning in compare mode follows each pane's zoom.

    Fixed image-space key steps feel too large at high zoom, and locked compare
    panes can have different zoom factors. This test prevents regressions where
    all panes receive the same raw pan delta regardless of zoom.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9600', 'dimgray'), ('IMG_9601', 'blue')],
    )

    window.viewer.set_fit_view()
    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    first_viewer = window.compare_viewer._viewers[0]
    second_viewer = window.compare_viewer._viewers[1]
    first_viewer.set_manual_view(2.0, (0.5, 0.5))
    second_viewer.set_manual_view(4.0, (0.5, 0.5))
    first_center_before = first_viewer.normalized_viewport_center()
    second_center_before = second_viewer.normalized_viewport_center()

    window._keyboard_pan_by(1, 0)

    assert (
        first_viewer.normalized_viewport_center()[0] - first_center_before[0]
    ) == pytest.approx((VIEWER_KEYBOARD_PAN_STEP / 2.0) / 640)
    assert (
        second_viewer.normalized_viewport_center()[0] - second_center_before[0]
    ) == pytest.approx((VIEWER_KEYBOARD_PAN_STEP / 4.0) / 640)

    window.compare_viewer.lock_zoom_button.setChecked(False)
    window.compare_viewer.set_active_photo_id('IMG_9601')
    first_viewer.set_manual_view(2.0, (0.5, 0.5))
    second_viewer.set_manual_view(4.0, (0.5, 0.5))
    first_center_before = first_viewer.normalized_viewport_center()
    second_center_before = second_viewer.normalized_viewport_center()

    window._keyboard_pan_by(1, 0)

    assert first_viewer.normalized_viewport_center() == pytest.approx(
        first_center_before
    )
    assert (
        second_viewer.normalized_viewport_center()[0] - second_center_before[0]
    ) == pytest.approx((VIEWER_KEYBOARD_PAN_STEP / 4.0) / 640)

    window.close()


def test_compare_mode_expands_selected_scene_stack_cover_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify selected scene-stack covers expand to their scene photos.

    The left strip can represent a whole scene as one item. Compare must open
    the photos inside that stack, not just the cover image, or scene-oriented
    culling would silently compare too little.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9100', 'dimgray'),
            ('IMG_9101', 'blue'),
            ('IMG_9102', 'green'),
        ],
        scene_groups=[['IMG_9100', 'IMG_9101', 'IMG_9102']],
    )

    _select_rows(window.thumbnail_list, [0])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        'IMG_9100',
        'IMG_9101',
        'IMG_9102',
    ]
    assert window.scene_list.isVisible() is False

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.scene_list.isVisible() is True

    window.close()


def test_compare_shortcut_works_immediately_after_initial_folder_load(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that compare mode is available after loading a folder.

    A previous shortcut-state bug required entering browse mode before ``C``
    worked. This test keeps the initial load path wired to compare shortcuts.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9300', 'dimgray'),
            ('IMG_9301', 'blue'),
            ('IMG_9302', 'green'),
        ],
    )

    assert window.compare_mode_shortcut.isEnabled() is True

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == ['IMG_9300', 'IMG_9301']

    window.close()


def test_compare_mode_arrow_selection_tags_only_active_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that arrow navigation in compare mode sets the tag target.

    Compare mode hides the normal strips, so metadata shortcuts must apply to
    the visibly active pane. This protects against accidentally tagging every
    compared photo or a stale pre-compare selection.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9400', 'dimgray'),
            ('IMG_9401', 'blue'),
            ('IMG_9402', 'green'),
        ],
    )
    _select_rows(window.thumbnail_list, [0, 1, 2])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    assert window.compare_viewer.active_photo_id() == 'IMG_9400'

    QTest.keyClick(window, Qt.Key_Right)
    app.processEvents()

    assert window.compare_viewer.active_photo_id() == 'IMG_9401'
    assert window.current_photo_id == 'IMG_9401'

    window.rating_actions[4].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9400').rating is None
    assert window.library.get_photo('IMG_9401').rating == 4
    assert window.library.get_photo('IMG_9402').rating is None
    assert window.metadata_label.text() == ''
    assert (
        window.compare_viewer
        ._metadata_labels[0]
        .text()
        .startswith('<span style="color: transparent;">')
    )
    assert '★★★★☆' in window.compare_viewer._metadata_labels[1].text()

    window.close()


def test_compare_mode_g_enters_browse_with_compared_photos_selected(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ``G`` leaves compare for browse with compared photos selected.

    Users often compare a subset and then continue culling that same subset in
    browse mode. The active pane should become current while the whole compared
    set remains selected.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9500', 'dimgray'),
            ('IMG_9501', 'blue'),
            ('IMG_9502', 'green'),
        ],
    )
    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    QTest.keyClick(window, Qt.Key_Right)
    app.processEvents()
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False
    assert window._browse_mode is True
    assert window.browse_list.isVisible() is True
    assert window.current_photo_id == 'IMG_9501'
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == ['IMG_9500', 'IMG_9501']

    window.close()


def test_compare_mode_esc_from_browse_restores_compared_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ``Esc`` from compare restores the original browse selection.

    Compare entered from browse temporarily hides the browse grid. Exiting with
    ``Esc`` should return users to the same selected working set, not collapse
    the selection to only the active compare photo.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9700', 'dimgray'),
            ('IMG_9701', 'blue'),
            ('IMG_9702', 'green'),
            ('IMG_9703', 'yellow'),
        ],
    )
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    _select_rows(window.browse_list, [0, 1, 2])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    QTest.keyClick(window, Qt.Key_Right)
    app.processEvents()

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.current_photo_id == 'IMG_9701'
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == ['IMG_9700', 'IMG_9701', 'IMG_9702']

    window.close()


def test_compare_mode_g_from_browse_restores_all_compared_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ``G`` from compare keeps every compared browse item selected.

    Setting the current browse row after selecting items can make Qt drop one
    item from an extended selection. This catches that ordering-sensitive bug.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9710', 'dimgray'),
            ('IMG_9711', 'blue'),
            ('IMG_9712', 'green'),
            ('IMG_9713', 'yellow'),
        ],
    )
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    _select_rows(window.browse_list, [0, 1, 2])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    QTest.keyClick(window, Qt.Key_Right)
    app.processEvents()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.current_photo_id == 'IMG_9711'
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == ['IMG_9710', 'IMG_9711', 'IMG_9712']

    window.close()


def test_metadata_assignment_targets_multi_selection_with_undo_and_redo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify metadata batches apply to multi-selection and undo/redo.

    Multi-selection changes are persisted as one batch. This test protects the
    selection-aware assignment behavior and the in-memory metadata history used
    to restore saved JSON contents.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9200', 'dimgray'),
            ('IMG_9201', 'blue'),
            ('IMG_9202', 'green'),
        ],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()

    window.rating_actions[5].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9200').rating == 5
    assert window.library.get_photo('IMG_9201').rating == 5
    assert window.library.get_photo('IMG_9202').rating is None
    assert window.undo_metadata_action.isEnabled() is True
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    ) == {
        'IMG_9200': {'rating': 5},
        'IMG_9201': {'rating': 5},
    }

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9200').rating is None
    assert window.library.get_photo('IMG_9201').rating is None
    assert window.redo_metadata_action.isEnabled() is True
    assert (
        json.loads((tmp_path / METADATA_FILENAME).read_text(encoding='utf-8'))
        == {}
    )

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9200').rating == 5
    assert window.library.get_photo('IMG_9201').rating == 5

    window.close()
