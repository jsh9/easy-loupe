"""Selection, browse-mode, and current-photo navigation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtWidgets import QApplication

from easy_cull.ui.theme import PHOTO_ID_ROLE, metadata_markup
from easy_cull.ui.viewers.compare_photo_viewer import (
    MIN_COMPARE_PHOTO_COUNT,
    ComparePhoto,
)

if TYPE_CHECKING:
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from easy_cull.core.photo_library import SceneGroup
    from easy_cull.ui.main_window.window import MainWindow


class MainWindowNavigationMixin:
    """Navigation and selection handlers for MainWindow."""

    def _active_navigation_widget(self: MainWindow) -> QListWidget | None:
        """Return the list widget that should own keyboard navigation."""
        if self._compare_mode:
            return None

        if (
            self._browse_mode
            and self.browse_list.isVisible()
            and self.browse_list.count() > 0
        ):
            return self.browse_list

        if (
            not self._browse_mode
            and self.scene_list.isVisible()
            and self.scene_list.count() > 0
        ):
            return self.scene_list

        if (
            not self._browse_mode
            and self.content_splitter.isVisible()
            and self.thumbnail_list.count() > 0
        ):
            return self.thumbnail_list

        return None

    def _restore_active_navigation_focus(
            self: MainWindow, *, defer: bool = False
    ) -> None:
        """Restore focus to the active navigation widget when usable."""
        if defer:
            QTimer.singleShot(0, self._restore_active_navigation_focus)
            return

        if (
            not self.isActiveWindow()
            or self._busy
            or self._background_task_active()
            or not self.library.photos
        ):
            return

        target = self._active_navigation_widget()
        if target is None or not target.isVisible() or not target.isEnabled():
            return

        if target.currentRow() < 0 and target.count() > 0:
            target.setCurrentRow(0)

        target.setFocus(Qt.OtherFocusReason)
        target.viewport().setFocus(Qt.OtherFocusReason)

    def _restore_thumbnail_strip_focus(
            self: MainWindow, *, defer: bool = False
    ) -> None:
        """Restore focus specifically to the vertical thumbnail strip."""
        if defer:
            QTimer.singleShot(0, self._restore_thumbnail_strip_focus)
            return

        if (
            not self.isActiveWindow()
            or self._busy
            or self._background_task_active()
            or self._compare_mode
            or self._browse_mode
            or not self.library.photos
            or not self.content_splitter.isVisible()
            or not self.thumbnail_list.isVisible()
            or not self.thumbnail_list.isEnabled()
            or self.thumbnail_list.count() == 0
        ):
            return

        if self.thumbnail_list.currentRow() < 0:
            self._select_left_item_for_current_photo(suppress_signals=True)

        if self.thumbnail_list.currentRow() < 0:
            self.thumbnail_list.setCurrentRow(0)

        self.thumbnail_list.setFocus(Qt.OtherFocusReason)
        self.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    def _list_selection_changed(self: MainWindow) -> None:
        """Refresh selection-dependent presentation for multi-selection."""
        if self._busy:
            return

        self._refresh_selection_labels()
        sender = self.sender()
        if sender not in {
            self.thumbnail_list,
            self.browse_list,
            self.scene_list,
        }:
            return

        for index in range(sender.count()):
            item = sender.item(index)
            if item is not None:
                self._refresh_item_style_for_photo_id(
                    sender, item.data(PHOTO_ID_ROLE)
                )

    def _left_list_selection_changed(
            self: MainWindow,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return

        if self._busy:
            return

        photo_id = current.data(PHOTO_ID_ROLE)
        if photo_id is None:
            return

        previous_photo_id = (
            previous.data(PHOTO_ID_ROLE) if previous is not None else None
        )
        self._scene_selection_anchor_row = None
        self.current_photo_id = str(photo_id)
        if not self._compare_mode:
            self._display_current_photo()

        if self.library.scene_detection_done:
            self._sync_scene_list_for_photo(
                self.current_photo_id, rebuild_if_scene_changed=True
            )

        self._refresh_selection_labels()
        self._refresh_selection_styles(
            previous_photo_id, self.current_photo_id, 'main'
        )

    def _browse_list_selection_changed(
            self: MainWindow,
            current: QListWidgetItem | None,
            _previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return

        if self._busy:
            return

        photo_id = current.data(PHOTO_ID_ROLE)
        if photo_id is None or photo_id == self.current_photo_id:
            return

        previous_photo_id = self.current_photo_id
        self.current_photo_id = str(photo_id)
        self._sync_left_list_for_photo(
            self.current_photo_id, suppress_signals=True
        )
        self._sync_scene_list_for_photo(
            self.current_photo_id, rebuild_if_scene_changed=True
        )
        self._refresh_selection_labels()
        self._refresh_selection_styles(
            previous_photo_id, self.current_photo_id, 'browse'
        )

    def _browse_item_double_clicked(
            self: MainWindow, item: QListWidgetItem
    ) -> None:
        if self._busy:
            return

        photo_id = item.data(PHOTO_ID_ROLE)
        if photo_id is None:
            return

        self.current_photo_id = str(photo_id)
        self._exit_browse_mode(force_fit_photo=True)

    def _scene_list_selection_changed(
            self: MainWindow,
            current: QListWidgetItem | None,
            previous: QListWidgetItem | None,
    ) -> None:
        if current is None:
            return

        if self._busy:
            return

        photo_id = current.data(PHOTO_ID_ROLE)
        if photo_id is None or photo_id == self.current_photo_id:
            return

        previous_photo_id = (
            previous.data(PHOTO_ID_ROLE) if previous is not None else None
        )
        if not self._extending_scene_selection:
            self._scene_selection_anchor_row = None

        self.current_photo_id = str(photo_id)
        if not self._compare_mode:
            self._display_current_photo()

        self._sync_left_list_for_photo(
            self.current_photo_id,
            suppress_signals=True,
            preserve_selection=True,
        )
        self._refresh_selection_labels()
        self._refresh_selection_styles(
            previous_photo_id, self.current_photo_id, 'scene'
        )

    def _navigate_scene(self: MainWindow, direction: int) -> None:
        if (
            not self.library.scene_detection_done
            or self.current_photo_id is None
            or self.scene_list.count() == 0
        ):
            return

        current_scene = self._current_scene()
        if current_scene is None:
            return

        current_row = self.scene_list.currentRow()
        if current_row < 0:
            current_row = next(
                (
                    index
                    for index, photo_id in enumerate(current_scene.photo_ids)
                    if photo_id == self.current_photo_id
                ),
                -1,
            )

        if current_row < 0:
            return

        self._scene_selection_anchor_row = None
        next_row = current_row + direction
        if next_row < 0 or next_row >= self.scene_list.count():
            return

        self.scene_list.setCurrentRow(next_row)
        self.scene_list.setFocus(Qt.OtherFocusReason)

    def _extend_scene_selection(self: MainWindow, direction: int) -> None:
        if (
            not self.library.scene_detection_done
            or self.current_photo_id is None
            or self.scene_list.count() == 0
        ):
            return

        current_row = self.scene_list.currentRow()
        if current_row < 0:
            current_row = self._scene_photo_rows.get(self.current_photo_id, -1)

        if current_row < 0:
            return

        if self._scene_selection_anchor_row is None:
            self._scene_selection_anchor_row = current_row

        next_row = current_row + direction
        if next_row < 0 or next_row >= self.scene_list.count():
            return

        self._extending_scene_selection = True
        self.scene_list.setCurrentRow(next_row)
        self._extending_scene_selection = False

        first_row = min(self._scene_selection_anchor_row, next_row)
        last_row = max(self._scene_selection_anchor_row, next_row)
        self.scene_list.blockSignals(True)
        self.scene_list.clearSelection()
        for row in range(first_row, last_row + 1):
            item = self.scene_list.item(row)
            if item is not None:
                item.setSelected(True)

        self.scene_list.blockSignals(False)
        self._refresh_selection_labels()
        self._refresh_item_styles(self.scene_list)
        self.scene_list.setFocus(Qt.OtherFocusReason)

    def _display_current_photo(
            self: MainWindow, *, force_fit: bool = False
    ) -> None:
        if self.current_photo_id is None:
            self.viewer.clear_photo()
            return

        photo = self.library.get_photo(self.current_photo_id)
        image_path = self.library.get_preview_path(photo.photo_id, 'viewer')
        if force_fit:
            self.viewer.set_fit_view()

        preserve_zoom = (
            False if force_fit else self.viewer.should_preserve_zoom()
        )
        preserved_center = (
            self.viewer.normalized_viewport_center() if preserve_zoom else None
        )
        self.viewer.set_photo(
            image_path,
            photo.focus_point,
            preserve_zoom=preserve_zoom,
            preserved_center=preserved_center,
        )

    def _compare_active_photo_changed(self: MainWindow, photo_id: str) -> None:
        self.current_photo_id = photo_id
        self._refresh_selection_labels()

    def _enter_compare_mode(self: MainWindow) -> None:
        if self._compare_mode or self._busy or not self.library.photos:
            return

        restore_photo_ids = self._resolved_selection_photo_ids()
        photo_ids = restore_photo_ids[: self.compare_viewer.photo_limit]
        if len(photo_ids) < MIN_COMPARE_PHOTO_COUNT:
            return

        self._compare_restore_browse_mode = self._browse_mode
        self._compare_restore_scene_visible = self.scene_list.isVisible()
        self._compare_restore_selection_photo_ids = list(restore_photo_ids)
        if self._browse_mode:
            self._set_browse_mode(active=False)

        compare_photos: list[ComparePhoto] = []
        for photo_id in photo_ids:
            photo = self.library.get_photo(photo_id)
            compare_photos.append(
                ComparePhoto(
                    photo_id=photo.photo_id,
                    image_path=self.library.get_preview_path(
                        photo.photo_id, 'viewer'
                    ),
                    focus_point=photo.focus_point,
                    display_name=photo.display_name,
                    metadata_text=metadata_markup(photo),
                )
            )

        self._compare_mode = True
        self.compare_viewer.set_photos(compare_photos)
        self.compare_viewer.lock_zoom_button.setChecked(True)
        active_photo_id = self.compare_viewer.active_photo_id()
        if active_photo_id is not None:
            self.current_photo_id = active_photo_id

        self.content_splitter.setVisible(True)
        self.thumbnail_list.setVisible(False)
        self.browse_list.setVisible(False)
        self.scene_list.setVisible(False)
        self.viewer_stack.setCurrentWidget(self.compare_viewer)
        self._refresh_visible_region_overlay(force_full=True)
        self._update_mode_shortcuts()
        self.compare_viewer.setFocus(Qt.OtherFocusReason)

    def _exit_compare_mode(
            self: MainWindow, *, restore_previous: bool = True
    ) -> None:
        if not self._compare_mode:
            return

        restore_browse_mode = self._compare_restore_browse_mode
        restore_scene_visible = self._compare_restore_scene_visible
        restore_photo_ids = list(self._compare_restore_selection_photo_ids)
        compared_photo_ids = self.compare_viewer.selected_photo_ids()
        active_photo_id = self.compare_viewer.active_photo_id()
        selection_photo_ids = restore_photo_ids or compared_photo_ids
        if active_photo_id in selection_photo_ids:
            self.current_photo_id = active_photo_id
        elif selection_photo_ids:
            self.current_photo_id = selection_photo_ids[0]

        self._compare_mode = False
        self._compare_restore_browse_mode = False
        self._compare_restore_scene_visible = False
        self._compare_restore_selection_photo_ids = []
        self.viewer_stack.setCurrentWidget(self.viewer)
        self.compare_viewer.clear()

        if not restore_previous:
            self.content_splitter.setVisible(True)
            self.thumbnail_list.setVisible(True)
            self.browse_list.setVisible(False)
            self.scene_list.setVisible(False)
            self._update_mode_shortcuts()
            return

        if restore_browse_mode:
            self._set_browse_mode(active=True)
            self._refresh_browse_layout()
            self._select_browse_items_for_photo_ids(selection_photo_ids)
        else:
            self.content_splitter.setVisible(True)
            self.thumbnail_list.setVisible(True)
            self.browse_list.setVisible(False)
            if restore_scene_visible:
                self._populate_scene_list()
            else:
                self.scene_list.setVisible(False)

        self._refresh_ui()
        if selection_photo_ids:
            self._restore_photo_selection(selection_photo_ids)

        self._refresh_visible_region_overlay(force_full=True)
        self._update_mode_shortcuts()
        self._restore_active_navigation_focus(defer=True)

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
        for photo in self.library.get_photos():
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

    def _photo_ids_for_selected_item(
            self: MainWindow, list_widget: QListWidget, photo_id: str
    ) -> list[str]:
        if (
            list_widget is self.thumbnail_list
            and self.library.scene_detection_done
        ):
            scene = self._scene_for_photo_id(photo_id)
            if scene is not None and scene.photo_ids:
                return list(scene.photo_ids)

        return [photo_id]

    def _set_browse_mode(self: MainWindow, *, active: bool) -> None:
        self._browse_mode = active
        self.content_splitter.setVisible(not active)
        self.browse_list.setVisible(active)
        if not active:
            self.thumbnail_list.setVisible(not self._compare_mode)

        if active:
            self.scene_list.setVisible(False)

        self._update_mode_shortcuts()

    def _refresh_browse_layout(self: MainWindow) -> None:
        if self.browse_list.count() == 0:
            return

        item = self.browse_list.item(0)
        if item is None:
            return

        size_hint = item.sizeHint()
        if not size_hint.isValid():
            return

        self.browse_list.setGridSize(size_hint)
        self.browse_list.doItemsLayout()
        self.browse_list.updateGeometries()
        self.browse_list.viewport().update()

    def _enter_browse_mode(self: MainWindow) -> None:
        if self._compare_mode:
            self._enter_browse_mode_from_compare()
            return

        if self._browse_mode or not self.library.photos:
            return

        self._populate_browse_list()
        self._set_browse_mode(active=True)
        self._refresh_browse_layout()
        QTimer.singleShot(0, self._refresh_browse_layout)
        self._select_browse_item_for_current_photo()
        self._refresh_ui()
        self.browse_list.setFocus(Qt.OtherFocusReason)

    def _enter_browse_mode_from_compare(self: MainWindow) -> None:
        compared_photo_ids = self.compare_viewer.selected_photo_ids()
        restore_photo_ids = (
            list(self._compare_restore_selection_photo_ids)
            or compared_photo_ids
        )
        active_photo_id = self.compare_viewer.active_photo_id()
        if not restore_photo_ids:
            self._exit_compare_mode()
            self._enter_browse_mode()
            return

        self.current_photo_id = (
            active_photo_id
            if active_photo_id in restore_photo_ids
            else restore_photo_ids[0]
        )
        self._exit_compare_mode(restore_previous=False)
        self._populate_browse_list()
        self._set_browse_mode(active=True)
        self._refresh_browse_layout()
        self._select_browse_items_for_photo_ids(restore_photo_ids)
        self._refresh_ui()
        self.browse_list.setFocus(Qt.OtherFocusReason)

    def _select_browse_items_for_photo_ids(
            self: MainWindow, photo_ids: list[str]
    ) -> None:
        selected = set(photo_ids)
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

        selected = set(photo_ids)
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

        self.thumbnail_list.blockSignals(False)
        self.scene_list.blockSignals(False)
        self._refresh_item_styles(self.thumbnail_list)
        self._refresh_item_styles(self.scene_list)
        self._refresh_selection_labels()

    def _exit_browse_mode(
            self: MainWindow, *, force_fit_photo: bool = False
    ) -> None:
        if not self._browse_mode:
            return

        self._set_browse_mode(active=False)
        if force_fit_photo:
            self._display_current_photo(force_fit=True)

        self._select_left_item_for_current_photo(suppress_signals=True)
        self._populate_scene_list()
        self._refresh_ui()
        self.thumbnail_list.setFocus(Qt.OtherFocusReason)

    def _sync_scene_list_for_photo(
            self: MainWindow,
            photo_id: str | None,
            *,
            rebuild_if_scene_changed: bool,
    ) -> None:
        if not self.library.scene_detection_done or photo_id is None:
            self.scene_list.setVisible(False)
            self._scene_list_scene_id = None
            self._scene_photo_rows = {}
            return

        target_scene = self._scene_for_photo_id(photo_id)
        if target_scene is None:
            self.scene_list.setVisible(False)
            self._scene_list_scene_id = None
            self._scene_photo_rows = {}
            return

        if self._scene_list_scene_id != target_scene.scene_id:
            if rebuild_if_scene_changed:
                self._populate_scene_list()

            return

        target_row = self._scene_photo_rows.get(photo_id)
        if (
            target_row is not None
            and target_row != self.scene_list.currentRow()
        ):
            self.scene_list.blockSignals(True)
            self.scene_list.setCurrentRow(target_row)
            self.scene_list.blockSignals(False)

        self.scene_list.setVisible(
            not self._browse_mode and not self._compare_mode
        )

    def _sync_left_list_for_photo(
            self: MainWindow,
            photo_id: str | None,
            *,
            suppress_signals: bool = False,
            restyle_only: bool = False,
            preserve_selection: bool = False,
    ) -> None:
        if restyle_only:
            return

        target_row = self._thumbnail_row_for_photo(photo_id)
        if target_row is None:
            return

        if suppress_signals:
            self.thumbnail_list.blockSignals(True)

        if preserve_selection:
            item = self.thumbnail_list.item(target_row)
            if item is not None:
                self.thumbnail_list.selectionModel().setCurrentIndex(
                    self.thumbnail_list.indexFromItem(item),
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )
        else:
            self.thumbnail_list.setCurrentRow(target_row)

        if suppress_signals:
            self.thumbnail_list.blockSignals(False)

    def navigate_global_from_scene(self: MainWindow, direction: int) -> bool:
        """Move the left-strip selection relative to the current scene item."""
        if self.thumbnail_list.count() == 0:
            return False

        current_row = self.thumbnail_list.currentRow()
        if current_row < 0:
            self._select_left_item_for_current_photo()
            current_row = self.thumbnail_list.currentRow()

        if current_row < 0:
            return False

        next_row = max(
            0, min(self.thumbnail_list.count() - 1, current_row + direction)
        )
        self.thumbnail_list.setCurrentRow(next_row)
        self.thumbnail_list.setFocus(Qt.OtherFocusReason)
        return True

    def _current_scene(self: MainWindow) -> SceneGroup | None:
        return self._scene_for_photo_id(self.current_photo_id)
