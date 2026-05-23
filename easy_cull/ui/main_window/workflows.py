"""Long-running workflows, busy-state handling, and metadata actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QListWidget,
    QMessageBox,
)

from easy_cull.operations.common import (
    OperationSummary,
    UndoPlan,
    undo_operation,
)
from easy_cull.operations.export import organize_photos
from easy_cull.operations.xmp import write_xmp_sidecars
from easy_cull.ui.main_window.build import TRANSIENT_MESSAGE_TIMEOUT_MS
from easy_cull.ui.main_window.dialogs import (
    OrganizerDialog,
    OrganizerDialogResult,
)
from easy_cull.ui.theme import (
    LOAD_AND_PREVIEW_PROGRESS_MAX,
    LOAD_PROGRESS_MAX,
    PHOTO_ID_ROLE,
)
from easy_cull.ui.workers import OperationWorker, SceneDetectionWorker

if TYPE_CHECKING:
    from easy_cull.ui.main_window.window import MainWindow

ProgressCallback = Callable[[str, int], None]


@dataclass(frozen=True)
class MetadataEdit:
    """In-memory undo record for a metadata assignment batch."""

    field: str
    before: dict[str, Any]
    after: dict[str, Any]


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

    def detect_scenes(self: MainWindow) -> None:
        """Start asynchronous scene detection for the loaded photo set."""
        if (
            self._busy
            or not self.library.photos
            or self._background_task_active()
        ):
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

    def _handle_scene_finished(self: MainWindow) -> None:
        was_browse_mode = self._browse_mode
        was_split_view = self.viewer.is_split_view()
        self._show_progress('Scene detection finished', 100)
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
            self: MainWindow, *, show_progress: bool = False
    ) -> None:
        if not self.library.photos and self._browse_mode:
            self._set_browse_mode(active=False)

        self.current_photo_id = (
            self.library.photos[0].photo_id if self.library.photos else None
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
        QApplication.processEvents()

    def _hide_progress(self: MainWindow) -> None:
        self.progress_overlay.hide()
        self.overlay_progress_bar.setVisible(True)
        self.overlay_progress_bar.setRange(0, 100)
        self.overlay_progress_bar.setValue(0)
        self.overlay_message_label.setText('')
        self._busy = False
        self._set_interaction_enabled(enabled=True)

    def _handle_load_progress(
            self: MainWindow, message: str, progress: int
    ) -> None:
        self._show_progress(message, progress)

    def _set_rating(self: MainWindow, rating: int | None) -> None:
        if hasattr(self, '_apply_metadata_to_selection'):
            self._apply_metadata_to_selection('rating', rating)
            return

        self.library.update_metadata(
            self.current_photo_id, rating=rating, fields={'rating'}
        )
        self.library.save_metadata()
        self._after_metadata_change()

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
        self._after_metadata_change()

    def _set_flag(self: MainWindow, flag: str | None) -> None:
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
        self._apply_metadata_values(edit.field, edit.before)
        self._metadata_redo_stack.append(edit)
        self.library.save_metadata()
        self._after_metadata_change()
        self._refresh_metadata_history_actions()

    def _redo_metadata_edit(self: MainWindow) -> None:
        if self._busy or not self._metadata_redo_stack:
            return

        edit = self._metadata_redo_stack.pop()
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
            self._restore_selected_item_ids(list_widget, selected_ids)

        for list_widget, scroll_state in scroll_states.items():
            self._restore_scroll_state(list_widget, scroll_state)

        self._refresh_compare_metadata_labels()
        self._refresh_ui()

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

        for action in self._assignment_actions:
            action.setEnabled(enabled)

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
