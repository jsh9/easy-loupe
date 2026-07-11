"""Application entry point for EasyLoupe."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from PySide6.QtCore import QEvent, QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QFileOpenEvent, QScreen
from PySide6.QtWidgets import QApplication, QMessageBox

from easy_loupe.core.records import SUPPORTED_EXTENSIONS
from easy_loupe.ui.identity import (
    APP_NAME,
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

APPLICATION_QUIT_ACCEPT_LABEL = f'Quit {APP_NAME}'


def confirm_application_quit(window_count: int) -> bool:
    """Return whether the user confirmed app-wide quit."""
    dialog = QMessageBox(QApplication.activeWindow())
    dialog.setIcon(QMessageBox.Icon.Question)
    dialog.setWindowTitle(f'Quit {APP_NAME}?')
    if window_count == 1:
        dialog.setText(f'Quit {APP_NAME} and close the open window?')
    else:
        dialog.setText(
            f'Quit {APP_NAME} and close all {window_count} windows?'
        )

    quit_button = dialog.addButton(
        APPLICATION_QUIT_ACCEPT_LABEL,
        QMessageBox.ButtonRole.AcceptRole,
    )
    cancel_button = dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.setDefaultButton(cancel_button)
    dialog.setEscapeButton(cancel_button)
    dialog.exec()
    return dialog.clickedButton() is quit_button


class EasyLoupeApplication(QApplication):
    """QApplication subclass that forwards OS file-open events."""

    file_opened = Signal(object)

    def __init__(self, argv: list[str]) -> None:
        super().__init__(argv)
        self._pending_open_files: list[Path] = []
        self._quit_handler: Callable[[], bool] | None = None

    def set_quit_handler(self, handler: Callable[[], bool] | None) -> None:
        """
        Set the application-level quit policy hook.

        The handler returns ``True`` to let Qt finish the current quit event,
        or ``False`` to keep the event loop alive while hidden windows finish
        background cleanup.
        """
        self._quit_handler = handler

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

        if (
            event.type() == QEvent.Type.Quit
            and self._quit_handler is not None
            and not self._quit_handler()
        ):
            event.ignore()
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

    close_app_requested: _WindowSignal
    destroyed: _WindowSignal

    def close(self) -> None:
        """Close the managed window."""

    def is_close_in_progress(self) -> bool:
        """
        Return whether the window is already closing.

        WindowManager uses this for hidden deferred-close windows, where Qt
        teardown is waiting on worker cleanup but another app-wide quit sweep
        can still arrive.
        """

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


class _ManagedApplication(Protocol):
    """Application hooks used by ``WindowManager`` for controlled shutdown."""

    def setQuitOnLastWindowClosed(  # noqa: N802 - Qt API naming
            self,
            should_quit: bool,  # noqa: FBT001
    ) -> None:
        """Set Qt's implicit last-window quit policy."""

    def set_quit_handler(self, handler: Callable[[], bool] | None) -> None:
        """Set the application-level quit policy hook."""

    def exit(self, return_code: int = 0) -> None:
        """Exit the application event loop with ``return_code``."""


class WindowManager:
    """Own live EasyLoupe windows and create one window per opened photo."""

    def __init__(
            self,
            culling_window_factory: _CullingWindowFactory = MainWindow,
            photo_window_factory: _PhotoWindowFactory = PhotoViewerWindow,
            app: _ManagedApplication | None = None,
            confirm_quit: Callable[[int], bool] = confirm_application_quit,
    ) -> None:
        self._culling_window_factory = culling_window_factory
        self._photo_window_factory = photo_window_factory
        self._app = app
        self._confirm_quit = confirm_quit
        self._confirmed_quit_window_ids: set[int] = set()
        self._close_all_requested_window_ids: set[int] = set()
        self._windows: list[_ManagedWindow] = []
        if self._app is not None:
            # Qt otherwise quits when the last visible window closes. Hidden
            # deferred-close windows still own QThreads, so WindowManager keeps
            # the event loop alive until those windows emit ``destroyed``.
            self._app.setQuitOnLastWindowClosed(False)
            self._app.set_quit_handler(self._handle_application_quit)

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
        # Route explicit Close App menu requests through the manager because
        # individual windows do not know which other windows are retained or
        # still waiting on deferred worker cleanup.
        window.close_app_requested.connect(
            self._request_application_quit_from_window
        )
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

    def close_all_windows(self) -> None:
        """Close every retained EasyLoupe window through normal close paths."""
        windows_to_close = [
            window
            for window in self._windows
            if id(window) not in self._close_all_requested_window_ids
        ]
        if not windows_to_close:
            return

        for window in windows_to_close:
            # Track each retained window before closing so a hidden deferred
            # cleanup window is not sent repeated close events, while later
            # windows opened during that cleanup remain closable.
            self._close_all_requested_window_ids.add(id(window))
            # Close-in-progress windows have already hidden and requested
            # worker shutdown. Marking them above is enough; calling close()
            # again would re-enter the deferred cleanup path.
            if window.is_close_in_progress():
                continue

            window.close()

    def request_application_quit(self) -> bool:
        """
        Confirm app-wide quit and report whether Qt may finish this event.

        ``False`` means the current quit event must stay consumed because the
        user canceled or because hidden retained windows are still draining
        worker cleanup.
        """
        if not self._windows:
            self._confirmed_quit_window_ids.clear()
            return True

        self._prune_confirmed_quit_window_ids()
        retained_window_ids = {id(window) for window in self._windows}
        unconfirmed_window_ids = (
            retained_window_ids - self._confirmed_quit_window_ids
        )
        if unconfirmed_window_ids:
            if not self._confirm_quit(len(self._windows)):
                return False

            # Native quit events can arrive again while deferred-close windows
            # are hidden. Remember which retained windows the user approved so
            # cleanup continues without re-prompting, while any window opened
            # during that cleanup still requires fresh confirmation.
            self._confirmed_quit_window_ids = retained_window_ids

        self.close_all_windows()
        return not self._windows

    def _prune_confirmed_quit_window_ids(self) -> None:
        """
        Forget confirmed-quit approvals for windows no longer retained.

        This keeps a confirmation scoped to the windows in the approved close
        sweep: repeated quit events can continue draining the same hidden
        windows, but later windows are not covered by that approval.
        """
        retained_window_ids = {id(window) for window in self._windows}
        self._confirmed_quit_window_ids.intersection_update(
            retained_window_ids
        )

    def _request_application_quit_from_window(self) -> None:
        """Request app-wide quit from a signal that expects a ``None`` slot."""
        self.request_application_quit()

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
        """Forget a destroyed window and exit after the last close."""
        self._close_all_requested_window_ids.discard(id(window))
        self._confirmed_quit_window_ids.discard(id(window))
        try:
            self._windows.remove(window)
        except ValueError:
            return

        if not self._windows and self._app is not None:
            # Final cleanup must not post another interruptible Quit event.
            # A native macOS Quit may already have been ignored while hidden
            # worker-owning windows drained, so end the event loop directly
            # only after every managed window has been destroyed.
            self._app.exit(0)

    def _handle_application_quit(self) -> bool:
        """
        Confirm app-wide quit and drain retained windows before exiting.

        Native macOS quit, Dock quit, and Ctrl/Cmd+Q can all arrive as a Qt
        quit event. Confirm the app-wide close once, then keep consuming quit
        events while hidden deferred-close windows finish worker cleanup.
        """
        # Returning False consumes the native Quit event. Returning True is
        # safe only after every worker-owning window has been forgotten.
        return self.request_application_quit()


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

    window_manager = WindowManager(app=app)
    startup_coordinator = StartupCoordinator(window_manager)
    app.file_opened.connect(startup_coordinator.open_file_from_system)
    startup_coordinator.start(startup_files, pending_open_files)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
