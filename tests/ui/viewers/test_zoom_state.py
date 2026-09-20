"""Regression coverage for inspection at or below fit-to-window scale."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from easy_loupe.ui.viewers.compare_photo_viewer import (
    ComparePhoto,
    ComparePhotoViewer,
)
from easy_loupe.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_loupe.ui.viewers.photo_viewer import ManualView, PhotoViewer
from tests.ui._helpers import create_jpeg

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture
def small_viewer(tmp_path: Path) -> Iterator[PhotoViewer]:
    """Use a real viewport so zoom assertions exercise native Qt geometry."""
    path = tmp_path / 'small.jpg'
    create_jpeg(path, 'gray', size=(100, 80))
    app = QApplication.instance() or QApplication([])
    viewer = PhotoViewer(hold_zoom_enabled=True)
    viewer.resize(400, 320)
    viewer.show()
    app.processEvents()
    viewer.set_photo(path, (0.5, 0.5))
    try:
        yield viewer
    finally:
        viewer.close()
        app.processEvents()


@pytest.mark.parametrize(
    ('start', 'multiplier', 'expected_scale'),
    [
        ('actual', 1.25, 1.25),
        ('actual', 0.8, 1.0),
        ('fit', 0.8, 3.2),
        ('manual', 0.8, 4.0),
    ],
    ids=['actual-plus', 'actual-minus', 'fit-minus', 'cross-fit'],
)
def test_upscaled_zoom_steps_keep_direction(
        small_viewer: PhotoViewer,
        start: str,
        multiplier: float,
        expected_scale: float,
) -> None:
    """
    Keep zoom steps directional when Fit is 400%.

    Using Fit as the minimum previously made minus enlarge a 100% inspection to
    400%; crossing Fit must also leave manual mode available to toggle.
    """
    viewer = small_viewer
    if start == 'actual':
        viewer.toggle_actual_size_zoom()
    elif start == 'manual':
        viewer.set_manual_view(1.25, (0.5, 0.5))

    viewer.zoom_step(multiplier)

    assert viewer._current_scale == pytest.approx(expected_scale)
    assert viewer.is_fit_view() is False
    if start == 'actual' and multiplier < 1:
        assert viewer.is_actual_size_zoom_active() is True


@pytest.mark.parametrize(
    'viewport_size',
    [(50, 40), (100, 80), (400, 320)],
    ids=['fit-below-actual', 'fit-equals-actual', 'fit-above-actual'],
)
def test_focus_toggle_returns_to_fit_and_restores_hold(
        tmp_path: Path, viewport_size: tuple[int, int]
) -> None:
    """
    Toggle the container and pane together, then restore hold inspection.

    Inferring mode from scale previously left the pane manual while its
    container reported Fit, making repeated Space presses disable hold zoom.
    """
    path = tmp_path / 'small.jpg'
    create_jpeg(path, 'gray', size=(100, 80))
    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()
    viewer.resize(*viewport_size)
    viewer.show()
    app.processEvents()
    viewer.set_photo(path, (0.5, 0.5))
    pane = viewer.single_viewer
    fit_scale = pane._fit_scale
    try:
        for _ in range(2):
            viewer.toggle_focus_zoom()
            assert viewer._mode == 'single-manual'
            assert pane.should_preserve_zoom() is True
            assert pane._current_scale == pytest.approx(1.0)

            viewer.toggle_focus_zoom()
            assert viewer._mode == 'single-fit'
            assert pane.is_fit_view() is True
            assert pane._current_scale == pytest.approx(fit_scale)

        position = pane.viewport().rect().center()
        QTest.mousePress(
            pane.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            position,
        )
        assert pane._hold_zoom_active is True
        assert pane._current_scale == pytest.approx(1.0)
        QTest.mouseRelease(
            pane.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            position,
        )
        assert pane.is_fit_view() is True
        assert pane._current_scale == pytest.approx(fit_scale)
    finally:
        viewer.close()
        app.processEvents()


@pytest.mark.parametrize(
    'viewport_size',
    [(50, 40), (100, 80), (400, 320)],
    ids=['below-actual', 'equal-actual', 'above-actual'],
)
def test_zoom_limits_do_not_change_mode_or_memory(
        small_viewer: PhotoViewer, viewport_size: tuple[int, int]
) -> None:
    """
    Leave mode and memory untouched when already at a zoom limit.

    Clearing inspection flags before detecting a no-op would silently change
    how the next resize or Fit toggle behaves, despite no visible zoom step.
    """
    viewer = small_viewer
    app = QApplication.instance()
    viewer.resize(*viewport_size)
    app.processEvents()
    viewer.set_manual_view(3.0, (0.5, 0.5))
    memory = dict(viewer._manual_views)
    viewer.set_fit_view()
    viewer.toggle_actual_size_zoom()

    if viewer._fit_scale < 1.0:
        viewer.zoom_step(0.1)
        assert viewer.is_fit_view() is True
    else:
        viewer.zoom_step(0.8)
        assert viewer.is_actual_size_zoom_active() is True

    assert viewer._current_scale == pytest.approx(min(viewer._fit_scale, 1.0))
    assert viewer._manual_views == memory
    viewer.zoom_step(0.8)
    assert viewer._manual_views == memory

    viewer.set_manual_view(10.0, (0.5, 0.5))
    memory = dict(viewer._manual_views)
    scale = viewer._current_scale
    viewer.zoom_step(1.25)
    assert viewer._current_scale == pytest.approx(scale)
    assert viewer.is_fit_view() is False
    assert viewer._manual_views == memory


@pytest.mark.parametrize(
    'actual_size', [False, True], ids=['manual', 'actual']
)
def test_fully_visible_inspection_ignores_pan_gestures(
        small_viewer: PhotoViewer, actual_size: bool
) -> None:
    """
    Ignore pan gestures when the whole photo is already visible.

    These inputs cannot move the image, so they must not clear the actual-size
    flag or replace remembered AF intent with a concrete center.
    """
    viewer = small_viewer
    viewer.toggle_focus_zoom()
    if actual_size:
        viewer.zoom_to_actual_size((0.2, 0.8))

    memory = dict(viewer._manual_views)
    viewer.pan_by(10, 20)
    viewer.keyboard_pan_by(1, 1)
    viewer.set_normalized_viewport_center((0.2, 0.8))
    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(190, 150),
    )
    QTest.mouseMove(viewer.viewport(), QPoint(210, 170))
    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(210, 170),
    )

    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.is_actual_size_zoom_active() is actual_size
    assert viewer.should_preserve_zoom() is True
    assert viewer.visible_region_rect() == pytest.approx((0, 0, 1, 1))
    assert viewer.normalized_viewport_center() == pytest.approx((0.5, 0.5))
    assert viewer._manual_views == memory
    viewer.set_fit_view()
    assert viewer.visible_region_rect() is None


@pytest.mark.parametrize(
    'restore_path',
    ['setter', 'normalized', 'legacy', 'handoff', 'tuple'],
)
def test_below_fit_manual_restoration_and_resize(
        small_viewer: PhotoViewer, tmp_path: Path, restore_path: str
) -> None:
    """
    Restore below-fit memory through current and legacy entry points.

    A factor of 0.3125 means 125% at Fit 400% and 250% at Fit 800%; checking
    both prevents a restore path from either forcing Fit or freezing pixels.
    """
    viewer = small_viewer
    path = tmp_path / 'small.jpg'
    center = (0.2, 0.8)
    factor = 0.3125
    if restore_path == 'setter':
        viewer.set_manual_view(factor, center)
    elif restore_path == 'normalized':
        viewer.zoom_to_normalized_center(center, zoom_factor=factor)
    elif restore_path == 'legacy':
        viewer.set_manual_view(factor, center)
        viewer.set_photo(path, center, preserve_zoom=True)
    elif restore_path == 'handoff':
        viewer.set_photo(
            path, center, handoff_manual_view=ManualView(factor, center)
        )
    else:
        viewer._manual_views[str(path)] = (factor, center)
        viewer.restore_or_focus_manual_view()

    assert viewer.should_preserve_zoom() is True
    assert viewer._current_scale == pytest.approx(1.25)
    assert viewer.normalized_viewport_center() == pytest.approx((0.5, 0.5))
    viewer.toggle_focus_zoom()
    viewer.toggle_focus_zoom()
    assert viewer._current_scale == pytest.approx(1.25)

    app = QApplication.instance()
    viewer.resize(800, 640)
    app.processEvents()
    assert viewer._current_scale == pytest.approx(2.5)
    assert viewer.current_zoom_factor() == pytest.approx(factor)
    assert viewer.should_preserve_zoom() is True


def test_below_fit_handoff_keeps_af_memory_across_photo_sizes(
        small_viewer: PhotoViewer, tmp_path: Path
) -> None:
    """
    Carry AF intent and zoom memory across differently sized photos.

    Hitting the 100% floor on the larger photo must not replace the stored
    factor or lose the AF sentinel when delayed focus metadata arrives.
    """
    viewer = small_viewer
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    memory = viewer.current_manual_view()
    assert memory == ManualView(0.3125, None)
    next_path = tmp_path / 'next.jpg'
    create_jpeg(next_path, 'gray', size=(200, 160))

    viewer.set_photo(
        next_path,
        (0.1, 0.9),
        focus_point_pending=True,
        handoff_manual_view=memory,
    )
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.current_manual_view() == memory
    viewer.set_focus_point((0.2, 0.8))
    assert viewer.current_manual_view() == memory
    viewer.set_photo(
        tmp_path / 'small.jpg',
        (0.2, 0.8),
        handoff_manual_view=viewer.current_manual_view(),
    )
    assert viewer._current_scale == pytest.approx(1.25)
    assert viewer.current_manual_view() == memory


def test_below_fit_transient_recenter_restores_inspection(
        small_viewer: PhotoViewer,
) -> None:
    """
    Restore below-fit memory after an edge AF recenter temporarily enlarges it.

    A restore that still uses Fit as its minimum would make Shift+F unable to
    return to the original 125% inspection of this small photo.
    """
    viewer = small_viewer
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.set_focus_point((0.05, 0.5))
    memory = viewer.current_manual_view()
    viewer.toggle_recenter_current_view()
    assert viewer._current_scale > viewer._fit_scale
    viewer.toggle_recenter_current_view()
    assert viewer._current_scale == pytest.approx(1.25)
    assert viewer.current_manual_view() == memory


def test_hold_resize_restores_fit_without_changing_memory(
        small_viewer: PhotoViewer,
) -> None:
    """
    Keep hold inspection at 100% through resize, then restore the new Fit.

    Release must use current geometry without saving the temporary inspection
    as the user's remembered manual view.
    """
    viewer = small_viewer
    viewer.toggle_focus_zoom()
    memory = dict(viewer._manual_views)
    viewer.set_fit_view()
    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(200, 160),
    )
    viewer.resize(600, 480)
    QApplication.instance().processEvents()
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer._hold_zoom_active is True
    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(200, 160),
    )
    assert viewer._current_scale == pytest.approx(6.0)
    assert viewer.is_fit_view() is True
    assert viewer._manual_views == memory


@pytest.mark.parametrize('promotion', ['space', 'split-toggle'])
def test_split_promotion_preserves_below_fit_af_memory(
        tmp_path: Path, promotion: str
) -> None:
    """
    Carry below-fit manual scale and AF intent when leaving split view.

    The right pane's scale must remain relative to Fit in the larger pane;
    resolving the AF sentinel through recentering could instead enlarge it.
    """
    path = tmp_path / 'small.jpg'
    create_jpeg(path, 'gray', size=(100, 80))
    app = QApplication.instance() or QApplication([])
    viewer = MainPhotoViewer()
    viewer.resize(800, 640)
    viewer.show()
    app.processEvents()
    viewer.set_photo(path, (0.1, 0.9))
    viewer.toggle_split_view()
    app.processEvents()
    try:
        assert viewer.split_zoom_viewer._current_scale == pytest.approx(1.0)
        viewer.zoom_step(1.25)
        memory = viewer.current_manual_view()
        assert memory is not None
        assert memory.center is None
        assert memory.zoom_factor < 1.0

        if promotion == 'space':
            viewer.toggle_focus_zoom()
        else:
            viewer.toggle_split_view()

        app.processEvents()
        assert viewer._mode == 'single-manual'
        assert viewer.current_manual_view() == memory
        assert viewer.single_viewer._current_scale == pytest.approx(
            viewer.single_viewer._fit_scale * memory.zoom_factor
        )
        viewer.toggle_focus_zoom()
        assert viewer.single_viewer.is_fit_view() is True
    finally:
        viewer.close()
        app.processEvents()


@pytest.fixture
def mixed_compare_viewer(tmp_path: Path) -> Iterator[ComparePhotoViewer]:
    """Compare panes on opposite sides of actual size using real geometry."""
    small_path = tmp_path / 'small.jpg'
    large_path = tmp_path / 'large.jpg'
    create_jpeg(small_path, 'gray', size=(100, 80))
    create_jpeg(large_path, 'gray', size=(4000, 3200))
    app = QApplication.instance() or QApplication([])
    viewer = ComparePhotoViewer()
    viewer.resize(800, 640)
    viewer.show()
    viewer.set_photos([
        ComparePhoto('small', small_path, (0.1, 0.9)),
        ComparePhoto('large', large_path, (0.5, 0.5)),
    ])
    app.processEvents()
    try:
        yield viewer
    finally:
        viewer.close()
        app.processEvents()


def test_compare_grid_actual_size_survives_resize_and_toggles_back(
        mixed_compare_viewer: ComparePhotoViewer,
) -> None:
    """
    Keep mixed-size compare panes at 100% through pan and resize.

    Panning must not convert actual size into fit-relative memory, and the
    smaller photo must still return to Fit even though inspection shrank it.
    """
    viewer = mixed_compare_viewer
    assert viewer._viewers[0]._fit_scale > 1.0
    assert viewer._viewers[1]._fit_scale < 1.0
    viewer.handle_zoom_toggle_shortcut()
    large_pane = viewer._viewers[1]
    large_pane.pan_by(100, 80)
    assert large_pane.normalized_viewport_center() != (0.5, 0.5)
    viewer.resize(1000, 800)
    QApplication.instance().processEvents()
    for pane in viewer._viewers:
        assert pane.is_actual_size_zoom_active() is True
        assert pane._current_scale == pytest.approx(1.0)

    viewer.handle_zoom_toggle_shortcut()
    assert all(pane.is_fit_view() for pane in viewer._viewers)


@pytest.mark.parametrize('restore_path', ['setter', 'normalized'])
@pytest.mark.parametrize('fit_toggle', ['focus', 'actual'])
def test_restoring_below_fit_memory_does_not_save_temporary_floor(
        small_viewer: PhotoViewer, restore_path: str, fit_toggle: str
) -> None:
    """
    Retain a restored factor while a smaller pane clamps its live scale.

    Returning to Fit after a resize must not save the temporary 100% clamp.
    Both toggles must preserve concrete centers and AF-centered intent.
    """
    viewer = small_viewer
    app = QApplication.instance()
    if restore_path == 'setter':
        viewer.set_manual_view(0.3125, (0.5, 0.5))
    else:
        viewer.zoom_to_normalized_center(None, zoom_factor=0.3125)

    memory = dict(viewer._manual_views)
    assert viewer._current_scale == pytest.approx(1.25)
    viewer.resize(200, 160)
    app.processEvents()
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.current_manual_view().zoom_factor == pytest.approx(0.3125)
    if fit_toggle == 'focus':
        viewer.toggle_focus_zoom()
    else:
        viewer.toggle_actual_size_zoom()

    assert viewer.is_fit_view() is True
    assert viewer._manual_views == memory
    viewer.resize(400, 320)
    app.processEvents()
    viewer.toggle_focus_zoom()
    assert viewer._current_scale == pytest.approx(1.25)
    assert viewer._manual_views == memory


@pytest.mark.parametrize(
    'focus_point', [(0.5, 0.5), (0.05, 0.9)], ids=['center', 'edge']
)
@pytest.mark.parametrize('state', ['manual', 'recentered', 'resized'])
def test_reset_centers_preserves_below_fit_zoom(
        small_viewer: PhotoViewer,
        focus_point: tuple[float, float],
        state: str,
) -> None:
    """
    Reset only centers, including after temporary recentering or a resize.

    The active photo must retain its saved factor rather than an AF-fitting
    scale or a temporary floor; inactive legacy entries must retain theirs.
    """
    viewer = small_viewer
    app = QApplication.instance()
    viewer.set_focus_point(focus_point)
    viewer.set_manual_view(0.3125, (0.5, 0.5))
    viewer._manual_views['other'] = (2.0, (0.2, 0.8))
    if state == 'recentered':
        viewer.toggle_recenter_current_view()
    elif state == 'resized':
        viewer.resize(200, 160)
        app.processEvents()

    viewer.reset_manual_view_centers()

    assert viewer.current_manual_view() == ManualView(0.3125, None)
    assert viewer._manual_views['other'] == ManualView(2.0, None)
    assert viewer._transient_recenter_active is False
    assert viewer._current_scale == pytest.approx(
        1.0 if state == 'resized' else 1.25
    )
    assert viewer.normalized_viewport_center() == pytest.approx((0.5, 0.5))
    viewer.resize(400, 320)
    app.processEvents()
    viewer.toggle_focus_zoom()
    viewer.toggle_focus_zoom()
    assert viewer._current_scale == pytest.approx(1.25)
    assert viewer.current_manual_view() == ManualView(0.3125, None)


@pytest.mark.parametrize('focus_center', [True, False], ids=['af', 'manual'])
@pytest.mark.parametrize('fit_exit', ['focus', 'actual', 'zoom-out'])
def test_return_to_fit_preserves_pre_recenter_memory(
        tmp_path: Path, focus_center: bool, fit_exit: str
) -> None:
    """
    Exiting an edge AF recenter through Fit must restore the original 100%.

    AF sentinel memory needs the same protection as concrete centers, across
    both toggle APIs and the zoom-out path that reaches Fit.
    """
    path = tmp_path / 'edge.jpg'
    create_jpeg(path, 'gray', size=(640, 480))
    app = QApplication.instance() or QApplication([])
    viewer = PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()
    viewer.set_photo(path, (0.9, 0.5))
    try:
        viewer.toggle_focus_zoom()
        if not focus_center:
            viewer.set_manual_view(2.0, (0.75, 0.5))

        memory = dict(viewer._manual_views)
        viewer.toggle_recenter_current_view()
        assert viewer._current_scale == pytest.approx(2.5)
        if fit_exit == 'focus':
            viewer.toggle_focus_zoom()
        elif fit_exit == 'actual':
            viewer.toggle_actual_size_zoom()
        else:
            viewer.zoom_step(0.1)

        assert viewer.is_fit_view() is True
        assert viewer._manual_views == memory
        viewer.toggle_focus_zoom()
        assert viewer._current_scale == pytest.approx(1.0)
        assert viewer.current_manual_view().zoom_factor == pytest.approx(2.0)
        assert viewer._manual_views == memory
    finally:
        viewer.close()
        app.processEvents()


@pytest.mark.parametrize('center', [None, (0.2, 0.8)], ids=['af', 'concrete'])
def test_legacy_preserve_zoom_records_carried_view(
        small_viewer: PhotoViewer,
        tmp_path: Path,
        center: tuple[float, float] | None,
) -> None:
    """
    Save legacy carryover before a fit transition trusts existing memory.

    Previously visited photos may have older tuple memory; carrying a new view
    must replace it without recording the new photo's temporary floor.
    """
    viewer = small_viewer
    path = tmp_path / 'next.jpg'
    create_jpeg(path, 'gray', size=(200, 160))
    viewer._manual_views[str(path)] = (3.0, (0.7, 0.3))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.set_photo(
        path, (0.1, 0.9), preserve_zoom=True, preserved_center=center
    )
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.current_manual_view() == ManualView(0.3125, center)
    viewer.toggle_focus_zoom()
    viewer.toggle_focus_zoom()
    assert viewer.current_manual_view() == ManualView(0.3125, center)


def test_selected_compare_fit_toggle_preserves_resize_clamp_memory(
        mixed_compare_viewer: ComparePhotoViewer,
) -> None:
    """Selected compare Space must not save a smaller window's 100% floor."""
    viewer = mixed_compare_viewer
    app = QApplication.instance()
    viewer.handle_space_shortcut()
    app.processEvents()
    viewer.handle_space_shortcut()
    viewer.zoom_step(1.25)
    pane = viewer.selected_viewer
    memory = pane.current_manual_view()
    viewer.resize(400, 320)
    app.processEvents()
    assert pane._current_scale == pytest.approx(1.0)
    viewer.handle_space_shortcut()
    assert pane.is_fit_view() is True
    viewer.resize(800, 640)
    app.processEvents()
    # Compare Space enters explicit 100%; use manual restore to inspect the
    # saved view independently of that absolute-size shortcut contract.
    pane.restore_or_focus_manual_view()
    assert pane.current_manual_view() == memory
    assert pane._current_scale == pytest.approx(1.25)


@pytest.mark.parametrize('locked', [True, False], ids=['locked', 'unlocked'])
def test_compare_click_preserves_below_fit_manual_zoom(
        mixed_compare_viewer: ComparePhotoViewer, locked: bool
) -> None:
    """
    Preserve a below-fit manual zoom when clicking locked or unlocked panes.

    Treating a factor below 1 as Fit would reset the clicked photo to 100%.
    Other panes must honor lock state and their own minimum zoom limits.
    """
    viewer = mixed_compare_viewer
    viewer.handle_zoom_toggle_shortcut()
    viewer.lock_zoom_button.setChecked(False)
    viewer.zoom_step(1.25)
    source, other = viewer._viewers
    factor = source.current_zoom_factor()
    assert factor < 1.0
    viewer.lock_zoom_button.setChecked(locked)
    viewer._handle_viewer_click(0, (0.5, 0.5))

    assert source._current_scale == pytest.approx(1.25)
    assert source.is_actual_size_zoom_active() is False
    assert other.is_actual_size_zoom_active() is (not locked)
    expected_scale = other._fit_scale if locked else 1.0
    assert other._current_scale == pytest.approx(expected_scale)
    viewer.zoom_step(1.25)
    assert source._current_scale == pytest.approx(1.5625)
    if not locked:
        assert other._current_scale == pytest.approx(1.0)


@pytest.mark.parametrize(
    'actual_size', [True, False], ids=['actual', 'manual']
)
def test_selected_compare_restores_below_fit_inspection(
        mixed_compare_viewer: ComparePhotoViewer, actual_size: bool
) -> None:
    """
    Restore actual-size and below-fit manual inspection after a grid rebuild.

    The selected pane is hidden and resized during rebuilding; restoring its
    memory must not save that intermediate layout's clamped magnification.
    """
    viewer = mixed_compare_viewer
    viewer.handle_space_shortcut()
    # Settle selected-pane geometry before choosing zoom so this tests the
    # rebuild's restoration, not an unrelated initial layout resize.
    QApplication.instance().processEvents()
    viewer.handle_space_shortcut()
    if not actual_size:
        viewer.zoom_step(1.25)

    photos = list(viewer._photos)
    viewer.set_photos(photos, preserve_selected_view_state=True)
    QApplication.instance().processEvents()
    assert viewer.is_selected_photo_view() is True
    assert viewer.selected_viewer._current_scale == pytest.approx(
        1.0 if actual_size else 1.25
    )
    assert viewer.selected_viewer.is_actual_size_zoom_active() is actual_size
    viewer.handle_space_shortcut()
    assert viewer.selected_viewer.is_fit_view() is True
