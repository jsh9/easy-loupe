"""Long-running workflows, busy-state handling, and metadata actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QPoint, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileDialog,
    QListWidget,
    QMenu,
    QMessageBox,
)

from easy_loupe.core.folder_loading import FOLDER_LOAD_PROGRESS_STAGES
from easy_loupe.operations.common import (
    OperationSummary,
    UndoPlan,
    undo_operation,
)
from easy_loupe.operations.export import organize_photos
from easy_loupe.operations.xmp import write_xmp_sidecars
from easy_loupe.progress import (
    ProgressReporter,
    ProgressSnapshot,
    ProgressStageDefinition,
    StructuredProgressCallback,
)
from easy_loupe.ui.main_window.build import (
    MIN_SCENE_MERGE_PHOTO_COUNT,
    TRANSIENT_MESSAGE_TIMEOUT_MS,
)
from easy_loupe.ui.main_window.dialogs import (
    OrganizerDialog,
    OrganizerDialogResult,
)
from easy_loupe.ui.theme import (
    LOAD_AND_PREVIEW_PROGRESS_MAX,
    LOAD_PROGRESS_MAX,
    PHOTO_ID_ROLE,
)
from easy_loupe.ui.workers import OperationWorker, SceneDetectionWorker

if TYPE_CHECKING:
    from easy_loupe.core.records import SceneGroup
    from easy_loupe.ui.launch import CullingLaunchRequest
    from easy_loupe.ui.main_window.window import MainWindow

ProgressCallback = Callable[[str, int], None]
LOAD_WORKFLOW_PROGRESS_STAGES = (
    *FOLDER_LOAD_PROGRESS_STAGES,
    ProgressStageDefinition('thumbnails', 'Preparing thumbnails'),
    ProgressStageDefinition('browse', 'Preparing browse grid'),
)
FILTERED_SCENE_MERGE_WARNING_TEXT = (
    'Some photos in the selected scene range are hidden by the current '
    'filter. If you continue, those hidden photos will be included in the '
    'merged scene.'
)
MERGE_REQUIRES_SELECTION_MESSAGE = (
    'Select at least two visible photos or scene stacks to merge.\n'
    'Press Esc to exit.'
)
FILTERED_SCENE_MERGE_REQUIRES_RANGE_MESSAGE = (
    'The current selection skips visible photos. When filtering is active, '
    'manual merging is only allowed when you select a continuous visible '
    'range.\n\n'
    'Press Esc to exit.'
)
BREAK_SCENE_FILTER_ACTIVE_MESSAGE = (
    'Breaking scenes is not allowed when filtering is active. To manually '
    'break scenes, please first turn off filtering.\n\n'
    'Press Esc to exit.'
)


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

        reporter = self._folder_load_progress_reporter()
        try:
            reporter.start_stage(
                'scan', message='Scanning folder', overall_progress=0
            )
            if self._closing:
                self._hide_progress()
                return

            self.open_button.setEnabled(False)
            self.detect_button.setEnabled(False)
            self.library.load_folder(Path(folder), progress_reporter=reporter)
            if self._closing:
                self._hide_progress()
                return

            self._reset_photo_filter_selection()
            # Rebuilding can generate previews and re-enter Qt through progress
            # events. Keep it inside this try block so failure after Quit still
            # clears `_busy` through the shared error cleanup.
            self._rebuild_loaded_views(
                show_progress=True, progress_reporter=reporter
            )
            if self._closing:
                self._hide_progress()
                return
        except Exception as exc:  # noqa: BLE001 - surface unexpected load errors in the UI
            self._hide_progress()
            if self._closing:
                return

            self.open_button.setEnabled(True)
            self.detect_button.setEnabled(bool(self.library.photos))
            QMessageBox.critical(self, 'Failed to Open Folder', str(exc))
            return

        self._clear_metadata_history()
        self._hide_progress()
        self._set_main_view_frozen_after_move_organize(frozen=False)
        self.open_button.setEnabled(True)
        self._refresh_ui()
        self._restore_active_navigation_focus(defer=True)
        # Show this only after the loaded-empty UI is fully restored. That
        # keeps the modal dialog from interrupting progress cleanup or leaving
        # controls in a transient disabled state while the user dismisses it.
        if not self.library.photos:
            self._show_no_eligible_photos_dialog()

    def _show_no_eligible_photos_dialog(self: MainWindow) -> None:
        """Tell the user the selected folder contained no loadable photos."""
        QMessageBox.information(
            self,
            'No Eligible Photos',
            'No supported photos were found in the selected folder.',
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )

    def load_culling_launch_request(
            self: MainWindow, request: CullingLaunchRequest
    ) -> None:
        """Load a culling workspace requested by a photo-viewer handoff."""
        load_recursively = self._load_photo_load_recursively()
        if request.preloaded_library is not None:
            self.library = request.preloaded_library
            self.library.set_load_recursively(load_recursively)
        else:
            self.library.set_load_recursively(load_recursively)
            self.library.load_folder(request.folder)

        # Handoff may reuse a hydrated photo-viewer library, whose order is
        # filename-only. Culling mode owns the persisted sort controls, so
        # reapply them before rebuilding any lists from the handed-off state.
        self.library.set_sort_order(
            sort_mode=self._load_photo_sort_mode(),
            sort_reversed=self._load_photo_sort_reversed(),
        )
        self._check_photo_sort_control(self.library.sort_mode)
        self._check_photo_sort_reverse_control(self.library.sort_reversed)
        self._check_photo_load_recursively_control(
            self.library.load_recursively
        )
        self._reset_photo_filter_selection()
        loaded_photo_ids = {photo.photo_id for photo in self.library.photos}
        self.current_photo_id = (
            request.selected_photo_id
            if request.selected_photo_id in loaded_photo_ids
            else self.library.photos[0].photo_id
            if self.library.photos
            else None
        )
        self._initial_folder_prompt_pending = False
        self._initial_folder_prompt_timer.stop()
        self._rebuild_loaded_views(preserve_current_photo=True)
        self._clear_metadata_history()
        self._set_main_view_frozen_after_move_organize(frozen=False)
        if request.enter_browse and self.library.photos:
            self._enter_browse_mode()

        self._restore_active_navigation_focus(defer=True)

    def detect_scenes(self: MainWindow) -> None:
        """Start asynchronous scene detection for the loaded photo set."""
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
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
        if self._closing:
            self._hide_progress()
            return

        self._scene_thread = QThread(self)
        self._scene_worker = SceneDetectionWorker(self.library)
        self._scene_worker.moveToThread(self._scene_thread)
        self._scene_thread.started.connect(self._scene_worker.run)
        # Structured reporters emit both signals; legacy-only workers still
        # need scalar progress so overlays are not stuck at "Preparing".
        self._scene_worker.progress.connect(self._handle_scene_progress)
        self._scene_worker.progress_snapshot.connect(
            self._handle_scene_progress_snapshot
        )
        self._scene_worker.finished.connect(self._handle_scene_finished)
        self._scene_worker.failed.connect(self._handle_scene_failed)
        self._scene_worker.finished.connect(self._scene_thread.quit)
        self._scene_worker.failed.connect(self._scene_thread.quit)
        self._scene_worker.finished.connect(self._scene_worker.deleteLater)
        self._scene_worker.failed.connect(self._scene_worker.deleteLater)
        self._scene_thread.finished.connect(self._scene_thread.deleteLater)
        # Capture this exact pair so cleanup ignores stale callbacks if a
        # future replacement path starts another scene worker first. Retain
        # the pair until the QThread QObject, not only its native thread, has
        # reached terminal destruction.
        finished_thread = self._scene_thread
        finished_worker = self._scene_worker
        self._scene_thread.destroyed.connect(
            lambda _object=None: self._clear_scene_worker(
                finished_thread, finished_worker
            )
        )
        self._scene_thread.start()

    def open_organizer_dialog(self: MainWindow) -> None:
        """Prompt for organizer options and start the selected workflow."""
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or not self.library.photos
        ):
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
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or self.library.current_folder is None
        ):
            return

        self._operation_kind = 'run'
        self._organizer_request = request
        self._show_progress('Preparing organizer workflow...', 0)
        if self._closing:
            self._organizer_request = None
            self._operation_kind = None
            self._hide_progress()
            return

        self._operation_thread = QThread(self)

        def run_operation(
                progress_callback: ProgressCallback,
                progress_snapshot_callback: StructuredProgressCallback,
        ) -> object:
            return self._run_organizer_request(
                request,
                progress_callback,
                progress_snapshot_callback,
            )

        self._operation_worker = OperationWorker(run_operation)
        self._operation_worker.moveToThread(self._operation_thread)
        self._operation_thread.started.connect(self._operation_worker.run)
        # Keep scalar progress connected for legacy-only operation callables;
        # structured snapshots replace it when richer stage data is available.
        self._operation_worker.progress.connect(
            self._handle_operation_progress
        )
        self._operation_worker.progress_snapshot.connect(
            self._handle_operation_progress_snapshot
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
        self._operation_thread.destroyed.connect(
            lambda _object=None: self._clear_operation_worker(
                finished_thread, finished_worker
            )
        )
        self._operation_thread.start()

    def _run_organizer_request(
            self: MainWindow,
            request: OrganizerDialogResult,
            progress_callback: ProgressCallback,
            progress_snapshot_callback: StructuredProgressCallback | None = (
                None
            ),
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
                progress_snapshot_callback=progress_snapshot_callback,
            )

        assert request.xmp_options is not None
        return write_xmp_sidecars(
            current_folder,
            photos,
            request.xmp_options,
            progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )

    def _start_undo_operation(self: MainWindow, undo_plan: UndoPlan) -> None:
        if self._busy:
            return

        self._operation_kind = 'undo'
        self._show_progress('Preparing undo...', 0)
        if self._closing:
            self._operation_kind = None
            self._hide_progress()
            return

        self._operation_thread = QThread(self)

        def run_undo(
                progress_callback: ProgressCallback,
                progress_snapshot_callback: StructuredProgressCallback,
        ) -> None:
            undo_operation(
                undo_plan,
                progress_callback,
                progress_snapshot_callback=progress_snapshot_callback,
            )

        self._operation_worker = OperationWorker(run_undo)
        self._operation_worker.moveToThread(self._operation_thread)
        self._operation_thread.started.connect(self._operation_worker.run)
        # Keep scalar progress connected for legacy-only operation callables;
        # structured snapshots replace it when richer stage data is available.
        self._operation_worker.progress.connect(
            self._handle_operation_progress
        )
        self._operation_worker.progress_snapshot.connect(
            self._handle_operation_progress_snapshot
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
        self._operation_thread.destroyed.connect(
            lambda _object=None: self._clear_operation_worker(
                finished_thread, finished_worker
            )
        )
        self._operation_thread.start()

    def _handle_scene_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        if self._closing:
            return

        self._show_progress(message, progress)

    def _handle_scene_progress_snapshot(
            self: MainWindow, snapshot: ProgressSnapshot
    ) -> None:
        if self._closing:
            return

        self._show_progress_snapshot(snapshot)

    def _handle_scene_finished(self: MainWindow) -> None:
        if self._closing:
            return

        was_browse_mode = self._browse_mode
        was_split_view = self.viewer.is_split_view()
        # Structured scene progress already has its own per-stage rows.
        # Update only the message so the list rebuild below does not briefly
        # clear those rows with the legacy scalar progress UI.
        if self.progress_overlay_controller.has_structured_rows():
            self.progress_overlay_controller.set_message_preserving_rows(
                'Scene detection finished'
            )
            QApplication.processEvents()
        else:
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
        if self._closing:
            return

        self._hide_progress()
        QMessageBox.critical(self, 'Scene Detection Failed', error)
        self.detect_button.setEnabled(bool(self.library.photos))

    def _clear_scene_worker(
            self: MainWindow,
            finished_thread: QThread | None,
            finished_worker: SceneDetectionWorker | None,
    ) -> None:
        if (
            self._background_thread_slots.clear_if_current(
                'scene', finished_thread, finished_worker
            )
            and not self._closing
        ):
            self.detect_button.setEnabled(bool(self.library.photos))
            self._refresh_ui()
            self._restore_thumbnail_strip_focus(defer=True)

        self._finish_deferred_close_if_ready()

    def _handle_operation_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        if self._closing:
            return

        self._show_progress(message, progress)

    def _handle_operation_progress_snapshot(
            self: MainWindow, snapshot: ProgressSnapshot
    ) -> None:
        if self._closing:
            return

        self._show_progress_snapshot(snapshot)

    def _handle_operation_finished(self: MainWindow, summary: object) -> None:
        if self._closing:
            return

        if self._operation_kind == 'undo':
            self._handle_undo_finished()
            return

        assert isinstance(summary, OperationSummary)
        request = self._organizer_request
        should_freeze_after_move = self._organizer_request_moves_files(request)

        self._hide_progress()
        if should_freeze_after_move:
            # Move organization can invalidate the loaded photo paths. Freeze
            # before showing the finished dialog so dismissing it cannot return
            # focus to now-stale navigation or tagging controls.
            self._set_main_view_frozen_after_move_organize(frozen=True)

        self._refresh_ui()
        should_undo = self._show_operation_finished_dialog(summary, request)
        self._organizer_request = None
        self._operation_kind = None
        if should_undo and summary.undo_plan is not None:
            self._start_undo_operation(summary.undo_plan)
            return

        if not self._main_view_frozen_after_move_organize:
            self._restore_active_navigation_focus(defer=True)

    @staticmethod
    def _organizer_request_moves_files(
            request: OrganizerDialogResult | None,
    ) -> bool:
        """Return whether the organizer request moved source files."""
        return (
            request is not None
            and request.mode == 'reorganize'
            and request.organize_options is not None
            and request.organize_options.action == 'move'
        )

    def _handle_operation_failed(self: MainWindow, error: str) -> None:
        if self._closing:
            return

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
        if (
            self._background_thread_slots.clear_if_current(
                'operation', finished_thread, finished_worker
            )
            and not self._closing
        ):
            self._refresh_ui()

        self._finish_deferred_close_if_ready()

    def _stop_main_window_background_tasks(self: MainWindow) -> None:
        """Request safe shutdown without clearing stored thread slots."""
        self._background_thread_slots.request_shutdown_all()

    def _finish_deferred_close_if_ready(self: MainWindow) -> None:
        """Complete a close that was waiting for background tasks to finish."""
        if (
            self._close_after_background_tasks
            and not self._busy
            and not self._background_task_active()
        ):
            # Re-enter close only after destroyed callbacks have cleared every
            # active thread reference. This makes QObject destruction, rather
            # than native-thread completion, the terminal ownership boundary.
            self._close_after_background_tasks = False
            # Queue the final close so the current QThread.destroyed callback
            # can return before deleting the window that owns this cleanup.
            QTimer.singleShot(0, self.close)

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
            if self._closing:
                return

            QMessageBox.critical(
                self,
                'Folder Reload Failed',
                'Undo completed, but the folder could not be reloaded:\n'
                f'{exc}',
            )
            return

        self._hide_progress()
        if self._closing:
            self._operation_kind = None
            return

        self._set_main_view_frozen_after_move_organize(frozen=False)
        self._refresh_ui()
        self._operation_kind = None
        QMessageBox.information(
            self,
            'Undo Complete',
            'The last photo organization operation was undone.',
        )
        self._restore_active_navigation_focus(defer=True)

    def _reload_current_folder_after_undo(self: MainWindow) -> None:
        current_folder = self.library.current_folder
        if current_folder is None:
            return

        reporter = self._folder_load_progress_reporter()
        self.library.load_folder(current_folder, progress_reporter=reporter)
        self._reset_photo_filter_selection()
        self._rebuild_loaded_views(
            show_progress=True, progress_reporter=reporter
        )
        self._clear_metadata_history()

    def _reload_current_folder_after_recursive_preference_change(
            self: MainWindow, *, load_recursively: bool
    ) -> None:
        """
        Reload the current folder after the recursive preference changes.

        Parameters
        ----------
        self : MainWindow
            Main window whose loaded library and visible lists should be
            rebuilt.
        load_recursively : bool
            New recursive-loading preference to apply before scanning.

        Returns
        -------
        None
            The loaded library, current selection, list widgets, metadata
            history, and focus state are updated in place.
        """
        current_folder = self.library.current_folder
        if current_folder is None:
            self.library.set_load_recursively(load_recursively)
            return

        previous_photo_id = self.current_photo_id
        if self._compare_mode:
            # Compare mode owns a capped set of photo IDs from the old load.
            # Exit before reloading so stale compared panes are not restored
            # after the recursive setting changes the available photo set.
            self._exit_compare_mode(restore_previous=False)

        reporter = self._folder_load_progress_reporter()
        reporter.start_stage(
            'scan', message='Scanning folder', overall_progress=0
        )
        self.library.set_load_recursively(load_recursively)
        self.library.load_folder(current_folder, progress_reporter=reporter)
        self._reset_photo_filter_selection()
        loaded_photo_ids = {photo.photo_id for photo in self.library.photos}
        # Keep the user's photo when it still exists after the scan-mode
        # change; otherwise fall back to the first loaded photo so the rebuilt
        # lists and viewer never point at an unloaded ID.
        self.current_photo_id = (
            previous_photo_id
            if previous_photo_id in loaded_photo_ids
            else self.library.photos[0].photo_id
            if self.library.photos
            else None
        )
        self._rebuild_loaded_views(
            show_progress=True,
            preserve_current_photo=True,
            progress_reporter=reporter,
        )
        self._clear_metadata_history()
        self._hide_progress()
        if self._closing:
            return

        self._refresh_ui()
        self._restore_active_navigation_focus(defer=True)
        # Unlike cancel/failure paths, this is a successful reload that found
        # no eligible photos under the new direct-vs-recursive setting. Reuse
        # the normal empty-folder dialog so the blank UI has an explanation.
        if not self.library.photos:
            self._show_no_eligible_photos_dialog()

    def _rebuild_loaded_views(
            self: MainWindow,
            *,
            show_progress: bool = False,
            preserve_current_photo: bool = False,
            progress_reporter: ProgressReporter | None = None,
    ) -> None:
        if (not self.library.photos or not self._visible_photos()) and (
            self._browse_mode
        ):
            self._set_browse_mode(active=False)

        preserved_photo_id = (
            self.current_photo_id if preserve_current_photo else None
        )
        self.current_photo_id = self._visible_photo_id_after_filter(
            preserved_photo_id
        )
        self._populate_thumbnail_list(
            show_progress=show_progress,
            progress_reporter=progress_reporter,
        )
        self._populate_browse_list(
            show_progress=show_progress,
            progress_reporter=progress_reporter,
        )
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
        self.progress_overlay_controller.show_scalar(
            message,
            progress,
            max_value=max_value,
            show_bar=show_bar,
        )
        self._refresh_info_overlay()
        QApplication.processEvents()

    def _show_progress_snapshot(
            self: MainWindow, snapshot: ProgressSnapshot
    ) -> None:
        """Show a structured, multi-stage progress snapshot."""
        self._set_interaction_enabled(enabled=False)
        self._busy = True
        self.progress_overlay_controller.show_snapshot(snapshot)
        self._refresh_info_overlay()
        QApplication.processEvents()

    def _hide_progress(self: MainWindow) -> None:
        self.progress_overlay_controller.hide()
        self._busy = False
        if self._closing:
            self._finish_deferred_close_if_ready()
            return

        self._set_interaction_enabled(enabled=True)
        self._refresh_info_overlay()

    def _handle_load_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        self._show_progress(message, progress)

    def _handle_load_progress_snapshot(
            self: MainWindow, snapshot: ProgressSnapshot
    ) -> None:
        self._show_progress_snapshot(snapshot)

    def _folder_load_progress_reporter(self: MainWindow) -> ProgressReporter:
        """Return a reporter for folder loading plus list preparation."""
        return ProgressReporter(
            'Loading folder',
            LOAD_WORKFLOW_PROGRESS_STAGES,
            snapshot_callback=self._handle_load_progress_snapshot,
        )

    def _set_rating(self: MainWindow, rating: int | None) -> None:
        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('rating', rating)
            return

        self.library.update_metadata(
            self.current_photo_id, rating=rating, fields={'rating'}
        )
        self.library.save_metadata()
        self._after_metadata_change(
            [] if self.current_photo_id is None else [self.current_photo_id]
        )

    def _set_color_label(self: MainWindow, color_label: str | None) -> None:
        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('color_label', color_label)
            return

        self.library.update_metadata(
            self.current_photo_id,
            color_label=color_label,
            fields={'color_label'},
        )
        self.library.save_metadata()
        self._after_metadata_change(
            [] if self.current_photo_id is None else [self.current_photo_id]
        )

    def _set_flag(self: MainWindow, flag: str | None) -> None:
        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('flag', flag)
            return

        self.library.update_metadata(
            self.current_photo_id, flag=flag, fields={'flag'}
        )
        self.library.save_metadata()
        self._after_metadata_change(
            [] if self.current_photo_id is None else [self.current_photo_id]
        )

    def _apply_metadata_to_selection(
            self: MainWindow, field: str, value: Any
    ) -> None:
        if (
            self._main_view_frozen_after_move_organize
            or self.current_photo_id is None
        ):
            return

        if not hasattr(self.library, 'get_photo'):
            self.library.update_metadata(
                self.current_photo_id,
                fields={field},
                **{field: value},
            )
            self.library.save_metadata()
            self._after_metadata_change(
                []
                if self.current_photo_id is None
                else [self.current_photo_id]
            )
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
        self._after_metadata_change(photo_ids)
        self._refresh_metadata_history_actions()

    def _undo_metadata_edit(self: MainWindow) -> None:
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or not self._metadata_undo_stack
        ):
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
        self._after_metadata_change(list(edit.before))
        self._refresh_metadata_history_actions()

    def _redo_metadata_edit(self: MainWindow) -> None:
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or not self._metadata_redo_stack
        ):
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
        self._after_metadata_change(list(edit.after))
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
        # Check the filtered warning path before normal scene resolution
        # because that resolver intentionally hides all filtered scene edits.
        if self._filter_blocks_break_scene_from_thumbnail_position(position):
            return

        scene = self._context_scene_from_thumbnail_position(position)
        if scene is None:
            return

        menu = QMenu(self)
        action = menu.addAction('Break Scene into Single Photos')
        scene_id = str(scene.scene_id)
        selected_action = menu.exec(
            self.thumbnail_list.viewport().mapToGlobal(position)
        )
        if selected_action is action:
            # Run the scene rebuild after QMenu.exec has unwound. Rebuilding
            # while the native menu is dispatching the action can leave macOS
            # focus stale, leaving shortcuts inert until a mouse click.
            QTimer.singleShot(
                0, lambda: self._break_scene_into_singletons(scene_id)
            )

    def _show_scene_context_menu(self: MainWindow, position: QPoint) -> None:
        # Check the filtered warning path before normal scene resolution
        # because that resolver intentionally hides all filtered scene edits.
        if self._filter_blocks_break_scene_from_scene_strip(position):
            return

        scene = self._context_scene_from_scene_strip()
        if scene is None:
            return

        menu = QMenu(self)
        action = menu.addAction('Break Scene into Single Photos')
        scene_id = str(scene.scene_id)
        selected_action = menu.exec(
            self.scene_list.viewport().mapToGlobal(position)
        )
        if selected_action is action:
            # Run the scene rebuild after QMenu.exec has unwound. Rebuilding
            # while the native menu is dispatching the action can leave macOS
            # focus stale, leaving shortcuts inert until a mouse click.
            QTimer.singleShot(
                0, lambda: self._break_scene_into_singletons(scene_id)
            )

    def _context_scene_from_thumbnail_position(
            self: MainWindow, position: QPoint
    ) -> SceneGroup | None:
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or self._photo_filter_active()
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

    def _filter_blocks_break_scene_from_thumbnail_position(
            self: MainWindow, position: QPoint
    ) -> bool:
        """
        Warn when a filtered thumbnail right-click targets a breakable scene.

        The normal context-menu resolver suppresses filtered scene edits, so
        this path checks the clicked row first to turn that blocked edit into
        explicit user feedback without opening the break menu.
        """
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or not self._photo_filter_active()
            or not self.library.scene_detection_done
        ):
            return False

        item = self.thumbnail_list.itemAt(position)
        if item is None:
            return False

        photo_id = item.data(PHOTO_ID_ROLE)
        if photo_id is None:
            return False

        scene = self._breakable_library_scene_for_photo_id(str(photo_id))
        if scene is None:
            return False

        self._show_break_scene_filter_warning()
        return True

    def _context_scene_from_scene_strip(self: MainWindow) -> SceneGroup | None:
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or self._photo_filter_active()
            or not self.library.scene_detection_done
            or not self.scene_list.isVisible()
        ):
            return None

        scene = self._current_scene()
        if scene is None or len(scene.photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return None

        return scene

    def _filter_blocks_break_scene_from_scene_strip(
            self: MainWindow, position: QPoint
    ) -> bool:
        """
        Warn when a filtered scene-strip right-click targets a breakable scene.

        The horizontal strip can show only visible scene members under a
        filter, so this checks the clicked item against the full scene before
        the filtered resolver converts the action into a silent no-op.
        """
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or not self._photo_filter_active()
            or not self.library.scene_detection_done
            or not self.scene_list.isVisible()
        ):
            return False

        item = self.scene_list.itemAt(position)
        if item is None:
            return False

        photo_id = item.data(PHOTO_ID_ROLE)
        if photo_id is None:
            return False

        scene = self._breakable_library_scene_for_photo_id(str(photo_id))
        if scene is None:
            return False

        self._show_break_scene_filter_warning()
        return True

    def _breakable_library_scene_for_photo_id(
            self: MainWindow, photo_id: str
    ) -> SceneGroup | None:
        """
        Return the full breakable library scene containing a photo.

        Filtered scene views can collapse a real multi-photo scene to one
        visible row, so warning decisions must inspect the unfiltered scene
        list rather than the visible scene lookup.
        """
        for scene in self.library.get_scene_groups():
            if (
                photo_id in scene.photo_ids
                and len(scene.photo_ids) >= MIN_SCENE_MERGE_PHOTO_COUNT
            ):
                return scene

        return None

    def _breakable_library_scene_by_id(
            self: MainWindow, scene_id: str
    ) -> SceneGroup | None:
        """
        Return a full breakable library scene by ID.

        Direct break-scene callers may run while filters hide members, so the
        defensive guard must check the unfiltered scene list before deciding
        whether the blocked call deserves a warning.
        """
        for scene in self.library.get_scene_groups():
            if (
                scene.scene_id == scene_id
                and len(scene.photo_ids) >= MIN_SCENE_MERGE_PHOTO_COUNT
            ):
                return scene

        return None

    def _show_break_scene_filter_warning(self: MainWindow) -> None:
        """
        Show the persistent warning for filtered break-scene attempts.

        The message uses the transient overlay with no timeout so it matches
        other validation warnings that explicitly tell users to press Esc.
        """
        self._show_transient_message(
            BREAK_SCENE_FILTER_ACTIVE_MESSAGE,
            timeout_ms=None,
        )

    def _break_scene_into_singletons(self: MainWindow, scene_id: str) -> None:
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or self._compare_mode
        ):
            return

        if self._photo_filter_active():
            if self._breakable_library_scene_by_id(scene_id) is not None:
                self._show_break_scene_filter_warning()

            return

        scene = self._scene_by_id.get(scene_id)
        if scene is None or len(scene.photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return

        if not self._confirm_break_scene():
            return

        thumbnail_anchor = self._capture_thumbnail_scroll_anchor(
            scene.photo_ids[0]
        )
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
        self._after_scene_change(
            selected_photo_ids=[scene.photo_ids[0]],
            thumbnail_anchor=thumbnail_anchor,
        )
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
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or self._compare_mode
        ):
            return

        selection_source = self._scene_merge_selection_source_for_action()
        photo_ids = self._mergeable_scene_photo_ids(selection_source)
        if len(photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
            self._show_transient_message(
                MERGE_REQUIRES_SELECTION_MESSAGE,
                timeout_ms=None,
            )
            return

        # Reject partial scene-strip selections before expanding hidden
        # filtered photos; otherwise the expansion could make a split-like
        # selection look like a valid full-scene merge.
        if self._is_scene_strip_subset_merge():
            self._show_transient_message(
                'Cannot split an existing scene group.\n'
                'Press Ctrl+Z to undo and group again.',
                timeout_ms=TRANSIENT_MESSAGE_TIMEOUT_MS,
            )
            return

        if self._photo_filter_active():
            if not self._filtered_merge_selection_is_contiguous(
                selection_source
            ):
                self._show_transient_message(
                    FILTERED_SCENE_MERGE_REQUIRES_RANGE_MESSAGE,
                    timeout_ms=None,
                )
                return

            # The visible lists omit filtered photos, while the library merge
            # API edits exactly the IDs it receives. After proving the visible
            # selection is continuous, fill hidden in-range photos before
            # saving.
            photo_ids, includes_hidden_photos = (
                self._expand_filtered_merge_photo_ids(
                    photo_ids,
                    selection_source=selection_source,
                )
            )
            if len(photo_ids) < MIN_SCENE_MERGE_PHOTO_COUNT:
                return

            # Expansion can turn one filtered stack back into the exact full
            # scene it already represents. Catch that before confirmation so
            # users are not asked to approve a merge the library must no-op.
            if self._photo_ids_are_exact_existing_scene_group(photo_ids):
                self._show_transient_message(
                    MERGE_REQUIRES_SELECTION_MESSAGE,
                    timeout_ms=None,
                )
                return

            if (
                includes_hidden_photos
                and not self._confirm_filtered_scene_merge()
            ):
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

    def _expand_filtered_merge_photo_ids(
            self: MainWindow,
            photo_ids: list[str],
            *,
            selection_source: str | None,
    ) -> tuple[list[str], bool]:
        """
        Include hidden photos in the selected scene-aware merge range.

        Continuous visible ranges may hide in-between photos. Scene-stack
        selections also represent full underlying scenes, while browse-grid
        selections remain exact photos.
        """
        selected = set(photo_ids)
        full_photo_ids = [
            photo.photo_id for photo in self.library.get_photos()
        ]
        ordered_selected = [
            photo_id for photo_id in full_photo_ids if photo_id in selected
        ]
        if len(ordered_selected) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return ordered_selected, False

        visible_photo_ids = {
            photo.photo_id for photo in self._visible_photos()
        }
        index_by_photo_id = {
            photo_id: index for index, photo_id in enumerate(full_photo_ids)
        }
        expanded_selected = set(ordered_selected)
        expand_scene_groups = (
            selection_source in {'thumbnail', 'scene'}
            and self.library.scene_detection_done
            and not self._browse_mode
        )
        if expand_scene_groups:
            # Filtered scene rows may expose only one visible member of a full
            # scene. Expand through the unfiltered groups so selecting that row
            # still preserves the hidden scene members during the merge.
            scene_photo_ids_by_photo_id: dict[str, list[str]] = {}
            for scene in self.library.get_scene_groups():
                for scene_photo_id in scene.photo_ids:
                    scene_photo_ids_by_photo_id[scene_photo_id] = (
                        scene.photo_ids
                    )

            for photo_id in ordered_selected:
                expanded_selected.update(
                    scene_photo_ids_by_photo_id.get(photo_id, [photo_id])
                )

        ordered_expanded = [
            photo_id
            for photo_id in full_photo_ids
            if photo_id in expanded_selected
        ]
        if len(ordered_expanded) < MIN_SCENE_MERGE_PHOTO_COUNT:
            return ordered_expanded, False

        first_index = index_by_photo_id[ordered_expanded[0]]
        last_index = index_by_photo_id[ordered_expanded[-1]]
        expanded_range = full_photo_ids[first_index : last_index + 1]
        includes_hidden_photos = any(
            photo_id not in visible_photo_ids for photo_id in expanded_range
        )

        return expanded_range, includes_hidden_photos

    def _photo_ids_are_exact_existing_scene_group(
            self: MainWindow, photo_ids: list[str]
    ) -> bool:
        """Return True when the merge would recreate an existing scene."""
        return any(
            photo_ids == group
            for group in self.library.scene_group_photo_ids()
        )

    def _filtered_merge_selection_is_contiguous(
            self: MainWindow,
            selection_source: str | None,
    ) -> bool:
        """
        Return True when selected visible rows form one continuous range.

        Hidden photos may be included after confirmation, but visible rows that
        users skipped must not be added implicitly.
        """
        rows = self._filtered_merge_visible_selection_rows(selection_source)
        if len(rows) <= 1:
            return True

        return rows == list(range(rows[0], rows[-1] + 1))

    def _filtered_merge_visible_selection_rows(
            self: MainWindow,
            selection_source: str | None,
    ) -> list[int]:
        if selection_source == 'browse':
            return self._selected_row_indexes_from_list(self.browse_list)

        if selection_source == 'scene':
            return self._filtered_scene_merge_stack_rows()

        return self._selected_row_indexes_from_list(self.thumbnail_list)

    def _filtered_scene_merge_stack_rows(self: MainWindow) -> list[int]:
        """
        Return selected visible scene-stack rows for filtered range checks.

        A full horizontal scene-strip selection means "include this current
        stack", so its vertical row participates in the continuity test even
        when the user made that part of the selection from the scene strip.
        """
        rows = set(self._selected_row_indexes_from_list(self.thumbnail_list))
        current_scene = self._current_scene()
        if current_scene is not None:
            row = self._thumbnail_scene_rows.get(current_scene.scene_id)
            if row is not None:
                rows.add(row)

        return sorted(rows)

    @staticmethod
    def _selected_row_indexes_from_list(list_widget: QListWidget) -> list[int]:
        selected_items = sorted(
            list_widget.selectedItems(), key=list_widget.row
        )
        if not selected_items and list_widget.currentItem() is not None:
            selected_items = [list_widget.currentItem()]

        rows = {
            row
            for item in selected_items
            if (row := list_widget.row(item)) >= 0
        }
        return sorted(rows)

    def _confirm_filtered_scene_merge(self: MainWindow) -> bool:
        """
        Ask before a filtered merge includes currently hidden photos.

        Hidden in-between photos are not visible in the selection UI, so this
        confirmation makes the broader scene edit explicit before metadata is
        saved and undo history is recorded.
        """
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Merge Includes Hidden Photos')
        dialog.setText(FILTERED_SCENE_MERGE_WARNING_TEXT)
        merge_button = dialog.addButton(
            'Merge Scene', QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        return dialog.clickedButton() is merge_button

    def _mergeable_scene_photo_ids(
            self: MainWindow,
            selection_source: str | None = None,
    ) -> list[str]:
        """
        Return the photos that the scene merge action should operate on.

        Scene mode has two live selection surfaces. The vertical thumbnail
        strip selects whole scene stacks for merge, while the horizontal scene
        strip selects exact in-scene photos so users can reject partial-scene
        merges that would otherwise imply a split.
        """
        if self._compare_mode:
            return []

        if selection_source is None:
            selection_source = self._scene_merge_selection_source_for_action()

        if selection_source == 'browse':
            return self._resolved_selection_photo_ids()

        if selection_source == 'scene':
            return self._mergeable_scene_strip_photo_ids()

        if (
            selection_source == 'thumbnail'
            and self.library.scene_detection_done
            and not self._browse_mode
        ):
            return self._selected_scene_stack_photo_ids()

        if selection_source == 'thumbnail':
            return self._resolved_selection_photo_ids()

        return []

    def _scene_merge_selection_source_for_action(
            self: MainWindow,
    ) -> str | None:
        """
        Resolve which visible list owns the current merge command.

        The same QAction can fire from focus, menu, or shortcut paths, so this
        method freezes the selection surface before filtered range validation
        and hidden-photo expansion derive different behavior from it.
        """
        if self._compare_mode:
            return None

        if self._browse_mode:
            return 'browse'

        if not self.library.scene_detection_done:
            return 'thumbnail'

        selection_source = self._scene_merge_selection_source
        if selection_source == 'thumbnail':
            return 'thumbnail'

        if selection_source == 'scene':
            return 'scene'

        focus_widget = QApplication.focusWidget()
        if focus_widget in {
            self.thumbnail_list,
            self.thumbnail_list.viewport(),
        }:
            return 'thumbnail'

        if focus_widget in {
            self.scene_list,
            self.scene_list.viewport(),
        }:
            return 'scene'

        thumbnail_selection_count = len(self.thumbnail_list.selectedItems())
        scene_selection_count = len(self.scene_list.selectedItems())

        if thumbnail_selection_count >= MIN_SCENE_MERGE_PHOTO_COUNT:
            return 'thumbnail'

        if scene_selection_count >= MIN_SCENE_MERGE_PHOTO_COUNT:
            return 'scene'

        if thumbnail_selection_count > 0:
            return 'thumbnail'

        if scene_selection_count > 0:
            return 'scene'

        return None

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
        enabled = (
            not self._busy
            and not self._main_view_frozen_after_move_organize
            and self.menuBar().isEnabled()
            and not self._shortcut_help_modal_active()
        )
        if hasattr(self, 'undo_metadata_action'):
            self.undo_metadata_action.setEnabled(
                enabled and bool(self._metadata_undo_stack)
            )

        if hasattr(self, 'redo_metadata_action'):
            self.redo_metadata_action.setEnabled(
                enabled and bool(self._metadata_redo_stack)
            )

        self._refresh_merge_scene_action(
            photo_actions_enabled=enabled and bool(self.library.photos)
        )

    def _metadata_change_requires_filtered_rebuild(
            self: MainWindow, photo_ids: list[str]
    ) -> bool:
        """Return whether metadata edits changed filtered list membership."""
        if not self._photo_filter_active():
            return False

        # The row map still represents visibility before the metadata edit,
        # while each photo record already contains its updated metadata.
        return any(
            (photo_id in self._browse_photo_rows)
            != self._photo_filter_selection.matches(
                self.library.get_photo(photo_id)
            )
            for photo_id in photo_ids
        )

    def _after_metadata_change(
            self: MainWindow, changed_photo_ids: list[str] | None = None
    ) -> None:
        """
        Refresh metadata presentation after an assignment, undo, or redo.

        Compare edits that preserve filtered list membership update existing
        hidden cards so Qt does not rebuild their row widgets before they
        become visible again. Edits that cross a filter boundary continue
        through the full rebuild and reconciliation path below.
        """
        photo_ids = (
            changed_photo_ids
            if changed_photo_ids is not None
            else [photo.photo_id for photo in self.library.get_photos()]
        )
        if (
            self._compare_mode
            and not self._metadata_change_requires_filtered_rebuild(photo_ids)
        ):
            self._refresh_metadata_items_in_place(photo_ids)
            self._refresh_compare_metadata_labels()
            self._refresh_ui()
            return

        previous_photo_id = self.current_photo_id
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
        if not self._visible_photos() and self._browse_mode:
            self._set_browse_mode(active=False)

        self.current_photo_id = self._visible_photo_id_after_filter(
            self.current_photo_id
        )
        self._populate_thumbnail_list(scroll_current_item_into_view=False)
        self._populate_browse_list(scroll_current_item_into_view=False)
        self._populate_scene_list()
        for list_widget, selected_ids in selection_states.items():
            if len(selected_ids) >= MIN_SCENE_MERGE_PHOTO_COUNT:
                self._restore_selected_item_ids(list_widget, selected_ids)

        for list_widget, scroll_state in scroll_states.items():
            self._restore_scroll_state(list_widget, scroll_state)

        was_compare_mode = self._compare_mode
        if self._compare_mode and self._photo_filter_active():
            # The normal lists now reflect the metadata edit. Compare mode owns
            # a separate grid, so reconcile it before any hidden active photo
            # can drive labels, overlays, or later compare exit state.
            self._reconcile_compare_photos_after_filter_change()

        compare_exited = was_compare_mode and not self._compare_mode
        if (
            self.current_photo_id != previous_photo_id
            and not self._compare_mode
            and not compare_exited
        ):
            self._display_current_photo()

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
        self._restore_active_navigation_focus(require_active_window=False)
        self._restore_active_navigation_focus(
            defer=True,
            require_active_window=False,
        )

    def _set_interaction_enabled(self: MainWindow, *, enabled: bool) -> None:
        # ``enabled`` tracks temporary modal work. ``workspace_enabled`` also
        # honors the persistent post-move freeze so worker cleanup cannot
        # accidentally re-enable controls that point at moved file paths.
        workspace_enabled = (
            enabled and not self._main_view_frozen_after_move_organize
        )
        photo_actions_enabled = (
            workspace_enabled
            and not self._background_task_active()
            and bool(self.library.photos)
        )
        self.open_button.setEnabled(enabled)
        self.detect_button.setEnabled(photo_actions_enabled)
        self.organize_button.setEnabled(photo_actions_enabled)
        self.filter_button.setEnabled(
            workspace_enabled
            and bool(self.library.photos)
            and not self._compare_mode
        )
        self.theme_toggle.setEnabled(enabled)
        self.show_af_point_toggle.setEnabled(workspace_enabled)
        self.show_clipping_toggle.setEnabled(workspace_enabled)
        self.photo_load_recursively_checkbox.setEnabled(workspace_enabled)
        for button in self.photo_sort_buttons.values():
            button.setEnabled(workspace_enabled)

        self.photo_sort_reverse_checkbox.setEnabled(workspace_enabled)
        self.thumbnail_list.setEnabled(workspace_enabled)
        self.browse_list.setEnabled(workspace_enabled)
        self.scene_list.setEnabled(workspace_enabled)
        self.viewer.setEnabled(workspace_enabled)
        self.compare_viewer.setEnabled(workspace_enabled)
        self.menuBar().setEnabled(enabled)
        self._refresh_file_actions(
            open_enabled=enabled,
            photo_actions_enabled=photo_actions_enabled,
        )

        self._refresh_merge_scene_action(
            photo_actions_enabled=photo_actions_enabled
        )

        for action in self._assignment_actions:
            action.setEnabled(workspace_enabled)

        for shortcut in self._assignment_shortcuts:
            shortcut.setEnabled(workspace_enabled)

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
