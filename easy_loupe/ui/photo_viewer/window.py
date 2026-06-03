"""Standalone photo-viewer window for system-opened files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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
from PySide6.QtGui import QCloseEvent, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QMainWindow,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from easy_loupe.core.folder_loading import (
    DEFAULT_PHOTO_SORT_REVERSED,
    PHOTO_SORT_MODE_FILENAME,
)
from easy_loupe.core.histogram import compute_rgb_histogram
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.ui.folder_access import FolderAccessManager
from easy_loupe.ui.identity import APP_NAME, easy_loupe_icon
from easy_loupe.ui.launch import CullingLaunchRequest
from easy_loupe.ui.main_window.build import TRANSIENT_MESSAGE_TIMEOUT_MS
from easy_loupe.ui.photo_viewer.workers import (
    FolderHydrationWorker,
    PhotoViewerExifResult,
    PhotoViewerExifWorker,
    ViewerPrefetchWorker,
)
from easy_loupe.ui.viewers.exif_overlay import ExifOverlayWidget
from easy_loupe.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_loupe.ui.viewers.shell import (
    VIEWER_KEYBOARD_PAN_STEP,
    build_progress_overlay,
    build_transient_message_overlay,
    build_viewer_shortcuts,
    confirm_reset_zoom_centers,
    exif_overlay_geometry_ready,
    make_window_shortcut,
    update_exif_overlay_geometry,
)
from easy_loupe.ui.widgets import ThumbnailPreviewWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from easy_loupe.ui.viewers.photo_viewer import ManualView

PERCENT_COMPLETE = 100
EXTENDED_PROGRESS_MAX = 200
PHOTO_VIEWER_MINIMAP_WIDTH = 180
PHOTO_VIEWER_MINIMAP_HEIGHT = 120
PHOTO_VIEWER_MINIMAP_MARGIN = 14
INFO_OVERLAY_MARGIN = 14
FOLDER_ACCESS_RECOVERY_MESSAGE = (
    'Browsing photos in this folder and adjacent-photo navigation need folder'
    ' access. EasyLoupe remembers denied access for this folder tree; grant'
    ' access in System Settings -> Privacy & Security -> Files & Folders or'
    ' equivalent folder permissions.'
)
FOLDER_ACCESS_RECOVERY_TIMEOUT_MS = TRANSIENT_MESSAGE_TIMEOUT_MS * 5
PHOTO_VIEWER_OVERLAY_BACKGROUND = '#d8dde2'
PHOTO_VIEWER_OVERLAY_TEXT = '#1c232b'
PHOTO_VIEWER_OVERLAY_BORDER = '#b6bec7'
PHOTO_VIEWER_PROGRESS_FONT_SIZE_PX = 16
PHOTO_VIEWER_TRANSIENT_FONT_SIZE_PX = 28
PHOTO_VIEWER_OVERLAY_FONT_WEIGHT = 600
EXIF_LOADING_VALUE = 'Loading...'
PHOTO_VIEWER_EXIF_PLACEHOLDER_LABELS = (
    'Captured',
    'Camera Model',
    'Lens Model',
    'Focal Length',
    'Aperture',
    'Shutter Speed',
    'ISO',
    'Resolution',
    'File Size',
)


@dataclass(frozen=True)
class ViewerInspectionState:
    """Photo-viewer inspection state to carry across photo loads."""

    split: bool
    manual_view: ManualView | None


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
        self._folder_hydration_error: str | None = None
        self._folder_hydration_thread: QThread | None = None
        self._folder_hydration_worker: FolderHydrationWorker | None = None
        self._folder_hydration_bridge: object | None = None
        self._photo_viewer_exif_thread: QThread | None = None
        self._photo_viewer_exif_worker: PhotoViewerExifWorker | None = None
        self._photo_viewer_exif_request_id = 0
        self._photo_viewer_exif_refresh_pending = False
        self._viewer_prefetch_thread: QThread | None = None
        self._viewer_prefetch_worker: ViewerPrefetchWorker | None = None
        self._show_af_point_marker = True
        self._info_overlay_enabled = False
        self._info_overlay_refresh_deferred = False
        self._minimap_photo_id: str | None = None
        self._closing = False
        self._close_after_background_tasks = False

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(easy_loupe_icon())
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
        self.exif_overlay = ExifOverlayWidget(self.viewer_stack_widget)
        self.exif_overlay.hide()
        self._build_progress_overlay()
        self._build_transient_message_overlay()
        self._apply_overlay_style()
        self.viewer_stack_widget.installEventFilter(self)

    def _build_progress_overlay(self) -> None:
        overlay = build_progress_overlay(self.central_widget)
        self.progress_overlay = overlay.overlay
        self.progress_panel = overlay.panel
        self.overlay_message_label = overlay.message_label
        self.overlay_progress_bar = overlay.progress_bar

    def _build_transient_message_overlay(self) -> None:
        overlay = build_transient_message_overlay(
            self.central_widget,
            timer_parent=self,
        )
        self.transient_message_overlay = overlay.overlay
        self.transient_message_panel = overlay.panel
        self.transient_message_label = overlay.message_label
        self.transient_message_timer = overlay.timer
        self.transient_message_timer.timeout.connect(
            self._hide_transient_message
        )

    def _apply_overlay_style(self) -> None:
        """Apply readable fixed styling to photo-viewer overlays."""
        self.overlay_message_label.setStyleSheet(
            f"""
            QLabel {{
                color: {PHOTO_VIEWER_OVERLAY_TEXT};
                font-size: {PHOTO_VIEWER_PROGRESS_FONT_SIZE_PX}px;
                font-weight: {PHOTO_VIEWER_OVERLAY_FONT_WEIGHT};
            }}
            """
        )
        self.progress_overlay.setStyleSheet(
            """
            QWidget#progressOverlay {
                background-color: rgba(20, 24, 29, 140);
            }
            """
        )
        self.progress_panel.setStyleSheet(
            f"""
            QFrame#progressPanel {{
                background-color: {PHOTO_VIEWER_OVERLAY_BACKGROUND};
                border: 1px solid {PHOTO_VIEWER_OVERLAY_BORDER};
                border-radius: 12px;
            }}
            """
        )
        self.transient_message_overlay.setStyleSheet(
            """
            QWidget#transientMessageOverlay {
                background-color: rgba(20, 24, 29, 90);
            }
            """
        )
        self.transient_message_label.setStyleSheet(
            f"""
            QLabel {{
                color: {PHOTO_VIEWER_OVERLAY_TEXT};
                font-size: {PHOTO_VIEWER_TRANSIENT_FONT_SIZE_PX}px;
                font-weight: {PHOTO_VIEWER_OVERLAY_FONT_WEIGHT};
            }}
            """
        )
        self.transient_message_panel.setStyleSheet(
            f"""
            QFrame#transientMessagePanel {{
                background-color: {PHOTO_VIEWER_OVERLAY_BACKGROUND};
                border: 1px solid {PHOTO_VIEWER_OVERLAY_BORDER};
                border-radius: 12px;
            }}
            """
        )

    def _build_shortcuts(self) -> None:
        self.space_shortcut = self._make_shortcut(
            Qt.Key_Space, self.viewer.toggle_focus_zoom
        )
        self.zoom_toggle_shortcut = self._make_shortcut(
            'Z', self.viewer.toggle_focus_zoom
        )
        self.split_mode_shortcut = self._make_shortcut(
            Qt.Key_Backslash, self.viewer.toggle_split_view
        )
        self.show_af_point_shortcut = self._make_shortcut(
            'F', self._toggle_show_af_point
        )
        self.recenter_zoom_shortcut = self._make_shortcut(
            'Shift+F', self.viewer.recenter_manual_view
        )
        self.reset_zoom_centers_shortcut = self._make_shortcut(
            'Ctrl+Shift+F', self._handle_reset_zoom_centers_shortcut
        )
        self.info_overlay_shortcut = self._make_shortcut(
            'I', self._toggle_info_overlay
        )
        self.dismiss_message_shortcut = self._make_shortcut(
            Qt.Key_Escape, self._hide_transient_message
        )
        self._viewer_shortcuts = build_viewer_shortcuts(
            self._make_shortcut,
            zoom_step=self.viewer.zoom_step,
            keyboard_pan_by=self._keyboard_pan_by,
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
        # Treat the progress overlay as modal: background hydration/close
        # states should not accept navigation or viewer mutations.
        return make_window_shortcut(
            self,
            key,
            callback,
            blocked=self.progress_overlay.isVisible,
        )

    def _keyboard_pan_by(self, x_direction: int, y_direction: int) -> None:
        """Pan using the same screen-feeling step as culling view."""
        base_dx = x_direction * VIEWER_KEYBOARD_PAN_STEP
        base_dy = y_direction * VIEWER_KEYBOARD_PAN_STEP
        self.viewer.keyboard_pan_by(base_dx, base_dy)

    def _toggle_show_af_point(self) -> None:
        """Toggle the autofocus marker in the standalone viewer."""
        self._show_af_point_marker = not self._show_af_point_marker
        self.viewer.set_focus_point_marker_visible(
            enabled=self._show_af_point_marker
        )

    def _handle_reset_zoom_centers_shortcut(self) -> None:
        if not confirm_reset_zoom_centers(self):
            return

        self.viewer.reset_manual_view_centers()

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
            # A granted prompt can still fail at scan time on protected
            # folders. Fall back to the selected photo only so opening remains
            # useful while navigation and handoff stay blocked.
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
        self._folder_hydration_error = None
        self.current_photo_id = self._photo_id_for_opened_file(resolved_path)
        if self.current_photo_id is None and self.library.photos:
            self.current_photo_id = self.library.photos[0].photo_id

        try:
            # Metadata loading can succeed even when preview rendering fails.
            # Treat that as an open failure instead of showing an empty shell.
            self._display_current_photo(force_fit=True)
        except (OSError, RuntimeError, ValueError) as exc:
            QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
            self.close()
            return

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
            self._show_folder_access_recovery_message()
            return

        photo_ids = [photo.photo_id for photo in self.library.get_photos()]
        try:
            current_index = photo_ids.index(self.current_photo_id)
        except ValueError:
            return

        next_index = current_index + direction
        if next_index < 0 or next_index >= len(photo_ids):
            return

        previous_photo_id = self.current_photo_id
        inspection_state = self._capture_inspection_state()
        self.current_photo_id = photo_ids[next_index]
        try:
            # Rendering needs the tentative current id. If it fails, restore
            # the old id so title, overlay, and handoff state remain coherent.
            self._display_current_photo(inspection_state=inspection_state)
        except (OSError, RuntimeError, ValueError) as exc:
            self.current_photo_id = previous_photo_id
            self._display_current_photo(inspection_state=inspection_state)
            self._show_transient_message(f'Failed to open photo: {exc}')
            return

        self._refresh_window_title()
        self._start_photo_viewer_exif_refresh()
        self._start_viewer_prefetch()

    def _capture_inspection_state(self) -> ViewerInspectionState:
        """Capture split/manual inspection state before a photo change."""
        if self.viewer.is_split_view():
            return ViewerInspectionState(
                split=True,
                manual_view=self.viewer.current_manual_view(),
            )

        return ViewerInspectionState(
            split=False,
            manual_view=self.viewer.current_manual_view(),
        )

    def _display_current_photo(
            self,
            *,
            force_fit: bool = False,
            inspection_state: ViewerInspectionState | None = None,
    ) -> None:
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
        if not force_fit and inspection_state is not None:
            self._restore_inspection_state(inspection_state)

        self._refresh_info_overlay()

    def _restore_inspection_state(
            self, inspection_state: ViewerInspectionState
    ) -> None:
        """Restore carried split/manual state after loading a new photo."""
        if inspection_state.split and not self.viewer.is_split_view():
            self.viewer.toggle_split_view()

        manual_view = inspection_state.manual_view
        if manual_view is not None:
            self.viewer.apply_manual_view(
                manual_view.zoom_factor, manual_view.center
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
            self._show_folder_access_recovery_message()
            return

        if (
            self.current_photo_id is None
            or self.library.current_folder is None
        ):
            return

        if self._folder_hydration_error is not None:
            # The fast viewer library is intentionally incomplete. After a
            # full hydration failure, culling must show the load error instead
            # of receiving the lightweight viewer state.
            QMessageBox.critical(
                self,
                'Failed to Open Folder',
                self._folder_hydration_error,
            )
            return

        if (
            self._folder_hydration_thread is not None
            and self._hydrated_library is None
        ):
            # The worker may still be hydrating the full folder needed for
            # culling. Once a hydrated library exists, handoff may proceed even
            # before QThread.finished has cleared the thread slot.
            self._pending_culling_handoff = True
            self._show_progress(
                self._folder_hydration_message or 'Loading folder...',
                self._folder_hydration_progress,
            )
            return

        if self._hydrated_library is None:
            return

        library = self._hydrated_library
        request = CullingLaunchRequest(
            folder=library.current_folder or self.library.current_folder,
            selected_photo_id=self.current_photo_id,
            enter_browse=True,
            preloaded_library=library,
        )
        self.culling_requested.emit(request)

    def _show_folder_access_recovery_message(self) -> None:
        """Show the macOS manual-grant guidance for selected-photo fallback."""
        self._show_transient_message(
            FOLDER_ACCESS_RECOVERY_MESSAGE,
            timeout_ms=FOLDER_ACCESS_RECOVERY_TIMEOUT_MS,
        )

    def _toggle_info_overlay(self) -> None:
        """Toggle the EXIF and histogram overlay."""
        self._info_overlay_enabled = not self._info_overlay_enabled
        self._refresh_info_overlay()

    def _refresh_info_overlay(self, *, allow_defer: bool = True) -> None:
        """Show or hide the EXIF/histogram pane for the active photo."""
        if (
            not self._info_overlay_enabled
            or self.progress_overlay.isVisible()
            or self.current_photo_id is None
            or not self.library.photos
        ):
            self.exif_overlay.hide()
            return

        photo = self.library.get_photo(self.current_photo_id)
        histogram = None
        try:
            image_path = self.library.get_preview_path(
                photo.photo_id, 'viewer'
            )
            histogram = compute_rgb_histogram(image_path)
        except (OSError, RuntimeError, ValueError):
            histogram = None

        self.exif_overlay.set_content(
            self._exif_display_for_overlay(photo), histogram
        )
        if not self._info_overlay_geometry_ready():
            self.exif_overlay.hide()
            if allow_defer:
                self._defer_info_overlay_refresh()

            return

        self._update_info_overlay_geometry()
        self.exif_overlay.show()
        self.exif_overlay.raise_()

    @staticmethod
    def _exif_display_for_overlay(photo: object) -> dict[str, str]:
        if getattr(photo, 'focus_point_pending', False):
            return dict.fromkeys(
                PHOTO_VIEWER_EXIF_PLACEHOLDER_LABELS, EXIF_LOADING_VALUE
            )

        exif_display = getattr(photo, 'exif_display', {})
        if exif_display:
            return dict(exif_display)

        return {}

    def _info_overlay_geometry_ready(self) -> bool:
        """Return whether the viewer stack can fit the EXIF overlay."""
        return exif_overlay_geometry_ready(
            self.viewer_stack_widget,
            self.exif_overlay,
            margin=INFO_OVERLAY_MARGIN,
        )

    def _defer_info_overlay_refresh(self) -> None:
        """Retry overlay refresh after Qt settles viewer geometry."""
        if self._info_overlay_refresh_deferred:
            return

        self._info_overlay_refresh_deferred = True
        QTimer.singleShot(0, self._finish_deferred_info_overlay_refresh)

    def _finish_deferred_info_overlay_refresh(self) -> None:
        self._info_overlay_refresh_deferred = False
        self._refresh_info_overlay(allow_defer=False)

    def _update_info_overlay_geometry(self) -> None:
        """Anchor the EXIF overlay at the top right of the viewer stack."""
        update_exif_overlay_geometry(
            self.viewer_stack_widget,
            self.exif_overlay,
            margin=INFO_OVERLAY_MARGIN,
        )

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
            [
                photo.preview_source.parent / filename
                for filename in photo.files
            ],
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
            result: object,
    ) -> None:
        if (
            self._closing
            or request_id != self._photo_viewer_exif_request_id
            or result is None
        ):
            return

        if not isinstance(result, PhotoViewerExifResult):
            return

        try:
            photo = self.library.get_photo(photo_id)
        except KeyError:
            return

        photo.focus_point = result.focus_point
        photo.focus_point_pending = False
        photo.capture_at = result.capture_at
        photo.image_width = result.image_width
        photo.image_height = result.image_height
        photo.exif_display = dict(result.exif_display)
        if self.current_photo_id == photo_id:
            self.viewer.set_focus_point(photo.focus_point)
            self._refresh_info_overlay()

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
        self._refresh_info_overlay()

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
        self._folder_hydration_error = None
        self._folder_hydration_message = 'Loading folder...'
        self._folder_hydration_progress = 0
        self._folder_hydration_thread = QThread(self)
        self._folder_hydration_worker = FolderHydrationWorker(
            request_id,
            expected_folder,
            cache_dir=self.library.cache_dir,
            sort_mode=PHOTO_SORT_MODE_FILENAME,
            sort_reversed=DEFAULT_PHOTO_SORT_REVERSED,
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

        preserved_photo_id = self.current_photo_id
        preserve_inspection = preserved_photo_id in {
            photo.photo_id for photo in library.photos
        }
        inspection_state = (
            self._capture_inspection_state() if preserve_inspection else None
        )
        self._hydrated_library = library
        self.library = library
        if preserve_inspection:
            self.current_photo_id = preserved_photo_id
        elif library.photos:
            self.current_photo_id = library.photos[0].photo_id
        else:
            self.current_photo_id = None

        try:
            self._display_current_photo(inspection_state=inspection_state)
        except (OSError, RuntimeError, ValueError) as exc:
            self._handle_folder_hydration_failed(
                request_id,
                expected_folder,
                str(exc),
            )
            return

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
            self._folder_hydration_error = error
            QMessageBox.critical(self, 'Failed to Open Folder', error)
            return

        self._folder_hydration_error = error
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
        self._folder_hydration_error = None
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
            try:
                thumb_path = self.library.get_preview_path(
                    self.current_photo_id, 'thumb'
                )
            except (OSError, RuntimeError, ValueError):
                # Visible-region updates are secondary to inspection. If the
                # thumbnail cannot render, hide only the minimap and keep the
                # already displayed viewer image stable.
                self._hide_minimap()
                return

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
        self.exif_overlay.hide()
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
        self._refresh_info_overlay()

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

    def _hide_transient_message(self) -> None:
        """Dismiss the non-modal message overlay and its auto-hide timer."""
        self.transient_message_timer.stop()
        self.transient_message_overlay.hide()

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
        self._update_info_overlay_geometry()

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        """Reposition floating overlays when the viewer stack changes size."""
        if (
            watched is self.viewer_stack_widget
            and event.type() == QEvent.Resize
        ):
            self._update_minimap_geometry()
            self._update_info_overlay_geometry()

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
