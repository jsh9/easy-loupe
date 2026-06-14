from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

import easy_loupe.ui as ui_package
import easy_loupe.ui.app as app_module
import easy_loupe.ui.identity as identity_module
import easy_loupe.ui.main_window as ui_main_window_package
import easy_loupe.ui.main_window.window as main_window_module
import easy_loupe.ui.viewers as ui_viewers_package
import easy_loupe.ui.viewers.exif_overlay as exif_overlay_module
import easy_loupe.ui.viewers.main_photo_viewer as main_photo_viewer_module
import easy_loupe.ui.viewers.photo_viewer as photo_viewer_module
import easy_loupe.ui.widgets as widgets_module
import easy_loupe.ui.workers as workers_module

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import ClassVar


def test_ui_packages_do_not_export_shortcuts() -> None:
    assert not hasattr(ui_package, 'MainWindow')
    assert not hasattr(ui_package, 'PhotoViewer')
    assert not hasattr(ui_package, 'ThumbnailPreviewWidget')
    assert not hasattr(ui_package, 'SceneDetectionWorker')
    assert not hasattr(ui_package, 'NO_METADATA_TEXT')
    assert not hasattr(ui_main_window_package, 'MainWindow')
    assert not hasattr(ui_viewers_package, 'PhotoViewer')
    assert not hasattr(ui_viewers_package, 'MainPhotoViewer')
    assert not hasattr(ui_viewers_package, 'ExifOverlayWidget')


def test_ui_modules_export_concrete_symbols() -> None:
    assert main_window_module.MainWindow.__name__ == 'MainWindow'
    assert photo_viewer_module.PhotoViewer.__name__ == 'PhotoViewer'
    assert (
        main_photo_viewer_module.MainPhotoViewer.__name__ == 'MainPhotoViewer'
    )
    assert (
        exif_overlay_module.ExifOverlayWidget.__name__ == 'ExifOverlayWidget'
    )
    assert (
        widgets_module.ThumbnailPreviewWidget.__name__
        == 'ThumbnailPreviewWidget'
    )
    assert (
        workers_module.SceneDetectionWorker.__name__ == 'SceneDetectionWorker'
    )
    assert workers_module.OperationWorker.__name__ == 'OperationWorker'


def test_ui_identity_uses_packaged_logo_assets() -> None:
    _app = QApplication.instance() or QApplication([])
    icns = identity_module.asset_resource(identity_module.ICON_ICNS)
    ico = identity_module.asset_resource(identity_module.ICON_ICO)
    png = identity_module.asset_resource(identity_module.ICON_PNG)
    svg = identity_module.asset_resource(identity_module.ICON_SVG)

    assert icns.is_file()
    assert ico.is_file()
    assert png.is_file()
    assert svg.is_file()
    assert not identity_module.easy_loupe_icon().isNull()


def test_easy_loupe_icon_adds_windows_ico_sizes(
        monkeypatch: object,
) -> None:
    _app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(identity_module.sys, 'platform', 'win32')

    sizes = {
        (size.width(), size.height())
        for size in identity_module.easy_loupe_icon().availableSizes()
    }

    assert (16, 16) in sizes
    assert (32, 32) in sizes
    assert (256, 256) in sizes


def test_branded_argv_replaces_process_executable_name() -> None:
    assert identity_module.branded_argv([
        'python3.13',
        '-m',
        'easy_loupe',
    ]) == [
        'EasyLoupe',
        '-m',
        'easy_loupe',
    ]
    assert identity_module.branded_argv([]) == ['EasyLoupe']


def test_app_extracts_supported_startup_photo_path(tmp_path: Path) -> None:
    photo_path = tmp_path / 'IMG_1000.ARW'
    photo_path.write_bytes(b'raw')

    assert (
        app_module._extract_startup_file([
            'EasyLoupe',
            '--some-qt-flag',
            str(photo_path),
        ])
        == photo_path
    )
    assert (
        app_module._extract_startup_file([
            'EasyLoupe',
            str(tmp_path / 'notes.txt'),
        ])
        is None
    )


def test_app_extracts_multiple_supported_startup_photo_paths(
        tmp_path: Path,
) -> None:
    """
    Collect every supported startup photo path from argv.

    This protects direct launches on Windows and command-line runs where the OS
    may pass several opened photos to one EasyLoupe process.
    """
    first_photo = tmp_path / 'IMG_1000.ARW'
    second_photo = tmp_path / 'IMG_1001.JPG'
    notes = tmp_path / 'notes.txt'
    for path in (first_photo, second_photo, notes):
        path.write_bytes(b'file')

    assert app_module._extract_startup_files([
        'EasyLoupe',
        str(first_photo),
        '--some-qt-flag',
        str(notes),
        str(second_photo),
    ]) == [first_photo, second_photo]


class _FakeSignal:
    def __init__(self) -> None:
        self._callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self._callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in self._callbacks:
            callback(*args)


class _FakeTimer:
    """
    Deterministic stand-in for ``QTimer`` in startup-coordinator tests.

    The coordinator's macOS path depends on a single-shot timer, but unit tests
    should not sleep or depend on a real Qt event loop timeout. This fake
    records each timer instance, captures the requested interval, and exposes
    ``fire()`` so tests can choose exactly when the launch-resolution timeout
    should run.
    """

    instances: ClassVar[list[_FakeTimer]] = []

    def __init__(self) -> None:
        """
        Create an inactive fake timer with a Qt-like ``timeout`` signal.

        Each instance is appended to ``instances`` so tests can inspect the
        timer created by ``StartupCoordinator`` and manually fire it.
        """
        self.timeout = _FakeSignal()
        self.interval: int | None = None
        self.single_shot = False
        self.active = False
        self.stopped = False
        self.__class__.instances.append(self)

    def setSingleShot(self, single_shot: bool) -> None:  # noqa: N802
        """Record whether the coordinator requested one-shot behavior."""
        self.single_shot = single_shot

    def start(self, interval: int) -> None:
        """
        Mark the timer active and remember the requested interval.

        The fake does not schedule real time; tests call ``fire()`` to emit the
        timeout signal after asserting the pending-startup state they care
        about.
        """
        self.interval = interval
        self.active = True

    def stop(self) -> None:
        """
        Mark the timer stopped without emitting ``timeout``.

        Tests use this to assert that a supported macOS ``FileOpen`` event
        canceled the pending plain-launch resolution.
        """
        self.stopped = True
        self.active = False

    def isActive(self) -> bool:  # noqa: N802
        """Return whether the fake timer is currently pending."""
        return self.active

    def fire(self) -> None:
        """
        Emit the timeout signal if the timer is active.

        Single-shot timers deactivate before emitting, matching the behavior
        the coordinator relies on when resolving a plain launch.
        """
        if not self.active:
            return

        if self.single_shot:
            self.active = False

        self.timeout.emit()


class _FakeApplication:
    """Small app stand-in for WindowManager shutdown tests."""

    def __init__(self) -> None:
        self.quit_on_last_window_closed: bool | None = None
        self.quit_handler: Callable[[], bool] | None = None
        self.quit_calls = 0

    def setQuitOnLastWindowClosed(  # noqa: N802
            self, should_quit: bool
    ) -> None:
        """Record Qt's implicit last-window quit setting."""
        self.quit_on_last_window_closed = should_quit

    def set_quit_handler(self, handler: Callable[[], bool] | None) -> None:
        """Record the application quit-event handler."""
        self.quit_handler = handler

    def quit(self) -> None:
        """Record explicit application quit requests."""
        self.quit_calls += 1

    def request_quit(self) -> bool:
        """Invoke the installed quit handler like a Qt quit event would."""
        if self.quit_handler is None:
            return True

        return bool(self.quit_handler())


class _FakeCullingWindow:
    def __init__(self, launch_request: object = None) -> None:
        self.launch_request = launch_request
        self.attributes: list[tuple[object, bool]] = []
        self.destroyed = _FakeSignal()
        self.geometry_calls: list[object] = []
        self.move_calls: list[object] = []
        self.show_maximized_calls = 0
        self.close_calls = 0
        self.closed = False
        self._destroyed = False

    def setAttribute(  # noqa: N802 - Qt naming in fake
            self, attribute: object, enabled: bool
    ) -> None:
        self.attributes.append((attribute, enabled))

    def setGeometry(self, geometry: object) -> None:  # noqa: N802
        self.geometry_calls.append(geometry)

    def move(self, point: object) -> None:
        self.move_calls.append(point)

    def showMaximized(self) -> None:  # noqa: N802 - Qt naming in fake
        self.show_maximized_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.destroy()

    def destroy(self) -> None:
        if self._destroyed:
            return

        self._destroyed = True
        self.destroyed.emit()


class _DeferredCloseCullingWindow(_FakeCullingWindow):
    """Window fake whose first close leaves it retained like worker cleanup."""

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def finish_close(self) -> None:
        self.destroy()


class _FakePhotoWindow:
    def __init__(self, startup_file: object = None) -> None:
        self.startup_file = startup_file
        self.attributes: list[tuple[object, bool]] = []
        self.destroyed = _FakeSignal()
        self.culling_requested = _FakeSignal()
        self.screen: object | None = None
        self.show_maximized_calls = 0
        self.closed = False
        self.close_calls = 0
        self._destroyed = False

    def setAttribute(  # noqa: N802 - Qt naming in fake
            self, attribute: object, enabled: bool
    ) -> None:
        self.attributes.append((attribute, enabled))

    def showMaximized(self) -> None:  # noqa: N802 - Qt naming in fake
        self.show_maximized_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True
        self.destroy()

    def windowHandle(self) -> object | None:  # noqa: N802 - Qt naming in fake
        if self.screen is None:
            return None

        return _FakeWindowHandle(self.screen)

    def destroy(self) -> None:
        if self._destroyed:
            return

        self._destroyed = True
        self.destroyed.emit()


class _FakeWindowHandle:
    def __init__(self, screen: object) -> None:
        self._screen = screen

    def screen(self) -> object:
        return self._screen


class _FakeGeometry:
    def __init__(self) -> None:
        self.top_left = object()

    def topLeft(self) -> object:  # noqa: N802 - Qt naming in fake
        return self.top_left


class _FakeScreen:
    def __init__(self) -> None:
        self.geometry = _FakeGeometry()

    def availableGeometry(self) -> _FakeGeometry:  # noqa: N802
        return self.geometry


def _fake_window_manager() -> app_module.WindowManager:
    return app_module.WindowManager(
        culling_window_factory=_FakeCullingWindow,
        photo_window_factory=_FakePhotoWindow,
    )


def test_window_manager_disables_implicit_last_window_quit() -> None:
    """
    Verify managed app shutdown does not depend on visible-window state.

    Hidden deferred-close windows must keep the Qt event loop alive while
    worker-thread cleanup drains, so the manager disables Qt's implicit
    last-visible-window quit policy and installs its own quit handler.
    """
    app = _FakeApplication()

    app_module.WindowManager(
        culling_window_factory=_FakeCullingWindow,
        photo_window_factory=_FakePhotoWindow,
        app=app,
    )

    assert app.quit_on_last_window_closed is False
    assert app.quit_handler is not None


def test_window_manager_quits_after_last_window_is_destroyed() -> None:
    """
    Quit the app only after the final retained window is destroyed.

    A normal close can destroy immediately; background-close windows reach the
    same path later from their deferred final close.
    """
    app = _FakeApplication()
    manager = app_module.WindowManager(
        culling_window_factory=_FakeCullingWindow,
        photo_window_factory=_FakePhotoWindow,
        app=app,
    )

    window = manager.open_culling_window()
    window.destroy()

    assert manager.windows() == []
    assert app.quit_calls == 1


def test_window_manager_quit_request_closes_retained_windows() -> None:
    """
    Close retained windows when Qt delivers an application quit request.

    Synchronously destroyed windows can allow the current quit event to proceed
    because no hidden worker-owning windows remain retained.
    """
    app = _FakeApplication()
    manager = app_module.WindowManager(
        culling_window_factory=_FakeCullingWindow,
        photo_window_factory=_FakePhotoWindow,
        app=app,
    )
    first = manager.open_culling_window()
    second = manager.open_photo_window(Path('IMG_1000.JPG'))

    assert app.request_quit() is True

    assert first.close_calls == 1
    assert second.close_calls == 1
    assert manager.windows() == []


def test_window_manager_deferred_quit_waits_for_window_destroyed() -> None:
    """
    Keep the app alive while a close-hidden window is still retained.

    This is the regression path from the crash report: the first close hides
    the window but worker cleanup has not emitted ``destroyed`` yet, so the
    application-level quit event must be consumed until final teardown.
    """
    app = _FakeApplication()
    manager = app_module.WindowManager(
        culling_window_factory=_DeferredCloseCullingWindow,
        photo_window_factory=_FakePhotoWindow,
        app=app,
    )
    window = manager.open_culling_window()

    assert app.request_quit() is False

    assert window.close_calls == 1
    assert window.closed is True
    assert manager.windows() == [window]
    assert app.quit_calls == 0

    window.finish_close()

    assert manager.windows() == []
    assert app.quit_calls == 1
    assert app.request_quit() is True


def test_window_manager_allows_quit_with_no_windows() -> None:
    """
    Allow the current quit event when there are no retained windows.

    Once the manager has no window-owned QThreads left to protect, Qt can exit
    the event loop normally.
    """
    app = _FakeApplication()
    app_module.WindowManager(
        culling_window_factory=_FakeCullingWindow,
        photo_window_factory=_FakePhotoWindow,
        app=app,
    )

    assert app.request_quit() is True


def test_startup_coordinator_opens_plain_window_without_startup_files() -> (
    None
):
    """
    Open the normal culling window when no startup files exist.

    This preserves the no-file launch path that should still prompt for a
    folder instead of creating a photo-viewer window.
    """
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(manager, platform='win32')

    coordinator.start([], [])

    windows = manager.windows()
    assert len(windows) == 1
    assert windows[0].launch_request is None
    assert windows[0].show_maximized_calls == 1


def test_startup_coordinator_delays_plain_macos_launch() -> None:
    """
    Delay plain culling-window startup on macOS while FileOpen can arrive.

    Finder may launch the app before delivering the file-open event. The delay
    prevents a temporary no-file window from showing the folder chooser behind
    the real photo-viewer window.
    """
    _FakeTimer.instances = []
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(
        manager,
        platform='darwin',
        timer_factory=_FakeTimer,
        launch_resolution_delay_ms=250,
    )

    coordinator.start([], [])

    assert manager.windows() == []
    timer = _FakeTimer.instances[0]
    assert timer.single_shot is True
    assert timer.interval == 250
    assert timer.isActive() is True

    timer.fire()

    windows = manager.windows()
    assert len(windows) == 1
    assert windows[0].launch_request is None


def test_startup_coordinator_macos_file_open_resolves_launch(
        tmp_path: Path,
) -> None:
    """
    Prefer a real macOS file-open event over delayed no-file startup.

    This covers the Finder launch race that otherwise creates a second
    EasyLoupe window whose initial folder prompt appears behind the photo.
    """
    _FakeTimer.instances = []
    photo = tmp_path / 'IMG_1000.JPG'
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(
        manager,
        platform='darwin',
        timer_factory=_FakeTimer,
    )

    coordinator.start([], [])
    coordinator.open_file_from_system(photo)
    _FakeTimer.instances[0].fire()

    windows = manager.windows()
    assert len(windows) == 1
    assert windows[0].startup_file == photo
    assert _FakeTimer.instances[0].stopped is True


def test_startup_coordinator_unsupported_macos_open_keeps_plain_launch(
        tmp_path: Path,
) -> None:
    """
    Keep delayed normal startup when macOS opens an unsupported file.

    Unsupported events should not create photo-viewer windows, but they also
    should not suppress the normal no-file culling window.
    """
    _FakeTimer.instances = []
    notes = tmp_path / 'notes.txt'
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(
        manager,
        platform='darwin',
        timer_factory=_FakeTimer,
    )

    coordinator.start([], [])
    coordinator.open_file_from_system(notes)
    _FakeTimer.instances[0].fire()

    windows = manager.windows()
    assert len(windows) == 1
    assert windows[0].launch_request is None


def test_startup_coordinator_opens_one_window_per_startup_file(
        tmp_path: Path,
) -> None:
    """
    Create an independent photo-viewer window for each startup file.

    This covers Windows and direct argv launches where multiple opened photos
    arrive before the Qt event loop starts.
    """
    first_photo = tmp_path / 'IMG_1000.ARW'
    second_photo = tmp_path / 'IMG_1001.JPG'
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(manager)

    coordinator.start([first_photo, second_photo], [])

    assert [window.startup_file for window in manager.windows()] == [
        first_photo,
        second_photo,
    ]


def test_startup_coordinator_opens_pending_file_events(
        tmp_path: Path,
) -> None:
    """
    Open supported file events queued before coordinator wiring completes.

    macOS can deliver ``FileOpen`` before ``main`` has connected the runtime
    signal, so pending events must follow the same path as argv photos.
    """
    first_photo = tmp_path / 'IMG_1000.JPG'
    second_photo = tmp_path / 'IMG_1001.HEIC'
    notes = tmp_path / 'notes.txt'
    _FakeTimer.instances = []
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(manager, platform='darwin')

    coordinator.start([], [first_photo, notes, second_photo])

    assert [window.startup_file for window in manager.windows()] == [
        first_photo,
        second_photo,
    ]
    assert _FakeTimer.instances == []


def test_main_keeps_pending_file_events_separate_from_argv(
        tmp_path: Path, monkeypatch: object
) -> None:
    """
    Pass queued macOS file-open events to the startup coordinator only once.

    ``StartupCoordinator.start`` owns combining argv files with pending
    ``FileOpen`` events, so ``main`` must not copy pending files into the argv
    startup list before calling it.
    """
    argv_photo = tmp_path / 'IMG_1000.JPG'
    pending_photo = tmp_path / 'IMG_1001.JPG'

    class FakeApplication:
        instances: ClassVar[list[FakeApplication]] = []

        def __init__(self, argv: list[str]) -> None:
            self.argv = argv
            self.file_opened = _FakeSignal()
            self.quit_handler: Callable[[], bool] | None = None
            self.quit_on_last_window_closed: bool | None = None
            self.__class__.instances.append(self)

        def setQuitOnLastWindowClosed(  # noqa: N802
                self, should_quit: bool
        ) -> None:
            self.quit_on_last_window_closed = should_quit

        def set_quit_handler(self, handler: Callable[[], bool] | None) -> None:
            self.quit_handler = handler

        @staticmethod
        def take_pending_open_files() -> list[Path]:
            return [pending_photo]

        @staticmethod
        def quit() -> None:
            return

        @staticmethod
        def exec() -> int:
            return 0

    class FakeStartupCoordinator:
        instances: ClassVar[list[FakeStartupCoordinator]] = []

        def __init__(self, window_manager: object) -> None:
            self.window_manager = window_manager
            self.startup_files: list[Path] = []
            self.pending_open_files: list[Path] = []
            self.__class__.instances.append(self)

        def open_file_from_system(self, file_path: object) -> None:
            self.live_file_open = file_path

        def start(
                self,
                startup_files: list[Path],
                pending_open_files: list[Path],
        ) -> None:
            self.startup_files = list(startup_files)
            self.pending_open_files = list(pending_open_files)

    monkeypatch.setattr(app_module, 'prepare_app_identity', lambda: None)
    monkeypatch.setattr(app_module, 'apply_app_identity', lambda _app: None)
    monkeypatch.setattr(app_module, 'EasyLoupeApplication', FakeApplication)
    monkeypatch.setattr(
        app_module, 'StartupCoordinator', FakeStartupCoordinator
    )

    assert app_module.main(['python', str(argv_photo)]) == 0

    coordinator = FakeStartupCoordinator.instances[0]
    assert coordinator.startup_files == [argv_photo]
    assert coordinator.pending_open_files == [pending_photo]


def test_startup_coordinator_system_open_creates_new_window(
        tmp_path: Path,
) -> None:
    """
    Handle later system file-open events by creating another window.

    This prevents macOS Finder opens from replacing the state of an existing
    EasyLoupe photo-viewer window.
    """
    first_photo = tmp_path / 'IMG_1000.JPG'
    second_photo = tmp_path / 'IMG_1001.JPG'
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(manager)
    coordinator.start([first_photo], [])
    first_window = manager.windows()[0]

    coordinator.open_file_from_system(second_photo)

    assert first_window.startup_file == first_photo
    assert [window.startup_file for window in manager.windows()] == [
        first_photo,
        second_photo,
    ]


def test_startup_coordinator_ignores_unsupported_system_open(
        tmp_path: Path,
) -> None:
    """
    Ignore later system-open events for unsupported file types.

    This keeps non-photo documents from creating empty EasyLoupe windows when
    the OS forwards unrelated file-open events.
    """
    first_photo = tmp_path / 'IMG_1000.JPG'
    notes = tmp_path / 'notes.txt'
    manager = _fake_window_manager()
    coordinator = app_module.StartupCoordinator(manager)
    coordinator.start([first_photo], [])

    coordinator.open_file_from_system(notes)

    assert [window.startup_file for window in manager.windows()] == [
        first_photo
    ]


def test_window_manager_forgets_destroyed_windows(tmp_path: Path) -> None:
    """
    Remove destroyed windows from the manager's live-window list.

    This is necessary because the manager owns Python references to every
    window until Qt closes and destroys them.
    """
    first_photo = tmp_path / 'IMG_1000.JPG'
    second_photo = tmp_path / 'IMG_1001.JPG'
    manager = _fake_window_manager()
    manager.open_photo_windows([first_photo, second_photo])
    first_window = manager.windows()[0]

    first_window.destroy()

    assert [window.startup_file for window in manager.windows()] == [
        second_photo
    ]


def test_window_manager_hands_viewer_off_to_culling_window(
        tmp_path: Path,
) -> None:
    """Open a culling window from a viewer request and close the viewer."""
    startup_photo = tmp_path / 'IMG_1000.JPG'
    manager = _fake_window_manager()
    viewer = manager.open_photo_window(startup_photo)
    request = app_module.CullingLaunchRequest(
        folder=tmp_path,
        selected_photo_id='IMG_1000',
        enter_browse=True,
    )

    viewer.culling_requested.emit(request)

    windows = manager.windows()
    assert viewer.closed is True
    assert len(windows) == 1
    assert windows[0].launch_request is request
    assert windows[0].geometry_calls == []
    assert windows[0].move_calls == []


def test_window_manager_handoff_places_culling_window_on_viewer_screen(
        tmp_path: Path,
) -> None:
    """Open handoff culling windows on the photo viewer's current screen."""
    startup_photo = tmp_path / 'IMG_1000.JPG'
    manager = _fake_window_manager()
    viewer = manager.open_photo_window(startup_photo)
    screen = _FakeScreen()
    viewer.screen = screen
    request = app_module.CullingLaunchRequest(
        folder=tmp_path,
        selected_photo_id='IMG_1000',
        enter_browse=True,
    )

    viewer.culling_requested.emit(request)

    windows = manager.windows()
    assert viewer.closed is True
    assert len(windows) == 1
    assert windows[0].launch_request is request
    assert windows[0].geometry_calls == [screen.geometry]
    assert windows[0].move_calls == [screen.geometry.top_left]
    assert windows[0].show_maximized_calls == 1


def test_apply_app_identity_sets_qt_name_and_icon() -> None:
    app = QApplication.instance() or QApplication([])

    identity_module.apply_app_identity(app)

    assert app.applicationName() == 'EasyLoupe'
    assert app.applicationVersion() == identity_module.APP_VERSION
    assert app.applicationDisplayName() == 'EasyLoupe'
    assert app.organizationName() == 'EasyLoupe'
    assert app.desktopFileName() == 'EasyLoupe'
    assert not app.windowIcon().isNull()
