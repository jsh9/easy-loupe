from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem

import easy_loupe.ui.viewers.photo_viewer as photo_viewer_module
from tests.ui._helpers import create_jpeg

if TYPE_CHECKING:
    from pathlib import Path


def test_photo_viewer_restores_last_manual_view_for_same_photo_and_not_other_photo(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7001.JPG', 'dimgray')
    create_jpeg(tmp_path / 'IMG_7002.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7001.JPG', (0.25, 0.75))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(40, -30)
    remembered_scale = viewer._current_scale
    remembered_center = viewer.normalized_viewport_center()

    viewer.set_fit_view()
    assert viewer._mode == 'fit'

    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(remembered_scale)
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    viewer.set_fit_view()
    viewer.set_photo(tmp_path / 'IMG_7002.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer.normalized_viewport_center()[0] > 0.6
    assert viewer.normalized_viewport_center()[1] < 0.4
    assert viewer.normalized_viewport_center() != pytest.approx(
        remembered_center, abs=0.02
    )

    viewer.close()


def test_photo_viewer_visible_region_rect_tracks_manual_zoom_and_pan(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7003.JPG', 'orange')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7003.JPG', (0.5, 0.5))

    assert viewer.visible_region_rect() is None

    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    visible_region_before = viewer.visible_region_rect()

    assert visible_region_before is not None
    assert visible_region_before[2] < 1.0
    assert visible_region_before[3] < 1.0

    viewer.pan_by(40, -30)
    visible_region_after = viewer.visible_region_rect()

    assert visible_region_after is not None
    assert visible_region_after[0] > visible_region_before[0]
    assert visible_region_after[1] < visible_region_before[1]

    viewer.set_fit_view()

    assert viewer.visible_region_rect() is None

    viewer.close()


def test_photo_viewer_focus_point_marker_tracks_loaded_photo(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7004.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    marker = viewer._focus_point_marker
    viewer.set_focus_point_marker_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7004.JPG', (0.25, 0.75))

    assert marker.isVisible() is True
    assert marker.pos().x() == pytest.approx(160)
    assert marker.pos().y() == pytest.approx(360)

    viewer.toggle_focus_zoom()

    assert marker.isVisible() is True

    viewer.set_fit_view()

    assert marker.isVisible() is True

    viewer.clear_photo()

    assert marker.isVisible() is False

    viewer.close()


def test_photo_viewer_hides_focus_marker_while_focus_point_pending(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7014.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    marker = viewer._focus_point_marker
    viewer.set_focus_point_marker_visible(enabled=True)
    viewer.set_photo(
        tmp_path / 'IMG_7014.JPG',
        (0.5, 0.5),
        focus_point_pending=True,
    )

    assert marker.isVisible() is False

    viewer.toggle_focus_zoom()

    assert viewer.normalized_viewport_center() == (
        pytest.approx(0.5),
        pytest.approx(0.5),
    )
    assert marker.isVisible() is False

    viewer.set_focus_point((0.25, 0.75))

    assert marker.isVisible() is True
    assert marker.pos().x() == pytest.approx(160)
    assert marker.pos().y() == pytest.approx(360)

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert viewer.normalized_viewport_center() == (
        pytest.approx(0.25),
        pytest.approx(0.75),
    )

    viewer.close()


def test_photo_viewer_focus_point_marker_can_be_disabled_and_stays_screen_sized(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7005.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    marker = viewer._focus_point_marker
    viewer.set_focus_point_marker_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7005.JPG', (0.5, 0.5))
    viewer.toggle_focus_zoom()
    before_rect = marker.rect()

    assert marker.isVisible() is True
    assert before_rect.width() == pytest.approx(
        photo_viewer_module.FOCUS_POINT_MARKER_SIZE
    )
    assert before_rect.height() == pytest.approx(
        photo_viewer_module.FOCUS_POINT_MARKER_SIZE
    )
    assert bool(
        marker.flags()
        & QGraphicsItem.GraphicsItemFlag.ItemIgnoresTransformations
    )

    viewer.zoom_step(1.25)

    assert marker.isVisible() is True
    assert marker.rect().width() == pytest.approx(before_rect.width())
    assert marker.rect().height() == pytest.approx(before_rect.height())

    viewer.set_focus_point_marker_visible(enabled=False)

    assert marker.isVisible() is False

    viewer.close()


def test_photo_viewer_focus_zoom_starts_from_af_point(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7006.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7006.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()

    assert viewer._mode == 'manual'
    assert viewer.normalized_viewport_center() == pytest.approx((0.8, 0.2))

    viewer.close()


def test_photo_viewer_actual_size_toggle_returns_to_fit_at_fit_scale_one(
        tmp_path: Path,
) -> None:
    """
    Verify actual-size zoom toggles back to fit when fit scale is already 1.0.

    For example, a 500x400 photo inside a 1000x800 viewer already fits at 100%,
    so fit view and actual-size view both use scale 1.0 and users will not see
    a visual scale change. The selected-photo compare shortcut still needs to
    advance internal state as fit -> actual-size -> fit.
    """
    create_jpeg(tmp_path / 'IMG_7012.JPG', 'white', size=(100, 80))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7012.JPG', (0.5, 0.5))

    assert viewer._mode == 'fit'
    assert viewer._fit_scale == pytest.approx(1.0)

    viewer.toggle_actual_size_zoom()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(1.0)

    viewer.toggle_actual_size_zoom()

    assert viewer._mode == 'fit'
    assert viewer._current_scale == pytest.approx(1.0)

    viewer.close()


def test_photo_viewer_actual_size_zoom_survives_resize(
        tmp_path: Path,
) -> None:
    """
    Verify 100% inspection remains absolute after the viewport changes.

    Actual-size compare inspection should stay at one image pixel per screen
    pixel instead of being restored as a fit-relative manual zoom factor.

    Manual check: open a large detailed photo in Compare, press Space twice to
    inspect at 100%, then resize the window much smaller and larger. Image
    detail should stay the same screen size while the visible area changes.
    """
    create_jpeg(tmp_path / 'IMG_7013.JPG', 'white', size=(1000, 800))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(500, 400)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7013.JPG', (0.25, 0.75))
    viewer.toggle_actual_size_zoom()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.normalized_viewport_center() == pytest.approx((0.25, 0.75))

    viewer.resize(250, 200)
    app.processEvents()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.normalized_viewport_center() == pytest.approx((0.25, 0.75))

    viewer.resize(1200, 1000)
    app.processEvents()

    assert viewer._mode == 'manual'
    assert viewer._current_scale == pytest.approx(1.0)
    assert viewer.normalized_viewport_center() == pytest.approx((0.5, 0.5))

    viewer.close()


def test_photo_viewer_actual_size_zoom_does_not_replace_manual_view(
        tmp_path: Path,
) -> None:
    """
    Verify actual-size inspection does not overwrite normal manual zoom memory.

    Selected-photo compare uses actual-size zoom as a temporary inspection
    state, while normal Space/focus zoom should still restore the user's last
    manual zoom and pan for that photo.
    """
    create_jpeg(tmp_path / 'IMG_7014.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    image_path = tmp_path / 'IMG_7014.JPG'
    viewer.set_photo(image_path, (0.8, 0.2))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-40, 30)
    remembered_manual_view = viewer.current_manual_view()
    stored_manual_views = dict(viewer._manual_views)

    viewer.set_fit_view()
    viewer.toggle_actual_size_zoom()

    assert viewer.current_manual_view() is None
    assert viewer._manual_views == stored_manual_views

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    restored_manual_view = viewer.current_manual_view()

    assert restored_manual_view is not None
    assert remembered_manual_view is not None
    assert restored_manual_view[0] == pytest.approx(remembered_manual_view[0])
    assert restored_manual_view[1] == pytest.approx(remembered_manual_view[1])

    viewer.close()


def test_photo_viewer_remembered_manual_zoom_precedes_af_point_zoom(
        tmp_path: Path,
) -> None:
    create_jpeg(tmp_path / 'IMG_7007.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7007.JPG', (0.8, 0.2))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-40, 30)
    remembered_scale = viewer._current_scale
    remembered_center = viewer.normalized_viewport_center()

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert viewer._current_scale == pytest.approx(remembered_scale)
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    viewer.close()


def test_photo_viewer_toggle_recenter_current_view_preserves_zoom_scale(
        tmp_path: Path,
) -> None:
    """
    Verify the view-only recenter toggle keeps the active zoom level.

    This protects Shift+F as a fast inspection aid: it should move the center
    between AF/default and remembered pan without changing magnification.
    """
    create_jpeg(tmp_path / 'IMG_7014.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7014.JPG', (0.65, 0.35))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-40, 30)
    scale_before = viewer._current_scale
    remembered_center = viewer.normalized_viewport_center()

    viewer.toggle_recenter_current_view()

    assert viewer._current_scale == pytest.approx(scale_before)
    assert viewer.normalized_viewport_center() == pytest.approx((0.65, 0.35))

    viewer.toggle_recenter_current_view()

    assert remembered_center is not None
    assert viewer._current_scale == pytest.approx(scale_before)
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    viewer.close()


def test_photo_viewer_recenter_toggle_does_not_replace_memory(
        tmp_path: Path,
) -> None:
    """
    Verify the recenter toggle does not overwrite remembered pan state.

    Shift+F temporarily snaps the current viewport to AF/default. Returning to
    the same photo should still restore the pre-existing manual center.
    """
    create_jpeg(tmp_path / 'IMG_7015.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7015.JPG', (0.65, 0.35))
    viewer.toggle_focus_zoom()
    viewer.pan_by(-40, 30)
    expected_center = viewer.normalized_viewport_center()

    viewer.toggle_recenter_current_view()
    assert viewer.normalized_viewport_center() == pytest.approx((0.65, 0.35))

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert expected_center is not None
    assert viewer.normalized_viewport_center() == pytest.approx(
        expected_center
    )

    viewer.close()


def test_photo_viewer_recenter_toggle_without_custom_center_is_safe(
        tmp_path: Path,
) -> None:
    """
    Verify toggling back with no custom center is a safe no-op.

    A photo may only have AF/default memory. In that case a second Shift+F
    should not crash or invent a remembered custom center.
    """
    create_jpeg(tmp_path / 'IMG_7019.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7019.JPG', (0.65, 0.35))
    viewer.toggle_focus_zoom()

    viewer.toggle_recenter_current_view()
    viewer.toggle_recenter_current_view()

    assert viewer.normalized_viewport_center() == pytest.approx((0.65, 0.35))

    viewer.close()


def test_photo_viewer_pan_after_recenter_toggle_updates_memory(
        tmp_path: Path,
) -> None:
    """
    Verify panning after the view-only recenter stores a new center.

    This protects the handoff from becoming sticky: Shift+F is temporary until
    the user pans, at which point the new inspected area is intentional.
    """
    create_jpeg(tmp_path / 'IMG_7018.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7018.JPG', (0.65, 0.35))
    viewer.toggle_focus_zoom()
    viewer.toggle_recenter_current_view()
    viewer.pan_by(-40, 30)
    expected_center = viewer.normalized_viewport_center()

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert expected_center is not None
    assert viewer.normalized_viewport_center() == pytest.approx(
        expected_center
    )
    assert viewer.normalized_viewport_center() != pytest.approx((0.65, 0.35))

    viewer.close()


def test_photo_viewer_reset_manual_centers_preserves_zoom_scale(
        tmp_path: Path,
) -> None:
    """
    Verify reset-all clears remembered centers but keeps zoom levels.

    Ctrl+Shift+F is the persistent memory reset, so previously panned photos
    should return to AF/default without losing their magnification.
    """
    create_jpeg(tmp_path / 'IMG_7016.JPG', 'white')
    create_jpeg(tmp_path / 'IMG_7017.JPG', 'blue')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    first_path = tmp_path / 'IMG_7016.JPG'
    second_path = tmp_path / 'IMG_7017.JPG'
    viewer.set_photo(first_path, (0.25, 0.75))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(40, -30)
    first_zoom = viewer.current_zoom_factor()

    viewer.set_photo(second_path, (0.65, 0.35))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-30, 35)
    second_zoom = viewer.current_zoom_factor()

    viewer.reset_manual_view_centers()

    assert viewer.current_zoom_factor() == pytest.approx(second_zoom)
    assert viewer.normalized_viewport_center() == pytest.approx((0.65, 0.35))

    viewer.set_fit_view()
    viewer.set_photo(first_path, (0.25, 0.75))
    viewer.toggle_focus_zoom()

    assert viewer.current_zoom_factor() == pytest.approx(first_zoom)
    assert viewer.normalized_viewport_center() == pytest.approx((0.25, 0.75))

    viewer.close()


def test_photo_viewer_hold_zoom_temporarily_zooms_pans_and_restores_fit(
        tmp_path: Path,
) -> None:
    """
    Pressing and holding the left mouse button in fit-to-window view should
    temporarily zoom the photo to 100%, let the user drag to pan that temporary
    view, and return to fit-to-window as soon as the mouse button is released.
    """
    create_jpeg(tmp_path / 'IMG_7008.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer(hold_zoom_enabled=True)
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7008.JPG', (0.5, 0.5))

    assert viewer._mode == 'fit'
    assert viewer.visible_region_rect() is None

    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    app.processEvents()

    visible_region_before = viewer.visible_region_rect()

    assert viewer._hold_zoom_active is True
    assert viewer._current_scale == pytest.approx(1.0)
    assert visible_region_before is not None

    center_before = viewer.normalized_viewport_center()
    QTest.mouseMove(viewer.viewport(), QPoint(120, 90))
    app.processEvents()
    center_after = viewer.normalized_viewport_center()

    assert center_after[0] > center_before[0]
    assert center_after[1] > center_before[1]

    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 90),
    )
    app.processEvents()

    assert viewer._hold_zoom_active is False
    assert viewer._mode == 'fit'
    assert viewer.visible_region_rect() is None

    viewer.close()


def test_photo_viewer_hold_zoom_does_not_change_remembered_manual_zoom(
        tmp_path: Path,
) -> None:
    """
    A click-and-hold inspection should be separate from normal manual zoom, so
    using it must not overwrite the zoom level and center restored by Space.
    """
    create_jpeg(tmp_path / 'IMG_7009.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer(hold_zoom_enabled=True)
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    image_path = tmp_path / 'IMG_7009.JPG'
    viewer.set_photo(image_path, (0.8, 0.2))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    viewer.pan_by(-40, 30)
    remembered_manual_view = viewer.current_manual_view()
    stored_manual_views = dict(viewer._manual_views)

    viewer.set_fit_view()

    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    QTest.mouseMove(viewer.viewport(), QPoint(120, 90))
    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 90),
    )
    app.processEvents()

    assert viewer._manual_views == stored_manual_views

    viewer.toggle_focus_zoom()

    restored_manual_view = viewer.current_manual_view()

    assert restored_manual_view is not None
    assert remembered_manual_view is not None
    assert restored_manual_view[0] == pytest.approx(remembered_manual_view[0])
    assert restored_manual_view[1] == pytest.approx(remembered_manual_view[1])

    viewer.close()


def test_photo_viewer_does_not_expose_compare_gesture_api(
        tmp_path: Path,
) -> None:
    """
    Verify the shared viewer does not own compare-only mouse gestures.

    Compare panes use a dedicated subclass for click-to-recenter and
    drag-to-pan signaling. This prevents normal single and split viewers from
    carrying hidden compare gesture state or signals they do not use.
    """
    create_jpeg(tmp_path / 'IMG_7010.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()
    viewer.set_photo(tmp_path / 'IMG_7010.JPG', (0.5, 0.5))

    assert not hasattr(viewer, 'normalized_left_clicked')
    assert not hasattr(viewer, 'image_dragged')

    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    QTest.mouseMove(viewer.viewport(), QPoint(120, 90))
    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(120, 90),
    )
    app.processEvents()

    assert not hasattr(viewer, '_left_press_active')
    assert not hasattr(viewer, '_left_drag_active')

    viewer.close()


def test_photo_viewer_manual_drag_pans_and_stores_view(
        tmp_path: Path,
) -> None:
    """
    Verify that in manual/zoomed view, holding the left mouse button and
    dragging pans the viewport, updates the normalized center, and saves the
    updated view immediately in manual_views.
    """
    create_jpeg(tmp_path / 'IMG_7011.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    image_path = tmp_path / 'IMG_7011.JPG'
    viewer.set_photo(image_path, (0.5, 0.5))

    # Zoom in to enter manual mode
    viewer.toggle_focus_zoom()
    assert viewer._mode == 'manual'
    assert viewer._pan_drag_active is False

    center_before = viewer.normalized_viewport_center()
    assert center_before is not None

    # Simulate mouse press and drag
    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(160, 120),
    )
    assert viewer._pan_drag_active is True

    # Drag to the top-left (meaning the viewport shifts down-right)
    QTest.mouseMove(viewer.viewport(), QPoint(100, 80))
    app.processEvents()

    center_after = viewer.normalized_viewport_center()
    assert center_after is not None
    assert center_after[0] > center_before[0]
    assert center_after[1] > center_before[1]

    # Verify that the manual view was saved automatically
    saved_view = viewer._manual_views.get(str(image_path))
    assert saved_view is not None
    assert saved_view.center == pytest.approx(center_after)

    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        QPoint(100, 80),
    )
    assert viewer._pan_drag_active is False
    assert viewer._mode == 'manual'

    viewer.close()
