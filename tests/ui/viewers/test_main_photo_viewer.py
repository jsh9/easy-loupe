from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
