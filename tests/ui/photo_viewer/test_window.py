from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

import easy_cull.ui.photo_viewer.window as photo_viewer_window_module
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.ui.launch import CullingLaunchRequest
from easy_cull.ui.photo_viewer.window import PhotoViewerWindow
from tests.ui._helpers import create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _disable_background_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        PhotoViewerWindow,
        '_start_photo_viewer_exif_refresh',
        lambda _self: None,
    )
    monkeypatch.setattr(
        PhotoViewerWindow, '_start_viewer_prefetch', lambda _self: None
    )
    monkeypatch.setattr(
        PhotoViewerWindow,
        '_start_folder_hydration',
        lambda _self, _folder: None,
    )


def _open_viewer(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        startup_name: str = 'B.JPG',
        folder_access_granted: bool = True,
) -> tuple[object, PhotoViewerWindow]:
    stub_read_exif(monkeypatch, {})
    _disable_background_startup(monkeypatch)
    monkeypatch.setattr(
        photo_viewer_window_module.FolderAccessManager,
        'ensure_access_for_file',
        lambda _manager, _path, _parent: folder_access_granted,
    )
    app = QApplication.instance() or QApplication([])
    window = PhotoViewerWindow(tmp_path / startup_name)
    window.show()
    app.processEvents()
    return app, window


def _trigger_viewer_shortcut(window: PhotoViewerWindow, key_text: str) -> None:
    for shortcut in window._viewer_shortcuts:
        if shortcut.key().toString(QKeySequence.PortableText) == key_text:
            shortcut.activated.emit()
            return

    raise AssertionError(f'Missing viewer shortcut for {key_text!r}')


def test_photo_viewer_window_opens_file_and_navigates_adjacent_photos(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify standalone file-open viewing and adjacent-photo navigation.

    The title assertions matter because this window now owns photo-viewer state
    directly instead of borrowing MainWindow's title and selection refreshes.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    create_jpeg(tmp_path / 'C.JPG', 'purple')

    _app, window = _open_viewer(tmp_path, monkeypatch)

    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyCull - B.JPG (2 / 3)'

    window.navigate(1)

    assert window.current_photo_id == 'C'
    assert window.windowTitle() == 'EasyCull - C.JPG (3 / 3)'

    window.navigate(-1)

    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyCull - B.JPG (2 / 3)'
    window.close()


def test_photo_viewer_shortcuts_control_split_zoom_and_keyboard_pan(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify standalone viewer shortcuts still control inspection state.

    These shortcuts used to come from MainWindow. The test guards against the
    decoupled PhotoViewerWindow dropping split view, zoom, or W/A/S/D panning.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    assert window.viewer.is_split_view() is False
    window.split_mode_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.is_split_view() is True

    window.split_mode_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer.is_split_view() is False

    window.viewer.set_fit_view()
    window.space_shortcut.activated.emit()
    app.processEvents()
    assert window.viewer._mode == 'single-manual'

    scale_before = window.viewer._current_scale
    _trigger_viewer_shortcut(window, '=')
    app.processEvents()

    assert window.viewer._current_scale > scale_before

    scale_before = window.viewer._current_scale
    _trigger_viewer_shortcut(window, '-')
    app.processEvents()

    assert window.viewer._current_scale < scale_before

    center_before = window.viewer.normalized_viewport_center()
    assert center_before is not None
    _trigger_viewer_shortcut(window, 'D')
    app.processEvents()
    center_after_d = window.viewer.normalized_viewport_center()
    assert center_after_d is not None
    assert center_after_d[0] > center_before[0]

    _trigger_viewer_shortcut(window, 'A')
    app.processEvents()
    center_after_a = window.viewer.normalized_viewport_center()
    assert center_after_a is not None
    assert center_after_a[0] < center_after_d[0]

    _trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    center_after_s = window.viewer.normalized_viewport_center()
    assert center_after_s is not None
    assert center_after_s[1] > center_after_a[1]

    _trigger_viewer_shortcut(window, 'W')
    app.processEvents()
    center_after_w = window.viewer.normalized_viewport_center()
    assert center_after_w is not None
    assert center_after_w[1] < center_after_s[1]
    window.close()


def test_photo_viewer_shortcuts_toggle_af_marker_and_info_overlay(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify standalone viewer shortcuts control AF and EXIF overlays.

    MainWindow used to own both shortcuts. This guards the decoupled viewer
    against losing ``F`` marker toggling or ``I`` EXIF/histogram display.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    photo = window.library.get_photo('A')
    photo.exif_display = {'Camera Model': 'Z 8', 'ISO': '800'}

    assert window.exif_overlay.isHidden() is True

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window._info_overlay_enabled is True
    assert window.exif_overlay.isVisible() is True
    assert window.exif_overlay.exif_display() == {
        'Camera Model': 'Z 8',
        'ISO': '800',
    }
    assert window.exif_overlay.histogram_plot.histogram() is not None

    window._photo_viewer_exif_request_id = 5
    window._handle_photo_viewer_exif_failed(5, 'exif failed')
    app.processEvents()
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

    assert window._show_af_point_marker is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

    assert window._show_af_point_marker is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window._info_overlay_enabled is False
    assert window.exif_overlay.isHidden() is True
    window.close()


def test_photo_viewer_denied_access_blocks_navigation_and_handoff(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify denied folder access stays limited to the opened photo.

    Navigation and culling handoff require a full folder scan, so both paths
    must stop with the recovery message instead of silently opening stale or
    incomplete culling state.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    messages: list[tuple[str, int]] = []
    monkeypatch.setattr(
        PhotoViewerWindow,
        '_show_transient_message',
        lambda _self, message, *, timeout_ms: messages.append((
            message,
            timeout_ms,
        )),
    )
    _app, window = _open_viewer(
        tmp_path, monkeypatch, folder_access_granted=False
    )
    requests: list[object] = []
    window.culling_requested.connect(requests.append)

    assert [photo.photo_id for photo in window.library.photos] == ['B']
    assert len(messages) == 1

    window.navigate(-1)
    window._request_culling_handoff()

    assert window.current_photo_id == 'B'
    assert requests == []
    assert len(messages) == 3
    assert 'Browsing photos in this folder' in messages[0][0]
    assert (
        messages[0][1]
        == photo_viewer_window_module.FOLDER_ACCESS_RECOVERY_TIMEOUT_MS
    )
    window.close()


def test_photo_viewer_exif_failure_reveals_fallback_focus_marker(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify EXIF failure clears the pending focus-point state.

    Without this fallback, the AF marker remains hidden forever even though the
    viewer has a usable center-point fallback for focus zoom.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    photo = window.library.get_photo('A')

    assert photo.focus_point == (0.5, 0.5)
    assert photo.focus_point_pending is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window._photo_viewer_exif_request_id = 7
    window._handle_photo_viewer_exif_failed(7, 'exif failed')
    app.processEvents()

    assert photo.focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True
    window.close()


def test_photo_viewer_culling_handoff_waits_for_hydration(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify culling handoff waits for full-folder hydration.

    The viewer opens quickly from a lightweight folder load, but the culler
    needs the hydrated library. This also protects the timing edge where
    hydration has finished before the thread cleanup slot clears.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    hydrated_library = PhotoLibrary(cache_dir=tmp_path / '.hydrated-cache')
    hydrated_library.load_folder(tmp_path)
    requests: list[object] = []
    window.culling_requested.connect(requests.append)
    request_id = window._folder_hydration_request_id = 3
    expected_folder = tmp_path.resolve()
    window._folder_hydration_folder = expected_folder
    window._folder_hydration_thread = object()
    window._folder_hydration_message = 'Loading folder...'
    window._folder_hydration_progress = 42

    window._request_culling_handoff()

    assert requests == []
    assert window._pending_culling_handoff is True
    assert window.progress_overlay.isVisible() is True

    window._handle_folder_hydration_finished(
        request_id, expected_folder, hydrated_library
    )

    assert len(requests) == 1
    request = requests[0]
    assert isinstance(request, CullingLaunchRequest)
    assert request.folder == tmp_path.resolve()
    assert request.selected_photo_id == 'B'
    assert request.enter_browse is True
    assert request.preloaded_library is hydrated_library
    window._folder_hydration_thread = None
    window.close()
