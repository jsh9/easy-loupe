"""Selection, browse-mode, and current-photo navigation helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer

from easy_cull.ui.theme import PHOTO_ID_ROLE

if TYPE_CHECKING:
    from PySide6.QtWidgets import QListWidget, QListWidgetItem

    from easy_cull.core.photo_library import SceneGroup
    from easy_cull.ui.main_window.window import MainWindow


class MainWindowNavigationMixin:
    """Navigation and selection handlers for MainWindow."""

    def _active_navigation_widget(self: MainWindow) -> QListWidget | None:
        """Return the list widget that should own keyboard navigation."""
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
        self.current_photo_id = str(photo_id)
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
        self.current_photo_id = str(photo_id)
        self._display_current_photo()
        self._sync_left_list_for_photo(
            self.current_photo_id, suppress_signals=True
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

        next_row = current_row + direction
        if next_row < 0 or next_row >= self.scene_list.count():
            return

        self.scene_list.setCurrentRow(next_row)
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

    def _set_browse_mode(self: MainWindow, *, active: bool) -> None:
        self._browse_mode = active
        self.content_splitter.setVisible(not active)
        self.browse_list.setVisible(active)
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
        if self._browse_mode or not self.library.photos:
            return

        self._populate_browse_list()
        self._set_browse_mode(active=True)
        self._refresh_browse_layout()
        QTimer.singleShot(0, self._refresh_browse_layout)
        self._select_browse_item_for_current_photo()
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

        self.scene_list.setVisible(not self._browse_mode)

    def _sync_left_list_for_photo(
            self: MainWindow,
            photo_id: str | None,
            *,
            suppress_signals: bool = False,
            restyle_only: bool = False,
    ) -> None:
        if restyle_only:
            return

        target_row = self._thumbnail_row_for_photo(photo_id)
        if target_row is None:
            return

        if suppress_signals:
            self.thumbnail_list.blockSignals(True)

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
