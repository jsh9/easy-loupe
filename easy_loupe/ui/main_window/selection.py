"""
Selection resolution and restoration helpers for MainWindow.

This mixin is tested through ``MainWindow`` navigation and compare workflows
rather than direct unit tests. Its behavior depends on live Qt list widgets,
scene-strip state, and hidden selection preservation, so the main-window tests
cover the meaningful contract without binding tests to the mixin extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication

from easy_loupe.ui.theme import PHOTO_ID_ROLE

if TYPE_CHECKING:
    from PySide6.QtWidgets import QListWidget

    from easy_loupe.ui.main_window.window import MainWindow


class MainWindowSelectionMixin:
    """Selection helpers for thumbnail, browse, scene, and compare modes."""

    def _clear_preserved_scene_selection_if_restarted(
            self: MainWindow, sender: object
    ) -> None:
        """Clear hidden scene selections when selection starts over."""
        if sender is self.browse_list:
            self._preserved_scene_selection_photo_ids.clear()
            return

        if (
            not self._extending_scene_selection
            and not self._selection_extending_modifier_active()
        ):
            self._preserved_scene_selection_photo_ids.clear()

    @staticmethod
    def _selection_extending_modifier_active() -> bool:
        """Return True while user input should preserve extended selection."""
        modifiers = QApplication.keyboardModifiers()
        return bool(modifiers & Qt.ShiftModifier) or bool(
            modifiers & Qt.ControlModifier
        )

    def _capture_scene_selection_for_left_change(
            self: MainWindow, photo_id: str
    ) -> list[str] | None:
        """
        Capture exact selected photos before a left-strip move rebuilds scenes.

        Moving the vertical scene-stack selection can replace ``scene_list``.
        This snapshot keeps previously selected non-cover scene photos in the
        logical selection even when their old horizontal rows disappear.
        """
        if (
            not self.library.scene_detection_done
            or not self._selection_extending_modifier_active()
        ):
            self._preserved_scene_selection_photo_ids.clear()
            return None

        photo_ids = self._resolved_scene_selection_photo_ids()
        if photo_id not in photo_ids:
            photo_ids.append(photo_id)

        return photo_ids

    def _restore_scene_selection_after_left_change(
            self: MainWindow, photo_ids: list[str] | None
    ) -> None:
        if photo_ids is None:
            return

        if QApplication.keyboardModifiers() & Qt.ControlModifier:
            # Qt applies Ctrl-click item toggling after currentItemChanged.
            # Defer restoration so its built-in toggle cannot drop the row.
            QTimer.singleShot(
                0,
                lambda captured_photo_ids=list(photo_ids): (
                    self._restore_photo_selection(captured_photo_ids)
                ),
            )
            return

        self._restore_photo_selection(photo_ids)

    def _resolved_selection_photo_ids(
            self: MainWindow, *, limit: int | None = None
    ) -> list[str]:
        """Return active selected photo ids in deterministic photo order."""
        if self._compare_mode:
            active_photo_id = self.compare_viewer.active_photo_id()
            return [] if active_photo_id is None else [active_photo_id]

        if (
            self.library.scene_detection_done
            and not self._browse_mode
            and self.scene_list.isVisible()
        ):
            return self._resolved_scene_selection_photo_ids(limit=limit)

        list_widget = self._selection_source_widget()
        selected_items = sorted(
            list_widget.selectedItems(),
            key=list_widget.row,
        )
        if not selected_items and list_widget.currentItem() is not None:
            selected_items = [list_widget.currentItem()]

        resolved: list[str] = []
        seen: set[str] = set()
        for item in selected_items:
            photo_id = item.data(PHOTO_ID_ROLE)
            if photo_id is None:
                continue

            candidate = str(photo_id)
            if candidate in seen:
                continue

            resolved.append(candidate)
            seen.add(candidate)
            if limit is not None and len(resolved) >= limit:
                return resolved

        if not resolved and self.current_photo_id is not None:
            resolved.append(self.current_photo_id)

        return resolved

    def _resolved_scene_selection_photo_ids(
            self: MainWindow, *, limit: int | None = None
    ) -> list[str]:
        photo_ids: list[str] = []
        scene_photo_ids = self._selected_photo_ids_from_list(self.scene_list)
        thumbnail_photo_ids = self._selected_photo_ids_from_list(
            self.thumbnail_list
        )
        left_current_photo_id = self._left_photo_id_for_photo(
            self.current_photo_id
        )
        synthetic_cover_selection = (
            bool(scene_photo_ids)
            and self.current_photo_id != left_current_photo_id
            and thumbnail_photo_ids == [left_current_photo_id]
        )
        include_thumbnail_selection = not synthetic_cover_selection
        if include_thumbnail_selection:
            photo_ids.extend(thumbnail_photo_ids)

        photo_ids.extend(scene_photo_ids)
        # Include non-cover scene photos selected before scene_list rebuilt.
        photo_ids.extend(self._preserved_scene_selection_photo_ids)
        if not photo_ids and self.current_photo_id is not None:
            photo_ids.append(self.current_photo_id)

        return self._photo_ids_in_library_order(photo_ids, limit=limit)

    @staticmethod
    def _selected_photo_ids_from_list(list_widget: QListWidget) -> list[str]:
        photo_ids: list[str] = []
        for item in sorted(list_widget.selectedItems(), key=list_widget.row):
            photo_id = item.data(PHOTO_ID_ROLE)
            if photo_id is not None:
                photo_ids.append(str(photo_id))

        return photo_ids

    def _photo_ids_in_library_order(
            self: MainWindow,
            photo_ids: list[str],
            *,
            limit: int | None = None,
    ) -> list[str]:
        seen = set(photo_ids)
        resolved: list[str] = []
        for photo in self._visible_photos():
            if photo.photo_id not in seen:
                continue

            resolved.append(photo.photo_id)
            if limit is not None and len(resolved) >= limit:
                return resolved

        return resolved

    def _selection_source_widget(self: MainWindow) -> QListWidget:
        if self._browse_mode and self.browse_list.isVisible():
            return self.browse_list

        focus_widget = QApplication.focusWidget()
        if focus_widget in {self.scene_list, self.scene_list.viewport()}:
            return self.scene_list

        if focus_widget in {
            self.thumbnail_list,
            self.thumbnail_list.viewport(),
        }:
            return self.thumbnail_list

        if self.scene_list.isVisible() and self.scene_list.selectedItems():
            return self.scene_list

        return self.thumbnail_list

    def _select_browse_items_for_photo_ids(
            self: MainWindow, photo_ids: list[str]
    ) -> None:
        selected = set(photo_ids)
        self._preserved_scene_selection_photo_ids.clear()
        self.browse_list.blockSignals(True)
        self.browse_list.clearSelection()
        current_row = self._browse_photo_rows.get(self.current_photo_id or '')
        if current_row is not None:
            self.browse_list.setCurrentRow(current_row)

        for photo_id in photo_ids:
            row = self._browse_photo_rows.get(photo_id)
            if row is None:
                continue

            item = self.browse_list.item(row)
            if item is not None:
                item.setSelected(True)

        self.browse_list.blockSignals(False)
        for index in range(self.browse_list.count()):
            item = self.browse_list.item(index)
            if item is not None and item.data(PHOTO_ID_ROLE) in selected:
                self._refresh_item_style_for_photo_id(
                    self.browse_list, item.data(PHOTO_ID_ROLE)
                )

    def _restore_photo_selection(
            self: MainWindow, photo_ids: list[str]
    ) -> None:
        if self._browse_mode and self.browse_list.isVisible():
            self._select_browse_items_for_photo_ids(photo_ids)
            return

        if not self.library.scene_detection_done:
            self._preserved_scene_selection_photo_ids.clear()
            selected = set(photo_ids)
            self.thumbnail_list.blockSignals(True)
            self.thumbnail_list.clearSelection()
            for photo_id in photo_ids:
                row = self._thumbnail_photo_rows.get(photo_id)
                if row is None:
                    continue

                item = self.thumbnail_list.item(row)
                if item is not None:
                    item.setSelected(True)

            self.thumbnail_list.blockSignals(False)
            self._refresh_item_styles(self.thumbnail_list)
            for photo_id in selected:
                self._refresh_item_style_for_photo_id(
                    self.thumbnail_list, photo_id
                )

            return

        hidden_scene_photo_ids: set[str] = set()
        self.thumbnail_list.blockSignals(True)
        self.scene_list.blockSignals(True)
        self.thumbnail_list.clearSelection()
        self.scene_list.clearSelection()
        for photo_id in photo_ids:
            left_photo_id = self._left_photo_id_for_photo(photo_id)
            if left_photo_id == photo_id:
                row = self._thumbnail_row_for_photo(photo_id)
                if row is not None:
                    item = self.thumbnail_list.item(row)
                    if item is not None:
                        item.setSelected(True)

            scene_row = self._scene_photo_rows.get(photo_id)
            if scene_row is not None:
                item = self.scene_list.item(scene_row)
                if item is not None:
                    item.setSelected(True)
            elif left_photo_id != photo_id:
                # The photo belongs to a different scene than the visible
                # scene_list; keep it selected until selection resets.
                hidden_scene_photo_ids.add(photo_id)

        self._preserved_scene_selection_photo_ids = hidden_scene_photo_ids
        self.thumbnail_list.blockSignals(False)
        self.scene_list.blockSignals(False)
        self._refresh_item_styles(self.thumbnail_list)
        self._refresh_item_styles(self.scene_list)
        self._refresh_selection_labels()
