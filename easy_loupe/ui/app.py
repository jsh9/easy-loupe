"""Application entry point for EasyLoupe."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFileOpenEvent, QScreen
from PySide6.QtWidgets import QApplication

from easy_loupe.core.records import SUPPORTED_EXTENSIONS
from easy_loupe.ui.identity import (
    apply_app_identity,
    branded_argv,
    prepare_app_identity,
)
from easy_loupe.ui.launch import CullingLaunchRequest
from easy_loupe.ui.main_window.build import INITIAL_FOLDER_PROMPT_GRACE_MS
from easy_loupe.ui.main_window.window import MainWindow
from easy_loupe.ui.photo_viewer.window import PhotoViewerWindow
from easy_loupe.ui.viewers.shell import resolve_widget_screen

if TYPE_CHECKING:
    from collections.abc import Callable


class EasyLoupeApplication(QApplication):
    """QApplication subclass that forwards OS file-open events."""

    file_opened = Signal(object)

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._pending_open_files: list[Path] = []

    def event(self, event: QEvent) -> bool:
        """Forward macOS Finder file-open events to the main window."""
        if event.type() == QEvent.Type.FileOpen and isinstance(
            event, QFileOpenEvent
        ):
            file_path = event.file()
            if file_path:
                path = Path(file_path)
                self._pending_open_files.append(path)
                self.file_opened.emit(path)
                return True

        return super().event(event)

    def take_pending_open_files(self) -> list[Path]:
        """Return file-open events received before the window was ready."""
        pending = list(self._pending_open_files)
        self._pending_open_files.clear()
        return pending


class _WindowSignal(Protocol):
    """Signal object that lets ``WindowManager`` subscribe to Qt events."""

    def connect(self, callback: Callable[..., None]) -> object:
        """Connect a callback to the signal."""


class _ManagedWindow(Protocol):
    """Top-level EasyLoupe window retained until its ``destroyed`` signal."""

    destroyed: _WindowSignal

    def setAttribute(  # noqa: N802 - Qt API naming
            self,
            attribute: Qt.WidgetAttribute,
            enabled: bool,  # noqa: FBT001
    ) -> None:
        """Set a Qt widget attribute."""

    def setGeometry(self, geometry: QRect) -> None:  # noqa: N802
        """Set the window geometry."""

    def move(self, point: QPoint) -> None:
        """Move the window to a screen point."""

    def showMaximized(self) -> None:  # noqa: N802
        """Show the window maximized."""


class _PhotoHandoffWindow(_ManagedWindow, Protocol):
    """Photo-viewer window that can request and then yield to culling mode."""

    culling_requested: _WindowSignal

    def close(self) -> None:
        """Close the handoff window after culling opens."""


class _CullingWindowFactory(Protocol):
    """Callable that builds a culling ``MainWindow`` for a launch request."""

    def __call__(
            self,
            *,
            launch_request: CullingLaunchRequest | None = None,
    ) -> _ManagedWindow:
        """Create a culling window."""


class _PhotoWindowFactory(Protocol):
    """Callable that builds a photo-viewer window for one opened file."""

    def __call__(self, *, startup_file: Path) -> _PhotoHandoffWindow:
        """Create a photo-viewer window."""


class WindowManager:
    """Own live EasyLoupe windows and create one window per opened photo."""

    def __init__(
            self,
            culling_window_factory: _CullingWindowFactory = MainWindow,
            photo_window_factory: _PhotoWindowFactory = PhotoViewerWindow,
    ) -> None:
        self._culling_window_factory = culling_window_factory
        self._photo_window_factory = photo_window_factory
        self._windows: list[_ManagedWindow] = []

    def windows(self) -> list[_ManagedWindow]:
        """Return the currently managed live windows."""
        return list(self._windows)

    def open_culling_window(
            self,
            launch_request: CullingLaunchRequest | None = None,
            *,
            target_screen: QScreen | None = None,
    ) -> _ManagedWindow:
        """Create and show the normal no-file culling window."""
        window = self._culling_window_factory(launch_request=launch_request)
        self._retain_and_show(window, target_screen=target_screen)
        return window

    def open_photo_window(self, startup_file: Path) -> _PhotoHandoffWindow:
        """Create and show a photo-viewer window for one opened photo."""
        window = self._photo_window_factory(startup_file=startup_file)
        window.culling_requested.connect(
            lambda request, viewer=window: self._handle_culling_request(
                viewer, request
            )
        )
        self._retain_and_show(window)
        return window

    def open_photo_windows(self, startup_files: list[Path]) -> None:
        """Create one photo-viewer window for each opened startup file."""
        for startup_file in startup_files:
            self.open_photo_window(startup_file)

    def _retain_and_show(
            self,
            window: _ManagedWindow,
            *,
            target_screen: QScreen | None = None,
    ) -> None:
        """Retain and show an EasyLoupe window."""
        window.setAttribute(Qt.WA_DeleteOnClose, True)
        self._windows.append(window)
        window.destroyed.connect(
            lambda _object=None, managed_window=window: self._remove_window(
                managed_window
            )
        )
        if target_screen is not None:
            target_geometry = target_screen.availableGeometry()
            window.setGeometry(target_geometry)
            window.move(target_geometry.topLeft())

        window.showMaximized()

    def _handle_culling_request(
            self,
            viewer: _PhotoHandoffWindow,
            request: object,
    ) -> None:
        """Open culling UI for a viewer handoff and close the viewer."""
        if not isinstance(request, CullingLaunchRequest):
            return

        target_screen = resolve_widget_screen(viewer)
        self.open_culling_window(
            launch_request=request,
            target_screen=target_screen,
        )
        viewer.close()

    def _remove_window(self, window: _ManagedWindow) -> None:
        """Forget a destroyed window so Qt can quit after the last close."""
        try:
            self._windows.remove(window)
        except ValueError:
            return


class StartupCoordinator:
    """
    Route cross-platform app launch events into the right window creation.

    On every platform, this object decides whether startup should create
    photo-viewer windows for supported files or one normal culling window for a
    plain no-file launch. Windows and argv-driven launches resolve immediately.
    The only delayed branch is macOS no-file startup, because Finder can launch
    the app before Qt delivers the matching ``FileOpen`` event. Keeping that
    policy here lets ``WindowManager`` focus only on live window lifetime.
    """

    def __init__(
            self,
            window_manager: WindowManager,
            *,
            platform: str | None = None,
            timer_factory: Callable[[], QTimer] = QTimer,
            launch_resolution_delay_ms: int = INITIAL_FOLDER_PROMPT_GRACE_MS,
    ) -> None:
        """
        Initialize the launch coordinator.

        ``platform`` and ``timer_factory`` are injectable so app-level tests
        can cover both immediate Windows-style launch routing and the macOS
        launch race without sleeping on real timers. The delay is used only for
        macOS plain-startup resolution and intentionally matches the
        main-window folder-prompt grace period.
        """
        self._window_manager = window_manager
        self._platform = platform if platform is not None else sys.platform
        self._timer_factory = timer_factory
        self._launch_resolution_delay_ms = launch_resolution_delay_ms
        self._launch_resolution_timer: QTimer | None = None

    def start(
            self,
            startup_files: list[Path],
            pending_open_files: list[Path],
    ) -> None:
        """
        Resolve the initial app launch into photo or plain culling windows.

        ``startup_files`` comes from argv, while ``pending_open_files`` holds
        macOS ``FileOpen`` events received before ``main`` connected the live
        signal. Both sources represent real photo-open intent and therefore
        take precedence over a plain no-file culling launch. If neither source
        contains supported photos, non-macOS platforms open the culling window
        immediately; macOS briefly waits for a late Finder ``FileOpen``.
        """
        supported_files = [
            path
            for path in [*startup_files, *pending_open_files]
            if path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if supported_files:
            self._resolve_as_file_open_launch(supported_files)
            return

        if self._platform == 'darwin':
            self._start_macos_launch_resolution()
            return

        self._resolve_as_plain_launch()

    def open_file_from_system(self, file_path: object) -> None:
        """
        Handle a live system file-open event after startup wiring is ready.

        Supported photo files resolve any pending macOS launch decision as a
        file-open launch and create a new photo-viewer window. Unsupported
        files are ignored and deliberately do not cancel a pending plain
        startup, because they do not prove the user intended EasyLoupe to open
        a photo.
        """
        path = Path(str(file_path)).expanduser()
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return

        self._resolve_as_file_open_launch([path])

    def _start_macos_launch_resolution(self) -> None:
        """
        Wait briefly for Finder ``FileOpen`` before plain no-file startup.

        Qt does not provide a signal that says launch-time ``FileOpen`` events
        are exhausted. The single-shot timer is the explicit macOS policy for
        resolving that uncertainty: a supported file event wins if it arrives
        first; otherwise EasyLoupe proceeds as a normal no-file launch.
        """
        if (
            self._launch_resolution_timer is not None
            and self._launch_resolution_timer.isActive()
        ):
            return

        timer = self._timer_factory()
        timer.setSingleShot(True)
        timer.timeout.connect(self._resolve_as_plain_launch)
        self._launch_resolution_timer = timer
        timer.start(self._launch_resolution_delay_ms)

    def _resolve_as_file_open_launch(self, startup_files: list[Path]) -> None:
        """
        Open photo-viewer windows and suppress pending plain startup.

        This is used for argv files, queued launch-time macOS events, and live
        ``FileOpen`` events. The coordinator does not dedupe paths: each
        supported photo-open request maps to one independent window.
        """
        self._cancel_launch_resolution()
        self._window_manager.open_photo_windows(startup_files)

    def _resolve_as_plain_launch(self) -> None:
        """
        Open the normal culling window for a resolved plain launch.

        On macOS this runs after the launch-resolution timer fires; on other
        platforms it runs immediately when no supported startup files exist.
        """
        self._cancel_launch_resolution()
        self._window_manager.open_culling_window()

    def _cancel_launch_resolution(self) -> None:
        """
        Cancel and drop a pending macOS launch-resolution timer.

        The timer is cleared before opening either photo-viewer or plain
        culling windows so a stale timeout cannot later create an extra window.
        """
        if self._launch_resolution_timer is None:
            return

        self._launch_resolution_timer.stop()
        self._launch_resolution_timer = None


def _extract_startup_files(argv: list[str] | None) -> list[Path]:
    source_argv = argv if argv is not None else sys.argv
    startup_files: list[Path] = []
    for raw_arg in source_argv[1:]:
        if raw_arg.startswith('-'):
            continue

        path = Path(raw_arg).expanduser()
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            startup_files.append(path)

    return startup_files


def _extract_startup_file(argv: list[str] | None) -> Path | None:
    startup_files = _extract_startup_files(argv)
    return startup_files[0] if startup_files else None


def main(argv: list[str] | None = None) -> int:
    """Launch the desktop application and return the Qt exit code."""
    prepare_app_identity()
    app = EasyLoupeApplication(branded_argv(argv))
    apply_app_identity(app)
    startup_files = _extract_startup_files(argv)
    pending_open_files = app.take_pending_open_files()

    window_manager = WindowManager()
    startup_coordinator = StartupCoordinator(window_manager)
    app.file_opened.connect(startup_coordinator.open_file_from_system)
    startup_coordinator.start(startup_files, pending_open_files)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
