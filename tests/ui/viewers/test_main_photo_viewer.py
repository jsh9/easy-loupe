from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from easy_cull.ui.main_window.build import VIEWER_KEYBOARD_PAN_STEP
from tests.ui._helpers import (
    create_main_window_with_library,
    trigger_viewer_shortcut,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_main_window_split_shortcut_enters_and_exits_split_with_preserved_manual_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8050', 'dimgray'), ('IMG_8051', 'blue')],
    )

    assert window.viewer._mode == 'single-fit'
    assert window.viewer.is_split_view() is False

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.viewer._mode == 'split'
    assert window.viewer.split_fit_viewer._mode == 'fit'
    assert window.viewer.split_zoom_viewer._mode == 'manual'
    assert (
        window.viewer.split_fit_viewer._focus_point_marker.isVisible() is True
    )
    assert (
        window.viewer.split_zoom_viewer._focus_point_marker.isVisible() is True
    )

    window.viewer.zoom_step(2.0)
    window.viewer.pan_by(45, -35)
    remembered_scale = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is False
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(remembered_scale)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.close()


def test_main_window_space_from_split_promotes_right_pane_then_returns_to_fit(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8060', 'dimgray'), ('IMG_8061', 'green')],
    )

    window.split_mode_shortcut.activated.emit()
    app.processEvents()
    window.viewer.zoom_step(2.0)
    window.viewer.pan_by(35, -20)
    remembered_scale = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is False
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(remembered_scale)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is False
    assert window.viewer._mode == 'single-fit'

    window.close()


def test_main_window_viewer_shortcuts_target_split_right_pane_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8070', 'dimgray'), ('IMG_8071', 'green')],
    )

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    left_scale_before = window.viewer.split_fit_viewer._current_scale
    left_center_before = (
        window.viewer.split_fit_viewer.normalized_viewport_center()
    )
    right_scale_before = window.viewer.split_zoom_viewer._current_scale
    right_center_before = (
        window.viewer.split_zoom_viewer.normalized_viewport_center()
    )

    trigger_viewer_shortcut(window, '=')
    trigger_viewer_shortcut(window, 'D')
    app.processEvents()

    assert window.viewer._mode == 'split'
    assert window.viewer.split_fit_viewer._current_scale == pytest.approx(
        left_scale_before
    )
    assert (
        window.viewer.split_fit_viewer.normalized_viewport_center()
        == pytest.approx(left_center_before)
    )
    assert window.viewer.split_zoom_viewer._current_scale > right_scale_before
    assert (
        window.viewer.split_zoom_viewer.normalized_viewport_center()[0]
        > right_center_before[0]
    )

    window.close()


def test_main_window_keyboard_pan_step_scales_with_zoom(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify keyboard panning shrinks as zoom increases.

    W/A/S/D should move the viewport by a consistent screen-feeling amount, not
    a fixed image-space distance that becomes too large at high zoom. The split
    assertion also protects the rule that only the zoom pane pans in split
    view.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8072', 'dimgray'), ('IMG_8073', 'green')],
    )
    window.resize(540, 420)
    app.processEvents()

    window.viewer.single_viewer.set_manual_view(4.0, (0.5, 0.5))
    center_before = window.viewer.normalized_viewport_center()
    window._keyboard_pan_by(1, 0)
    center_after = window.viewer.normalized_viewport_center()
    zoom_four_delta = center_after[0] - center_before[0]

    window.viewer.single_viewer.set_manual_view(8.0, (0.5, 0.5))
    center_before = window.viewer.normalized_viewport_center()
    window._keyboard_pan_by(1, 0)
    center_after = window.viewer.normalized_viewport_center()
    zoom_eight_delta = center_after[0] - center_before[0]

    assert zoom_four_delta == pytest.approx(
        (VIEWER_KEYBOARD_PAN_STEP / 4.0) / 640
    )
    assert zoom_eight_delta == pytest.approx(
        (VIEWER_KEYBOARD_PAN_STEP / 8.0) / 640
    )
    assert zoom_eight_delta < zoom_four_delta

    window.split_mode_shortcut.activated.emit()
    app.processEvents()
    left_center_before = (
        window.viewer.split_fit_viewer.normalized_viewport_center()
    )
    right_viewer = window.viewer.split_zoom_viewer
    right_viewer.set_manual_view(8.0, (0.5, 0.5))
    right_center_before = right_viewer.normalized_viewport_center()

    window._keyboard_pan_by(1, 0)

    assert (
        window.viewer.split_fit_viewer.normalized_viewport_center()
        == pytest.approx(left_center_before)
    )
    assert (
        right_viewer.normalized_viewport_center()[0] - right_center_before[0]
    ) == pytest.approx((VIEWER_KEYBOARD_PAN_STEP / 8.0) / 640)

    window.close()


def test_main_window_split_left_pane_hold_zoom_is_temporary_and_left_only(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    In split view, the left fit-to-window pane should support temporary
    click-and-hold inspection without changing the right zoomed pane's scale or
    center.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8080', 'dimgray'), ('IMG_8081', 'green')],
    )

    window.resize(560, 420)
    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    left_viewer = window.viewer.split_fit_viewer
    right_viewer = window.viewer.split_zoom_viewer
    left_viewer.resize(240, 240)
    app.processEvents()

    right_scale_before = right_viewer._current_scale
    right_center_before = right_viewer.normalized_viewport_center()

    QTest.mousePress(
        left_viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 120),
    )
    app.processEvents()

    assert left_viewer._hold_zoom_active is True
    assert left_viewer.visible_region_rect() is not None

    left_center_before = left_viewer.normalized_viewport_center()
    QTest.mouseMove(left_viewer.viewport(), QPoint(90, 90))
    app.processEvents()
    left_center_after = left_viewer.normalized_viewport_center()

    assert left_center_after[0] > left_center_before[0]
    assert left_center_after[1] > left_center_before[1]
    assert right_viewer._current_scale == pytest.approx(right_scale_before)
    assert right_viewer.normalized_viewport_center() == pytest.approx(
        right_center_before
    )

    QTest.mouseRelease(
        left_viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(90, 90),
    )
    app.processEvents()

    assert left_viewer._hold_zoom_active is False
    assert left_viewer._mode == 'fit'
    assert left_viewer.visible_region_rect() is None
    assert right_viewer._current_scale == pytest.approx(right_scale_before)
    assert right_viewer.normalized_viewport_center() == pytest.approx(
        right_center_before
    )

    window.close()


def test_main_window_space_exit_from_browse_mode_returns_to_fit_then_restores_manual_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8150', 'dimgray'), ('IMG_8151', 'green')],
    )

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(35, -25)
    remembered_scale = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window._browse_mode is False
    assert window.viewer._mode == 'single-fit'

    window.space_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(remembered_scale)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.close()


def test_main_window_split_mode_restores_manual_view_per_photo_across_navigation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8170', 'dimgray'),
            ('IMG_8171', 'green'),
            ('IMG_8172', 'blue'),
        ],
    )

    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(40, -30)
    first_scale = window.viewer._current_scale
    first_center = window.viewer.normalized_viewport_center()

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.current_photo_id == 'IMG_8171'

    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(-35, 25)
    second_scale = window.viewer._current_scale
    second_center = window.viewer.normalized_viewport_center()

    window.thumbnail_list.setCurrentRow(0)
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.current_photo_id == 'IMG_8170'
    assert window.viewer._current_scale == pytest.approx(first_scale)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        first_center
    )

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.current_photo_id == 'IMG_8171'
    assert window.viewer._current_scale == pytest.approx(second_scale)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        second_center
    )

    window.close()


def test_main_window_browse_mode_uses_full_width_on_first_entry(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8300', 'dimgray'),
            ('IMG_8301', 'green'),
            ('IMG_8302', 'blue'),
            ('IMG_8303', 'yellow'),
            ('IMG_8304', 'purple'),
            ('IMG_8305', 'white'),
            ('IMG_8306', 'black'),
            ('IMG_8307', 'orange'),
        ],
    )

    def first_row_item_count() -> int:
        first_row_y = window.browse_list.visualItemRect(
            window.browse_list.item(0)
        ).y()
        return sum(
            1
            for index in range(window.browse_list.count())
            if window.browse_list.visualItemRect(
                window.browse_list.item(index)
            ).y()
            == first_row_y
        )

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    app.processEvents()

    first_entry_count = first_row_item_count()

    assert window._browse_mode is True
    assert window.browse_list.isVisible() is True
    assert first_entry_count > 2

    window.space_shortcut.activated.emit()
    app.processEvents()

    window.browse_mode_shortcut.activated.emit()
    app.processEvents()
    app.processEvents()

    second_entry_count = first_row_item_count()

    assert second_entry_count == first_entry_count

    window.close()


def test_viewer_zoom_and_pan_shortcuts_change_scale_and_center(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_K500', 'dimgray')],
    )

    window.viewer.toggle_focus_zoom()
    app.processEvents()

    scale_before = window.viewer._current_scale
    trigger_viewer_shortcut(window, '=')
    app.processEvents()
    assert window.viewer._current_scale > scale_before

    scale_before = window.viewer._current_scale
    trigger_viewer_shortcut(window, '+')
    app.processEvents()
    assert window.viewer._current_scale > scale_before

    scale_before = window.viewer._current_scale
    trigger_viewer_shortcut(window, '-')
    app.processEvents()
    assert window.viewer._current_scale < scale_before

    center_before = window.viewer.normalized_viewport_center()
    trigger_viewer_shortcut(window, 'D')
    app.processEvents()
    center_after = window.viewer.normalized_viewport_center()
    assert center_after[0] > center_before[0]

    center_before = window.viewer.normalized_viewport_center()
    trigger_viewer_shortcut(window, 'A')
    app.processEvents()
    center_after = window.viewer.normalized_viewport_center()
    assert center_after[0] < center_before[0]

    center_before = window.viewer.normalized_viewport_center()
    trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    center_after = window.viewer.normalized_viewport_center()
    assert center_after[1] > center_before[1]

    center_before = window.viewer.normalized_viewport_center()
    trigger_viewer_shortcut(window, 'W')
    app.processEvents()
    center_after = window.viewer.normalized_viewport_center()
    assert center_after[1] < center_before[1]

    window.close()
