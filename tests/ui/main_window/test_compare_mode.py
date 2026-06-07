"""
Behavior tests for compare-mode flows through the real ``MainWindow``.

``easy_loupe.ui.main_window.compare`` is intentionally covered here instead of
with direct mixin unit tests because compare behavior is the integration of
shortcuts, selection restoration, pane state, and metadata assignment.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt

from easy_loupe.core.records import METADATA_FILENAME
from easy_loupe.ui.main_window.build import VIEWER_KEYBOARD_PAN_STEP
from tests.ui._helpers import (
    create_main_window_with_library,
    set_scene_detection_result,
    thumbnail_overlay,
    trigger_scene_shortcut,
)

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


def _select_rows_with_current(
        list_widget: object, rows: list[int], current_row: int
) -> None:
    """Select rows while preserving a separate current/focus row."""
    list_widget.clearSelection()
    for row in rows:
        item = list_widget.item(row)
        assert item is not None
        item.setSelected(True)

    current_item = list_widget.item(current_row)
    assert current_item is not None
    flags = QItemSelectionModel.SelectionFlag.NoUpdate
    list_widget.selectionModel().setCurrentIndex(
        list_widget.indexFromItem(current_item), flags
    )
    list_widget.setFocus(Qt.OtherFocusReason)


def test_compare_mode_opens_default_limit_and_esc_restores_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify that compare mode uses the default limit and restores view mode.

    This guards the main compare entry/exit contract: users can over-select,
    compare only the default configured batch, then leave compare without
    losing the surrounding view-mode chrome.
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


def test_compare_mode_esc_reloads_viewer_and_overlay_for_active_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify compare exit realigns viewer, strip focus, and minimap target.

    The normal viewer is hidden during compare. Leaving compare must reload it
    for the active compare pane before Space can enter manual zoom; otherwise
    the viewer can zoom one selected photo while the visible-region overlay is
    painted on another.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_99700', 'dimgray'),
            ('IMG_99701', 'blue'),
            ('IMG_99702', 'green'),
        ],
    )

    _select_rows_with_current(window.thumbnail_list, [0, 1, 2], 2)
    app.processEvents()

    assert window.current_photo_id == 'IMG_99702'

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.active_photo_id() == 'IMG_99700'
    assert window.current_photo_id == 'IMG_99700'

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    expected_image_path = window.library.get_preview_path(
        'IMG_99700', 'viewer'
    )

    assert window._compare_mode is False
    assert window.current_photo_id == 'IMG_99700'
    assert window.viewer._current_image_path == expected_image_path
    assert window.thumbnail_list.currentRow() == 0
    assert [
        item.data(Qt.UserRole)
        for item in window.thumbnail_list.selectedItems()
    ] == ['IMG_99700', 'IMG_99701', 'IMG_99702']
    assert thumbnail_overlay(window.thumbnail_list, 0) is None
    assert thumbnail_overlay(window.thumbnail_list, 1) is None
    assert thumbnail_overlay(window.thumbnail_list, 2) is None

    window.space_shortcut.activated.emit()
    app.processEvents()

    visible_region = window.viewer.visible_region_rect()

    assert visible_region is not None
    assert thumbnail_overlay(window.thumbnail_list, 0) == pytest.approx(
        visible_region
    )
    assert thumbnail_overlay(window.thumbnail_list, 1) is None
    assert thumbnail_overlay(window.thumbnail_list, 2) is None

    window.close()


def test_compare_mode_opens_configured_limit_from_overselection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify compare mode honors the configured limit above the old cap.

    The user preference can raise the compare cap beyond eight photos, so entry
    must slice the selected set by the current setting rather than a constant.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'IMG_990{index:02d}', 'dimgray') for index in range(20)
        ],
    )

    window.compare_limit_actions[12].trigger()
    _select_rows(window.thumbnail_list, range(20))
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        f'IMG_990{index:02d}' for index in range(12)
    ]
    assert (window.compare_viewer._rows, window.compare_viewer._columns) == (
        3,
        4,
    )

    window.close()


def test_compare_mode_uses_selection_count_for_grid_below_configured_limit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify sparse selections do not use the configured maximum grid shape.

    A high compare limit should cap only the maximum number of panes; selecting
    three photos should still render the normal 1x3 grid.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_995{index:02d}', 'dimgray') for index in range(5)],
    )

    window.compare_limit_actions[20].trigger()
    _select_rows(window.thumbnail_list, [0, 1, 2])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        f'IMG_995{index:02d}' for index in range(3)
    ]
    assert (window.compare_viewer._rows, window.compare_viewer._columns) == (
        1,
        3,
    )

    window.close()


def test_compare_mode_split_shortcut_shows_no_effect_message(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify split-view shortcut gives feedback instead of silently doing
    nothing.

    Compare mode does not support split view, but the shortcut remains enabled
    so users get an explanatory transient message.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_99600', 'dimgray'), ('IMG_99601', 'blue')],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.split_mode_shortcut.isEnabled() is True

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is False
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        'Split view is not available\nin the Compare mode'
    )
    assert window.transient_message_timer.interval() == 1600

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.transient_message_overlay.isHidden() is True

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False

    window.close()


def test_compare_mode_scene_detection_finish_shows_scene_notice(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-detection completion explains where scenes are visible.

    Scene detection can complete while compare mode remains active, so users
    need a transient hint that scene navigation appears outside compare mode.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_99700', 'dimgray'),
            ('IMG_99701', 'blue'),
            ('IMG_99702', 'green'),
        ],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    set_scene_detection_result(
        window,
        [['IMG_99700', 'IMG_99701'], ['IMG_99702']],
    )

    window._handle_scene_finished()
    app.processEvents()

    assert window._compare_mode is True
    assert window.viewer_stack.currentWidget() is window.compare_viewer
    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_label.text() == (
        'Scene detection completed; you can view scenes'
        ' outside the Compare mode.'
    )
    assert window.transient_message_timer.interval() == 3200

    window.close()


def test_compare_mode_live_limit_increase_updates_grid_and_g_restores_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify changing the compare limit expands the active compare grid.

    Users should see the newly configured limit immediately in compare mode,
    while ``G`` still restores the original full pre-compare selection.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'IMG_991{index:02d}', 'dimgray') for index in range(13)
        ],
    )

    _select_rows(window.thumbnail_list, range(13))
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        f'IMG_991{index:02d}' for index in range(8)
    ]

    window.compare_limit_actions[12].trigger()

    assert window.progress_overlay.isVisible() is True
    assert window.overlay_message_label.text() == (
        'Re-rendering comparison grid...'
    )
    assert window.overlay_progress_bar.isVisible() is False
    assert window.compare_viewer.photo_ids() == [
        f'IMG_991{index:02d}' for index in range(8)
    ]

    app.processEvents()

    assert window.progress_overlay.isHidden() is True
    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == [
        f'IMG_991{index:02d}' for index in range(12)
    ]
    assert (window.compare_viewer._rows, window.compare_viewer._columns) == (
        3,
        4,
    )

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == [f'IMG_991{index:02d}' for index in range(13)]

    window.close()


def test_compare_mode_current_limit_does_not_show_overlay_or_rebuild(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify reselecting the active compare limit is a no-op.

    The re-render overlay should appear only when the visible compare set
    actually changes, and the grid should not rebuild for an unchanged limit.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[(f'IMG_994{index:02d}', 'dimgray') for index in range(8)],
    )
    _select_rows(window.thumbnail_list, range(8))
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    def fail_set_photos(*_args: object, **_kwargs: object) -> None:
        raise AssertionError('compare grid should not rebuild')

    monkeypatch.setattr(window.compare_viewer, 'set_photos', fail_set_photos)

    window.compare_limit_actions[8].trigger()
    app.processEvents()

    assert window.progress_overlay.isHidden() is True
    assert window.overlay_message_label.text() == ''

    window.close()


def test_compare_mode_live_limit_decrease_preserves_visible_active_pane(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify lowering the compare limit keeps a still-visible active pane.

    Rebuilding the compare grid should not reset the active pane when that
    photo remains inside the newly visible capped set.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'IMG_992{index:02d}', 'dimgray') for index in range(12)
        ],
    )

    window.compare_limit_actions[12].trigger()
    _select_rows(window.thumbnail_list, range(12))
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window.compare_viewer.set_active_photo_id('IMG_99205')

    window.compare_limit_actions[8].trigger()
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        f'IMG_992{index:02d}' for index in range(8)
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_99205'
    assert window.current_photo_id == 'IMG_99205'

    window.close()


def test_compare_mode_live_limit_decrease_clamps_active_and_esc_restores_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify lowering the compare limit clamps an active pane that falls out.

    The visible active pane should move to the last remaining photo, but
    ``Esc`` must still restore the full original selection.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'IMG_993{index:02d}', 'dimgray') for index in range(12)
        ],
    )

    window.compare_limit_actions[12].trigger()
    _select_rows(window.thumbnail_list, range(12))
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window.compare_viewer.set_active_photo_id('IMG_99310')

    window.compare_limit_actions[8].trigger()
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        f'IMG_993{index:02d}' for index in range(8)
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_99307'
    assert window.current_photo_id == 'IMG_99307'

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False
    assert [
        item.data(Qt.UserRole)
        for item in window.thumbnail_list.selectedItems()
    ] == [f'IMG_993{index:02d}' for index in range(12)]

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


def test_compare_mode_space_inspects_active_photo_and_esc_returns_to_grid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Space opens one compare pane and Esc returns before exiting compare.

    ``Esc`` has two compare-mode meanings now: leave the selected-photo view
    first, then exit Compare from the grid. This keeps one-photo inspection
    from disrupting the surrounding comparison set.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9650', 'dimgray'), ('IMG_9651', 'slategray')],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window.compare_viewer.set_active_photo_id('IMG_9651')

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.is_selected_photo_view() is True
    assert window.compare_viewer.selected_viewer._mode == 'fit'
    assert window.compare_viewer.active_photo_id() == 'IMG_9651'

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.selected_viewer._mode == 'manual'
    assert (
        window.compare_viewer.selected_viewer._current_scale
        == pytest.approx(1.0)
    )

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.is_selected_photo_view() is False

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False

    window.close()


def test_compare_mode_z_toggles_all_grid_panes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Z carries the old all-pane compare zoom behavior.

    Space now opens the active photo, so the all-photo focus zoom needs its own
    shortcut to preserve synchronized comparison.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9660', 'dimgray'), ('IMG_9661', 'slategray')],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.is_selected_photo_view() is False
    assert all(
        viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()

    assert all(
        not viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.close()


def test_compare_mode_z_toggles_selected_photo_without_changing_grid(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Z zooms the visible selected photo in selected-photo compare view.

    The compare grid is hidden in this sub-mode, so the shortcut should affect
    the visible selected photo instead of silently changing hidden grid panes.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_9670', 'dimgray'), ('IMG_9671', 'slategray')],
    )

    _select_rows(window.thumbnail_list, [0, 1])
    app.processEvents()
    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window.compare_viewer.set_active_photo_id('IMG_9671')

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.is_selected_photo_view() is True
    assert window.compare_viewer.selected_viewer._mode == 'fit'
    assert all(
        not viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.selected_viewer._mode == 'manual'
    assert (
        window.compare_viewer.selected_viewer._current_scale
        == pytest.approx(1.0)
    )
    assert all(
        not viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.zoom_toggle_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.selected_viewer._mode == 'fit'
    assert all(
        not viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.exit_compare_shortcut.activated.emit()
    app.processEvents()

    assert window.compare_viewer.is_selected_photo_view() is False
    assert all(
        not viewer.should_preserve_zoom()
        for viewer in window.compare_viewer._viewers
    )

    window.close()


def test_compare_mode_uses_exact_scene_selection_instead_of_expanding_stack(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-stack cover selection resolves to the exact cover photo.

    Scene mode has two selection surfaces: the vertical strip for scene covers
    and the horizontal strip for photos inside the current scene. This protects
    against accidentally comparing every photo in a scene when the user only
    selected the cover row.
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

    assert window._resolved_selection_photo_ids() == ['IMG_9100']

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is False

    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._compare_mode is True
    assert window.compare_viewer.photo_ids() == ['IMG_9100', 'IMG_9101']
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

    window._compare_nav_shortcuts[1].activated.emit()
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

    window._compare_nav_shortcuts[1].activated.emit()
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


@pytest.mark.parametrize(
    ('exit_shortcut_attr', 'photo_prefix'),
    [
        pytest.param(
            'exit_compare_shortcut', 'IMG_970', id='esc-restores-browse'
        ),
        pytest.param('browse_mode_shortcut', 'IMG_971', id='g-enters-browse'),
    ],
)
def test_compare_mode_from_browse_restores_original_selection(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        exit_shortcut_attr: str,
        photo_prefix: str,
) -> None:
    """
    Verify leaving compare from browse restores the selected working set.

    ``Esc`` and ``G`` use different compare-exit paths, but both must preserve
    the original browse selection and keep the active compare pane current.
    This guards against Qt current-row updates dropping an extended selection.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'{photo_prefix}0', 'dimgray'),
            (f'{photo_prefix}1', 'blue'),
            (f'{photo_prefix}2', 'green'),
            (f'{photo_prefix}3', 'yellow'),
        ],
    )
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    _select_rows(window.browse_list, [0, 1, 2])
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window._compare_nav_shortcuts[1].activated.emit()
    app.processEvents()

    getattr(window, exit_shortcut_attr).activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.current_photo_id == f'{photo_prefix}1'
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == [f'{photo_prefix}0', f'{photo_prefix}1', f'{photo_prefix}2']

    window.close()


def test_compare_mode_g_from_overselected_browse_restores_original_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify ``G`` from compare restores the full pre-compare selection.

    Compare mode caps oversized selections visually, but browse remains the
    place for managing the whole selected set. Leaving compare with ``G`` must
    not silently drop selected photos that were beyond the compare display cap.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'IMG_972{index:02d}', 'dimgray') for index in range(11)
        ],
    )
    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    _select_rows(window.browse_list, range(11))
    app.processEvents()

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window._compare_nav_shortcuts[1].activated.emit()
    app.processEvents()

    assert window.compare_viewer.photo_ids() == [
        f'IMG_972{index:02d}' for index in range(8)
    ]
    assert window.compare_viewer.active_photo_id() == 'IMG_97201'

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is True
    assert window.current_photo_id == 'IMG_97201'
    assert [
        item.data(Qt.UserRole) for item in window.browse_list.selectedItems()
    ] == [f'IMG_972{index:02d}' for index in range(11)]

    window.close()


@pytest.mark.parametrize(
    ('exit_shortcut_attr', 'photo_prefix', 'expected_target'),
    [
        pytest.param(
            'exit_compare_shortcut',
            'IMG_980',
            'scene',
            id='esc-restores-scene',
        ),
        pytest.param(
            'browse_mode_shortcut',
            'IMG_981',
            'browse',
            id='g-enters-browse',
        ),
    ],
)
def test_compare_mode_from_scene_restores_exact_mixed_selection(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        exit_shortcut_attr: str,
        photo_prefix: str,
        expected_target: str,
) -> None:
    """
    Verify scene compare exits preserve mixed exact selections.

    Scene-mode selections can span the vertical scene-stack strip and the
    horizontal in-scene strip. ``Esc`` must restore those widgets directly,
    while ``G`` rebuilds browse mode with the same logical photo set selected.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            (f'{photo_prefix}0', 'dimgray'),
            (f'{photo_prefix}1', 'blue'),
            (f'{photo_prefix}2', 'green'),
            (f'{photo_prefix}3', 'yellow'),
        ],
        scene_groups=[
            [f'{photo_prefix}0', f'{photo_prefix}1'],
            [f'{photo_prefix}2'],
            [f'{photo_prefix}3'],
        ],
    )
    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()
    window.thumbnail_list.item(1).setSelected(True)
    app.processEvents()

    assert window._resolved_selection_photo_ids() == [
        f'{photo_prefix}0',
        f'{photo_prefix}1',
        f'{photo_prefix}2',
    ]

    window.compare_mode_shortcut.activated.emit()
    app.processEvents()
    window._compare_nav_shortcuts[1].activated.emit()
    app.processEvents()
    getattr(window, exit_shortcut_attr).activated.emit()
    app.processEvents()

    assert window.current_photo_id == f'{photo_prefix}1'
    if expected_target == 'browse':
        assert window._browse_mode is True
        assert [
            item.data(Qt.UserRole)
            for item in window.browse_list.selectedItems()
        ] == [f'{photo_prefix}0', f'{photo_prefix}1', f'{photo_prefix}2']
    else:
        assert window._compare_mode is False
        assert window.scene_list.isVisible() is True
        assert [
            item.data(Qt.UserRole)
            for item in window.thumbnail_list.selectedItems()
        ] == [f'{photo_prefix}0', f'{photo_prefix}2']
        assert [
            item.data(Qt.UserRole)
            for item in window.scene_list.selectedItems()
        ] == [f'{photo_prefix}0', f'{photo_prefix}1']
        assert window._resolved_selection_photo_ids() == [
            f'{photo_prefix}0',
            f'{photo_prefix}1',
            f'{photo_prefix}2',
        ]

    window.close()


def test_scene_mode_metadata_assignment_targets_exact_mixed_selection(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify scene-mode tagging uses exact selected photos across both strips.

    Scene covers must not implicitly stand in for every photo in the scene, but
    users still need batch metadata assignment for a mixed cover plus in-scene
    selection.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_9820', 'dimgray'),
            ('IMG_9821', 'blue'),
            ('IMG_9822', 'green'),
            ('IMG_9823', 'yellow'),
        ],
        scene_groups=[['IMG_9820', 'IMG_9821'], ['IMG_9822'], ['IMG_9823']],
    )
    trigger_scene_shortcut(window, 'Shift+Right')
    app.processEvents()
    window.thumbnail_list.item(1).setSelected(True)
    app.processEvents()

    window.rating_actions[3].trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9820').rating == 3
    assert window.library.get_photo('IMG_9821').rating == 3
    assert window.library.get_photo('IMG_9822').rating == 3
    assert window.library.get_photo('IMG_9823').rating is None

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
        'photos': {
            'IMG_9200': {'rating': 5},
            'IMG_9201': {'rating': 5},
        }
    }

    window.undo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9200').rating is None
    assert window.library.get_photo('IMG_9201').rating is None
    assert window.redo_metadata_action.isEnabled() is True
    assert json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    ) == {'photos': {}}

    window.redo_metadata_action.trigger()
    app.processEvents()

    assert window.library.get_photo('IMG_9200').rating == 5
    assert window.library.get_photo('IMG_9201').rating == 5

    window.close()
