"""Browse-mode and current-photo navigation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QItemSelectionModel, Qt, QTimer

from easy_loupe.ui.theme import PHOTO_ID_ROLE

if TYPE_CHECKING:
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from easy_loupe.core.photo_library import SceneGroup
    from easy_loupe.ui.main_window.window import MainWindow


class MainWindowNavigationMixin:
    """Browse, scene, focus, and current-photo handlers for MainWindow."""

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
            or self._shortcut_help_modal_active()
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

        if not self._thumbnail_strip_focus_available():
            return

        if self.thumbnail_list.currentRow() < 0:
            self._select_left_item_for_current_photo(suppress_signals=True)

        if self.thumbnail_list.currentRow() < 0:
            self.thumbnail_list.setCurrentRow(0)

        self.thumbnail_list.setFocus(Qt.OtherFocusReason)
        self.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)

    def _thumbnail_strip_focus_available(self: MainWindow) -> bool:
        """Return whether the thumbnail strip can accept focus now."""
        if (
            not self.isActiveWindow()
            or self._busy
            or self._background_task_active()
            or self._shortcut_help_modal_active()
            or self._compare_mode
            or self._browse_mode
            or not self.library.photos
        ):
            return False

        return (
            self.content_splitter.isVisible()
            and self.thumbnail_list.isVisible()
            and self.thumbnail_list.isEnabled()
            and self.thumbnail_list.count() > 0
        )

    def _list_selection_changed(self: MainWindow) -> None:
        """Refresh selection-dependent presentation for multi-selection."""
        if self._busy:
            return

        sender = self.sender()
        list_widgets = {
            self.thumbnail_list,
            self.browse_list,
            self.scene_list,
        }
        if sender in list_widgets:
            if sender is self.thumbnail_list:
                self._scene_merge_selection_source = 'thumbnail'
                if (
                    not self._extending_thumbnail_selection
                    and not self._selection_extending_modifier_active()
                ):
                    # A fresh click/plain navigation starts a new range.
                    # Without this reset, the next Shift+Up/Down would extend
                    # from an old anchor instead of the user's current row.
                    self._thumbnail_selection_anchor_row = None
            elif sender is self.scene_list:
                self._scene_merge_selection_source = 'scene'
            elif sender is self.browse_list:
                self._scene_merge_selection_source = 'browse'

            self._clear_preserved_scene_selection_if_restarted(sender)

        self._refresh_selection_labels()
        self._refresh_metadata_history_actions()
        if sender not in list_widgets:
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

        self._scene_merge_selection_source = 'thumbnail'
        previous_photo_id = (
            previous.data(PHOTO_ID_ROLE) if previous is not None else None
        )
        self._scene_selection_anchor_row = None
        if not self._extending_thumbnail_selection:
            # currentItemChanged also fires for our custom Shift navigation.
            # Keep the anchor during that path, but clear it for ordinary
            # thumbnail moves so later Shift selection starts where expected.
            self._thumbnail_selection_anchor_row = None

        photo_id = str(photo_id)
        preserved_selection_photo_ids = (
            self._capture_scene_selection_for_left_change(photo_id)
        )

        self.current_photo_id = photo_id
        if not self._compare_mode:
            self._display_current_photo()

        if self.library.scene_detection_done:
            self._sync_scene_list_for_photo(
                self.current_photo_id, rebuild_if_scene_changed=True
            )

        self._restore_scene_selection_after_left_change(
            preserved_selection_photo_ids
        )

        center = self._take_pending_thumbnail_click_center(
            self.thumbnail_list, self.current_photo_id
        )
        if center is not None:
            self.viewer.set_normalized_viewport_center(center)

        self._refresh_selection_labels()
        self._refresh_metadata_history_actions()
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
            self._scene_merge_selection_source = 'browse'
            self._refresh_metadata_history_actions()
            return

        self._scene_merge_selection_source = 'browse'
        self._preserved_scene_selection_photo_ids.clear()
        previous_photo_id = self.current_photo_id
        self.current_photo_id = str(photo_id)
        self._sync_left_list_for_photo(
            self.current_photo_id, suppress_signals=True
        )
        self._sync_scene_list_for_photo(
            self.current_photo_id, rebuild_if_scene_changed=True
        )
        self._refresh_selection_labels()
        self._refresh_metadata_history_actions()
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
            self._scene_merge_selection_source = 'scene'
            if photo_id is not None:
                self._take_pending_thumbnail_click_center(
                    self.scene_list, str(photo_id)
                )

            self._refresh_metadata_history_actions()
            return

        self._scene_merge_selection_source = 'scene'
        previous_photo_id = (
            previous.data(PHOTO_ID_ROLE) if previous is not None else None
        )
        if not self._extending_scene_selection:
            self._scene_selection_anchor_row = None
            if not self._selection_extending_modifier_active():
                self._preserved_scene_selection_photo_ids.clear()

        self.current_photo_id = str(photo_id)
        if not self._compare_mode:
            self._display_current_photo()

        self._sync_left_list_for_photo(
            self.current_photo_id,
            suppress_signals=True,
            preserve_selection=self._selection_extending_modifier_active(),
        )
        center = self._take_pending_thumbnail_click_center(
            self.scene_list, self.current_photo_id
        )
        if center is not None:
            self.viewer.set_normalized_viewport_center(center)

        self._refresh_selection_labels()
        self._refresh_metadata_history_actions()
        self._refresh_selection_styles(
            previous_photo_id, self.current_photo_id, 'scene'
        )

    def _take_pending_thumbnail_click_center(
            self: MainWindow,
            list_widget: QListWidget,
            photo_id: str,
    ) -> tuple[float, float] | None:
        """
        Return a matching spatial thumbnail click and clear stale requests.

        Thumbnail image clicks arrive before Qt changes the list current item.
        Clearing on every selection attempt prevents an unmatched click from
        affecting later keyboard, programmatic, or modifier-driven navigation.
        """
        pending = self._pending_thumbnail_click_center
        self._pending_thumbnail_click_center = None
        if pending is None:
            return None

        pending_widget, pending_photo_id, center = pending
        if pending_widget is not list_widget or pending_photo_id != photo_id:
            return None

        return center

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
        self._preserved_scene_selection_photo_ids.clear()
        next_row = current_row + direction
        if next_row < 0 or next_row >= self.scene_list.count():
            return

        item = self.scene_list.item(next_row)
        if item is None:
            return

        self.scene_list.selectionModel().setCurrentIndex(
            self.scene_list.indexFromItem(item),
            QItemSelectionModel.SelectionFlag.ClearAndSelect,
        )
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
            if hasattr(self, '_refresh_info_overlay'):
                self._refresh_info_overlay()

            return

        photo = self.library.get_photo(self.current_photo_id)
        image_path = self.library.get_preview_path(photo.photo_id, 'viewer')
        if force_fit:
            self.viewer.set_fit_view()

        manual_view = None
        if not force_fit:
            # Carry the full manual-view state, including either a concrete
            # center or the AF/default-center sentinel. Passing only
            # coordinates would lose reset-center intent and can leak
            # temporary recenter scale into normal navigation.
            manual_view = self.viewer.current_manual_view()

        self.viewer.set_photo(
            image_path,
            photo.focus_point,
            focus_point_pending=getattr(photo, 'focus_point_pending', False),
            handoff_manual_view=manual_view,
        )
        if hasattr(self, '_refresh_info_overlay'):
            self._refresh_info_overlay()

    def _set_browse_mode(self: MainWindow, *, active: bool) -> None:
        self._browse_mode = active
        self.content_splitter.setVisible(not active)
        self.browse_list.setVisible(active)
        if not active:
            self.thumbnail_list.setVisible(not self._compare_mode)

        if active:
            self.scene_list.setVisible(False)

        self._update_mode_shortcuts()
        self._refresh_info_overlay()

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
        compared_photo_ids = self.compare_viewer.photo_ids()
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

    def navigate_global_from_scene(
            self: MainWindow,
            direction: int,
            *,
            extend_selection: bool = False,
    ) -> bool:
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
        if extend_selection:
            # Shift+Up/Down from scene_list moves in the vertical strip while
            # keeping exact in-scene selections from the previous scene.
            selection_photo_ids = self._resolved_scene_selection_photo_ids()
            item = self.thumbnail_list.item(next_row)
            if item is not None:
                photo_id = item.data(PHOTO_ID_ROLE)
                if photo_id is not None:
                    selection_photo_ids.append(str(photo_id))

                self.thumbnail_list.selectionModel().setCurrentIndex(
                    self.thumbnail_list.indexFromItem(item),
                    QItemSelectionModel.SelectionFlag.NoUpdate,
                )

            self._restore_photo_selection(selection_photo_ids)
        else:
            self._preserved_scene_selection_photo_ids.clear()
            item = self.thumbnail_list.item(next_row)
            if item is not None:
                # Plain up/down from the scene strip is a new navigation
                # action, so collapse any selection restored by a sort rebuild.
                self.thumbnail_list.selectionModel().setCurrentIndex(
                    self.thumbnail_list.indexFromItem(item),
                    QItemSelectionModel.SelectionFlag.ClearAndSelect,
                )

        self.thumbnail_list.setFocus(Qt.OtherFocusReason)
        return True

    def extend_thumbnail_selection(self: MainWindow, direction: int) -> bool:
        """
        Extend vertical thumbnail selection as one exact anchored range.

        The default Qt range behavior can leave rows selected after reversing
        direction. This method makes Shift+Up/Down deterministic by moving the
        current row, clearing the vertical strip, and selecting only the range
        between the saved anchor and the new current row.
        """
        if (
            self._busy
            or self._compare_mode
            or self._browse_mode
            or self.thumbnail_list.count() == 0
        ):
            return False

        current_row = self.thumbnail_list.currentRow()
        if current_row < 0:
            self._select_left_item_for_current_photo()
            current_row = self.thumbnail_list.currentRow()

        if current_row < 0:
            return False

        if self._thumbnail_selection_anchor_row is None:
            self._thumbnail_selection_anchor_row = current_row

        next_row = current_row + direction
        if next_row < 0 or next_row >= self.thumbnail_list.count():
            return False

        item = self.thumbnail_list.item(next_row)
        if item is None:
            return False

        previous_photo_id = self.current_photo_id
        self._extending_thumbnail_selection = True
        self.thumbnail_list.setCurrentRow(next_row)
        self._extending_thumbnail_selection = False

        first_row = min(self._thumbnail_selection_anchor_row, next_row)
        last_row = max(self._thumbnail_selection_anchor_row, next_row)
        # Vertical range navigation is a new cover/stack selection, so hidden
        # exact scene-strip selections from prior scenes no longer apply.
        self._preserved_scene_selection_photo_ids.clear()
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.clearSelection()
        for row in range(first_row, last_row + 1):
            range_item = self.thumbnail_list.item(row)
            if range_item is not None:
                range_item.setSelected(True)

        self.thumbnail_list.blockSignals(False)
        self._refresh_selection_labels()
        self._refresh_metadata_history_actions()
        self._refresh_item_styles(self.thumbnail_list)
        if self.library.scene_detection_done:
            self._refresh_item_styles(self.scene_list)

        self._refresh_selection_styles(
            previous_photo_id, self.current_photo_id, 'main'
        )
        self.thumbnail_list.setFocus(Qt.OtherFocusReason)
        self.thumbnail_list.viewport().setFocus(Qt.OtherFocusReason)
        return True

    def _current_scene(self: MainWindow) -> SceneGroup | None:
        return self._scene_for_photo_id(self.current_photo_id)
