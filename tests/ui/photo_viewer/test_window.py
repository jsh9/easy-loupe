from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

import easy_loupe.ui.identity as identity_module
import easy_loupe.ui.main_window.build as build_module
import easy_loupe.ui.photo_viewer.window as photo_viewer_window_module
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.progress import ProgressReporter, ProgressStageDefinition
from easy_loupe.ui.launch import CullingLaunchRequest
from easy_loupe.ui.photo_viewer.window import PhotoViewerWindow
from easy_loupe.ui.photo_viewer.workers import PhotoViewerExifResult
from tests.ui._helpers import create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path


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


def _assert_close_tuple(
        actual: tuple[float, ...],
        expected: tuple[float, ...],
        *,
        tolerance: float = 0.02,
) -> None:
    assert len(actual) == len(expected)
    for actual_value, expected_value in zip(actual, expected, strict=True):
        assert abs(actual_value - expected_value) <= tolerance


def _minimap_point(widget: Any, x: float, y: float) -> QPoint:
    target = widget.displayed_image_rect()
    return QPoint(
        int(target.left() + (target.width() * x)),
        int(target.top() + (target.height() * y)),
    )


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
    assert window.windowTitle() == 'EasyLoupe - B.JPG (2 / 3)'

    window.navigate(1)

    assert window.current_photo_id == 'C'
    assert window.windowTitle() == 'EasyLoupe - C.JPG (3 / 3)'

    window.navigate(-1)

    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyLoupe - B.JPG (2 / 3)'
    window.close()


def test_photo_viewer_culling_hydration_uses_recursive_preference(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify culling handoff hydration reads the recursive preference.

    Standalone viewer navigation remains immediate-folder based, but the
    hydrated culling library should honor the culling workspace setting.
    """
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    settings = QSettings(identity_module.APP_NAME, identity_module.APP_NAME)
    settings.setValue(build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY, False)
    settings.sync()

    _app, window = _open_viewer(tmp_path, monkeypatch)

    assert window._load_culling_recursive_preference() is False

    settings.setValue(build_module.PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY, True)
    settings.sync()

    assert window._load_culling_recursive_preference() is True

    window.close()


def test_photo_viewer_navigation_preview_failure_preserves_current_photo(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify a bad adjacent preview preserves the current photo.

    Navigation updates the current id before rendering the next preview; this
    guards the rollback path so title, state, and handoff stay on the last
    successfully displayed photo.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    create_jpeg(tmp_path / 'C.JPG', 'purple')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    original_get_preview_path = window.library.get_preview_path
    messages: list[str] = []
    monkeypatch.setattr(
        window,
        '_show_transient_message',
        lambda message, **_kwargs: messages.append(message),
    )

    def get_preview_path(photo_id: str, kind: str) -> Path:
        if photo_id == 'C':
            raise RuntimeError('corrupt preview')

        return original_get_preview_path(photo_id, kind)

    monkeypatch.setattr(window.library, 'get_preview_path', get_preview_path)

    window.navigate(1)

    assert window.current_photo_id == 'B'
    assert window.windowTitle() == 'EasyLoupe - B.JPG (2 / 3)'
    assert messages == ['Failed to open photo: corrupt preview']
    window.close()


def test_photo_viewer_minimap_thumb_failure_hides_minimap(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify thumbnail failure during minimap refresh stays non-fatal.

    Manual zoom emits visible-region updates after the main preview is already
    displayed; a bad thumbnail should hide only the minimap, not disrupt the
    active viewer state.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    app.processEvents()
    window.space_shortcut.activated.emit()
    app.processEvents()
    original_get_preview_path = window.library.get_preview_path

    def get_preview_path(photo_id: str, kind: str) -> Path:
        if kind == 'thumb':
            raise RuntimeError('corrupt thumb')

        return original_get_preview_path(photo_id, kind)

    monkeypatch.setattr(window.library, 'get_preview_path', get_preview_path)
    window._minimap_photo_id = None

    window._refresh_visible_region_overlay()

    assert window.current_photo_id == 'A'
    assert window.minimap.isHidden() is True
    window.close()


def test_photo_viewer_minimap_drag_recenters_zoomed_photo(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify the standalone floating minimap can pan the zoomed viewer.

    The minimap is hosted outside the culling thumbnail lists, so this covers
    the direct PhotoViewerWindow signal wiring.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    app.processEvents()

    window.space_shortcut.activated.emit()
    window.viewer.zoom_step(1.25)
    app.processEvents()

    assert window.minimap.isVisible() is True

    QTest.mousePress(
        window.minimap,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(window.minimap, 0.5, 0.5),
    )
    QTest.mouseMove(window.minimap, _minimap_point(window.minimap, 0.65, 0.35))
    QTest.mouseRelease(
        window.minimap,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
        _minimap_point(window.minimap, 0.65, 0.35),
    )
    app.processEvents()

    assert window.viewer.normalized_viewport_center() == pytest.approx(
        (0.65, 0.35), abs=0.02
    )
    window.close()


def test_photo_viewer_startup_preview_failure_closes_viewer(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify startup preview render errors close through the open-failure UI.

    Metadata scanning can succeed before image decoding fails, so startup needs
    a controlled error path instead of leaving a blank viewer window.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    stub_read_exif(monkeypatch, {})
    _disable_background_startup(monkeypatch)
    monkeypatch.setattr(
        photo_viewer_window_module.FolderAccessManager,
        'ensure_access_for_file',
        lambda _manager, _path, _parent: True,
    )

    def fail_preview(
            _library: PhotoLibrary, _photo_id: str, _kind: str
    ) -> Path:
        raise RuntimeError('decode failed')

    monkeypatch.setattr(PhotoLibrary, 'get_preview_path', fail_preview)
    critical_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, message: critical_calls.append((
            title,
            message,
        )),
    )
    app = QApplication.instance() or QApplication([])
    window = PhotoViewerWindow(tmp_path / 'A.JPG')
    window.show()

    app.processEvents()

    assert critical_calls == [('Failed to Open Photo', 'decode failed')]
    assert window._closing is True


def test_photo_viewer_message_overlays_are_framed_and_readable(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify viewer messages use visible framed overlays.

    The standalone viewer owns these overlays now; without local styling,
    hydration and access messages regress to barely visible bare labels over
    the photo.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    window._show_progress('Loading folder...', 42)

    assert window.progress_overlay.isVisible() is True
    assert 'rgba(20, 24, 29, 140)' in window.progress_overlay.styleSheet()
    assert 'QFrame#progressPanel' in window.progress_panel.styleSheet()
    assert 'border-radius: 12px' in window.progress_panel.styleSheet()
    assert 'font-size: 16px' in window.overlay_message_label.styleSheet()

    window._hide_progress()
    window._show_transient_message('Grant folder access')

    assert window.transient_message_overlay.isVisible() is True
    assert (
        'rgba(20, 24, 29, 90)' in window.transient_message_overlay.styleSheet()
    )
    assert (
        'QFrame#transientMessagePanel'
        in window.transient_message_panel.styleSheet()
    )
    assert 'border-radius: 12px' in window.transient_message_panel.styleSheet()
    assert 'font-size: 28px' in window.transient_message_label.styleSheet()
    window.close()


def test_photo_viewer_escape_dismisses_transient_message_overlay(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify Escape immediately dismisses transient viewer messages.

    Folder-access recovery messages are intentionally non-modal, but they can
    linger long enough to block inspection. This protects the manual dismissal
    path without making real progress overlays dismissible.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window._show_transient_message('Grant folder access', timeout_ms=10_000)
    app.processEvents()

    assert window.transient_message_overlay.isVisible() is True
    assert window.transient_message_timer.isActive() is True

    window.dismiss_message_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    assert window.transient_message_timer.isActive() is False
    window.close()


def test_photo_viewer_shortcut_help_toggles_and_esc_closes_first(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify standalone viewer help uses ? and wins the first Esc press.

    The viewer already uses Esc to dismiss transient messages, so this guards
    the new shortcut-help overlay from being skipped by that older behavior.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    assert (
        window.shortcut_help_shortcut.key().toString(QKeySequence.PortableText)
        == '?'
    )

    window._show_transient_message('Ready')
    window.shortcut_help_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isVisible() is True
    assert window.shortcut_help_overlay.isVisible() is True
    assert window.shortcut_help_overlay.title_label.text() == (
        'Photo Viewer Shortcuts'
    )

    window.dismiss_message_shortcut.activated.emit()
    app.processEvents()

    assert window.shortcut_help_overlay.isHidden() is True
    assert window.transient_message_overlay.isVisible() is True

    window.dismiss_message_shortcut.activated.emit()
    app.processEvents()

    assert window.transient_message_overlay.isHidden() is True
    window.close()
    app.processEvents()


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


def test_photo_viewer_fit_mode_stays_fit_across_navigation(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify fit view remains fit when navigating photos.

    Preserving inspection state should not turn ordinary fit-to-window browsing
    into manual zoom.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    assert window.viewer._mode == 'single-fit'

    window.navigate(1)

    assert window.current_photo_id == 'B'
    assert window.viewer._mode == 'single-fit'
    assert window.viewer.visible_region_rect() is None
    window.close()


def test_photo_viewer_manual_zoom_carries_across_navigation(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify single-pane manual zoom carries to the next photo.

    This protects inspection workflows where the user checks the same area and
    scale across adjacent photos with arrow-key navigation.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    app.processEvents()

    window.space_shortcut.activated.emit()
    _trigger_viewer_shortcut(window, '=')
    _trigger_viewer_shortcut(window, 'D')
    _trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    expected_zoom = window.viewer._current_scale
    expected_center = window.viewer.normalized_viewport_center()
    assert expected_center is not None

    window.navigate(1)
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window.viewer._mode == 'single-manual'
    assert abs(window.viewer._current_scale - expected_zoom) <= 0.02
    center = window.viewer.normalized_viewport_center()
    assert center is not None
    _assert_close_tuple(center, expected_center)
    window.close()


def test_photo_viewer_registers_recenter_zoom_shortcuts(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    assert (
        window.recenter_zoom_shortcut.key().toString(QKeySequence.PortableText)
        == 'Shift+F'
    )
    assert (
        window.reset_zoom_centers_shortcut.key().toString(
            QKeySequence.PortableText
        )
        == 'Ctrl+Shift+F'
    )

    window.close()


def test_photo_viewer_recenter_zoom_shortcut_does_not_change_navigation_handoff(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify Shift+F stays view-only in standalone photo-viewer navigation.

    The file-open viewer captures inspection state before adjacent-photo loads,
    so this guards against carrying the temporary AF/default recenter to the
    next photo.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    window.library.get_photo('A').focus_point = (0.35, 0.65)
    window.library.get_photo('B').focus_point = (0.65, 0.35)
    window._display_current_photo()
    app.processEvents()

    window.space_shortcut.activated.emit()
    _trigger_viewer_shortcut(window, '=')
    _trigger_viewer_shortcut(window, 'D')
    _trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    expected_zoom = window.viewer._current_scale
    remembered_center = window.viewer.normalized_viewport_center()

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.35,
        0.65,
    ))

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    assert remembered_center is not None
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )

    window.recenter_zoom_shortcut.activated.emit()
    app.processEvents()

    window.navigate(1)
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx(
        remembered_center
    )
    window.close()


def test_photo_viewer_reset_zoom_centers_uses_next_photo_focus_point(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify Ctrl+Shift+F resets standalone viewer navigation centers.

    Reset-all should persist the AF/default-center intent across adjacent-photo
    navigation while preserving the active zoom scale.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    window.library.get_photo('A').focus_point = (0.35, 0.65)
    window.library.get_photo('B').focus_point = (0.65, 0.35)
    window._display_current_photo()
    app.processEvents()

    window.space_shortcut.activated.emit()
    _trigger_viewer_shortcut(window, '=')
    _trigger_viewer_shortcut(window, 'D')
    _trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    expected_zoom = window.viewer._current_scale
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
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.35,
        0.65,
    ))

    window.navigate(1)
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window.viewer._mode == 'single-manual'
    assert window.viewer._current_scale == pytest.approx(expected_zoom)
    assert window.viewer.normalized_viewport_center() == pytest.approx((
        0.65,
        0.35,
    ))
    window.close()


def test_photo_viewer_split_zoom_carries_across_navigation(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify split mode and right-pane inspection carry to the next photo.

    The left split pane should remain fit view while the right pane keeps the
    previous zoom factor and normalized viewport center.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.resize(1200, 800)
    app.processEvents()
    window.split_mode_shortcut.activated.emit()
    _trigger_viewer_shortcut(window, '=')
    _trigger_viewer_shortcut(window, 'D')
    _trigger_viewer_shortcut(window, 'S')
    app.processEvents()
    expected_zoom = window.viewer.split_zoom_viewer.current_zoom_factor()
    expected_center = (
        window.viewer.split_zoom_viewer.normalized_viewport_center()
    )
    assert expected_center is not None

    window.navigate(1)
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window.viewer.is_split_view() is True
    assert window.viewer._mode == 'split'
    assert window.viewer.split_fit_viewer.should_preserve_zoom() is False
    assert (
        abs(
            window.viewer.split_zoom_viewer.current_zoom_factor()
            - expected_zoom
        )
        <= 0.02
    )
    center = window.viewer.split_zoom_viewer.normalized_viewport_center()
    assert center is not None
    _assert_close_tuple(center, expected_center)
    window.close()


def test_photo_viewer_hydration_preserves_split_inspection_state(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify folder hydration does not collapse the active inspection state.

    Background hydration prepares a full culling-ready library; it should not
    reset a user's active standalone split/zoom view.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2400, 1600))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2400, 1600))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    original_library = window.library
    hydrated_library = PhotoLibrary(cache_dir=tmp_path / '.hydrated-cache')
    hydrated_library.load_folder(tmp_path)
    window.resize(1200, 800)
    app.processEvents()
    window.split_mode_shortcut.activated.emit()
    _trigger_viewer_shortcut(window, '=')
    _trigger_viewer_shortcut(window, 'D')
    app.processEvents()
    expected_zoom = window.viewer.split_zoom_viewer.current_zoom_factor()
    expected_center = (
        window.viewer.split_zoom_viewer.normalized_viewport_center()
    )
    assert expected_center is not None
    request_id = window._folder_hydration_request_id = 8
    expected_folder = tmp_path.resolve()
    window._folder_hydration_folder = expected_folder

    window._handle_folder_hydration_finished(
        request_id, expected_folder, hydrated_library
    )
    app.processEvents()

    assert window.library is original_library
    assert window._hydrated_library is hydrated_library
    assert window.current_photo_id == 'A'
    assert window.viewer.is_split_view() is True
    assert (
        abs(
            window.viewer.split_zoom_viewer.current_zoom_factor()
            - expected_zoom
        )
        <= 0.02
    )
    center = window.viewer.split_zoom_viewer.normalized_viewport_center()
    assert center is not None
    _assert_close_tuple(center, expected_center)
    window.close()


def test_photo_viewer_hydration_does_not_expand_standalone_navigation(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify recursive culling hydration does not change viewer navigation.

    Standalone viewer mode follows the opened file's immediate folder. The
    hydrated recursive library should be retained only for culling handoff.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    nested = tmp_path / 'nested'
    nested.mkdir()
    create_jpeg(nested / 'C.JPG', 'purple')
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='B.JPG')
    original_library = window.library
    hydrated_library = PhotoLibrary(cache_dir=tmp_path / '.hydrated-cache')
    hydrated_library.load_folder(tmp_path)
    request_id = window._folder_hydration_request_id = 9
    expected_folder = tmp_path.resolve()
    window._folder_hydration_folder = expected_folder
    requests: list[object] = []
    window.culling_requested.connect(requests.append)

    window._handle_folder_hydration_finished(
        request_id, expected_folder, hydrated_library
    )
    app.processEvents()

    assert window.library is original_library
    assert window._hydrated_library is hydrated_library
    assert [photo.photo_id for photo in window.library.photos] == ['A', 'B']
    assert [photo.photo_id for photo in hydrated_library.photos] == [
        'A',
        'B',
        'nested/C',
    ]
    assert window.current_photo_id == 'B'

    window.navigate(1)

    assert window.current_photo_id == 'B'

    window._request_culling_handoff()

    assert len(requests) == 1
    request = requests[0]
    assert isinstance(request, CullingLaunchRequest)
    assert request.preloaded_library is hydrated_library
    assert request.selected_photo_id == 'B'

    window.close()
    del app


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
    photo.focus_point_pending = False

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
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

    assert window._show_af_point_marker is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

    assert window._show_af_point_marker is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window._info_overlay_enabled is False
    assert window.exif_overlay.isHidden() is True
    window.close()


def test_photo_viewer_af_marker_toggle_persists_through_pending_navigation(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify ``F`` enables AF display through pending EXIF and navigation."""
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    create_jpeg(tmp_path / 'B.JPG', 'blue', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    assert window._show_af_point_marker is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

    assert window._show_af_point_marker is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window._photo_viewer_exif_request_id = 6
    window._handle_photo_viewer_exif_finished(
        6,
        'A',
        PhotoViewerExifResult(
            focus_point=(0.25, 0.6),
            exif_display={},
            capture_at=None,
            image_width=1000,
            image_height=500,
        ),
    )
    app.processEvents()

    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True

    window.navigate(1)
    app.processEvents()

    assert window.current_photo_id == 'B'
    assert window._show_af_point_marker is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False

    window._photo_viewer_exif_request_id = 7
    window._handle_photo_viewer_exif_failed(7, 'exif failed')
    app.processEvents()

    assert window.viewer.single_viewer._focus_point_marker.isVisible() is True
    window.close()


def test_photo_viewer_info_overlay_shows_exif_loading_placeholders(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify the EXIF overlay opens with placeholder rows while EXIF loads.

    The standalone viewer opens before full metadata is available, so pressing
    ``I`` should show the panel shape immediately instead of an empty EXIF area
    until the worker finishes.

    The placeholder labels mirror the formatter order so late-arriving
    shooting-mode and exposure-compensation values do not reshape the pane.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')

    window.info_overlay_shortcut.activated.emit()
    app.processEvents()

    assert window.exif_overlay.isVisible() is True
    assert window.exif_overlay.exif_display() == {
        'Captured': 'Loading...',
        'Camera Model': 'Loading...',
        'Lens Model': 'Loading...',
        'Focal Length': 'Loading...',
        'Aperture': 'Loading...',
        'Shutter Speed': 'Loading...',
        'Shooting Mode': 'Loading...',
        'Exposure Compensation': 'Loading...',
        'ISO': 'Loading...',
        'Resolution': 'Loading...',
        'File Size': 'Loading...',
    }
    assert window.exif_overlay.histogram_plot.histogram() is not None
    window.close()


def test_photo_viewer_exif_success_replaces_loading_placeholders(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify async EXIF success updates visible placeholder rows in place.

    Users can open ``I`` before metadata is ready; the worker completion must
    refresh the already-open overlay without requiring another key press.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window.info_overlay_shortcut.activated.emit()
    app.processEvents()
    assert window.exif_overlay.exif_display()['ISO'] == 'Loading...'

    window._photo_viewer_exif_request_id = 8
    window._handle_photo_viewer_exif_finished(
        8,
        'A',
        PhotoViewerExifResult(
            focus_point=(0.25, 0.6),
            exif_display={'Camera Model': 'Z 8', 'ISO': '800'},
            capture_at=None,
            image_width=1000,
            image_height=500,
        ),
    )
    app.processEvents()
    photo = window.library.get_photo('A')

    assert photo.focus_point == (0.25, 0.6)
    assert photo.focus_point_pending is False
    assert photo.image_width == 1000
    assert photo.image_height == 500
    assert window.exif_overlay.exif_display() == {
        'Camera Model': 'Z 8',
        'ISO': '800',
    }
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False
    window.close()


def test_photo_viewer_exif_refresh_waits_for_active_thread(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify rapid navigation does not quit an active EXIF thread early.

    The old worker should be canceled and allowed to finish naturally so Qt
    owns the thread and worker teardown order.
    """

    class FakeExifThread:
        def __init__(self) -> None:
            self.quit_calls = 0

        def quit(self) -> None:
            self.quit_calls += 1

    class FakeExifWorker:
        def __init__(self) -> None:
            self.cancel_calls = 0

        def cancel(self) -> None:
            self.cancel_calls += 1

    original_start = PhotoViewerWindow._start_photo_viewer_exif_refresh
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    monkeypatch.setattr(
        window,
        '_start_photo_viewer_exif_refresh',
        original_start.__get__(window, PhotoViewerWindow),
    )
    fake_thread = FakeExifThread()
    fake_worker = FakeExifWorker()
    window._photo_viewer_exif_thread = fake_thread
    window._photo_viewer_exif_worker = fake_worker
    window._photo_viewer_exif_request_id = 4

    window._start_photo_viewer_exif_refresh()

    assert window._photo_viewer_exif_request_id == 5
    assert window._photo_viewer_exif_refresh_pending is True
    assert fake_worker.cancel_calls == 1
    assert fake_thread.quit_calls == 0
    assert window._photo_viewer_exif_thread is fake_thread
    assert window._photo_viewer_exif_worker is fake_worker

    window._photo_viewer_exif_thread = None
    window._photo_viewer_exif_worker = None
    window._photo_viewer_exif_refresh_pending = False
    window.close()


def test_photo_viewer_exif_clear_starts_one_pending_refresh(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify pending EXIF refresh starts only after thread cleanup."""
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    finished_thread = object()
    finished_worker = object()
    start_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_start_photo_viewer_exif_refresh',
        lambda: start_calls.append('start'),
    )
    window._photo_viewer_exif_thread = finished_thread
    window._photo_viewer_exif_worker = finished_worker
    window._photo_viewer_exif_refresh_pending = True

    window._clear_photo_viewer_exif_worker(finished_thread, finished_worker)

    assert window._photo_viewer_exif_thread is None
    assert window._photo_viewer_exif_worker is None
    assert window._photo_viewer_exif_refresh_pending is False
    assert start_calls == ['start']
    window.close()


def test_photo_viewer_exif_clear_skips_pending_refresh_while_closing(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify closing viewer windows do not start replacement EXIF work."""
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    finished_thread = object()
    finished_worker = object()
    start_calls: list[str] = []
    monkeypatch.setattr(
        window,
        '_start_photo_viewer_exif_refresh',
        lambda: start_calls.append('start'),
    )
    window._photo_viewer_exif_thread = finished_thread
    window._photo_viewer_exif_worker = finished_worker
    window._photo_viewer_exif_refresh_pending = True
    window._closing = True

    window._clear_photo_viewer_exif_worker(finished_thread, finished_worker)

    assert window._photo_viewer_exif_thread is None
    assert window._photo_viewer_exif_worker is None
    assert start_calls == []

    window._photo_viewer_exif_refresh_pending = False
    window._closing = False
    window.close()


def test_photo_viewer_close_waits_for_stored_background_thread_slot(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify close hides first and destroys only after worker cleanup.

    Qt can report a thread as not running before its finished cleanup slot has
    cleared the Python owner reference. The visible viewer should disappear
    immediately, while widget teardown still waits for that cleanup slot. This
    observes ``destroyed`` because visibility is already false before the
    queued final close runs.
    """

    class FakeThread:
        def __init__(self) -> None:
            self.quit_calls = 0

        @staticmethod
        def isRunning() -> bool:  # noqa: N802 - Qt API
            return False

        def quit(self) -> None:
            self.quit_calls += 1

    create_jpeg(tmp_path / 'A.JPG', 'green')
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    fake_thread = FakeThread()
    fake_worker = object()
    destroyed: list[str] = []
    # Match production ownership so `destroyed` proves the deferred final close
    # accepted, rather than only proving that the first close hid the window.
    window.setAttribute(Qt.WA_DeleteOnClose, True)
    window.destroyed.connect(lambda *_args: destroyed.append('destroyed'))
    window._photo_viewer_exif_thread = fake_thread
    window._photo_viewer_exif_worker = fake_worker

    window.close()
    app.processEvents()

    assert window.isVisible() is False
    assert window.progress_overlay.isHidden() is True
    assert window.overlay_message_label.text() != 'Closing...'
    assert window._close_after_background_tasks is True
    assert window._photo_viewer_exif_thread is fake_thread
    assert fake_thread.quit_calls == 0
    assert destroyed == []

    window._clear_photo_viewer_exif_worker(fake_thread, fake_worker)

    assert window.isVisible() is False
    assert window._close_after_background_tasks is False
    assert destroyed == []

    # The cleanup path posts a zero-delay close, and Qt delivers deletion on a
    # later event turn. Drain both turns so the assertion observes teardown.
    for _ in range(2):
        app.processEvents()

    assert destroyed == ['destroyed']


def test_photo_viewer_replacement_cleanup_clears_inactive_thread_slot(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify replacement cleanup can drop an already-finished thread reference.

    This is narrower than close-time handling: replacing background work can
    clean up an inactive slot immediately, while window close waits for the
    normal finished cleanup callback.
    """

    class FakeThread:
        @staticmethod
        def isRunning() -> bool:  # noqa: N802 - Qt API
            return False

        @staticmethod
        def quit() -> None:
            raise AssertionError('inactive replacement thread should not quit')

    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    window._photo_viewer_exif_thread = FakeThread()
    window._photo_viewer_exif_worker = object()

    window._background_thread_slots.slot(
        'photo_viewer_exif'
    ).stop_for_replacement()

    assert window._photo_viewer_exif_thread is None
    assert window._photo_viewer_exif_worker is None

    window.close()


def test_photo_viewer_prefetch_cleanup_ignores_stale_finished_slot(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify an old prefetch cleanup cannot clear a newer thread slot.

    Prefetch is currently one-at-a-time, but matching the finished thread and
    worker avoids a future replacement path dropping the active prefetch owner
    references and reintroducing the shutdown wrapper race.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    _app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    old_thread = object()
    old_worker = object()
    new_thread = object()
    new_worker = object()
    window._viewer_prefetch_thread = new_thread
    window._viewer_prefetch_worker = new_worker

    window._clear_viewer_prefetch_worker(old_thread, old_worker)

    assert window._viewer_prefetch_thread is new_thread
    assert window._viewer_prefetch_worker is new_worker

    window._clear_viewer_prefetch_worker(new_thread, new_worker)

    assert window._viewer_prefetch_thread is None
    assert window._viewer_prefetch_worker is None

    window.close()


def test_photo_viewer_denied_access_blocks_navigation_and_handoff(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify denied folder access stays limited to the opened photo.

    Navigation and culling handoff require a full folder scan, so both paths
    must stop with the recovery message. Initial single-photo viewing should
    stay quiet and usable because it does not require folder access. The
    message should also explain that remembered denials need manual recovery.
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
    assert messages == []

    window.navigate(-1)

    assert window.current_photo_id == 'B'
    assert len(messages) == 1

    window._request_culling_handoff()

    assert window.current_photo_id == 'B'
    assert requests == []
    assert len(messages) == 2
    assert 'Browsing photos in this folder' in messages[0][0]
    assert 'remembers denied access' in messages[0][0]
    assert 'equivalent folder permissions' in messages[0][0]
    assert (
        messages[0][1]
        == photo_viewer_window_module.FOLDER_ACCESS_RECOVERY_TIMEOUT_MS
    )
    window.close()


def test_photo_viewer_exif_failure_clears_pending_fallback_focus_marker(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify EXIF failure clears the pending focus-point state.

    The marker remains hidden by default, but once the user enables AF display
    the cleared pending state lets the usable center-point fallback appear.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green', size=(2000, 1500))
    app, window = _open_viewer(tmp_path, monkeypatch, startup_name='A.JPG')
    photo = window.library.get_photo('A')

    assert photo.focus_point == (0.5, 0.5)
    assert photo.focus_point_pending is True
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False
    window.info_overlay_shortcut.activated.emit()
    app.processEvents()
    assert window.exif_overlay.exif_display()['ISO'] == 'Loading...'

    window._photo_viewer_exif_request_id = 7
    window._handle_photo_viewer_exif_failed(7, 'exif failed')
    app.processEvents()

    assert photo.focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_pending is False
    assert window.viewer.single_viewer._focus_point_marker.isVisible() is False
    assert window.exif_overlay.exif_display() == {'File Size': 'JPG: 47 KB'}

    window.show_af_point_shortcut.activated.emit()
    app.processEvents()

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

    Structured hydration snapshots should be stored silently until handoff
    waits, and stale request ids must not replace the latest valid snapshot.
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
    reporter = ProgressReporter(
        'Loading folder',
        (
            ProgressStageDefinition(
                'viewer_cache', 'Preparing photo viewer cache'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'viewer_cache', current=4, total=37, overall_progress=42
    )
    window._handle_folder_hydration_progress_snapshot(
        request_id + 1, expected_folder, snapshot
    )

    assert window._folder_hydration_snapshot is None

    window._handle_folder_hydration_progress_snapshot(
        request_id, expected_folder, snapshot
    )

    assert window.progress_overlay.isHidden() is True

    window._request_culling_handoff()

    assert requests == []
    assert window._pending_culling_handoff is True
    assert window.progress_overlay.isVisible() is True
    assert window.overlay_progress_bar.isVisible() is False
    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert 'Preparing photo viewer cache' in label_texts
    assert '4 of 37' in label_texts

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


def test_photo_viewer_handoff_without_snapshot_shows_scalar_progress(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify culling handoff has a scalar fallback before snapshots arrive.

    Hydration usually emits a structured snapshot quickly, but a handoff can
    wait after only legacy scalar progress has arrived. The viewer should show
    that scalar state until a snapshot becomes available.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    requests: list[object] = []
    window.culling_requested.connect(requests.append)
    request_id = window._folder_hydration_request_id = 4
    expected_folder = tmp_path.resolve()
    window._folder_hydration_folder = expected_folder
    window._folder_hydration_thread = object()
    window._folder_hydration_snapshot = None
    window._folder_hydration_message = 'Loading folder...'
    window._folder_hydration_progress = 42

    window._request_culling_handoff()

    assert requests == []
    assert window._pending_culling_handoff is True
    assert window.progress_overlay.isVisible() is True
    assert window.overlay_message_label.text() == 'Loading folder...'
    assert window.overlay_progress_bar.isVisible() is True
    assert window.overlay_progress_bar.maximum() == 100
    assert window.overlay_progress_bar.value() == 42
    assert window.progress_stage_list.isHidden() is True

    window._handle_folder_hydration_progress(
        request_id,
        expected_folder,
        'Preparing photo viewer cache',
        150,
    )

    assert window.overlay_message_label.text() == (
        'Preparing photo viewer cache'
    )
    assert window.overlay_progress_bar.maximum() == 200
    assert window.overlay_progress_bar.value() == 150
    assert window.progress_stage_list.isHidden() is True

    window._pending_culling_handoff = False
    window._folder_hydration_thread = None
    window.close()


def test_photo_viewer_handoff_keeps_snapshot_rows_after_scalar_hydration_update(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify scalar hydration updates do not replace active snapshot rows.

    Background hydration emits both callback styles. Once handoff is waiting
    with structured rows visible, a later scalar update should update stored
    progress only and leave the row overlay intact.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    request_id = window._folder_hydration_request_id = 5
    expected_folder = tmp_path.resolve()
    window._folder_hydration_folder = expected_folder
    window._folder_hydration_thread = object()
    reporter = ProgressReporter(
        'Loading folder',
        (
            ProgressStageDefinition(
                'viewer_cache', 'Preparing photo viewer cache'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'viewer_cache', current=4, total=37, overall_progress=42
    )
    window._handle_folder_hydration_progress_snapshot(
        request_id, expected_folder, snapshot
    )

    window._request_culling_handoff()
    window._handle_folder_hydration_progress(
        request_id,
        expected_folder,
        'Scalar hydration update',
        88,
    )

    label_texts = {
        label.text()
        for label in window.progress_stage_list.findChildren(QLabel)
    }
    assert window._folder_hydration_message == 'Scalar hydration update'
    assert window._folder_hydration_progress == 88
    assert window.overlay_message_label.text() == snapshot.current_message
    assert window.overlay_progress_bar.isVisible() is False
    assert window.progress_stage_list.isVisible() is True
    assert 'Preparing photo viewer cache' in label_texts
    assert '4 of 37' in label_texts

    window._pending_culling_handoff = False
    window._folder_hydration_thread = None
    window.close()


@pytest.mark.parametrize(
    'cleanup_action',
    [
        pytest.param('worker-finished', id='worker-finished'),
        pytest.param('replacement', id='replacement'),
        pytest.param('close-stop', id='close-stop'),
    ],
)
def test_photo_viewer_hydration_snapshot_is_cleared_by_cleanup_paths(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        cleanup_action: str,
) -> None:
    """
    Verify stored hydration snapshots do not survive cleanup boundaries.

    Background hydration stores snapshots silently until a handoff waits for
    them. Worker cleanup, viewer replacement, and close-time shutdown should
    all clear that cache so a later handoff cannot show stale stage rows.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    request_id = window._folder_hydration_request_id = 8
    expected_folder = tmp_path.resolve()
    finished_thread = object()
    finished_worker = object()
    reporter = ProgressReporter(
        'Loading folder',
        (
            ProgressStageDefinition(
                'viewer_cache', 'Preparing photo viewer cache'
            ),
        ),
    )
    snapshot = reporter.update_stage(
        'viewer_cache', current=1, total=2, overall_progress=150
    )
    window._folder_hydration_folder = expected_folder
    window._folder_hydration_thread = finished_thread
    window._folder_hydration_worker = finished_worker
    window._folder_hydration_snapshot = snapshot

    if cleanup_action == 'worker-finished':
        window._clear_folder_hydration_worker(
            request_id,
            expected_folder,
            finished_thread,
            finished_worker,
        )
    elif cleanup_action == 'replacement':
        window._cancel_background_tasks_for_replacement()
    else:
        window._stop_photo_viewer_background_tasks()

    assert window._folder_hydration_snapshot is None

    window._folder_hydration_thread = None
    window._folder_hydration_worker = None
    window.close()


def test_photo_viewer_handoff_blocks_after_hydration_failure(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify hydration failure blocks culling handoff and shows the load error.

    The initial viewer library is intentionally lightweight. Culling should
    never receive it after full-folder hydration fails, because that would hide
    the real folder-load problem and start with incomplete metadata.
    """
    create_jpeg(tmp_path / 'A.JPG', 'green')
    create_jpeg(tmp_path / 'B.JPG', 'blue')
    _app, window = _open_viewer(tmp_path, monkeypatch)
    requests: list[object] = []
    critical_calls: list[tuple[str, str]] = []
    window.culling_requested.connect(requests.append)
    monkeypatch.setattr(
        QMessageBox,
        'critical',
        lambda _parent, title, message: critical_calls.append((
            title,
            message,
        )),
    )
    window._folder_hydration_error = 'bad metadata'

    window._request_culling_handoff()

    assert requests == []
    assert critical_calls == [('Failed to Open Folder', 'bad metadata')]
    window.close()
