"""Long-running workflows, busy-state handling, and metadata actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QObject, QPoint, QThread, Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QListWidget,
    QMenu,
    QMessageBox,
)

from easy_cull.operations.common import (
    OperationSummary,
    UndoPlan,
    undo_operation,
)
from easy_cull.operations.export import organize_photos
from easy_cull.operations.xmp import write_xmp_sidecars
from easy_cull.ui.main_window.build import (
    MIN_SCENE_MERGE_PHOTO_COUNT,
    TRANSIENT_MESSAGE_TIMEOUT_MS,
)
from easy_cull.ui.main_window.dialogs import (
    OrganizerDialog,
    OrganizerDialogResult,
)
from easy_cull.ui.theme import (
    LOAD_AND_PREVIEW_PROGRESS_MAX,
    LOAD_PROGRESS_MAX,
    PHOTO_ID_ROLE,
)
from easy_cull.ui.workers import (
    FolderHydrationWorker,
    OperationWorker,
    PhotoViewerExifWorker,
    SceneDetectionWorker,
    ViewerPrefetchWorker,
)

if TYPE_CHECKING:
    from easy_cull.core.records import SceneGroup
    from easy_cull.ui.main_window.window import MainWindow

ProgressCallback = Callable[[str, int], None]
FOCUS_POINT_COORDINATE_COUNT = 2


@dataclass(frozen=True)
class MetadataEdit:
    """In-memory undo record for a metadata assignment batch."""

    field: str
    before: dict[str, Any]
    after: dict[str, Any]


@dataclass(frozen=True)
class SceneEdit:
    """In-memory undo record for a scene grouping edit."""

    before_groups: list[list[str]]
    before_source: str | None
    after_groups: list[list[str]]
    after_source: str | None


@dataclass(frozen=True)
class ThumbnailScrollAnchor:
    """Viewport anchor for preserving a thumbnail row across a rebuild."""

    photo_id: str
    visible_top: int | None


class FolderHydrationSignalBridge(QObject):
    """
    Relay folder-hydration worker signals on the main-window GUI thread.

    ``FolderHydrationWorker`` lives in a background ``QThread`` because full
    folder loading and preview warming can be slow. Its results eventually
    rebuild Qt list widgets and item widgets, and Qt widgets must only be
    touched from the GUI thread. This bridge is a ``QObject`` parented to the
    ``MainWindow``, so Qt's queued cross-thread signal delivery invokes these
    handlers in the same thread as the window.
    """

    def __init__(self, window: MainWindow) -> None:
        """
        Create a GUI-thread bridge owned by ``window``.

        Parenting the bridge to the window gives it the window's thread
        affinity and lifetime. The worker can be deleted with its background
        thread while the bridge remains safe to receive queued completion
        signals until the window clears it.
        """
        super().__init__(window)
        self._window = window

    # ``@Slot`` registers this Python method as a typed Qt slot. Combined with
    # this bridge object's GUI-thread affinity, PySide queues cross-thread
    # worker emissions here instead of running the callback in the worker
    # thread. That matters because even progress handling can update overlays.
    @Slot(int, object, str, int)
    def handle_progress(
            self,
            request_id: int,
            expected_folder: Path,
            message: str,
            progress: int,
    ) -> None:
        """
        Apply hydration progress after Qt queues it to the GUI thread.

        The request id and expected folder are preserved in the signal payload
        so the window can ignore progress from an older hydration request after
        a newer photo-open has replaced it.
        """
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
        """
        Apply hydration results after Qt queues them to the GUI thread.

        The finished path swaps in the fully hydrated library and rebuilds list
        widgets. Keeping this work on the GUI thread prevents the macOS abort
        caused by creating item widgets from the worker thread.
        """
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
        """
        Apply hydration failures on the GUI thread for safe UI updates.

        Failure handling may show a dialog, hide an overlay, or show a
        transient message. Those UI operations follow the same thread rule as
        successful hydration results.
        """
        self._window._handle_folder_hydration_failed(  # noqa: SLF001
            request_id, expected_folder, error
        )


class MainWindowWorkflowMixin:
    """Workflow handlers for folder loading, scene detection, and metadata."""

    def choose_folder(self: MainWindow) -> None:
        """Prompt for a photo folder, load it, and refresh the UI."""
        if self._busy:
            return

        folder = QFileDialog.getExistingDirectory(
            self, 'Choose a folder of photos'
        )
        if not folder:
            return

        try:
            self._set_photo_viewer_mode(active=False)
            self._show_progress('Scanning folder', 0)
            self.open_button.setEnabled(False)
            self.detect_button.setEnabled(False)
            self.library.load_folder(
                Path(folder), progress_callback=self._handle_load_progress
            )
        except Exception as exc:  # noqa: BLE001 - surface unexpected load errors in the UI
            self._hide_progress()
            self.open_button.setEnabled(True)
            self.detect_button.setEnabled(bool(self.library.photos))
            QMessageBox.critical(self, 'Failed to Open Folder', str(exc))
            return

        self._rebuild_loaded_views(show_progress=True)
        self._clear_metadata_history()
        self._hide_progress()
        self.open_button.setEnabled(True)
        self._refresh_ui()
        self._restore_active_navigation_focus(defer=True)

    def open_file_from_system(self: MainWindow, file_path: object) -> None:
        """Open a photo file passed by Finder, Explorer, or argv."""
        if self._busy:
            return

        self._initial_folder_prompt_timer.stop()
        self._initial_folder_prompt_pending = False
        self._startup_file = None
        path = Path(str(file_path)).expanduser()
        folder_access_granted = False
        try:
            resolved_path = path.resolve()
            self._cancel_photo_viewer_background_tasks_for_replacement()
            folder_access_granted = (
                self.folder_access_manager.ensure_access_for_file(
                    resolved_path, self
                )
            )
            self.library.load_viewer_folder(
                resolved_path,
                allow_folder_scan=folder_access_granted,
            )
        except PermissionError as exc:
            if not folder_access_granted:
                QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
                return

            folder_access_granted = self._retry_photo_viewer_folder_access(
                resolved_path
            )
            if not self._load_photo_viewer_folder_after_access_retry(
                resolved_path, allow_folder_scan=folder_access_granted
            ):
                return
        except Exception as exc:  # noqa: BLE001 - surface file-open failures
            QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
            return

        self._clear_metadata_history()
        self._photo_viewer_folder_access_granted = folder_access_granted
        self._photo_viewer_title_suffix = resolved_path.suffix.casefold()
        self.current_photo_id = self._photo_id_for_opened_file(resolved_path)
        if self.current_photo_id is None and self.library.photos:
            self.current_photo_id = self.library.photos[0].photo_id

        self._set_photo_viewer_mode(active=True)
        self._display_current_photo(force_fit=True)
        self._refresh_ui()
        self._start_photo_viewer_exif_refresh()
        self._start_viewer_prefetch()
        if folder_access_granted and self.library.current_folder is not None:
            self._start_folder_hydration(self.library.current_folder)

    def _retry_photo_viewer_folder_access(
            self: MainWindow, file_path: Path
    ) -> bool:
        suggested_root = self.folder_access_manager.suggest_access_root(
            file_path
        )
        uses_macos_prompt = (
            self.folder_access_manager.is_macos_promptable_root(suggested_root)
        )
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Folder Access Blocked')
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText(
            'macOS blocked EasyCull from scanning this photo folder.'
        )
        if uses_macos_prompt:
            dialog.setInformativeText(
                'EasyCull can ask macOS for this folder permission again. If'
                ' macOS still blocks access, add EasyCull in System Settings >'
                ' Privacy & Security > Full Disk Access.'
            )
            retry_label = 'Try macOS Permission Again'
        else:
            dialog.setInformativeText(
                'EasyCull can reopen the native folder chooser to refresh'
                ' access. If macOS still blocks access, add EasyCull in'
                ' System Settings > Privacy & Security > Full Disk Access.'
            )
            retry_label = 'Choose Folder'

        retry_button = dialog.addButton(
            retry_label, QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(
            'Open Selected Photo Only', QMessageBox.ButtonRole.RejectRole
        )
        dialog.setDefaultButton(retry_button)
        dialog.exec()
        if dialog.clickedButton() is not retry_button:
            return False

        return self.folder_access_manager.request_access_for_file(
            file_path, self
        )

    def _load_photo_viewer_folder_after_access_retry(
            self: MainWindow,
            file_path: Path,
            *,
            allow_folder_scan: bool,
    ) -> bool:
        try:
            self.library.load_viewer_folder(
                file_path,
                allow_folder_scan=allow_folder_scan,
            )
        except PermissionError as exc:
            if allow_folder_scan:
                QMessageBox.warning(
                    self,
                    'Folder Access Still Blocked',
                    (
                        'macOS still blocked folder scanning. Add EasyCull in'
                        ' System Settings > Privacy & Security > Full Disk'
                        ' Access, then try again.\n\n'
                        'The selected photo will open by itself for now.'
                    ),
                )
                return self._load_photo_viewer_folder_after_access_retry(
                    file_path, allow_folder_scan=False
                )

            QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 - surface file-open failures
            QMessageBox.critical(self, 'Failed to Open Photo', str(exc))
            return False
        else:
            return True

    def _photo_id_for_opened_file(
            self: MainWindow, file_path: Path
    ) -> str | None:
        """Return the loaded photo id that contains the opened filename."""
        target_name = file_path.name.casefold()
        for photo in self.library.get_photos():
            if any(name.casefold() == target_name for name in photo.files):
                return photo.photo_id

        return None

    def _start_photo_viewer_exif_refresh(self: MainWindow) -> None:
        """Start or queue a focus-point refresh for the active viewer photo."""
        if (
            not self._photo_viewer_mode
            or self.current_photo_id is None
            or not self.library.photos
        ):
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
            self: MainWindow,
            request_id: int,
            photo_id: str,
            focus_point: object,
    ) -> None:
        """Apply a current EXIF focus result to the loaded viewer photo."""
        if (
            self._closing
            or not self._photo_viewer_mode
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
            self: MainWindow, request_id: int, _error: str
    ) -> None:
        """Invalidate the active EXIF request after a worker failure."""
        if request_id == self._photo_viewer_exif_request_id:
            self._photo_viewer_exif_request_id += 1

    def _clear_photo_viewer_exif_worker(
            self: MainWindow, finished_thread: object, finished_worker: object
    ) -> None:
        """Clear the finished EXIF worker and run any queued refresh."""
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

    def _start_viewer_prefetch(self: MainWindow) -> None:
        """Warm nearby viewer previews for photo-viewer navigation."""
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
        prefetch_ids = photo_ids[first_index:last_index]
        self._viewer_prefetch_thread = QThread(self)
        self._viewer_prefetch_worker = ViewerPrefetchWorker(
            self.library, prefetch_ids
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

    def _clear_viewer_prefetch_worker(self: MainWindow) -> None:
        """Clear the finished preview-prefetch worker slot."""
        self._viewer_prefetch_thread = None
        self._viewer_prefetch_worker = None
        self._finish_deferred_close_if_ready()

    def _stop_photo_viewer_background_tasks(self: MainWindow) -> None:
        """Request cancellation for photo-viewer background work."""
        self._pending_browse_after_hydration = False
        self._queued_folder_hydration_folder = None
        self._photo_viewer_exif_refresh_pending = False
        self._photo_viewer_exif_request_id += 1
        self._folder_hydration_request_id += 1
        self._folder_hydration_folder = None
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

        self._folder_hydration_message = ''
        self._folder_hydration_progress = 0

    def _cancel_photo_viewer_background_tasks_for_replacement(
            self: MainWindow,
    ) -> None:
        """Cancel stale background work before opening another system file."""
        self._pending_browse_after_hydration = False
        self._queued_folder_hydration_folder = None
        self._photo_viewer_exif_refresh_pending = False
        self._photo_viewer_exif_request_id += 1
        self._folder_hydration_request_id += 1
        self._folder_hydration_folder = None
        self._folder_hydration_message = ''
        self._folder_hydration_progress = 0
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

    def _stop_background_thread(
            self: MainWindow,
            *,
            thread_attr: str,
            worker_attr: str,
    ) -> None:
        """Request cancellation and clear already-stopped worker slots."""
        thread = getattr(self, thread_attr)
        worker = getattr(self, worker_attr)
        if worker is not None and hasattr(worker, 'cancel'):
            worker.cancel()

        if thread is not None:
            thread.quit()
            is_running = getattr(thread, 'isRunning', None)
            if callable(is_running) and not is_running():
                # Qt may have emitted finished before the queued cleanup slot
                # runs. Clear stopped slots now so closeEvent does not defer
                # on a thread object that can no longer do work.
                setattr(self, thread_attr, None)
                setattr(self, worker_attr, None)

            return

        setattr(self, thread_attr, None)
        setattr(self, worker_attr, None)

    def _start_folder_hydration(self: MainWindow, folder: Path) -> None:
        """Start full folder loading for photo-viewer handoff to culling UI."""
        if self._folder_hydration_thread is not None:
            # Folder hydration is a background convenience, so when multiple
            # opens arrive quickly only the newest folder should run after the
            # current worker winds down.
            self._queued_folder_hydration_folder = folder
            if self._folder_hydration_worker is not None:
                self._folder_hydration_worker.cancel()

            self._folder_hydration_thread.quit()
            return

        expected_folder = folder.expanduser().resolve()
        self._folder_hydration_request_id += 1
        request_id = self._folder_hydration_request_id
        self._folder_hydration_folder = expected_folder
        self._queued_folder_hydration_folder = None
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

    def detect_scenes(self: MainWindow) -> None:
        """Start asynchronous scene detection for the loaded photo set."""
        if (
            self._busy
            or not self.library.photos
            or self._background_task_active()
        ):
            return

        if self.library.scene_detection_done and self.library.scenes:
            dialog = QMessageBox(self)
            dialog.setWindowTitle('Replace Scenes?')
            dialog.setText('Replace existing scene groups?')
            dialog.setInformativeText(
                'Running scene detection will replace the saved scene groups'
                ' for this folder.'
            )
            replace_button = dialog.addButton(
                'Replace', QMessageBox.ButtonRole.AcceptRole
            )
            dialog.addButton(QMessageBox.StandardButton.Cancel)
            dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
            dialog.exec()
            if dialog.clickedButton() is not replace_button:
                return

        self._show_progress('Preparing scene detection...', 0)

        self._scene_thread = QThread(self)
        self._scene_worker = SceneDetectionWorker(self.library)
        self._scene_worker.moveToThread(self._scene_thread)
        self._scene_thread.started.connect(self._scene_worker.run)
        self._scene_worker.progress.connect(self._handle_scene_progress)
        self._scene_worker.finished.connect(self._handle_scene_finished)
        self._scene_worker.failed.connect(self._handle_scene_failed)
        self._scene_worker.finished.connect(self._scene_thread.quit)
        self._scene_worker.failed.connect(self._scene_thread.quit)
        self._scene_worker.finished.connect(self._scene_worker.deleteLater)
        self._scene_worker.failed.connect(self._scene_worker.deleteLater)
        self._scene_thread.finished.connect(self._scene_thread.deleteLater)
        self._scene_thread.finished.connect(self._clear_scene_worker)
        self._scene_thread.start()

    def open_organizer_dialog(self: MainWindow) -> None:
        """Prompt for organizer options and start the selected workflow."""
        if self._busy or not self.library.photos:
            return

        dialog = OrganizerDialog(
            self, current_folder=self.library.current_folder
        )
        if dialog.exec() != OrganizerDialog.DialogCode.Accepted:
            return

        self._start_organizer_request(dialog.selected_result())

    def _start_organizer_request(
            self: MainWindow, request: OrganizerDialogResult
    ) -> None:
        if self._busy or self.library.current_folder is None:
            return

        self._operation_kind = 'run'
        self._organizer_request = request
        self._show_progress('Preparing organizer workflow...', 0)
        self._operation_thread = QThread(self)
        self._operation_worker = OperationWorker(
            lambda progress_callback: self._run_organizer_request(
                request, progress_callback
            )
        )
        self._operation_worker.moveToThread(self._operation_thread)
        self._operation_thread.started.connect(self._operation_worker.run)
        self._operation_worker.progress.connect(
            self._handle_operation_progress
        )
        self._operation_worker.finished.connect(
            self._handle_operation_finished
        )
        self._operation_worker.failed.connect(self._handle_operation_failed)
        self._operation_worker.finished.connect(self._operation_thread.quit)
        self._operation_worker.failed.connect(self._operation_thread.quit)
        self._operation_worker.finished.connect(
            self._operation_worker.deleteLater
        )
        self._operation_worker.failed.connect(
            self._operation_worker.deleteLater
        )
        self._operation_thread.finished.connect(
            self._operation_thread.deleteLater
        )
        finished_thread = self._operation_thread
        finished_worker = self._operation_worker
        self._operation_thread.finished.connect(
            lambda: self._clear_operation_worker(
                finished_thread, finished_worker
            )
        )
        self._operation_thread.start()

    def _run_organizer_request(
            self: MainWindow,
            request: OrganizerDialogResult,
            progress_callback: ProgressCallback,
    ) -> OperationSummary:
        current_folder = self.library.current_folder
        if current_folder is None:
            raise RuntimeError('No folder is currently loaded')

        photos = self.library.get_photos()
        if request.mode == 'reorganize':
            assert request.organize_options is not None
            return organize_photos(
                current_folder,
                photos,
                request.organize_options,
                progress_callback,
            )

        assert request.xmp_options is not None
        return write_xmp_sidecars(
            current_folder,
            photos,
            request.xmp_options,
            progress_callback,
        )

    def _start_undo_operation(self: MainWindow, undo_plan: UndoPlan) -> None:
        if self._busy:
            return

        self._operation_kind = 'undo'
        self._show_progress('Preparing undo...', 0)
        self._operation_thread = QThread(self)
        self._operation_worker = OperationWorker(
            lambda progress_callback: undo_operation(
                undo_plan, progress_callback
            )
        )
        self._operation_worker.moveToThread(self._operation_thread)
        self._operation_thread.started.connect(self._operation_worker.run)
        self._operation_worker.progress.connect(
            self._handle_operation_progress
        )
        self._operation_worker.finished.connect(
            self._handle_operation_finished
        )
        self._operation_worker.failed.connect(self._handle_operation_failed)
        self._operation_worker.finished.connect(self._operation_thread.quit)
        self._operation_worker.failed.connect(self._operation_thread.quit)
        self._operation_worker.finished.connect(
            self._operation_worker.deleteLater
        )
        self._operation_worker.failed.connect(
            self._operation_worker.deleteLater
        )
        self._operation_thread.finished.connect(
            self._operation_thread.deleteLater
        )
        finished_thread = self._operation_thread
        finished_worker = self._operation_worker
        self._operation_thread.finished.connect(
            lambda: self._clear_operation_worker(
                finished_thread, finished_worker
            )
        )
        self._operation_thread.start()

    def _handle_scene_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        self._show_progress(message, progress)

    @Slot(int, object, str, int)
    def _handle_folder_hydration_progress(
            self: MainWindow,
            request_id: int,
            expected_folder: Path,
            message: str,
            progress: int,
    ) -> None:
        """Record progress for the current folder-hydration request."""
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        self._folder_hydration_message = message
        self._folder_hydration_progress = progress
        if self._pending_browse_after_hydration and self._busy:
            self._show_progress(message, progress)

    @Slot(int, object, object)
    def _handle_folder_hydration_finished(
            self: MainWindow,
            request_id: int,
            expected_folder: Path,
            library: object,
    ) -> None:
        """Apply the current folder-hydration result to the window state."""
        # Hydration finishes after the fast viewer state is already visible.
        # Match the captured request before swapping libraries so an older
        # folder cannot replace a newer system-opened photo.
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        if not hasattr(library, 'photos'):
            self._handle_folder_hydration_failed(
                request_id,
                expected_folder,
                'Folder loading returned an invalid result.',
            )
            return

        hydrated_folder = getattr(library, 'current_folder', None)
        if hydrated_folder != expected_folder:
            self._handle_folder_hydration_failed(
                request_id,
                expected_folder,
                'Folder loading returned a stale result.',
            )
            return

        self.library = library
        self._photo_viewer_folder_access_granted = True
        self._rebuild_loaded_views(preserve_current_photo=True)
        if self._pending_browse_after_hydration:
            self._pending_browse_after_hydration = False
            self._hide_progress()
            self._enter_browse_mode()

    @Slot(int, object, str)
    def _handle_folder_hydration_failed(
            self: MainWindow,
            request_id: int,
            expected_folder: Path,
            error: str,
    ) -> None:
        """Show a failure only for the current folder-hydration request."""
        if not self._folder_hydration_request_matches(
            request_id, expected_folder
        ):
            return

        if self._pending_browse_after_hydration:
            self._pending_browse_after_hydration = False
            self._hide_progress()
            QMessageBox.critical(self, 'Failed to Open Folder', error)
            return

        self._show_transient_message('Folder loading failed in the background')

    def _clear_folder_hydration_worker(
            self: MainWindow,
            request_id: int,
            expected_folder: Path,
            finished_thread: object,
            finished_worker: object,
    ) -> None:
        """Clear a finished hydration worker and start queued replacement."""
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

        queued_folder = self._queued_folder_hydration_folder
        if queued_folder is not None and not self._closing:
            # A newer file-open may have arrived while the old hydration was
            # uninterruptible. Start only that latest queued folder now that
            # the old thread slot is clear.
            self._queued_folder_hydration_folder = None
            self._start_folder_hydration(queued_folder)

        if not self._closing:
            self._refresh_ui()
            self._update_mode_shortcuts()

        self._finish_deferred_close_if_ready()

    def _clear_folder_hydration_bridge(self: MainWindow) -> None:
        """Release the GUI-thread bridge for finished hydration signals."""
        bridge = self._folder_hydration_bridge
        self._folder_hydration_bridge = None
        if isinstance(bridge, QObject):
            bridge.deleteLater()

    def _folder_hydration_request_matches(
            self: MainWindow, request_id: int, expected_folder: Path
    ) -> bool:
        """Return whether a hydration signal belongs to the latest request."""
        return (
            self._folder_hydration_request_id == request_id
            and self._folder_hydration_folder == expected_folder
        )

    def _photo_viewer_background_tasks_active(self: MainWindow) -> bool:
        """Return whether a photo-viewer background thread is still running."""
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
        """Return whether a stored thread slot represents active work."""
        if thread is None:
            return False

        is_running = getattr(thread, 'isRunning', None)
        if callable(is_running):
            return bool(is_running())

        return True

    def _finish_deferred_close_if_ready(self: MainWindow) -> None:
        """Retry a deferred close once photo-viewer workers are inactive."""
        if (
            self._close_after_background_tasks
            and not self._photo_viewer_background_tasks_active()
        ):
            # The original close event was ignored to avoid blocking Qt while
            # workers stopped. Re-issue close after cleanup so normal window
            # teardown runs once the background slots are inactive.
            self._close_after_background_tasks = False
            self.close()

    def _handle_scene_finished(self: MainWindow) -> None:
        was_browse_mode = self._browse_mode
        was_split_view = self.viewer.is_split_view()
        self._show_progress('Scene detection finished', 100)
        self._clear_scene_history()
        self._populate_thumbnail_list()
        self._populate_browse_list()
        self._populate_scene_list()
        self._hide_progress()
        if was_browse_mode:
            self._set_browse_mode(active=False)
            self._select_left_item_for_current_photo(suppress_signals=True)
            self._populate_scene_list()
            self.viewer.set_fit_view()
        elif not was_split_view:
            self.viewer.set_fit_view()

        self._refresh_ui()
        if self._compare_mode:
            self._show_transient_message(
                'Scene detection completed; you can view scenes outside'
                ' the Compare mode.',
                timeout_ms=TRANSIENT_MESSAGE_TIMEOUT_MS * 2,
            )

        self._restore_thumbnail_strip_focus(defer=True)

    def _handle_scene_failed(self: MainWindow, error: str) -> None:
        self._hide_progress()
        QMessageBox.critical(self, 'Scene Detection Failed', error)
        self.detect_button.setEnabled(bool(self.library.photos))

    def _clear_scene_worker(self: MainWindow) -> None:
        self._scene_thread = None
        self._scene_worker = None
        self.detect_button.setEnabled(bool(self.library.photos))
        self._refresh_ui()
        self._restore_thumbnail_strip_focus(defer=True)

    def _handle_operation_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        self._show_progress(message, progress)

    def _handle_operation_finished(self: MainWindow, summary: object) -> None:
        if self._operation_kind == 'undo':
            self._handle_undo_finished()
            return

        assert isinstance(summary, OperationSummary)
        request = self._organizer_request
        try:
            if (
                request is not None
                and request.mode == 'reorganize'
                and request.organize_options is not None
                and request.organize_options.action == 'move'
            ):
                self._reload_current_folder_after_move()
        except Exception as exc:  # noqa: BLE001 - surface unexpected reload errors in the UI
            self._hide_progress()
            self._organizer_request = None
            QMessageBox.critical(
                self,
                'Folder Reload Failed',
                'File organization completed, but the folder could not be'
                f' reloaded:\n{exc}',
            )
            return

        self._hide_progress()
        self._refresh_ui()
        should_undo = self._show_operation_finished_dialog(summary, request)
        self._organizer_request = None
        self._operation_kind = None
        self._operation_thread = None
        self._operation_worker = None
        if should_undo and summary.undo_plan is not None:
            self._start_undo_operation(summary.undo_plan)
            return

        self._restore_active_navigation_focus(defer=True)

    def _handle_operation_failed(self: MainWindow, error: str) -> None:
        self._hide_progress()
        operation_kind = self._operation_kind
        request = self._organizer_request
        self._operation_kind = None
        self._organizer_request = None
        if operation_kind == 'undo':
            title = 'Undo Failed'
        else:
            title = (
                'Write XMP Failed'
                if request is not None and request.mode == 'xmp'
                else 'Organize Photos Failed'
            )

        QMessageBox.critical(self, title, error)

    def _clear_operation_worker(
            self: MainWindow,
            finished_thread: QThread | None,
            finished_worker: OperationWorker | None,
    ) -> None:
        if self._operation_thread is finished_thread:
            self._operation_thread = None

        if self._operation_worker is finished_worker:
            self._operation_worker = None

        self._refresh_ui()

    def _show_operation_finished_dialog(
            self: MainWindow,
            summary: OperationSummary,
            request: OrganizerDialogResult | None,
    ) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Photo Organization Finished')
        dialog.setText('Photo Organization Finished')
        dialog.setInformativeText(
            self._operation_finished_message(summary, request)
        )
        undo_button = dialog.addButton(
            'Undo', QMessageBox.ButtonRole.ActionRole
        )
        close_button = dialog.addButton(QMessageBox.StandardButton.Close)
        dialog.setDefaultButton(close_button)
        dialog.exec()
        return dialog.clickedButton() is undo_button

    @staticmethod
    def _operation_finished_message(
            summary: OperationSummary,
            request: OrganizerDialogResult | None,
    ) -> str:
        if request is not None and request.mode == 'xmp':
            return (
                f'Processed photos: {summary.processed_photos}\n'
                f'Wrote sidecars: {summary.written_sidecars}\n'
                f'Skipped photos: {summary.skipped_photos}'
            )

        return (
            f'Processed photos: {summary.processed_photos}\n'
            f'Copied files: {summary.copied_files}\n'
            f'Moved files: {summary.moved_files}\n'
            f'Skipped photos: {summary.skipped_photos}'
        )

    def _handle_undo_finished(self: MainWindow) -> None:
        try:
            self._reload_current_folder_after_undo()
        except Exception as exc:  # noqa: BLE001 - surface unexpected reload errors in the UI
            self._hide_progress()
            self._operation_kind = None
            QMessageBox.critical(
                self,
                'Folder Reload Failed',
                'Undo completed, but the folder could not be reloaded:\n'
                f'{exc}',
            )
            return

        self._hide_progress()
        self._refresh_ui()
        self._operation_kind = None
        QMessageBox.information(
            self,
            'Undo Complete',
            'The last photo organization operation was undone.',
        )
        self._restore_active_navigation_focus(defer=True)

    def _reload_current_folder_after_move(self: MainWindow) -> None:
        current_folder = self.library.current_folder
        if current_folder is None:
            return

        self.library.load_folder(
            current_folder, progress_callback=self._handle_load_progress
        )
        self._rebuild_loaded_views(show_progress=True)
        self._clear_metadata_history()

    def _reload_current_folder_after_undo(self: MainWindow) -> None:
        current_folder = self.library.current_folder
        if current_folder is None:
            return

        self.library.load_folder(
            current_folder, progress_callback=self._handle_load_progress
        )
        self._rebuild_loaded_views(show_progress=True)
        self._clear_metadata_history()

    def _rebuild_loaded_views(
            self: MainWindow,
            *,
            show_progress: bool = False,
            preserve_current_photo: bool = False,
    ) -> None:
        if not self.library.photos and self._browse_mode:
            self._set_browse_mode(active=False)

        preserved_photo_id = (
            self.current_photo_id if preserve_current_photo else None
        )
        loaded_photo_ids = {photo.photo_id for photo in self.library.photos}
        self.current_photo_id = (
            preserved_photo_id
            if preserved_photo_id in loaded_photo_ids
            else self.library.photos[0].photo_id
            if self.library.photos
            else None
        )
        self._populate_thumbnail_list(show_progress=show_progress)
        self._populate_browse_list(show_progress=show_progress)
        self._populate_scene_list()
        self._display_current_photo()
        self._refresh_ui()
        self._update_mode_shortcuts()
        if self._browse_mode:
            self._select_browse_item_for_current_photo()

    def _show_progress(
            self: MainWindow,
            message: str,
            progress: int,
            *,
            show_bar: bool = True,
    ) -> None:
        # Loading workflows use a two-phase progress scale:
        # 0..100 covers the primary library operation, and 101..200 covers
        # follow-up preview generation while the same progress UI remains open.
        max_value = (
            LOAD_AND_PREVIEW_PROGRESS_MAX
            if progress > LOAD_PROGRESS_MAX
            else LOAD_PROGRESS_MAX
        )
        self._set_interaction_enabled(enabled=False)
        self._busy = True
        self.progress_overlay.show()
        self.progress_overlay.raise_()
        self.overlay_message_label.setText(message)
        self.overlay_progress_bar.setVisible(show_bar)
        self.overlay_progress_bar.setRange(0, max_value)
        self.overlay_progress_bar.setValue(max(0, min(max_value, progress)))
        self._update_progress_overlay_geometry()
        self._refresh_info_overlay()
        QApplication.processEvents()

    def _hide_progress(self: MainWindow) -> None:
        self.progress_overlay.hide()
        self.overlay_progress_bar.setVisible(True)
        self.overlay_progress_bar.setRange(0, 100)
        self.overlay_progress_bar.setValue(0)
        self.overlay_message_label.setText('')
        self._busy = False
        self._set_interaction_enabled(enabled=True)
        self._refresh_info_overlay()

    def _handle_load_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        self._show_progress(message, progress)

    def _set_rating(self: MainWindow, rating: int | None) -> None:
        if getattr(self, '_photo_viewer_mode', False):
            return

        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('rating', rating)
            return

        self.library.update_metadata(
            self.current_photo_id, rating=rating, fields={'rating'}
        )
        self.library.save_metadata()
        self._after_metadata_change()

    def _set_color_label(self: MainWindow, color_label: str | None) -> None:
        if getattr(self, '_photo_viewer_mode', False):
            return

        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('color_label', color_label)
            return

        self.library.update_metadata(
            self.current_photo_id,
            color_label=color_label,
            fields={'color_label'},
        )
        self.library.save_metadata()
        self._after_metadata_change()

    def _set_flag(self: MainWindow, flag: str | None) -> None:
        if getattr(self, '_photo_viewer_mode', False):
            return

        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('flag', flag)
            return

        self.library.update_metadata(
            self.current_photo_id, flag=flag, fields={'flag'}
        )
        self.library.save_metadata()
        self._after_metadata_change()

    def _apply_metadata_to_selection(
            self: MainWindow, field: str, value: Any
    ) -> None:
        if self.current_photo_id is None:
            return

        if not hasattr(self.library, 'get_photo'):
            self.library.update_metadata(
                self.current_photo_id,
                fields={field},
                **{field: value},
            )
            self.library.save_metadata()
            self._after_metadata_change()
            return

        photo_ids = self._resolved_selection_photo_ids()
        if not photo_ids:
            return

        before = {
            photo_id: getattr(self.library.get_photo(photo_id), field)
            for photo_id in photo_ids
        }
        after = dict.fromkeys(photo_ids, value)
        if before == after:
            return

        self._apply_metadata_values(field, after)
        self._metadata_undo_stack.append(
            MetadataEdit(field=field, before=before, after=after)
        )
        self._metadata_redo_stack.clear()
        self.library.save_metadata()
        self._after_metadata_change()
        self._refresh_metadata_history_actions()

    def _undo_metadata_edit(self: MainWindow) -> None:
        if self._busy or not self._metadata_undo_stack:
            return

        edit = self._metadata_undo_stack.pop()
        if isinstance(edit, SceneEdit):
            self._apply_scene_state(edit.before_groups, edit.before_source)
            self._metadata_redo_stack.append(edit)
            self.library.save_metadata()
            self._after_scene_change()
            self._refresh_metadata_history_actions()
            return

        self._apply_metadata_values(edit.field, edit.before)
        self._metadata_redo_stack.append(edit)
        self.library.save_metadata()
        self._after_metadata_change()
        self._refresh_metadata_history_actions()

    def _redo_metadata_edit(self: MainWindow) -> None:
        if self._busy or not self._metadata_redo_stack:
            return

        edit = self._metadata_redo_stack.pop()
        if isinstance(edit, SceneEdit):
            self._apply_scene_state(edit.after_groups, edit.after_source)
            self._metadata_undo_stack.append(edit)
            self.library.save_metadata()
            self._after_scene_change()
            self._refresh_metadata_history_actions()
            return

        self._apply_metadata_values(edit.field, edit.after)
        self._metadata_undo_stack.append(edit)
        self.library.save_metadata()
        self._after_metadata_change()
        self._refresh_metadata_history_actions()

    def _apply_metadata_values(
            self: MainWindow, field: str, values: dict[str, Any]
    ) -> None:
        for photo_id, value in values.items():
            self.library.update_metadata(
                photo_id,
                fields={field},
                **{field: value},
            )

    def _clear_metadata_history(self: MainWindow) -> None:
        self._metadata_undo_stack.clear()
        self._metadata_redo_stack.clear()
        self._refresh_metadata_history_actions()

    def _clear_scene_history(self: MainWindow) -> None:
        """
        Remove scene merge/break undo records after scene detection reruns.

        Those records contain full old scene layouts. Once detection replaces
        the scene list, applying an older scene edit would overwrite the new
        detected groups.
        """
        self._metadata_undo_stack = [
            edit
            for edit in self._metadata_undo_stack
            if not isinstance(edit, SceneEdit)
        ]
        self._metadata_redo_stack = [
            edit
            for edit in self._metadata_redo_stack
            if not isinstance(edit, SceneEdit)
        ]
        self._refresh_metadata_history_actions()

    def _show_thumbnail_context_menu(
            self: MainWindow, position: QPoint
    ) -> None:
        scene = self._context_scene_from_thumbnail_position(position)
        if scene is None:
            return

        menu = QMenu(self)
        action = menu.addAction('Break Scene into Single Photos')
        action.triggered.connect(
            lambda *_: self._break_scene_into_singletons(scene.scene_id)
        )
        menu.exec(self.thumbnail_list.viewport().mapToGlobal(position))

    def _show_scene_context_menu(self: MainWindow, position: QPoint) -> None:
        scene = self._context_scene_from_scene_strip()
        if scene is None:
            return

        menu = QMenu(self)
        action = menu.addAction('Break Scene into Single Photos')
        action.triggered.connect(
            lambda *_: self._break_scene_into_singletons(scene.scene_id)
        )
        menu.exec(self.scene_list.viewport().mapToGlobal(position))

    def _context_scene_from_thumbnail_position(
            self: MainWindow, position: QPoint
    ) -> SceneGroup | None:
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or not self.library.scene_detection_done
        ):
            return None

        item = self.thumbnail_list.itemAt(position)
        if item is None:
            return None

        photo_id = item.data(PHOTO_ID_ROLE)
        if photo_id is None:
            return None

        scene = self._scene_for_photo_id(str(photo_id))
        if scene is None or len(scene.photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return None

        return scene

    def _context_scene_from_scene_strip(self: MainWindow) -> SceneGroup | None:
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or not self.library.scene_detection_done
            or not self.scene_list.isVisible()
        ):
            return None

        scene = self._current_scene()
        if scene is None or len(scene.photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return None

        return scene

    def _break_scene_into_singletons(self: MainWindow, scene_id: str) -> None:
        if self._busy or self._compare_mode:
            return

        scene = self._scene_by_id.get(scene_id)
        if scene is None or len(scene.photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return

        if not self._confirm_break_scene():
            return

        before_groups = self.library.scene_group_photo_ids()
        before_source = self.library.scene_source
        after_groups: list[list[str]] = []
        for existing_scene in self.library.scenes:
            if existing_scene.scene_id == scene_id:
                after_groups.extend(
                    [photo_id] for photo_id in existing_scene.photo_ids
                )
            else:
                after_groups.append(list(existing_scene.photo_ids))

        if before_groups == after_groups:
            return

        self.library.set_scene_group_photo_ids(
            after_groups,
            scene_source='manual',
        )
        after_source = self.library.scene_source
        self._metadata_undo_stack.append(
            SceneEdit(
                before_groups=before_groups,
                before_source=before_source,
                after_groups=after_groups,
                after_source=after_source,
            )
        )
        self._metadata_redo_stack.clear()
        self.library.save_metadata()
        self._after_scene_change(selected_photo_ids=[scene.photo_ids[0]])
        self._refresh_metadata_history_actions()

    def _confirm_break_scene(self: MainWindow) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Break Scene?')
        dialog.setText('Break this scene into individual photos?')
        dialog.setInformativeText('You can press Ctrl+Z to undo this action.')
        break_button = dialog.addButton(
            'Break Scene', QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        return dialog.clickedButton() is break_button

    def _merge_selected_photos_into_scene(self: MainWindow) -> None:
        if self._busy or self._compare_mode:
            return

        photo_ids = self._mergeable_scene_photo_ids()
        if len(photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return

        if self._is_scene_strip_subset_merge():
            self._show_transient_message(
                'Cannot split an existing scene group.\n'
                'Press Ctrl+Z to undo and group again.',
                timeout_ms=TRANSIENT_MESSAGE_TIMEOUT_MS,
            )
            return

        thumbnail_anchor = self._capture_thumbnail_scroll_anchor(photo_ids[0])
        before_groups = self.library.scene_group_photo_ids()
        before_source = self.library.scene_source
        self.library.merge_photos_into_scene(photo_ids)
        after_groups = self.library.scene_group_photo_ids()
        after_source = self.library.scene_source
        if before_groups == after_groups and before_source == after_source:
            return

        self._metadata_undo_stack.append(
            SceneEdit(
                before_groups=before_groups,
                before_source=before_source,
                after_groups=after_groups,
                after_source=after_source,
            )
        )
        self._metadata_redo_stack.clear()
        self.library.save_metadata()
        self._after_scene_change(
            selected_photo_ids=photo_ids,
            thumbnail_anchor=thumbnail_anchor,
        )
        self._refresh_metadata_history_actions()

    def _mergeable_scene_photo_ids(self: MainWindow) -> list[str]:
        """
        Return the photos that the scene merge action should operate on.

        Scene mode has two live selection surfaces. The vertical thumbnail
        strip selects whole scene stacks for merge, while the horizontal scene
        strip selects exact in-scene photos so users can reject partial-scene
        merges that would otherwise imply a split.
        """
        if self._compare_mode:
            return []

        if not self.library.scene_detection_done or self._browse_mode:
            return self._resolved_selection_photo_ids()

        selection_source = self._scene_merge_selection_source
        if selection_source == 'thumbnail':
            return self._selected_scene_stack_photo_ids()

        if selection_source == 'scene':
            return self._mergeable_scene_strip_photo_ids()

        focus_widget = QApplication.focusWidget()
        if focus_widget in {
            self.thumbnail_list,
            self.thumbnail_list.viewport(),
        }:
            return self._selected_scene_stack_photo_ids()

        if focus_widget in {
            self.scene_list,
            self.scene_list.viewport(),
        }:
            return self._mergeable_scene_strip_photo_ids()

        thumbnail_selection_count = len(self.thumbnail_list.selectedItems())
        scene_selection_count = len(self.scene_list.selectedItems())

        if thumbnail_selection_count >= MIN_SCENE_MERGE_PHOTO_COUNT:
            return self._selected_scene_stack_photo_ids()

        if scene_selection_count >= MIN_SCENE_MERGE_PHOTO_COUNT:
            return self._mergeable_scene_strip_photo_ids()

        if thumbnail_selection_count > 0:
            return self._selected_scene_stack_photo_ids()

        if scene_selection_count > 0:
            return self._mergeable_scene_strip_photo_ids()

        return []

    def _mergeable_scene_strip_photo_ids(self: MainWindow) -> list[str]:
        """
        Resolve merge ids when the horizontal scene strip was active.

        A partial scene-strip selection is handled by
        ``_is_scene_strip_subset_merge`` and blocked as an attempted split. A
        full scene-strip selection means "include this whole scene"; in that
        case we also include any selected vertical stacks so users can merge a
        complete existing scene with other scene rows.
        """
        scene_photo_ids = self._photo_ids_in_library_order(
            self._selected_photo_ids_from_list(self.scene_list)
        )
        current_scene = self._current_scene()
        if current_scene is None:
            return scene_photo_ids

        if set(scene_photo_ids) != set(current_scene.photo_ids):
            return scene_photo_ids

        photo_ids = self._selected_scene_stack_photo_ids()
        photo_ids.extend(scene_photo_ids)
        return self._photo_ids_in_library_order(photo_ids)

    def _is_scene_strip_subset_merge(self: MainWindow) -> bool:
        """
        Return True when a scene-strip merge would split a scene.

        The check intentionally looks only at the horizontal strip selection.
        Vertical selections may be present at the same time, but they should
        not turn a partial in-scene selection into a valid merge because the
        selected scene would have to be split first.
        """
        if (
            self._browse_mode
            or not self.library.scene_detection_done
            or self._scene_merge_selection_source != 'scene'
        ):
            return False

        current_scene = self._current_scene()
        if current_scene is None:
            return False

        selected = set(self._selected_photo_ids_from_list(self.scene_list))
        scene_photo_ids = set(current_scene.photo_ids)
        return selected < scene_photo_ids

    def _selected_scene_stack_photo_ids(self: MainWindow) -> list[str]:
        selected_items = sorted(
            self.thumbnail_list.selectedItems(),
            key=self.thumbnail_list.row,
        )
        if (
            not selected_items
            and self.thumbnail_list.currentItem() is not None
        ):
            selected_items = [self.thumbnail_list.currentItem()]

        photo_ids: list[str] = []
        for item in selected_items:
            cover_photo_id = item.data(PHOTO_ID_ROLE)
            if cover_photo_id is None:
                continue

            scene = self._scene_for_photo_id(str(cover_photo_id))
            if scene is None:
                photo_ids.append(str(cover_photo_id))
                continue

            photo_ids.extend(scene.photo_ids)

        return self._photo_ids_in_library_order(photo_ids)

    def _apply_scene_state(
            self: MainWindow,
            groups: list[list[str]],
            scene_source: str | None,
    ) -> None:
        self.library.set_scene_group_photo_ids(
            groups, scene_source=scene_source
        )

    def _refresh_metadata_history_actions(self: MainWindow) -> None:
        enabled = not self._busy and self.menuBar().isEnabled()
        if hasattr(self, 'undo_metadata_action'):
            self.undo_metadata_action.setEnabled(
                enabled and bool(self._metadata_undo_stack)
            )

        if hasattr(self, 'redo_metadata_action'):
            self.redo_metadata_action.setEnabled(
                enabled and bool(self._metadata_redo_stack)
            )

        if hasattr(self, 'merge_scene_action'):
            self.merge_scene_action.setEnabled(
                enabled
                and bool(self.library.photos)
                and not self._compare_mode
            )

    def _after_metadata_change(self: MainWindow) -> None:
        scroll_states = {
            self.thumbnail_list: self._capture_scroll_state(
                self.thumbnail_list
            ),
            self.browse_list: self._capture_scroll_state(self.browse_list),
            self.scene_list: self._capture_scroll_state(self.scene_list),
        }
        selection_states = {
            self.thumbnail_list: self._capture_selected_item_ids(
                self.thumbnail_list
            ),
            self.browse_list: self._capture_selected_item_ids(
                self.browse_list
            ),
            self.scene_list: self._capture_selected_item_ids(self.scene_list),
        }
        self._populate_thumbnail_list(scroll_current_item_into_view=False)
        self._populate_browse_list(scroll_current_item_into_view=False)
        self._populate_scene_list()
        for list_widget, selected_ids in selection_states.items():
            if len(selected_ids) >= MIN_SCENE_MERGE_PHOTO_COUNT:
                self._restore_selected_item_ids(list_widget, selected_ids)

        for list_widget, scroll_state in scroll_states.items():
            self._restore_scroll_state(list_widget, scroll_state)

        self._refresh_compare_metadata_labels()
        self._refresh_ui()

    def _after_scene_change(
            self: MainWindow,
            selected_photo_ids: list[str] | None = None,
            thumbnail_anchor: ThumbnailScrollAnchor | None = None,
    ) -> None:
        """
        Rebuild the thumbnail, browse, and scene lists after scene edits.

        Scene merge, break, undo, and redo can change which rows exist in each
        list. After rebuilding, keep the intended current photo selected and
        return keyboard focus to the visible navigation list.
        """
        self._preserved_scene_selection_photo_ids.clear()
        if selected_photo_ids:
            self.current_photo_id = selected_photo_ids[0]

        self._populate_thumbnail_list(scroll_current_item_into_view=False)
        self._populate_browse_list(scroll_current_item_into_view=False)
        self._populate_scene_list()
        if thumbnail_anchor is not None:
            self._restore_thumbnail_scroll_anchor(thumbnail_anchor)

        self._scene_merge_selection_source = (
            'browse' if self._browse_mode else 'thumbnail'
        )
        self._refresh_ui()
        self._restore_active_navigation_focus()
        self._restore_active_navigation_focus(defer=True)

    def _set_interaction_enabled(self: MainWindow, *, enabled: bool) -> None:
        photo_actions_enabled = (
            enabled
            and not self._background_task_active()
            and bool(self.library.photos)
        )
        self.open_button.setEnabled(enabled)
        self.detect_button.setEnabled(photo_actions_enabled)
        self.organize_button.setEnabled(photo_actions_enabled)
        self.theme_toggle.setEnabled(enabled)
        self.show_af_point_toggle.setEnabled(enabled)
        for button in self.photo_sort_buttons.values():
            button.setEnabled(enabled)

        self.photo_sort_reverse_checkbox.setEnabled(enabled)
        self.thumbnail_list.setEnabled(enabled)
        self.browse_list.setEnabled(enabled)
        self.scene_list.setEnabled(enabled)
        self.compare_viewer.setEnabled(enabled)
        self.menuBar().setEnabled(enabled)
        if hasattr(self, 'open_action'):
            self.open_action.setEnabled(enabled)

        if hasattr(self, 'detect_action'):
            self.detect_action.setEnabled(photo_actions_enabled)

        if hasattr(self, 'organize_action'):
            self.organize_action.setEnabled(photo_actions_enabled)

        if hasattr(self, 'merge_scene_action'):
            self.merge_scene_action.setEnabled(
                photo_actions_enabled and not self._compare_mode
            )

        for action in self._assignment_actions:
            action.setEnabled(enabled and not self._photo_viewer_mode)

        for shortcut in self._assignment_shortcuts:
            shortcut.setEnabled(enabled and not self._photo_viewer_mode)

        self._refresh_metadata_history_actions()

    @staticmethod
    def _capture_scroll_state(
            list_widget: QListWidget,
    ) -> tuple[int, int]:
        return (
            list_widget.horizontalScrollBar().value(),
            list_widget.verticalScrollBar().value(),
        )

    @staticmethod
    def _restore_scroll_state(
            list_widget: QListWidget, scroll_state: tuple[int, int]
    ) -> None:
        horizontal, vertical = scroll_state
        horizontal_bar = list_widget.horizontalScrollBar()
        vertical_bar = list_widget.verticalScrollBar()
        horizontal_bar.setValue(min(horizontal, horizontal_bar.maximum()))
        vertical_bar.setValue(min(vertical, vertical_bar.maximum()))

    def _capture_thumbnail_scroll_anchor(
            self: MainWindow, photo_id: str
    ) -> ThumbnailScrollAnchor | None:
        row = self._thumbnail_row_for_photo(photo_id)
        if row is None:
            return None

        item = self.thumbnail_list.item(row)
        if item is None:
            return None

        rect = self.thumbnail_list.visualItemRect(item)
        if self.thumbnail_list.viewport().rect().intersects(rect):
            return ThumbnailScrollAnchor(
                photo_id=photo_id,
                visible_top=rect.top(),
            )

        return ThumbnailScrollAnchor(photo_id=photo_id, visible_top=None)

    def _restore_thumbnail_scroll_anchor(
            self: MainWindow, anchor: ThumbnailScrollAnchor
    ) -> None:
        row = self._thumbnail_row_for_photo(anchor.photo_id)
        if row is None:
            return

        item = self.thumbnail_list.item(row)
        if item is None:
            return

        if anchor.visible_top is None:
            self.thumbnail_list.scrollToItem(
                item,
                QAbstractItemView.ScrollHint.PositionAtTop,
            )
            return

        rect = self.thumbnail_list.visualItemRect(item)
        vertical_bar = self.thumbnail_list.verticalScrollBar()
        vertical_bar.setValue(
            max(
                0,
                min(
                    vertical_bar.value() + rect.top() - anchor.visible_top,
                    vertical_bar.maximum(),
                ),
            )
        )

    @staticmethod
    def _capture_selected_item_ids(list_widget: QListWidget) -> set[str]:
        selected_ids: set[str] = set()
        for item in list_widget.selectedItems():
            photo_id = item.data(PHOTO_ID_ROLE)
            if photo_id is not None:
                selected_ids.add(str(photo_id))

        return selected_ids

    @staticmethod
    def _restore_selected_item_ids(
            list_widget: QListWidget, selected_ids: set[str]
    ) -> None:
        if not selected_ids:
            return

        list_widget.blockSignals(True)
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            if item is not None:
                item.setSelected(str(item.data(PHOTO_ID_ROLE)) in selected_ids)

        list_widget.blockSignals(False)
