"""
Compare-mode entry, exit, and active-photo helpers.

This mixin is tested through ``MainWindow`` compare-mode behavior rather than
direct unit tests. Its methods coordinate real widgets, shortcuts, selection
state, and viewer state, so direct mixin tests would duplicate implementation
details while missing the integration boundary users actually exercise.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt

from easy_loupe.ui.theme import metadata_markup
from easy_loupe.ui.viewers.compare_photo_viewer import (
    MIN_COMPARE_PHOTO_COUNT,
    ComparePhoto,
)

if TYPE_CHECKING:
    from easy_loupe.ui.main_window.window import MainWindow


class MainWindowCompareMixin:
    """Compare-mode handlers for MainWindow."""

    def _compare_active_photo_changed(self: MainWindow, photo_id: str) -> None:
        self.current_photo_id = photo_id
        self._refresh_selection_labels()

    def _enter_compare_mode(self: MainWindow) -> None:
        if (
            self._compare_mode
            or self._busy
            or self._main_view_frozen_after_move_organize
            or not self.library.photos
        ):
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

        self._compare_mode = True
        self.compare_viewer.set_photos(
            self._compare_photos_for_photo_ids(photo_ids)
        )
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
        self._refresh_info_overlay()
        self._update_mode_shortcuts()
        self.compare_viewer.setFocus(Qt.OtherFocusReason)

    def _compare_photos_for_photo_ids(
            self: MainWindow,
            photo_ids: list[str],
    ) -> list[ComparePhoto]:
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
                    metadata_text=metadata_markup(photo),
                )
            )

        return compare_photos

    def _refresh_compare_photos_for_limit(self: MainWindow) -> None:
        if not self._compare_mode:
            return

        refresh_plan = self._compare_limit_refresh_plan()
        if refresh_plan is None:
            return

        photo_ids, next_active_photo_id = refresh_plan
        self.compare_viewer.set_photos(
            self._compare_photos_for_photo_ids(photo_ids),
            active_photo_id=next_active_photo_id,
        )
        refreshed_active_photo_id = self.compare_viewer.active_photo_id()
        if refreshed_active_photo_id is not None:
            self.current_photo_id = refreshed_active_photo_id

        self._refresh_selection_labels()
        self._refresh_visible_region_overlay(force_full=True)
        self.compare_viewer.setFocus(Qt.OtherFocusReason)

    def _refresh_compare_photos_after_sort_change(
            self: MainWindow,
            compared_photo_ids: list[str],
            *,
            active_photo_id: str | None,
    ) -> None:
        if not self._compare_mode:
            return

        ordered_photo_ids = self._photo_ids_in_library_order(
            compared_photo_ids
        )
        if len(ordered_photo_ids) < MIN_COMPARE_PHOTO_COUNT:
            return

        if self._compare_restore_selection_photo_ids:
            # The full restore selection remains the same set, but future
            # compare-limit changes should expand from the active sort order.
            self._compare_restore_selection_photo_ids = (
                self._photo_ids_in_library_order(
                    self._compare_restore_selection_photo_ids
                )
            )

        next_active_photo_id = (
            active_photo_id
            if active_photo_id in ordered_photo_ids
            else ordered_photo_ids[0]
        )
        self.compare_viewer.set_photos(
            self._compare_photos_for_photo_ids(ordered_photo_ids),
            active_photo_id=next_active_photo_id,
            preserve_selected_view_state=True,
        )
        refreshed_active_photo_id = self.compare_viewer.active_photo_id()
        if refreshed_active_photo_id is not None:
            self.current_photo_id = refreshed_active_photo_id

        self._refresh_selection_labels()
        self._refresh_visible_region_overlay(force_full=True)
        self.compare_viewer.setFocus(Qt.OtherFocusReason)

    def _reconcile_compare_photos_after_filter_change(
            self: MainWindow,
    ) -> None:
        """
        Keep compare mode aligned with an active metadata filter.

        Metadata shortcuts can hide the active compare photo while the normal
        lists are already rebuilt from filtered rows. Prune the separate
        compare grid before the user exits it so stale hidden IDs cannot be
        restored into the main viewer or selection state.
        """
        if not self._compare_mode or not self._photo_filter_active():
            return

        visible_photo_ids = {
            photo.photo_id for photo in self._visible_photos()
        }
        compared_photo_ids = self.compare_viewer.photo_ids()
        visible_compared_photo_ids = [
            photo_id
            for photo_id in compared_photo_ids
            if photo_id in visible_photo_ids
        ]
        self._compare_restore_selection_photo_ids = [
            photo_id
            for photo_id in self._compare_restore_selection_photo_ids
            if photo_id in visible_photo_ids
        ]
        active_photo_id = self.compare_viewer.active_photo_id()
        # Use the active photo's old grid position when picking a replacement
        # so keyboard users continue from the same visual compare location.
        active_index = (
            compared_photo_ids.index(active_photo_id)
            if active_photo_id in compared_photo_ids
            else 0
        )
        if len(visible_compared_photo_ids) < MIN_COMPARE_PHOTO_COUNT:
            self._exit_compare_mode()
            return

        next_active_photo_id = (
            active_photo_id
            if active_photo_id in visible_compared_photo_ids
            else visible_compared_photo_ids[
                min(active_index, len(visible_compared_photo_ids) - 1)
            ]
        )
        self.compare_viewer.set_photos(
            self._compare_photos_for_photo_ids(visible_compared_photo_ids),
            active_photo_id=next_active_photo_id,
            preserve_selected_view_state=True,
        )
        refreshed_active_photo_id = self.compare_viewer.active_photo_id()
        if refreshed_active_photo_id is not None:
            self.current_photo_id = refreshed_active_photo_id

        self._refresh_selection_labels()
        self._refresh_visible_region_overlay(force_full=True)
        self.compare_viewer.setFocus(Qt.OtherFocusReason)

    def _compare_limit_refresh_needed(self: MainWindow) -> bool:
        return self._compare_limit_refresh_plan() is not None

    def _compare_limit_refresh_plan(
            self: MainWindow,
    ) -> tuple[list[str], str] | None:
        if not self._compare_mode:
            return None

        restore_photo_ids = (
            list(self._compare_restore_selection_photo_ids)
            or self.compare_viewer.photo_ids()
        )
        photo_ids = restore_photo_ids[: self.compare_viewer.photo_limit]
        if len(photo_ids) < MIN_COMPARE_PHOTO_COUNT:
            return None

        active_photo_id = self.compare_viewer.active_photo_id()
        next_active_photo_id = (
            active_photo_id if active_photo_id in photo_ids else photo_ids[-1]
        )
        if (
            self.compare_viewer.photo_ids() == photo_ids
            and active_photo_id == next_active_photo_id
        ):
            return None

        return photo_ids, next_active_photo_id

    def _finish_compare_limit_refresh(self: MainWindow) -> None:
        try:
            self._refresh_compare_photos_for_limit()
        finally:
            self._hide_progress()

    def _exit_compare_mode(
            self: MainWindow, *, restore_previous: bool = True
    ) -> None:
        if not self._compare_mode:
            return

        restore_browse_mode = self._compare_restore_browse_mode
        restore_scene_visible = self._compare_restore_scene_visible
        restore_photo_ids = list(self._compare_restore_selection_photo_ids)
        compared_photo_ids = self.compare_viewer.photo_ids()
        active_photo_id = self.compare_viewer.active_photo_id()
        selection_photo_ids = restore_photo_ids or compared_photo_ids
        if self._photo_filter_active():
            # Compare exit normally restores the pre-compare selection. Under a
            # filter, hidden IDs must be removed first or Esc can redisplay the
            # photo that a just-applied metadata edit intentionally hid.
            visible_photo_ids = {
                photo.photo_id for photo in self._visible_photos()
            }
            selection_photo_ids = [
                photo_id
                for photo_id in selection_photo_ids
                if photo_id in visible_photo_ids
            ]
            if active_photo_id not in visible_photo_ids:
                active_photo_id = None

        if active_photo_id in selection_photo_ids:
            self.current_photo_id = active_photo_id
        elif selection_photo_ids:
            if self.current_photo_id not in selection_photo_ids:
                self.current_photo_id = selection_photo_ids[0]
        elif self._photo_filter_active():
            self.current_photo_id = self._visible_photo_id_after_filter(
                self.current_photo_id
            )

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
            self._refresh_info_overlay()
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

            # Compare updates ``current_photo_id`` while the normal viewer is
            # hidden. Reload that viewer in fit mode so the next Space press
            # zooms the same photo that overlay ownership will target.
            self._display_current_photo(force_fit=True)

        self._refresh_ui()
        if selection_photo_ids:
            self._restore_photo_selection(selection_photo_ids)

        if not restore_browse_mode:
            # Restoring selected flags does not make the strip current row
            # follow ``current_photo_id``. Move the current index without
            # clearing selection so focus styling and minimap ownership stay
            # aligned with the active compare photo.
            self._sync_left_list_for_photo(
                self.current_photo_id,
                suppress_signals=True,
                preserve_selection=True,
            )
            self._refresh_item_styles(self.thumbnail_list)
            if self.library.scene_detection_done:
                self._refresh_item_styles(self.scene_list)

        self._refresh_visible_region_overlay(force_full=True)
        self._refresh_info_overlay()
        self._update_mode_shortcuts()
        self._restore_active_navigation_focus(defer=True)
