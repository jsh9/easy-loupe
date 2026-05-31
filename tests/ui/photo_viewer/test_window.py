from __future__ import annotations

from typing import TYPE_CHECKING

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


def test_photo_viewer_window_opens_file_and_navigates_adjacent_photos(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def test_photo_viewer_denied_access_blocks_navigation_and_handoff(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(
        tmp_path, monkeypatch, folder_access_granted=False
    )
    messages: list[tuple[str, int]] = []
    requests: list[object] = []
    monkeypatch.setattr(
        window,
        '_show_transient_message',
        lambda message, *, timeout_ms: messages.append((message, timeout_ms)),
    )
    window.culling_requested.connect(requests.append)

    assert [photo.photo_id for photo in window.library.photos] == ['B']

    window.navigate(-1)
    window._request_culling_handoff()

    assert window.current_photo_id == 'B'
    assert requests == []
    assert len(messages) == 2
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
