"""Standalone photo-viewer window for system-opened files."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast

from PySide6.QtCore import (
    QEvent,
    QObject,
    QSize,
    Qt,
    QThread,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCloseEvent, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.ui.folder_access import FolderAccessManager
from easy_cull.ui.identity import APP_NAME, easy_cull_icon
from easy_cull.ui.launch import CullingLaunchRequest
from easy_cull.ui.main_window.build import TRANSIENT_MESSAGE_TIMEOUT_MS
from easy_cull.ui.photo_viewer.workers import (
    FolderHydrationWorker,
    PhotoViewerExifWorker,
    ViewerPrefetchWorker,
)
from easy_cull.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_cull.ui.widgets import ThumbnailPreviewWidget

if TYPE_CHECKING:
    from collections.abc import Callable

FOCUS_POINT_COORDINATE_COUNT = 2
PERCENT_COMPLETE = 100
EXTENDED_PROGRESS_MAX = 200
PHOTO_VIEWER_MINIMAP_WIDTH = 180
PHOTO_VIEWER_MINIMAP_HEIGHT = 120
PHOTO_VIEWER_MINIMAP_MARGIN = 14
FOLDER_ACCESS_RECOVERY_MESSAGE = (
    'Browsing photos in this folder and adjacent-photo navigation need folder'
    ' access. Grant EasyCull access in System Settings -> Privacy & Security'
    ' -> Files & Folders.'
)
FOLDER_ACCESS_RECOVERY_TIMEOUT_MS = TRANSIENT_MESSAGE_TIMEOUT_MS * 5


class FolderHydrationSignalBridge(QObject):
    """Relay hydration worker signals onto the viewer window GUI thread."""

    def __init__(self, window: PhotoViewerWindow) -> None:
        super().__init__(window)
        self._window = window

    @Slot(int, object, str, int)
    def handle_progress(
            self,
            request_id: int,
            expected_folder: Path,
            message: str,
            progress: int,
    ) -> None:
        """Forward worker progress to the window on the GUI thread."""
        self._window._handle_folder_hydration_progress(  # noqa: SLF001
            request_id, expected_folder, message, progress
        )

    @Slot(int, object, object)
    def handle_finished(
            self,
            request_id: int,
            expected_folder: Path,
            library: object,
    ) -> None:
        """Forward worker completion to the window on the GUI thread."""
        self._window._handle_folder_hydration_finished(  # noqa: SLF001
            request_id, expected_folder, library
        )

    @Slot(int, object, str)
    def handle_failed(
            self,
            request_id: int,
            expected_folder: Path,
            error: str,
    ) -> None:
        """Forward worker failure to the window on the GUI thread."""
        self._window._handle_folder_hydration_failed(  # noqa: SLF001
            request_id, expected_folder, error
        )


class PhotoViewerWindow(QMainWindow):
    """Lightweight file-open photo viewer with culling handoff."""

    culling_requested = Signal(object)

    def __init__(self, startup_file: Path) -> None:
        super().__init__()
        self.library = PhotoLibrary()
        self.folder_access_manager = FolderAccessManager()
        self.current_photo_id: str | None = None
        self._startup_file = Path(startup_file)
        self._folder_access_granted = True
        self._title_suffix: str | None = None
        self._pending_culling_handoff = False
        self._hydrated_library: PhotoLibrary | None = None
        self._folder_hydration_message = ''
        self._folder_hydration_progress = 0
        self._folder_hydration_request_id = 0
        self._folder_hydration_folder: Path | None = None
        self._folder_hydration_thread: QThread | None = None
        self._folder_hydration_worker: FolderHydrationWorker | None = None
        self._folder_hydration_bridge: object | None = None
        self._photo_viewer_exif_thread: QThread | None = None
        self._photo_viewer_exif_worker: PhotoViewerExifWorker | None = None
        self._photo_viewer_exif_request_id = 0
        self._photo_viewer_exif_refresh_pending = False
        self._viewer_prefetch_thread: QThread | None = None
        self._viewer_prefetch_worker: ViewerPrefetchWorker | None = None
        self._minimap_photo_id: str | None = None
        self._closing = False
        self._close_after_background_tasks = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(easy_cull_icon())
        self.resize(1400, 900)
        self._build_ui()
        self._build_shortcuts()
        QTimer.singleShot(0, lambda: self.open_file(self._startup_file))

    def _build_ui(self) -> None:
        root = QWidget(self)
        root.setObjectName('photoViewerRoot')
        self.setCentralWidget(root)
        self.central_widget = root
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        self.viewer_stack_widget = QWidget(root)
        stack_layout = QVBoxLayout(self.viewer_stack_widget)
        stack_layout.setContentsMargins(0, 0, 0, 0)
        self.viewer = MainPhotoViewer(self.viewer_stack_widget)
        self.viewer.set_focus_point_marker_visible(enabled=True)
        self.viewer.visible_region_changed.connect(
            self._refresh_visible_region_overlay
        )
        stack_layout.addWidget(self.viewer)
        layout.addWidget(self.viewer_stack_widget, 1)
        self.minimap = ThumbnailPreviewWidget(
            QSize(PHOTO_VIEWER_MINIMAP_WIDTH, PHOTO_VIEWER_MINIMAP_HEIGHT),
            self.viewer_stack_widget,
        )
        self.minimap.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.minimap.hide()
        self._build_progress_overlay()
        self._build_transient_message_overlay()
        self.viewer_stack_widget.installEventFilter(self)

    def _build_progress_overlay(self) -> None:
        self.progress_overlay = QWidget(self.central_widget)
        self.progress_overlay.setObjectName('progressOverlay')
        self.progress_overlay.hide()
        overlay_layout = QVBoxLayout(self.progress_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch(1)
        overlay_center = QHBoxLayout()
        overlay_center.addStretch(1)
        self.progress_panel = QFrame(self.progress_overlay)
        self.progress_panel.setObjectName('progressPanel')
        panel_layout = QVBoxLayout(self.progress_panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(14)
        self.overlay_message_label = QLabel('', self.progress_panel)
        self.overlay_message_label.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self.overlay_message_label)
        self.overlay_progress_bar = QProgressBar(self.progress_panel)
        self.overlay_progress_bar.setRange(0, 100)
        self.overlay_progress_bar.setFixedWidth(360)
        panel_layout.addWidget(self.overlay_progress_bar)
        overlay_center.addWidget(self.progress_panel)
        overlay_center.addStretch(1)
        overlay_layout.addLayout(overlay_center)
        overlay_layout.addStretch(1)

    def _build_transient_message_overlay(self) -> None:
        self.transient_message_overlay = QWidget(self.central_widget)
        self.transient_message_overlay.setObjectName('transientMessageOverlay')
        self.transient_message_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.transient_message_overlay.hide()
        overlay_layout = QVBoxLayout(self.transient_message_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch(1)
        overlay_center = QHBoxLayout()
        overlay_center.addStretch(1)
        self.transient_message_panel = QFrame(self.transient_message_overlay)
        self.transient_message_panel.setObjectName('transientMessagePanel')
        panel_layout = QVBoxLayout(self.transient_message_panel)
        panel_layout.setContentsMargins(22, 16, 22, 16)
        self.transient_message_label = QLabel('', self.transient_message_panel)
        self.transient_message_label.setAlignment(Qt.AlignCenter)
        self.transient_message_label.setWordWrap(True)
        panel_layout.addWidget(self.transient_message_label)
        overlay_center.addWidget(self.transient_message_panel)
        overlay_center.addStretch(1)
        overlay_layout.addLayout(overlay_center)
        overlay_layout.addStretch(1)
        self.transient_message_timer = QTimer(self)
        self.transient_message_timer.setSingleShot(True)
        self.transient_message_timer.timeout.connect(
            self.transient_message_overlay.hide
        )

    def _build_shortcuts(self) -> None:
        self.space_shortcut = self._make_shortcut(
            Qt.Key_Space, self.viewer.toggle_focus_zoom
        )
        self.zoom_toggle_shortcut = self._make_shortcut(
            'Z', self.viewer.toggle_focus_zoom
        )
        self.browse_mode_shortcut = self._make_shortcut(
            'G', self._request_culling_handoff
        )
        self.enter_shortcut = self._make_shortcut(
            Qt.Key_Return, self._request_culling_handoff
        )
        self.keypad_enter_shortcut = self._make_shortcut(
            Qt.Key_Enter, self._request_culling_handoff
        )
        for key, direction in (
            (Qt.Key_Left, -1),
            (Qt.Key_Up, -1),
            (Qt.Key_Right, 1),
            (Qt.Key_Down, 1),
        ):
            self._make_shortcut(
                key, lambda step=direction: self.navigate(step)
            )

    def _make_shortcut(
            self, key: str | int, callback: Callable[[], None]
    ) -> QShortcut:
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.WindowShortcut)
        shortcut.activated.connect(
            lambda: None if self.progress_overlay.isVisible() else callback()
        )
        return shortcut

    def open_file(self, file_path: object) -> None:
        """Open a photo file into the lightweight viewer state."""
        path = Path(str(file_path)).expanduser()
        folder_access_granted = False
        try:
            resolved_path = path.resolve()
            self._cancel_background_tasks_for_replacement()
            folder_access_granted = (
                self.folder_access_manager.ensure_access_for_file(
                    resolved_path, self
                )
            )
            self.library.load_viewer_folder(
                resolved_path,
                allow_folder_scan=folder_access_granted,
            )
        except PermissionError:
            folder_access_granted = False
            self.library.load_viewer_folder(
                resolved_path, allow_folder_scan=False
            )
        except Exception as exc:  # noqa: BLE001 - surface file-open failures
            QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
            self.close()
            return

        self._folder_access_granted = folder_access_granted
        self._title_suffix = resolved_path.suffix.casefold()
        self._hydrated_library = None
        self.current_photo_id = self._photo_id_for_opened_file(resolved_path)
        if self.current_photo_id is None and self.library.photos:
            self.current_photo_id = self.library.photos[0].photo_id

        self._display_current_photo(force_fit=True)
        self._refresh_window_title()
        self._start_photo_viewer_exif_refresh()
        self._start_viewer_prefetch()
        if folder_access_granted and self.library.current_folder is not None:
            self._start_folder_hydration(self.library.current_folder)

    def _photo_id_for_opened_file(self, file_path: Path) -> str | None:
        target_name = file_path.name.casefold()
        for photo in self.library.get_photos():
            if any(name.casefold() == target_name for name in photo.files):
                return photo.photo_id

        return None

    def navigate(self, direction: int) -> None:
        """Move to an adjacent photo in the opened folder."""
        if self.current_photo_id is None or not self.library.photos:
            return

        if not self._folder_access_granted:
            self._show_transient_message(
                FOLDER_ACCESS_RECOVERY_MESSAGE,
                timeout_ms=FOLDER_ACCESS_RECOVERY_TIMEOUT_MS,
            )
            return

        photo_ids = [photo.photo_id for photo in self.library.get_photos()]
        try:
            current_index = photo_ids.index(self.current_photo_id)
        except ValueError:
            return

        next_index = current_index + direction
        if next_index < 0 or next_index >= len(photo_ids):
            return

        self.current_photo_id = photo_ids[next_index]
        self.viewer.set_fit_view()
        self._display_current_photo(force_fit=True)
        self._refresh_window_title()
        self._start_photo_viewer_exif_refresh()
        self._start_viewer_prefetch()

    def _display_current_photo(self, *, force_fit: bool = False) -> None:
        if self.current_photo_id is None:
            self.viewer.clear_photo()
            return

        photo = self.library.get_photo(self.current_photo_id)
        image_path = self.library.get_preview_path(photo.photo_id, 'viewer')
        if force_fit:
            self.viewer.set_fit_view()

        self.viewer.set_photo(
            image_path,
            photo.focus_point,
            focus_point_pending=getattr(photo, 'focus_point_pending', False),
            preserve_zoom=False,
        )

    def _refresh_window_title(self) -> None:
        if self.current_photo_id is None or not self.library.photos:
            self.setWindowTitle(APP_NAME)
            return

        photos = self.library.get_photos()
        photo_ids = [photo.photo_id for photo in photos]
        try:
            photo_index = photo_ids.index(self.current_photo_id)
        except ValueError:
            self.setWindowTitle(APP_NAME)
            return

        photo = photos[photo_index]
        preferred_suffix = self._title_suffix
        title_filename = next(
            (
                filename
                for filename in photo.files
                if preferred_suffix is not None
                and Path(filename).suffix.casefold() == preferred_suffix
            ),
            photo.preview_source.name,
        )
        self.setWindowTitle(
            f'{APP_NAME} - {title_filename} ({photo_index + 1} /'
            f' {len(photos)})'
        )

    def _request_culling_handoff(self) -> None:
        if not self._folder_access_granted:
            self._show_transient_message(
                FOLDER_ACCESS_RECOVERY_MESSAGE,
                timeout_ms=FOLDER_ACCESS_RECOVERY_TIMEOUT_MS,
            )
            return

        if (
            self.current_photo_id is None
            or self.library.current_folder is None
        ):
            return

        if (
            self._folder_hydration_thread is not None
            and self._hydrated_library is None
        ):
            self._pending_culling_handoff = True
            self._show_progress(
                self._folder_hydration_message or 'Loading folder...',
                self._folder_hydration_progress,
            )
            return

        library = self._hydrated_library or self.library
        request = CullingLaunchRequest(
            folder=library.current_folder or self.library.current_folder,
            selected_photo_id=self.current_photo_id,
            enter_browse=True,
            preloaded_library=library,
        )
        self.culling_requested.emit(request)

    def _start_photo_viewer_exif_refresh(self) -> None:
        if self.current_photo_id is None or not self.library.photos:
            return

        if self._photo_viewer_exif_thread is not None:
            self._photo_viewer_exif_request_id += 1
            self._photo_viewer_exif_refresh_pending = True
            if self._photo_viewer_exif_worker is not None:
                self._photo_viewer_exif_worker.cancel()

            self._photo_viewer_exif_thread.quit()
            return

        try:
            photo = self.library.get_photo(self.current_photo_id)
        except KeyError:
            return

        self._photo_viewer_exif_request_id += 1
        request_id = self._photo_viewer_exif_request_id
        self._photo_viewer_exif_thread = QThread(self)
        self._photo_viewer_exif_worker = PhotoViewerExifWorker(
            request_id,
            photo.photo_id,
            photo.metadata_source,
            photo.preview_source,
        )
        self._photo_viewer_exif_worker.moveToThread(
            self._photo_viewer_exif_thread
        )
        self._photo_viewer_exif_thread.started.connect(
            self._photo_viewer_exif_worker.run
        )
        self._photo_viewer_exif_worker.finished.connect(
            self._handle_photo_viewer_exif_finished
        )
        self._photo_viewer_exif_worker.failed.connect(
            self._handle_photo_viewer_exif_failed
        )
        self._photo_viewer_exif_worker.finished.connect(
            self._photo_viewer_exif_thread.quit
        )
        self._photo_viewer_exif_worker.failed.connect(
            self._photo_viewer_exif_thread.quit
        )
        self._photo_viewer_exif_worker.finished.connect(
            self._photo_viewer_exif_worker.deleteLater
        )
        self._photo_viewer_exif_worker.failed.connect(
            self._photo_viewer_exif_worker.deleteLater
        )
        self._photo_viewer_exif_thread.finished.connect(
            self._photo_viewer_exif_thread.deleteLater
        )
        finished_thread = self._photo_viewer_exif_thread
        finished_worker = self._photo_viewer_exif_worker
        self._photo_viewer_exif_thread.finished.connect(
            lambda: self._clear_photo_viewer_exif_worker(
                finished_thread, finished_worker
            )
        )
        self._photo_viewer_exif_thread.start()

    def _handle_photo_viewer_exif_finished(
            self,
            request_id: int,
            photo_id: str,
            focus_point: object,
    ) -> None:
        if (
            self._closing
            or request_id != self._photo_viewer_exif_request_id
            or focus_point is None
        ):
            return

        if (
            not isinstance(focus_point, tuple)
            or len(focus_point) != FOCUS_POINT_COORDINATE_COUNT
        ):
            return

        try:
            photo = self.library.get_photo(photo_id)
        except KeyError:
            return

        point = cast('tuple[float, float]', focus_point)
        photo.focus_point = (float(point[0]), float(point[1]))
        photo.focus_point_pending = False
        if self.current_photo_id == photo_id:
            self.viewer.set_focus_point(photo.focus_point)

    def _handle_photo_viewer_exif_failed(
            self, request_id: int, _error: str
    ) -> None:
        if request_id != self._photo_viewer_exif_request_id:
            return

        self._photo_viewer_exif_request_id += 1
        if self.current_photo_id is None:
            return

        try:
            photo = self.library.get_photo(self.current_photo_id)
        except KeyError:
            return

        photo.focus_point_pending = False
        self.viewer.set_focus_point(photo.focus_point)

    def _clear_photo_viewer_exif_worker(
            self, finished_thread: object, finished_worker: object
    ) -> None:
        if (
            self._photo_viewer_exif_thread is finished_thread
            and self._photo_viewer_exif_worker is finished_worker
        ):
            self._photo_viewer_exif_thread = None
            self._photo_viewer_exif_worker = None

        if self._photo_viewer_exif_refresh_pending and not self._closing:
            self._photo_viewer_exif_refresh_pending = False
            self._start_photo_viewer_exif_refresh()

        self._finish_deferred_close_if_ready()

    def _start_viewer_prefetch(self) -> None:
        if (
            self._viewer_prefetch_thread is not None
            or self.current_photo_id is None
            or not self.library.photos
        ):
            return

        photo_ids = [photo.photo_id for photo in self.library.get_photos()]
        try:
            current_index = photo_ids.index(self.current_photo_id)
        except ValueError:
            return

        first_index = max(0, current_index - 5)
        last_index = min(len(photo_ids), current_index + 6)
        self._viewer_prefetch_thread = QThread(self)
        self._viewer_prefetch_worker = ViewerPrefetchWorker(
            self.library, photo_ids[first_index:last_index]
        )
        self._viewer_prefetch_worker.moveToThread(self._viewer_prefetch_thread)
        self._viewer_prefetch_thread.started.connect(
            self._viewer_prefetch_worker.run
        )
        self._viewer_prefetch_worker.finished.connect(
            self._viewer_prefetch_thread.quit
        )
        self._viewer_prefetch_worker.failed.connect(
            self._viewer_prefetch_thread.quit
        )
        self._viewer_prefetch_worker.finished.connect(
            self._viewer_prefetch_worker.deleteLater
        )
        self._viewer_prefetch_worker.failed.connect(
            self._viewer_prefetch_worker.deleteLater
        )
        self._viewer_prefetch_thread.finished.connect(
            self._viewer_prefetch_thread.deleteLater
        )
        self._viewer_prefetch_thread.finished.connect(
            self._clear_viewer_prefetch_worker
        )
        self._viewer_prefetch_thread.start()

    def _clear_viewer_prefetch_worker(self) -> None:
        self._viewer_prefetch_thread = None
        self._viewer_prefetch_worker = None
        self._finish_deferred_close_if_ready()

    def _start_folder_hydration(self, folder: Path) -> None:
        if self._folder_hydration_thread is not None:
            return

        expected_folder = folder.expanduser().resolve()
        self._folder_hydration_request_id += 1
        request_id = self._folder_hydration_request_id
        self._folder_hydration_folder = expected_folder
        self._folder_hydration_message = 'Loading folder...'
        self._folder_hydration_progress = 0
        self._folder_hydration_thread = QThread(self)
        self._folder_hydration_worker = FolderHydrationWorker(
            request_id,
            expected_folder,
            cache_dir=self.library.cache_dir,
            sort_mode=self.library.sort_mode,
            sort_reversed=self.library.sort_reversed,
        )
        bridge = FolderHydrationSignalBridge(self)
        self._folder_hydration_bridge = bridge
        self._folder_hydration_worker.moveToThread(
            self._folder_hydration_thread
        )
        self._folder_hydration_thread.started.connect(
            self._folder_hydration_worker.run
        )
        self._folder_hydration_worker.progress.connect(bridge.handle_progress)
        self._folder_hydration_worker.finished.connect(bridge.handle_finished)
        self._folder_hydration_worker.failed.connect(bridge.handle_failed)
        self._folder_hydration_worker.finished.connect(
            self._folder_hydration_thread.quit
        )
        self._folder_hydration_worker.failed.connect(
            self._folder_hydration_thread.quit
        )
        self._folder_hydration_worker.finished.connect(
            self._folder_hydration_worker.deleteLater
        )
        self._folder_hydration_worker.failed.connect(
            self._folder_hydration_worker.deleteLater
        )
        self._folder_hydration_thread.finished.connect(
            self._folder_hydration_thread.deleteLater
        )
        finished_thread = self._folder_hydration_thread
        finished_worker = self._folder_hydration_worker
        self._folder_hydration_thread.finished.connect(
            lambda: self._clear_folder_hydration_worker(
                request_id,
                expected_folder,
                finished_thread,
                finished_worker,
            )
        )
        self._folder_hydration_thread.start()

    @Slot(int, object, str, int)
    def _handle_folder_hydration_progress(
            self,
            request_id: int,
            expected_folder: Path,
            message: str,
            progress: int,
    ) -> None:
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        self._folder_hydration_message = message
        self._folder_hydration_progress = progress
        if self._pending_culling_handoff and self.progress_overlay.isVisible():
            self._show_progress(message, progress)

    @Slot(int, object, object)
    def _handle_folder_hydration_finished(
            self,
            request_id: int,
            expected_folder: Path,
            library: object,
    ) -> None:
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        if not isinstance(library, PhotoLibrary):
            self._handle_folder_hydration_failed(
                request_id,
                expected_folder,
                'Folder loading returned an invalid result.',
            )
            return

        self._hydrated_library = library
        preserved_photo_id = self.current_photo_id
        self.library = library
        if preserved_photo_id in {photo.photo_id for photo in library.photos}:
            self.current_photo_id = preserved_photo_id
        elif library.photos:
            self.current_photo_id = library.photos[0].photo_id
        else:
            self.current_photo_id = None

        self._display_current_photo(force_fit=True)
        self._refresh_window_title()
        if self._pending_culling_handoff:
            self._pending_culling_handoff = False
            self._hide_progress()
            self._request_culling_handoff()

    @Slot(int, object, str)
    def _handle_folder_hydration_failed(
            self,
            request_id: int,
            expected_folder: Path,
            error: str,
    ) -> None:
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        if self._pending_culling_handoff:
            self._pending_culling_handoff = False
            self._hide_progress()
            QMessageBox.critical(self, 'Failed to Open Folder', error)
            return

        self._show_transient_message('Folder loading failed in the background')

    def _clear_folder_hydration_worker(
            self,
            request_id: int,
            expected_folder: Path,
            finished_thread: object,
            finished_worker: object,
    ) -> None:
        if (
            self._folder_hydration_thread is finished_thread
            and self._folder_hydration_worker is finished_worker
        ):
            self._folder_hydration_thread = None
            self._folder_hydration_worker = None
            self._clear_folder_hydration_bridge()
            if self._folder_hydration_request_matches(
                request_id, expected_folder
            ):
                self._folder_hydration_folder = None
                self._folder_hydration_message = ''
                self._folder_hydration_progress = 0

        self._finish_deferred_close_if_ready()

    def _folder_hydration_request_matches(
            self, request_id: int, expected_folder: Path
    ) -> bool:
        return (
            self._folder_hydration_request_id == request_id
            and self._folder_hydration_folder == expected_folder
        )

    def _clear_folder_hydration_bridge(self) -> None:
        bridge = self._folder_hydration_bridge
        self._folder_hydration_bridge = None
        if isinstance(bridge, QObject):
            bridge.deleteLater()

    def _cancel_background_tasks_for_replacement(self) -> None:
        self._pending_culling_handoff = False
        self._photo_viewer_exif_refresh_pending = False
        self._photo_viewer_exif_request_id += 1
        self._folder_hydration_request_id += 1
        self._folder_hydration_folder = None
        self._hydrated_library = None
        self._stop_background_thread(
            thread_attr='_photo_viewer_exif_thread',
            worker_attr='_photo_viewer_exif_worker',
        )
        self._stop_background_thread(
            thread_attr='_viewer_prefetch_thread',
            worker_attr='_viewer_prefetch_worker',
        )
        self._stop_background_thread(
            thread_attr='_folder_hydration_thread',
            worker_attr='_folder_hydration_worker',
        )
        if self._folder_hydration_thread is None:
            self._clear_folder_hydration_bridge()

    def _stop_photo_viewer_background_tasks(self) -> None:
        self._cancel_background_tasks_for_replacement()
        self._folder_hydration_message = ''
        self._folder_hydration_progress = 0

    def _stop_background_thread(
            self,
            *,
            thread_attr: str,
            worker_attr: str,
    ) -> None:
        thread = getattr(self, thread_attr)
        worker = getattr(self, worker_attr)
        if worker is not None and hasattr(worker, 'cancel'):
            worker.cancel()

        if thread is not None:
            thread.quit()
            is_running = getattr(thread, 'isRunning', None)
            if callable(is_running) and not is_running():
                setattr(self, thread_attr, None)
                setattr(self, worker_attr, None)

            return

        setattr(self, thread_attr, None)
        setattr(self, worker_attr, None)

    def _photo_viewer_background_tasks_active(self) -> bool:
        return (
            self._background_thread_slot_active(self._photo_viewer_exif_thread)
            or self._background_thread_slot_active(
                self._viewer_prefetch_thread
            )
            or self._background_thread_slot_active(
                self._folder_hydration_thread
            )
        )

    @staticmethod
    def _background_thread_slot_active(thread: object) -> bool:
        if thread is None:
            return False

        is_running = getattr(thread, 'isRunning', None)
        if callable(is_running):
            return bool(is_running())

        return True

    def _finish_deferred_close_if_ready(self) -> None:
        if (
            self._close_after_background_tasks
            and not self._photo_viewer_background_tasks_active()
        ):
            self._close_after_background_tasks = False
            self.close()

    def _refresh_visible_region_overlay(self) -> None:
        visible_region = self.viewer.visible_region_rect()
        if (
            visible_region is None
            or self.current_photo_id is None
            or not self.library.photos
        ):
            self._hide_minimap()
            return

        if self._minimap_photo_id != self.current_photo_id:
            thumb_path = self.library.get_preview_path(
                self.current_photo_id, 'thumb'
            )
            self.minimap.set_pixmap(QPixmap(str(thumb_path)))
            self._minimap_photo_id = self.current_photo_id

        self.minimap.set_visible_region_overlay(visible_region)
        if not self._update_minimap_geometry():
            return

        self.minimap.show()
        self.minimap.raise_()

    def _hide_minimap(self) -> None:
        self.minimap.set_visible_region_overlay(None)
        self.minimap.set_pixmap(QPixmap())
        self.minimap.hide()
        self._minimap_photo_id = None

    def _update_minimap_geometry(self) -> bool:
        margin = PHOTO_VIEWER_MINIMAP_MARGIN
        parent_rect = self.viewer_stack_widget.rect()
        width = PHOTO_VIEWER_MINIMAP_WIDTH
        height = PHOTO_VIEWER_MINIMAP_HEIGHT
        if parent_rect.width() < width + (margin * 2) or (
            parent_rect.height() < height + (margin * 2)
        ):
            self.minimap.hide()
            return False

        self.minimap.setGeometry(
            margin,
            parent_rect.height() - height - margin,
            width,
            height,
        )
        return True

    def _show_progress(self, message: str, progress: int) -> None:
        max_value = (
            EXTENDED_PROGRESS_MAX
            if progress > PERCENT_COMPLETE
            else PERCENT_COMPLETE
        )
        self.progress_overlay.show()
        self.progress_overlay.raise_()
        self.overlay_message_label.setText(message)
        self.overlay_progress_bar.setRange(0, max_value)
        self.overlay_progress_bar.setValue(max(0, min(max_value, progress)))
        self._update_progress_overlay_geometry()

    def _hide_progress(self) -> None:
        self.progress_overlay.hide()
        self.overlay_progress_bar.setRange(0, 100)

    def _show_transient_message(
            self,
            message: str,
            *,
            timeout_ms: int = TRANSIENT_MESSAGE_TIMEOUT_MS,
    ) -> None:
        self.transient_message_label.setText(message)
        self._update_transient_message_overlay_geometry()
        self.transient_message_overlay.show()
        self.transient_message_overlay.raise_()
        self.transient_message_timer.start(timeout_ms)

    def _update_progress_overlay_geometry(self) -> None:
        self.progress_overlay.setGeometry(self.central_widget.rect())

    def _update_transient_message_overlay_geometry(self) -> None:
        self.transient_message_overlay.setGeometry(self.central_widget.rect())

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt API
        """Keep overlays anchored when the viewer window resizes."""
        super().resizeEvent(event)
        self._update_progress_overlay_geometry()
        self._update_transient_message_overlay_geometry()
        self._update_minimap_geometry()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        """Reposition the minimap when the viewer stack changes size."""
        if (
            watched is self.viewer_stack_widget
            and event.type() == QEvent.Resize
        ):
            self._update_minimap_geometry()

        return super().eventFilter(watched, event)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """Cancel background work before allowing the viewer to close."""
        if self._photo_viewer_background_tasks_active():
            event.ignore()
            self._closing = True
            self._close_after_background_tasks = True
            self._show_progress('Closing...', 0)
            self.overlay_progress_bar.setRange(0, 0)
            self._stop_photo_viewer_background_tasks()
            return

        self._closing = True
        self._close_after_background_tasks = False
        super().closeEvent(event)
