from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from easy_loupe.ui.main_window.build import VIEWER_KEYBOARD_PAN_STEP
from easy_loupe.ui.viewers.main_photo_viewer import MainPhotoViewer
from tests.ui._helpers import (
    create_jpeg,
    create_main_window_with_library,
    process_events_until,
    trigger_viewer_shortcut,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_main_photo_viewer_defaults_to_hidden_af_marker() -> None:
    """
    Verify single and split panes inherit the hidden AF-marker default.

    Host windows also apply the setting, but direct ``MainPhotoViewer``
    construction should stay aligned so future callers cannot accidentally
    restore visible markers by default.
    """
    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()

    assert viewer._focus_point_marker_enabled is False
    assert viewer.single_viewer._focus_point_marker_enabled is False
    assert viewer.split_fit_viewer._focus_point_marker_enabled is False
    assert viewer.split_zoom_viewer._focus_point_marker_enabled is False
    assert viewer._clipping_warning_enabled is False
    assert viewer.single_viewer._clipping_warning_enabled is False
    assert viewer.split_fit_viewer._clipping_warning_enabled is False
    assert viewer.split_zoom_viewer._clipping_warning_enabled is False
    viewer.close()
    app.processEvents()


def test_main_photo_viewer_clipping_warning_applies_to_split_panes(
        tmp_path: Path,
) -> None:
    """
    Verify clipping visibility is synchronized across single and split panes.

    Split mode rebuilds both pane pixmaps, so the clipping preference must be
    stored on the container and applied to every embedded ``PhotoViewer``.
    """
    create_jpeg(tmp_path / 'IMG_8052.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_8052.JPG', (0.5, 0.5))

    process_events_until(
        app,
        viewer.single_viewer._clipping_overlay_item.isVisible,
    )

    viewer.toggle_split_view()
    app.processEvents()

    assert viewer._clipping_warning_enabled is True
    assert viewer.split_fit_viewer._clipping_warning_enabled is True
    assert viewer.split_zoom_viewer._clipping_warning_enabled is True
    process_events_until(
        app,
        lambda: (
            viewer.split_fit_viewer._clipping_overlay_item.isVisible()
            and viewer.split_zoom_viewer._clipping_overlay_item.isVisible()
        ),
    )
    assert viewer.split_fit_viewer._clipping_overlay_item.isVisible() is True
    assert viewer.split_zoom_viewer._clipping_overlay_item.isVisible() is True

    viewer.set_clipping_warning_visible(enabled=False)

    assert viewer.single_viewer._clipping_warning_enabled is False
    assert viewer.split_fit_viewer._clipping_warning_enabled is False
    assert viewer.split_zoom_viewer._clipping_warning_enabled is False
    viewer.close()


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
    assert window.show_af_point_toggle.isChecked() is False

    window.show_af_point_toggle.setChecked(True)

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


def test_main_photo_viewer_minimap_center_targets_split_right_pane(
        tmp_path: Path,
) -> None:
    """
    Verify minimap recentering follows the active zoom-pane contract.

    In split view, the right pane owns manual zoom while the left pane stays
    fit-only, so minimap input must leave the left pane unchanged.
    """
    create_jpeg(tmp_path / 'IMG_8072.JPG', 'dimgray', size=(1000, 800))

    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()
    viewer.resize(640, 480)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_8072.JPG', (0.5, 0.5))
    viewer.toggle_split_view()
    app.processEvents()

    left_center_before = viewer.split_fit_viewer.normalized_viewport_center()
    right_zoom_before = viewer.split_zoom_viewer.current_zoom_factor()

    viewer.set_normalized_viewport_center((0.65, 0.35))

    assert viewer.split_fit_viewer.normalized_viewport_center() == (
        pytest.approx(left_center_before)
    )
    assert viewer.split_zoom_viewer.current_zoom_factor() == pytest.approx(
        right_zoom_before
    )
    assert viewer.split_zoom_viewer.normalized_viewport_center() == (
        pytest.approx((0.65, 0.35))
    )

    viewer.close()


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


def test_main_window_recenter_zoom_shortcut_targets_single_manual_view(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Shift+F toggles only the active single-pane view.

    The old remembered pan center must be one shortcut press away after the
    AF/default snap, otherwise Shift+F becomes a one-way recenter.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8500', 'dimgray')],
    )
    window.library.get_photo('IMG_8500').focus_point = (0.65, 0.35)
    window._display_current_photo()

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(-40, 30)
    scale_before = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(scale_before)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.65,
        0.35,
    ))

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert remembered_center is not None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.close()


def test_main_window_recenter_zoom_shortcut_targets_split_zoom_pane(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Shift+F toggles only the right split zoom pane.

    Split-to-single promotion must preserve the pre-existing remembered center
    after toggling back from a temporary AF/default recenter.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8501', 'dimgray')],
    )
    window.library.get_photo('IMG_8501').focus_point = (0.65, 0.35)
    window._display_current_photo()
    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(-40, 30)
    scale_before = window.viewer.split_zoom_viewer.current_zoom_factor()
    remembered_center = window.viewer.normalized_viewport_center()

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.viewer.split_fit_viewer.should_preserve_zoom() is False
    assert window.viewer.split_zoom_viewer.current_zoom_factor() == (
        pytest.approx(scale_before)
    )
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.65,
        0.35,
    ))

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert remembered_center is not None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.split_mode_shortcut.activated.emit()
    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is True
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.close()


def test_main_window_recenter_zoom_shortcut_does_not_change_navigation_handoff(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Shift+F does not alter photo-to-photo zoom carryover.

    Navigation reads handoff state from the viewer, so this guards against the
    visible AF/default center leaking into the next photo after a temporary
    recenter.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8504', 'dimgray'), ('IMG_8505', 'blue')],
    )
    window.library.get_photo('IMG_8504').focus_point = (0.35, 0.65)
    window.library.get_photo('IMG_8505').focus_point = (0.65, 0.35)
    window._display_current_photo()

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(40, -30)
    zoom_factor = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.35,
        0.65,
    ))

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert remembered_center is not None
    assert window.current_photo_id == 'IMG_8505'
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(zoom_factor)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.close()


def test_main_window_reset_zoom_centers_shortcut_uses_next_photo_focus_point(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify Ctrl+Shift+F resets remembered centers for navigation.

    Unlike Shift+F, reset-all is persistent, so the next zoomed photo should
    use its own AF/default center while keeping the carried zoom scale.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8502', 'dimgray'), ('IMG_8503', 'blue')],
    )
    window.library.get_photo('IMG_8502').focus_point = (0.35, 0.65)
    window.library.get_photo('IMG_8503').focus_point = (0.65, 0.35)
    window._display_current_photo()

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(1.25)
    window.viewer.pan_by(40, -30)
    zoom_factor = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    question_results = [QMessageBox.No, QMessageBox.Yes]
    question_calls: list[tuple[str, str, object]] = []

    def confirm_reset(
            _parent: object,
            title: str,
            text: str,
            buttons: object,
            default_button: object,
    ) -> object:
        question_calls.append((title, text, default_button))
        assert buttons == QMessageBox.Yes | QMessageBox.No
        return question_results.pop(0)

    monkeypatch.setattr(QMessageBox, 'question', confirm_reset)

    window.reset_zoom_centers_shortcut.activated.emit()
    app.processEvents()

    assert remembered_center is not None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.reset_zoom_centers_shortcut.activated.emit()
    app.processEvents()

    assert question_calls == [
        (
            'Reset Zoom Centers',
            'Reset all remembered zoom centers to AF points or image centers?',
            QMessageBox.No,
        ),
        (
            'Reset Zoom Centers',
            'Reset all remembered zoom centers to AF points or image centers?',
            QMessageBox.No,
        ),
    ]
    assert window.viewer._current_scale == pytest.approx(zoom_factor)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.35,
        0.65,
    ))

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8503'
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(zoom_factor)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.65,
        0.35,
    ))

    window.close()


def test_main_window_reset_zoom_centers_survives_multiple_photo_hops(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify AF/default-center memory remains a sentinel across navigation.

    A reset center should not become photo B's concrete focus coordinates when
    the user continues from B to C.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[
            ('IMG_8506', 'dimgray'),
            ('IMG_8507', 'blue'),
            ('IMG_8508', 'green'),
        ],
    )
    window.library.get_photo('IMG_8506').focus_point = (0.35, 0.65)
    window.library.get_photo('IMG_8507').focus_point = (0.65, 0.35)
    window.library.get_photo('IMG_8508').focus_point = (0.20, 0.80)
    window._display_current_photo()

    window.viewer.toggle_focus_zoom()
    window.viewer.zoom_step(2.0)
    window.viewer.pan_by(40, -30)

    monkeypatch.setattr(
        QMessageBox,
        'question',
        lambda *_args, **_kwargs: QMessageBox.Yes,
    )
    window.reset_zoom_centers_shortcut.activated.emit()
    app.processEvents()
    expected_zoom = window.viewer._current_scale

    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.35,
        0.65,
    ))

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8507'
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.65,
        0.35,
    ))

    window.thumbnail_list.setCurrentRow(2)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8508'
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.20,
        0.80,
    ))

    window.close()


def test_main_window_shift_recenter_edge_scale_does_not_leak_to_next_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify temporary edge recenter scale is not used for navigation handoff.

    Centering an edge AF point can require a larger live scale than the
    remembered custom view. The next photo should receive the remembered view,
    not that transient edge-corrected scale.
    """
    _, app, window = create_main_window_with_library(
        tmp_path,
        monkeypatch,
        photo_specs=[('IMG_8509', 'dimgray'), ('IMG_8510', 'blue')],
    )
    window.library.get_photo('IMG_8509').focus_point = (0.5, 0.5)
    window.library.get_photo('IMG_8510').focus_point = (0.65, 0.35)
    window._display_current_photo()

    window.viewer.apply_manual_view(1.25, (0.5, 0.5))
    window.viewer.pan_by(24, 0)
    expected_zoom = window.viewer._current_scale
    expected_center = window.viewer.normalized_viewport_center()

    window.library.get_photo('IMG_8509').focus_point = (0.02, 0.5)
    window.viewer.set_focus_point((0.02, 0.5))
    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert expected_center is not None
    assert window.viewer._current_scale > expected_zoom
    assert window.viewer.normalized_viewport_center() != pytest.approx(
        expected_center
    )

    window.thumbnail_list.setCurrentRow(1)
    app.processEvents()

    assert window.current_photo_id == 'IMG_8510'
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        expected_center
    )

    window.close()
