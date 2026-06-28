from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QGraphicsItem

import easy_loupe.ui.viewers.clipping as clipping_module
import easy_loupe.ui.viewers.photo_viewer as photo_viewer_module
from tests.ui._helpers import create_jpeg, process_events_until

if TYPE_CHECKING:
    from pathlib import Path


CLIPPING_OVERLAY_TIMEOUT_MS = 5_000


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


def test_photo_viewer_minimap_center_preserves_manual_zoom(
        tmp_path: Path,
) -> None:
    """
    Verify minimap recentering moves the manual viewport without rescaling.

    The minimap is an alternate pan control, so it should reuse the current
    zoom level rather than acting like a new focus-zoom request.
    """
    create_jpeg(tmp_path / 'IMG_7010.JPG', 'orange')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7010.JPG', (0.5, 0.5))
    viewer.toggle_focus_zoom()
    viewer.zoom_step(1.25)
    zoom_before = viewer.current_zoom_factor()

    viewer.set_normalized_viewport_center((0.75, 0.25))

    assert viewer.current_zoom_factor() == pytest.approx(zoom_before)
    assert viewer.normalized_viewport_center() == pytest.approx((0.75, 0.25))
    assert viewer.visible_region_rect() is not None

    viewer.close()


def test_photo_viewer_minimap_center_noops_in_fit_view(
        tmp_path: Path,
) -> None:
    """
    Fit view has no red-box minimap owner, so recenter requests are inert.
    """
    create_jpeg(tmp_path / 'IMG_7011.JPG', 'orange')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7011.JPG', (0.5, 0.5))
    center_before = viewer.normalized_viewport_center()

    viewer.set_normalized_viewport_center((0.75, 0.25))

    assert viewer._mode == 'fit'
    assert viewer.normalized_viewport_center() == pytest.approx(center_before)
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


def test_photo_viewer_clipping_warning_tracks_loaded_photo(
        tmp_path: Path,
) -> None:
    """
    Verify clipping warnings are a persistent viewer overlay preference.

    Toggling should apply to the active photo, survive zoom mode changes, and
    hide cleanly when the photo is cleared without resetting the user's
    preference.
    """
    create_jpeg(tmp_path / 'IMG_7016.JPG', 'white')

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    overlay = viewer._clipping_overlay_item
    viewer.set_photo(tmp_path / 'IMG_7016.JPG', (0.5, 0.5))

    assert viewer._clipping_warning_enabled is False
    assert overlay.isVisible() is False

    viewer.set_clipping_warning_visible(enabled=True)

    assert viewer._clipping_warning_enabled is True
    # Clipping work is timer-delayed and backgrounded, so native macOS CI can
    # need longer than the generic deferred-UI wait after full-suite runs.
    process_events_until(
        app,
        overlay.isVisible,
        timeout_ms=CLIPPING_OVERLAY_TIMEOUT_MS,
    )
    assert overlay.pixmap().isNull() is False
    assert overlay.zValue() < viewer._focus_point_marker.zValue()

    viewer.toggle_focus_zoom()

    assert overlay.isVisible() is True

    viewer.clear_photo()

    assert viewer._clipping_warning_enabled is True
    assert overlay.isVisible() is False
    assert overlay.pixmap().isNull() is True

    viewer.set_photo(tmp_path / 'IMG_7016.JPG', (0.5, 0.5))

    # The first load populated the cache, so revisiting reuses cached payload
    # data while still decoding the overlay image off the UI thread.
    process_events_until(
        app,
        overlay.isVisible,
        timeout_ms=CLIPPING_OVERLAY_TIMEOUT_MS,
    )
    assert overlay.isVisible() is True

    viewer.close()


def test_photo_viewer_scales_bounded_clipping_overlay_to_photo(
        tmp_path: Path,
) -> None:
    """
    Verify bounded clipping overlays still cover the loaded image scene.

    The generated overlay pixmap may be smaller than the displayed preview, so
    the graphics item must scale it back into photo coordinate space. Clearing
    must also reset that transform so later photos cannot inherit stale scale.
    """
    create_jpeg(
        tmp_path / 'IMG_7017.JPG',
        'white',
        size=(4000, 1000),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7017.JPG', (0.5, 0.5))
    viewer.set_clipping_warning_visible(enabled=True)

    overlay = viewer._clipping_overlay_item
    process_events_until(
        app,
        overlay.isVisible,
        timeout_ms=CLIPPING_OVERLAY_TIMEOUT_MS,
    )
    transform = overlay.transform()

    assert overlay.pixmap().width() == 3000
    assert overlay.pixmap().height() == 750
    assert transform.m11() == pytest.approx(4000 / 3000)
    assert transform.m22() == pytest.approx(1000 / 750)
    assert overlay.boundingRect().width() * transform.m11() == pytest.approx(
        4000
    )
    assert overlay.boundingRect().height() * transform.m22() == pytest.approx(
        1000
    )

    viewer.clear_photo()

    assert overlay.transform().m11() == pytest.approx(1.0)
    assert overlay.transform().m22() == pytest.approx(1.0)
    viewer.close()


def test_photo_viewer_clipping_cache_miss_starts_background_job(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify uncached clipping overlays do not block ``set_photo``.

    Cache misses should defer background generation briefly, enqueue one
    current job, and leave the overlay hidden until the worker result arrives.
    """
    create_jpeg(tmp_path / 'IMG_7025.JPG', 'white')
    started_jobs = []

    class FakeThreadPool:
        @staticmethod
        def start(job: object) -> None:
            started_jobs.append(job)

    monkeypatch.setattr(
        photo_viewer_module.QThreadPool,
        'globalInstance',
        staticmethod(FakeThreadPool),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7025.JPG', (0.5, 0.5))

    assert started_jobs == []
    process_events_until(app, lambda: len(started_jobs) == 1)
    assert len(started_jobs) == 1
    assert viewer._clipping_overlay_item.isVisible() is False
    viewer.close()


def test_photo_viewer_close_before_clipping_delay_prevents_job_start(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify closing the viewer cancels delayed clipping work before enqueue.

    The delayed start exists to skip stale rapid-navigation requests. Closing
    the widget is another stale path, so teardown must stop the child timer
    before it can hand work to the global thread pool.
    """
    create_jpeg(tmp_path / 'IMG_7030.JPG', 'white')
    started_jobs = []

    class FakeThreadPool:
        @staticmethod
        def start(job: object) -> None:
            started_jobs.append(job)

    monkeypatch.setattr(
        photo_viewer_module.QThreadPool,
        'globalInstance',
        staticmethod(FakeThreadPool),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(tmp_path / 'IMG_7030.JPG', (0.5, 0.5))
    assert viewer._clipping_overlay_start_timer.isActive() is True

    viewer.close()
    app.processEvents()
    QTest.qWait(photo_viewer_module.CLIPPING_OVERLAY_JOB_START_DELAY_MS * 2)
    app.processEvents()

    assert started_jobs == []
    assert viewer._clipping_overlay_start_timer.isActive() is False
    assert viewer._pending_clipping_overlay_request is None
    assert viewer._clipping_overlay_jobs == {}


def test_photo_viewer_close_after_clipping_enqueue_cancels_job(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify an enqueued clipping job becomes inert after viewer teardown.

    A job may already be held by the thread pool when the widget closes. The
    worker can finish its Python run method later, but it must not build new
    overlay data, emit Qt signals, or mutate the now-closed viewer.
    """
    image_path = tmp_path / 'IMG_7031.JPG'
    create_jpeg(image_path, 'white')
    started_jobs = []

    class FakeThreadPool:
        @staticmethod
        def start(job: object) -> None:
            started_jobs.append(job)

    monkeypatch.setattr(
        photo_viewer_module.QThreadPool,
        'globalInstance',
        staticmethod(FakeThreadPool),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(image_path, (0.5, 0.5))
    process_events_until(app, lambda: len(started_jobs) == 1)
    job = started_jobs[0]
    emitted_signals = []
    job.signals.finished.connect(
        lambda *_args: emitted_signals.append('finished')
    )
    job.signals.failed.connect(lambda *_args: emitted_signals.append('failed'))

    build_calls = []

    def fail_if_build_runs(*_args: object, **_kwargs: object) -> object:
        build_calls.append('build')
        raise AssertionError('cancelled clipping job should not build')

    monkeypatch.setattr(
        clipping_module, '_build_clipping_overlay_payload', fail_if_build_runs
    )

    viewer.close()
    app.processEvents()
    job.run()
    app.processEvents()

    assert job._cancelled.is_set() is True
    assert build_calls == []
    assert emitted_signals == []
    assert viewer._clipping_overlay_jobs == {}
    assert viewer._clipping_overlay_item.isVisible() is False


def test_photo_viewer_clipping_cache_hit_applies_asynchronously(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify cached clipping payloads appear without rebuilding analysis data.

    Cache hits still decode off the UI thread, so repeat navigation should
    reuse the payload cache while keeping display work asynchronous.
    """
    image_path = tmp_path / 'IMG_7026.JPG'
    create_jpeg(image_path, 'white')
    cache_key = clipping_module.clipping_overlay_cache_key(image_path)
    clipping_module.clipping_overlay_payload_for_key(cache_key)

    def fail_build(*_args: object, **_kwargs: object) -> object:
        raise AssertionError('cached overlay should not rebuild payload')

    monkeypatch.setattr(
        clipping_module, '_build_clipping_overlay_payload', fail_build
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(image_path, (0.5, 0.5))

    process_events_until(app, viewer._clipping_overlay_item.isVisible)
    assert viewer._clipping_overlay_item.isVisible() is True
    viewer.close()


def test_photo_viewer_ignores_stale_clipping_worker_result(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify stale clipping requests are dropped before worker enqueue.

    Rapid navigation should replace photo A with photo B before the delayed
    start fires, so only the current photo reaches the global thread pool.
    """
    first_path = tmp_path / 'IMG_7027.JPG'
    second_path = tmp_path / 'IMG_7028.JPG'
    create_jpeg(first_path, 'white')
    create_jpeg(second_path, 'black')
    started_jobs = []

    class FakeThreadPool:
        @staticmethod
        def start(job: object) -> None:
            started_jobs.append(job)

    monkeypatch.setattr(
        photo_viewer_module.QThreadPool,
        'globalInstance',
        staticmethod(FakeThreadPool),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(first_path, (0.5, 0.5))
    viewer.set_photo(second_path, (0.5, 0.5))

    process_events_until(app, lambda: len(started_jobs) == 1)
    assert len(started_jobs) == 1
    current_job = started_jobs[0]
    assert current_job.cache_key.image_path == str(second_path)
    current_payload = clipping_module.clipping_overlay_payload_for_key(
        current_job.cache_key
    )
    current_image = clipping_module.clipping_overlay_qimage_from_payload(
        current_payload
    )
    current_result = photo_viewer_module._ClippingOverlayResult(
        current_payload.width,
        current_payload.height,
        current_image,
    )
    current_job.signals.finished.emit(
        current_job.request_id, current_job.cache_key, current_result
    )
    app.processEvents()

    assert viewer._clipping_overlay_item.isVisible() is True
    viewer.close()


def test_photo_viewer_ignores_disabled_clipping_worker_result(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify disabling clipping before delayed start prevents worker enqueue.

    This covers the same async race as fast navigation, but with the overlay
    preference invalidating the pending request before it reaches the pool.
    """
    image_path = tmp_path / 'IMG_7029.JPG'
    create_jpeg(image_path, 'white')
    started_jobs = []

    class FakeThreadPool:
        @staticmethod
        def start(job: object) -> None:
            started_jobs.append(job)

    monkeypatch.setattr(
        photo_viewer_module.QThreadPool,
        'globalInstance',
        staticmethod(FakeThreadPool),
    )

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_clipping_warning_visible(enabled=True)
    viewer.set_photo(image_path, (0.5, 0.5))
    viewer.set_clipping_warning_visible(enabled=False)

    app.processEvents()
    QTest.qWait(photo_viewer_module.CLIPPING_OVERLAY_JOB_START_DELAY_MS * 2)
    app.processEvents()

    assert started_jobs == []
    assert viewer._clipping_overlay_item.isVisible() is False
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
    assert restored_manual_view.zoom_factor == pytest.approx(
        remembered_manual_view.zoom_factor
    )
    assert restored_manual_view.center == pytest.approx(
        remembered_manual_view.center
    )

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


def test_photo_viewer_edge_recenter_does_not_persist_transient_scale(
        tmp_path: Path,
) -> None:
    """
    Verify edge AF recentering does not replace remembered zoom.

    Centering an edge focus point can require a much larger live scale than the
    user's remembered manual view. Returning to fit and back should restore the
    remembered zoom and pan, not the temporary edge-corrected scale.
    """
    create_jpeg(tmp_path / 'IMG_7020.JPG', 'white', size=(2400, 1600))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(1200, 800)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7020.JPG', (0.5, 0.5))
    viewer.set_manual_view(1.25, (0.5, 0.5))
    viewer.pan_by(24, 0)
    remembered_view = viewer.current_manual_view()

    viewer.set_focus_point((0.02, 0.5))
    viewer.toggle_recenter_current_view()

    assert remembered_view is not None
    assert viewer.current_zoom_factor() > remembered_view.zoom_factor
    assert viewer.normalized_viewport_center() != pytest.approx(
        remembered_view.center
    )

    viewer.toggle_focus_zoom()
    viewer.toggle_focus_zoom()

    restored_view = viewer.current_manual_view()

    assert restored_view is not None
    assert restored_view.zoom_factor == pytest.approx(
        remembered_view.zoom_factor
    )
    assert restored_view.center == pytest.approx(remembered_view.center)
    assert viewer.current_zoom_factor() == pytest.approx(
        remembered_view.zoom_factor
    )
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_view.center
    )

    viewer.close()


def test_photo_viewer_edge_recenter_toggle_restores_original_zoom(
        tmp_path: Path,
) -> None:
    """
    Verify toggling back from an edge AF snap restores the whole manual view.

    Shift+F may need extra live zoom to center an edge AF point, but a second
    Shift+F should return to the user's original zoom level and center.
    """
    create_jpeg(tmp_path / 'IMG_7024.JPG', 'white', size=(2400, 1600))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(1200, 800)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7024.JPG', (0.5, 0.5))
    viewer.set_manual_view(1.25, (0.5, 0.5))
    viewer.pan_by(24, 0)
    remembered_view = viewer.current_manual_view()

    viewer.set_focus_point((0.02, 0.5))
    viewer.toggle_recenter_current_view()

    assert remembered_view is not None
    assert viewer.current_zoom_factor() > remembered_view.zoom_factor
    assert viewer.normalized_viewport_center() != pytest.approx(
        remembered_view.center
    )

    viewer.toggle_recenter_current_view()

    assert viewer.current_zoom_factor() == pytest.approx(
        remembered_view.zoom_factor
    )
    assert viewer.normalized_viewport_center() == pytest.approx(
        remembered_view.center
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


def test_photo_viewer_pending_focus_reset_center_survives_focus_update(
        tmp_path: Path,
) -> None:
    """
    Verify late AF metadata preserves reset-center zoom memory.

    Ctrl+Shift+F stores ``center=None`` to mean "use this photo's AF/default
    center". When the real AF point arrives later, the zoom factor should stay
    remembered and the sentinel should resolve to the new AF point.
    """
    image_path = tmp_path / 'IMG_7021.JPG'
    create_jpeg(image_path, 'white', size=(2400, 1600))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(1200, 800)
    viewer.show()
    app.processEvents()

    viewer.set_photo(image_path, (0.5, 0.5), focus_point_pending=True)
    viewer.toggle_focus_zoom()
    initial_zoom = viewer.current_zoom_factor()
    viewer.zoom_step(2.0)
    expected_zoom = viewer.current_zoom_factor()

    viewer.reset_manual_view_centers()
    viewer.set_focus_point((0.2, 0.8))

    stored_view = viewer._manual_views.get(str(image_path))

    assert expected_zoom == pytest.approx(initial_zoom * 2.0)
    assert stored_view is not None
    assert stored_view.zoom_factor == pytest.approx(expected_zoom)
    assert stored_view.center is None

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert viewer.current_zoom_factor() == pytest.approx(expected_zoom)
    assert viewer.normalized_viewport_center() == pytest.approx((0.2, 0.8))

    viewer.close()


def test_photo_viewer_pending_focus_concrete_center_is_cleared_on_focus_update(
        tmp_path: Path,
) -> None:
    """
    Verify concrete fallback centers do not survive late AF metadata.

    If the user panned while focus was still pending, that center was based on
    fallback coordinates. Once the real AF point arrives, restoring should use
    the new AF point rather than the stale fallback-centered pan.
    """
    image_path = tmp_path / 'IMG_7022.JPG'
    create_jpeg(image_path, 'white', size=(2400, 1600))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(1200, 800)
    viewer.show()
    app.processEvents()

    viewer.set_photo(image_path, (0.5, 0.5), focus_point_pending=True)
    viewer.toggle_focus_zoom()
    viewer.zoom_step(2.0)
    viewer.pan_by(120, -80)
    stale_center = viewer.normalized_viewport_center()

    assert viewer._manual_views.get(str(image_path)) is not None

    viewer.set_focus_point((0.2, 0.8))

    assert viewer._manual_views.get(str(image_path)) is None

    viewer.set_fit_view()
    viewer.toggle_focus_zoom()

    assert stale_center is not None
    assert viewer.normalized_viewport_center() == pytest.approx((0.2, 0.8))
    assert viewer.normalized_viewport_center() != pytest.approx(stale_center)

    viewer.close()


def test_photo_viewer_transient_recenter_survives_resize_without_storing(
        tmp_path: Path,
) -> None:
    """
    Verify resize keeps a temporary recenter visible without saving it.

    A geometry change during Shift+F should not snap back to the remembered
    custom center, and it should not replace the stored manual view.
    """
    image_path = tmp_path / 'IMG_7023.JPG'
    create_jpeg(image_path, 'white', size=(2400, 1600))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer()
    viewer.resize(1200, 800)
    viewer.show()
    app.processEvents()

    viewer.set_photo(image_path, (0.7, 0.3))
    viewer.toggle_focus_zoom()
    viewer.pan_by(200, 100)
    expected_zoom = viewer.current_zoom_factor()
    stored_views = dict(viewer._manual_views)

    viewer.toggle_recenter_current_view()
    viewer.resize(1000, 800)
    app.processEvents()

    assert viewer.normalized_viewport_center() == pytest.approx((0.7, 0.3))
    assert viewer._manual_views == stored_views

    viewer.toggle_recenter_current_view()

    stored_view = stored_views[str(image_path)]
    assert viewer.current_zoom_factor() == pytest.approx(expected_zoom)
    assert viewer.normalized_viewport_center() == pytest.approx(
        stored_view.center
    )
    assert viewer._manual_views == stored_views

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


def test_photo_viewer_hold_zoom_anchors_off_center_cursor(
        tmp_path: Path,
) -> None:
    """
    Verify hold zoom keeps the clicked image point under the mouse cursor.

    This guards against treating the clicked point as the viewport center,
    which drifts increasingly far from the cursor for off-center clicks.
    """
    create_jpeg(tmp_path / 'IMG_7015.JPG', 'white', size=(640, 480))

    app = QApplication.instance() or QApplication([])
    viewer = photo_viewer_module.PhotoViewer(hold_zoom_enabled=True)
    viewer.resize(320, 240)
    viewer.show()
    app.processEvents()

    viewer.set_photo(tmp_path / 'IMG_7015.JPG', (0.5, 0.5))

    click_pos = QPoint(200, 120)
    clicked_scene_pos = viewer.mapToScene(click_pos)

    QTest.mousePress(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        click_pos,
    )
    app.processEvents()

    anchored_scene_pos = viewer.mapToScene(click_pos)

    assert viewer._hold_zoom_active is True
    assert viewer._current_scale == pytest.approx(1.0)
    assert anchored_scene_pos.x() == pytest.approx(
        clicked_scene_pos.x(), abs=1.0
    )
    assert anchored_scene_pos.y() == pytest.approx(
        clicked_scene_pos.y(), abs=1.0
    )

    QTest.mouseRelease(
        viewer.viewport(),
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        click_pos,
    )
    app.processEvents()

    assert viewer._hold_zoom_active is False
    assert viewer._mode == 'fit'

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
    assert restored_manual_view.zoom_factor == pytest.approx(
        remembered_manual_view.zoom_factor
    )
    assert restored_manual_view.center == pytest.approx(
        remembered_manual_view.center
    )

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
