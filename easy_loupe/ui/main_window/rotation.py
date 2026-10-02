"""
View-only photo rotation workflow for MainWindow.

Rotation is stored with the other per-photo metadata and shares its undo
history, so ``[`` and ``]`` follow the same selection rules as ratings: every
selected photo in culling and browse view, only the active pane in compare
view. Unlike tags, rotation never changes filter membership, sort order, or
card geometry, so refreshes turn existing cards and viewers in place instead of
rebuilding lists.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from easy_loupe.core.rotation import ROTATION_METADATA_FIELD, step_rotation
from easy_loupe.ui.main_window.workflows import MetadataEdit

if TYPE_CHECKING:
    from easy_loupe.ui.main_window.window import MainWindow


class MainWindowRotationMixin:
    """Rotate selected photos for viewing and refresh rotated displays."""

    def _rotate_selection(self: MainWindow, quarter_turns: int) -> None:
        """
        Rotate the resolved selection and save it as one undoable edit.

        Positive ``quarter_turns`` turn clockwise. Each photo keeps its own
        resulting angle, so the undo snapshot stores per-photo values rather
        than one shared value like tag assignments do.
        """
        if (
            self._main_view_frozen_after_move_organize
            or self.current_photo_id is None
        ):
            return

        photo_ids = self._resolved_selection_photo_ids()
        if not photo_ids:
            return

        before = {
            photo_id: self.library.get_photo(photo_id).rotation
            for photo_id in photo_ids
        }
        after = {
            photo_id: step_rotation(rotation, quarter_turns)
            for photo_id, rotation in before.items()
        }
        self._apply_metadata_values(ROTATION_METADATA_FIELD, after)
        self._metadata_undo_stack.append(
            MetadataEdit(
                field=ROTATION_METADATA_FIELD, before=before, after=after
            )
        )
        self._metadata_redo_stack.clear()
        self._save_metadata_or_warn()
        self._refresh_rotated_photos(photo_ids)
        self._refresh_metadata_history_actions()

    def _refresh_rotated_photos(
            self: MainWindow, photo_ids: list[str]
    ) -> None:
        """
        Show new rotations on existing cards, compare panes, and the viewer.

        Rows that are not built (filtered out, or non-cover scene photos in the
        left strip) are skipped; later list rebuilds read the record's
        rotation. The main viewer is turned whenever it holds a rotated photo,
        even while browse or compare hides it: its cached rotation drives every
        reload path (split toggles, Space promotion, the fit reset after scene
        detection), so it must never fall behind the record. Hidden turns are
        cheap because only an item transform changes.
        """
        for photo_id in photo_ids:
            rotation = self.library.get_photo(photo_id).rotation
            # In scene mode ``_thumbnail_photo_rows`` maps stack covers, so a
            # rotated cover also turns its stacked left-strip card.
            self._update_photo_item_rotation(
                self.thumbnail_list,
                self._thumbnail_photo_rows.get(photo_id),
                rotation,
            )
            self._update_photo_item_rotation(
                self.browse_list,
                self._browse_photo_rows.get(photo_id),
                rotation,
            )
            self._update_photo_item_rotation(
                self.scene_list,
                self._scene_photo_rows.get(photo_id),
                rotation,
            )
            if self._compare_mode:
                self.compare_viewer.set_photo_rotation(photo_id, rotation)

        viewer_photo_id = self._viewer_photo_id
        if viewer_photo_id is not None and viewer_photo_id in photo_ids:
            self.viewer.set_rotation(
                self.library.get_photo(viewer_photo_id).rotation
            )
