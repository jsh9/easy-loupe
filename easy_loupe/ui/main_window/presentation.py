"""Presentation, list population, theming, and UI refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from easy_loupe.ui.identity import APP_NAME
from easy_loupe.ui.main_window.build import (
    TRANSIENT_MESSAGE_FONT_SIZE_PX,
    TRANSIENT_MESSAGE_FONT_WEIGHT,
)
from easy_loupe.ui.theme import (
    FLAG_ROLE,
    NO_METADATA_TEXT,
    PHOTO_ID_ROLE,
    SCENE_COUNT_ROLE,
    THEMES,
    metadata_markup,
)
from easy_loupe.ui.widgets import ThumbnailItemWidget

if TYPE_CHECKING:
    from easy_loupe.core.photo_library import PhotoRecord, SceneGroup
    from easy_loupe.ui.main_window.window import MainWindow

MULTI_PHOTO_SELECTION_COUNT = 2


class MainWindowPresentationMixin:
    """List population, presentation refresh, and theming helpers."""

    def _rebuild_scene_lookup(self: MainWindow) -> None:
        self._scene_id_by_photo_id = {}
        self._scene_by_id = {}
        if not self.library.scene_detection_done:
            return

        for scene in self.library.get_scene_groups():
            self._scene_by_id[scene.scene_id] = scene
            for photo_id in scene.photo_ids:
                self._scene_id_by_photo_id[photo_id] = scene.scene_id

    def _scene_for_photo_id(
            self: MainWindow, photo_id: str | None
    ) -> SceneGroup | None:
        if photo_id is None:
            return None

        scene_id = self._scene_id_by_photo_id.get(photo_id)
        if scene_id is None:
            return None

        return self._scene_by_id.get(scene_id)

    def _left_photo_id_for_photo(
            self: MainWindow, photo_id: str | None
    ) -> str | None:
        if photo_id is None:
            return None

        if not self.library.scene_detection_done:
            return photo_id

        scene = self._scene_for_photo_id(photo_id)
        if scene is None or not scene.photo_ids:
            return None

        return scene.photo_ids[0]

    def _thumbnail_row_for_photo(
            self: MainWindow, photo_id: str | None
    ) -> int | None:
        target_photo_id = self._left_photo_id_for_photo(photo_id)
        if target_photo_id is None:
            return None

        if not self.library.scene_detection_done:
            return self._thumbnail_photo_rows.get(target_photo_id)

        scene = self._scene_for_photo_id(photo_id)
        if scene is None:
            return None

        return self._thumbnail_scene_rows.get(scene.scene_id)

    def _refresh_action_controls(
            self: MainWindow, *, photo_actions_enabled: bool
    ) -> None:
        self.detect_button.setEnabled(photo_actions_enabled)
        self.organize_button.setEnabled(photo_actions_enabled)
        if hasattr(self, 'detect_action'):
            self.detect_action.setEnabled(photo_actions_enabled)

        if hasattr(self, 'organize_action'):
            self.organize_action.setEnabled(photo_actions_enabled)

        if hasattr(self, 'merge_scene_action'):
            self.merge_scene_action.setEnabled(
                photo_actions_enabled and not self._compare_mode
            )

        if hasattr(self, 'undo_metadata_action'):
            self._refresh_metadata_history_actions()

    def _refresh_selection_labels(self: MainWindow) -> None:
        if self.current_photo_id is None or not self.library.photos:
            self.selection_label.setText('Selection: Nothing selected')
            self.metadata_label.setText(f'Metadata: {NO_METADATA_TEXT}')
            return

        photo = self.library.get_photo(self.current_photo_id)
        index = self._photo_position_by_id.get(photo.photo_id, 1)
        selected_count = len(self._resolved_selection_photo_ids())
        if self._compare_mode:
            self.selection_label.setText(
                f'Selection: {photo.display_name}'
                f' ({index}/{len(self.library.photos)})'
            )
            self.metadata_label.setText('')
        elif selected_count >= MULTI_PHOTO_SELECTION_COUNT:
            self.selection_label.setText(
                f'Selection: {selected_count} photos'
                f' ({index}/{len(self.library.photos)})'
            )
        else:
            self.selection_label.setText(
                f'Selection: {photo.display_name}'
                f' ({index}/{len(self.library.photos)})'
            )

        symbols = metadata_markup(photo)
        if not self._compare_mode:
            self.metadata_label.setText(
                f'Metadata: {symbols or NO_METADATA_TEXT}'
            )

    def _refresh_window_title(self: MainWindow) -> None:
        """Keep the native title bar aligned with culling mode."""
        self.setWindowTitle(APP_NAME)

    def _refresh_compare_metadata_labels(self: MainWindow) -> None:
        if not self._compare_mode:
            return

        self.compare_viewer.update_metadata_texts({
            photo_id: metadata_markup(self.library.get_photo(photo_id))
            for photo_id in self.compare_viewer.photo_ids()
        })

    def _populate_thumbnail_list(
            self: MainWindow,
            *,
            show_progress: bool = False,
            scroll_current_item_into_view: bool = True,
    ) -> None:
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.clear()
        self._thumbnail_photo_rows = {}
        self._thumbnail_scene_rows = {}

        if not self.library.scene_detection_done:
            self._scene_id_by_photo_id = {}
            self._scene_by_id = {}
            photos = self.library.get_photos()
            total = max(len(photos), 1)
            for index, photo in enumerate(photos, start=1):
                if show_progress:
                    self._show_progress(
                        'Preparing thumbnails',
                        100 + int((index / total) * 100),
                    )

                self._add_photo_item(
                    self.thumbnail_list, photo, frame_size=QSize(220, 165)
                )
                self._thumbnail_photo_rows[photo.photo_id] = index - 1
        else:
            self._rebuild_scene_lookup()
            scenes = self.library.get_scene_groups()
            total = max(len(scenes), 1)
            for index, scene in enumerate(scenes, start=1):
                cover = self.library.get_photo(scene.photo_ids[0])
                scene_count = len(scene.photo_ids)
                all_rejected = scene_count > 1 and all(
                    self.library.get_photo(photo_id).flag == 'rejected'
                    for photo_id in scene.photo_ids
                )
                if show_progress:
                    self._show_progress(
                        'Preparing scene stacks',
                        100 + int((index / total) * 100),
                    )

                self._add_photo_item(
                    self.thumbnail_list,
                    cover,
                    frame_size=QSize(220, 165),
                    display_name=self._scene_display_name(scene)
                    if scene_count > 1
                    else cover.display_name,
                    metadata_text_override='' if scene_count > 1 else None,
                    rejected_override=all_rejected
                    if scene_count > 1
                    else None,
                    scene_count=scene_count if scene_count > 1 else None,
                    stacked=scene_count > 1,
                )
                self._thumbnail_photo_rows[cover.photo_id] = index - 1
                self._thumbnail_scene_rows[scene.scene_id] = index - 1

        self._select_left_item_for_current_photo(
            scroll_into_view=scroll_current_item_into_view
        )
        self.thumbnail_list.blockSignals(False)

    def _populate_browse_list(
            self: MainWindow,
            *,
            show_progress: bool = False,
            scroll_current_item_into_view: bool = True,
    ) -> None:
        self.browse_list.blockSignals(True)
        self.browse_list.clear()
        self._browse_photo_rows = {}
        self._photo_position_by_id = {}

        photos = self.library.get_photos()
        total = max(len(photos), 1)
        for index, photo in enumerate(photos, start=1):
            if show_progress:
                self._show_progress(
                    'Preparing browse grid', 100 + int((index / total) * 100)
                )

            self._add_photo_item(
                self.browse_list, photo, frame_size=QSize(220, 165)
            )
            self._browse_photo_rows[photo.photo_id] = index - 1
            self._photo_position_by_id[photo.photo_id] = index

        self._select_browse_item_for_current_photo(
            scroll_into_view=scroll_current_item_into_view
        )
        self.browse_list.blockSignals(False)
        self._refresh_browse_layout()

    def _select_left_item_for_current_photo(
            self: MainWindow,
            *,
            suppress_signals: bool = False,
            scroll_into_view: bool = True,
    ) -> None:
        target_row = self._thumbnail_row_for_photo(self.current_photo_id)
        if target_row is None:
            return

        if suppress_signals:
            self.thumbnail_list.blockSignals(True)

        self.thumbnail_list.setCurrentRow(target_row)
        if scroll_into_view:
            item = self.thumbnail_list.item(target_row)
            if item is not None:
                self.thumbnail_list.scrollToItem(item)

        if suppress_signals:
            self.thumbnail_list.blockSignals(False)

    def _select_browse_item_for_current_photo(
            self: MainWindow, *, scroll_into_view: bool = True
    ) -> None:
        if self.current_photo_id is None:
            return

        target_row = self._browse_photo_rows.get(self.current_photo_id)
        if target_row is None:
            return

        self.browse_list.setCurrentRow(target_row)
        if scroll_into_view:
            item = self.browse_list.item(target_row)
            if item is not None:
                self.browse_list.scrollToItem(item)

    def _populate_scene_list(self: MainWindow) -> None:
        if (
            not self.library.scene_detection_done
            or self.current_photo_id is None
        ):
            self.scene_list.clear()
            self.scene_list.setVisible(False)
            self._scene_photo_rows = {}
            self._scene_list_scene_id = None
            self._scene_overlay_photo_id = None
            return

        current_scene = self._current_scene()
        if current_scene is None:
            self.scene_list.clear()
            self.scene_list.setVisible(False)
            self._scene_photo_rows = {}
            self._scene_list_scene_id = None
            self._scene_overlay_photo_id = None
            return

        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        self._scene_photo_rows = {}
        self._scene_list_scene_id = current_scene.scene_id
        # Clearing the list discards the widget that owns the overlay. Reset
        # the cached owner so the rebuilt strip is painted from scratch.
        self._scene_overlay_photo_id = None
        for index, photo_id in enumerate(current_scene.photo_ids):
            photo = self.library.get_photo(photo_id)
            self._add_photo_item(
                self.scene_list, photo, frame_size=QSize(160, 120)
            )
            self._scene_photo_rows[photo_id] = index

        current_row = self._scene_photo_rows.get(self.current_photo_id)
        if current_row is not None:
            self.scene_list.setCurrentRow(current_row)

        self.scene_list.blockSignals(False)
        self.scene_list.setVisible(
            not self._browse_mode and not self._compare_mode
        )
        # Photo loading can emit the visible-region signal before this rebuilt
        # strip exists, so reapply the current viewer rectangle now.
        self._refresh_visible_region_overlay(force_full=True)

    def _toggle_theme_checked(
            self: MainWindow,
            checked: bool,  # noqa: FBT001
    ) -> None:
        self.current_theme = THEMES['dark'] if checked else THEMES['light']
        self._apply_theme()

    def _add_photo_item(
            self: MainWindow,
            list_widget: QListWidget,
            photo: PhotoRecord,
            *,
            frame_size: QSize,
            display_name: str | None = None,
            metadata_text_override: str | None = None,
            rejected_override: bool | None = None,
            scene_count: int | None = None,
            stacked: bool = False,
    ) -> None:
        thumb_path = self.library.get_preview_path(photo.photo_id, 'thumb')
        metadata_text = (
            metadata_markup(photo)
            if metadata_text_override is None
            else metadata_text_override
        )
        rejected = (
            photo.flag == 'rejected'
            if rejected_override is None
            else rejected_override
        )
        selected = photo.photo_id == self.current_photo_id
        if (
            list_widget is self.thumbnail_list
            and self.library.scene_detection_done
        ):
            current_scene = self._current_scene()
            selected = (
                current_scene is not None
                and current_scene.photo_ids[0] == photo.photo_id
            )

        widget = ThumbnailItemWidget(
            thumb_path=thumb_path,
            stem=display_name or photo.display_name,
            metadata_text=metadata_text,
            frame_size=frame_size,
            theme=self.current_theme,
            selected=selected,
            current=selected,
            rejected=rejected,
            scene_count=scene_count,
            stacked=stacked,
        )
        item = QListWidgetItem()
        item.setData(PHOTO_ID_ROLE, photo.photo_id)
        item.setData(SCENE_COUNT_ROLE, scene_count)
        item.setData(FLAG_ROLE, 'rejected' if rejected else None)
        item.setToolTip(', '.join(photo.files))
        item.setSizeHint(widget.sizeHint())
        list_widget.addItem(item)
        list_widget.setItemWidget(item, widget)

    def _scene_display_name(self: MainWindow, scene: SceneGroup) -> str:
        if not scene.photo_ids:
            return ''

        first_photo = self.library.get_photo(scene.photo_ids[0]).display_name
        last_photo = self.library.get_photo(scene.photo_ids[-1]).display_name
        if first_photo == last_photo:
            return first_photo

        return f'{first_photo}...{last_photo}'

    def _apply_theme(self: MainWindow) -> None:
        viewer_background = self.current_theme.viewer_background
        ttc = self.current_theme.topbar_text_color
        strip_style = f"""
        QListWidget {{
            background-color: {self.current_theme.strip_background};
            border: none;
            border-radius: 12px;
            outline: none;
        }}
        QListWidget::item {{
            border: none;
        }}
        """
        self.central_widget.setStyleSheet(
            f'QWidget#appRoot {{ background-color: {viewer_background}; }}'
        )
        self.theme_toggle.blockSignals(True)
        self.theme_toggle.setChecked(self.current_theme.name == 'dark')
        self.theme_toggle.blockSignals(False)
        label_style = f'QLabel {{ color: {ttc}; background: transparent; }}'
        button_style = f"""
        QPushButton {{
            color: {self.current_theme.button_text_color};
            background-color: {self.current_theme.button_background};
            border: 1px solid {self.current_theme.button_border};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        QPushButton:disabled {{
            color: #7f8791;
        }}
        """
        if self.current_theme.name == 'dark':
            sort_group_background = 'rgba(0, 123, 255, 14)'
            sort_group_border = '#4f8fd8'
            sort_track_background = 'rgba(0, 123, 255, 28)'
            sort_track_border = '#345f95'
            sort_inactive_text = '#b5c7dc'
        else:
            sort_group_background = 'rgba(0, 123, 255, 10)'
            sort_group_border = '#6aaeff'
            sort_track_background = 'rgba(0, 123, 255, 20)'
            sort_track_border = '#b8d7ff'
            sort_inactive_text = '#4f5a66'

        sort_group_style = f"""
        QFrame#photoSortGroup {{
            background-color: {sort_group_background};
            border: 2px solid {sort_group_border};
            border-radius: 12px;
            padding: 3px 7px;
        }}
        """
        sort_segment_style = f"""
        QFrame#photoSortSegment {{
            background-color: {sort_track_background};
            border: 1px solid {sort_track_border};
            border-radius: 9px;
        }}
        """
        sort_button_style = f"""
        QPushButton#photoSortButton {{
            color: {sort_inactive_text};
            background-color: transparent;
            border: none;
            border-radius: 7px;
            padding: 5px 10px;
            font-weight: 600;
        }}
        QPushButton#photoSortButton:checked {{
            color: #ffffff;
            background-color: #007bff;
        }}
        QPushButton#photoSortButton:disabled {{
            color: #7f8791;
        }}
        """
        self.open_button.setStyleSheet(button_style)
        self.detect_button.setStyleSheet(button_style)
        self.organize_button.setStyleSheet(button_style)
        self.photo_sort_group.setStyleSheet(sort_group_style)
        self.sort_label.setStyleSheet(label_style)
        self.photo_sort_segment.setStyleSheet(sort_segment_style)
        for button in self.photo_sort_buttons.values():
            button.setStyleSheet(sort_button_style)

        self.folder_label.setStyleSheet(label_style)
        self.selection_label.setStyleSheet(label_style)
        self.metadata_label.setStyleSheet(label_style)
        self.progress_label.setStyleSheet(label_style)
        self.overlay_message_label.setStyleSheet(
            f'QLabel {{ color: {ttc}; font-size: 16px; font-weight: 600; }}'
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
                background-color: {self.current_theme.viewer_background};
                border: 1px solid {self.current_theme.button_border};
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
                color: {ttc};
                font-size: {TRANSIENT_MESSAGE_FONT_SIZE_PX}px;
                font-weight: {TRANSIENT_MESSAGE_FONT_WEIGHT};
            }}
            """
        )
        self.transient_message_panel.setStyleSheet(
            f"""
            QFrame#transientMessagePanel {{
                background-color: {self.current_theme.viewer_background};
                border: 1px solid {self.current_theme.button_border};
                border-radius: 12px;
            }}
            """
        )
        self.theme_toggle.setStyleSheet(
            f"""
            QCheckBox {{
                color: {self.current_theme.topbar_text_color};
                font-weight: 600;
                background: transparent;
            }}
            """
        )
        self.show_af_point_toggle.setStyleSheet(self.theme_toggle.styleSheet())
        self.photo_sort_reverse_checkbox.setStyleSheet(
            self.theme_toggle.styleSheet()
        )
        self.thumbnail_list.setStyleSheet(strip_style)
        self.browse_list.setStyleSheet(strip_style)
        self.scene_list.setStyleSheet(strip_style)
        self.viewer.set_theme(self.current_theme)
        self.compare_viewer.set_theme(self.current_theme)
        if hasattr(self, 'exif_overlay'):
            self.exif_overlay.set_theme(self.current_theme)

        self._refresh_item_styles(self.thumbnail_list)
        self._refresh_item_styles(self.browse_list)
        self._refresh_item_styles(self.scene_list)
        self._refresh_strip_items()

    def _is_item_selected(
            self: MainWindow, list_widget: QListWidget, photo_id: str | None
    ) -> bool:
        if photo_id is None:
            return False

        row: int | None
        if list_widget is self.thumbnail_list:
            row = self._thumbnail_row_for_photo(photo_id)
        elif list_widget is self.browse_list:
            row = self._browse_photo_rows.get(photo_id)
        elif list_widget is self.scene_list:
            row = self._scene_photo_rows.get(photo_id)
        else:
            row = None

        if row is None:
            return False

        item = list_widget.item(row)
        return item is not None and item.isSelected()

    def _is_item_current(
            self: MainWindow, list_widget: QListWidget, photo_id: str | None
    ) -> bool:
        if photo_id is None:
            return False

        row: int | None
        if list_widget is self.thumbnail_list:
            row = self._thumbnail_row_for_photo(photo_id)
        elif list_widget is self.browse_list:
            row = self._browse_photo_rows.get(photo_id)
        elif list_widget is self.scene_list:
            row = self._scene_photo_rows.get(photo_id)
        else:
            row = None

        return row is not None and row == list_widget.currentRow()

    def _refresh_item_style_for_photo_id(
            self: MainWindow, list_widget: QListWidget, photo_id: str | None
    ) -> None:
        if photo_id is None:
            return

        row: int | None
        if list_widget is self.thumbnail_list:
            row = self._thumbnail_row_for_photo(photo_id)
        elif list_widget is self.browse_list:
            row = self._browse_photo_rows.get(photo_id)
        elif list_widget is self.scene_list:
            row = self._scene_photo_rows.get(photo_id)
        else:
            row = None

        if row is None:
            return

        item = list_widget.item(row)
        if item is None:
            return

        widget = list_widget.itemWidget(item)
        if not isinstance(widget, ThumbnailItemWidget):
            return

        widget.apply_theme(
            self.current_theme,
            selected=self._is_item_selected(
                list_widget, item.data(PHOTO_ID_ROLE)
            ),
            current=self._is_item_current(
                list_widget, item.data(PHOTO_ID_ROLE)
            ),
            rejected=item.data(FLAG_ROLE) == 'rejected',
        )

    def _refresh_item_styles(
            self: MainWindow, list_widget: QListWidget
    ) -> None:
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            widget = list_widget.itemWidget(item)
            if not isinstance(widget, ThumbnailItemWidget):
                continue

            widget.apply_theme(
                self.current_theme,
                selected=self._is_item_selected(
                    list_widget, item.data(PHOTO_ID_ROLE)
                ),
                current=self._is_item_current(
                    list_widget, item.data(PHOTO_ID_ROLE)
                ),
                rejected=item.data(FLAG_ROLE) == 'rejected',
            )

    def _refresh_selection_styles(
            self: MainWindow,
            previous_photo_id: str | None,
            current_photo_id: str | None,
            source: str,
    ) -> None:
        if source == 'browse':
            for photo_id in {previous_photo_id, current_photo_id}:
                self._refresh_item_style_for_photo_id(
                    self.browse_list, photo_id
                )

        for photo_id in {
            self._left_photo_id_for_photo(previous_photo_id),
            self._left_photo_id_for_photo(current_photo_id),
        }:
            self._refresh_item_style_for_photo_id(
                self.thumbnail_list, photo_id
            )

        if source in {'main', 'scene'} and self.library.scene_detection_done:
            for photo_id in {previous_photo_id, current_photo_id}:
                self._refresh_item_style_for_photo_id(
                    self.scene_list, photo_id
                )

    def _refresh_strip_items(self: MainWindow) -> None:
        self._refresh_item_styles(self.thumbnail_list)
        self._refresh_item_styles(self.browse_list)
        self._refresh_item_styles(self.scene_list)
        self._thumbnail_overlay_photo_id = None
        self._scene_overlay_photo_id = None
        self._refresh_visible_region_overlay(force_full=True)

    def _set_item_overlay_by_photo_id(
            self: MainWindow,
            list_widget: QListWidget,
            photo_id: str | None,
            visible_region: tuple[float, float, float, float] | None,
    ) -> None:
        if photo_id is None:
            return

        row: int | None
        if list_widget is self.thumbnail_list:
            row = self._thumbnail_row_for_photo(photo_id)
        elif list_widget is self.scene_list:
            row = self._scene_photo_rows.get(photo_id)
        else:
            row = None

        if row is None:
            return

        item = list_widget.item(row)
        if item is None:
            return

        widget = list_widget.itemWidget(item)
        if isinstance(widget, ThumbnailItemWidget):
            widget.set_visible_region_overlay(visible_region)

    def _refresh_visible_region_overlay(
            self: MainWindow, *, force_full: bool = False
    ) -> None:
        visible_region = (
            None
            if self._browse_mode or self._compare_mode
            else self.viewer.visible_region_rect()
        )
        thumb_photo_id = (
            None
            if (
                self._browse_mode
                or self._compare_mode
                or self.library.scene_detection_done
            )
            else self.current_photo_id
        )
        scene_photo_id = (
            self.current_photo_id
            if (
                not self._browse_mode
                and not self._compare_mode
                and self.library.scene_detection_done
            )
            else None
        )

        if force_full:
            self._apply_visible_region_overlay(
                self.thumbnail_list, thumb_photo_id, visible_region
            )
            self._apply_visible_region_overlay(self.browse_list, None, None)
            self._apply_visible_region_overlay(
                self.scene_list, scene_photo_id, visible_region
            )
        else:
            if (
                self._thumbnail_overlay_photo_id is not None
                and self._thumbnail_overlay_photo_id != thumb_photo_id
            ):
                self._set_item_overlay_by_photo_id(
                    self.thumbnail_list,
                    self._thumbnail_overlay_photo_id,
                    None,
                )

            if (
                self._scene_overlay_photo_id is not None
                and self._scene_overlay_photo_id != scene_photo_id
            ):
                self._set_item_overlay_by_photo_id(
                    self.scene_list,
                    self._scene_overlay_photo_id,
                    None,
                )

            if thumb_photo_id is not None:
                self._set_item_overlay_by_photo_id(
                    self.thumbnail_list, thumb_photo_id, visible_region
                )

            if scene_photo_id is not None:
                self._set_item_overlay_by_photo_id(
                    self.scene_list, scene_photo_id, visible_region
                )

        self._thumbnail_overlay_photo_id = thumb_photo_id
        self._scene_overlay_photo_id = scene_photo_id

    @staticmethod
    def _apply_visible_region_overlay(
            list_widget: QListWidget,
            target_photo_id: str | None,
            visible_region: tuple[float, float, float, float] | None,
    ) -> None:
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            widget = list_widget.itemWidget(item)
            if not isinstance(widget, ThumbnailItemWidget):
                continue

            overlay = (
                visible_region
                if target_photo_id is not None
                and item.data(PHOTO_ID_ROLE) == target_photo_id
                else None
            )
            widget.set_visible_region_overlay(overlay)

    def _refresh_ui(self: MainWindow) -> None:
        photo_actions_enabled = not self._background_task_active() and bool(
            self.library.photos
        )
        folder_text = (
            str(self.library.current_folder)
            if self.library.current_folder
            else 'No folder selected'
        )
        self.folder_label.setText(f'Folder: {folder_text}')
        self._refresh_window_title()
        self._refresh_action_controls(
            photo_actions_enabled=photo_actions_enabled
        )
        self._refresh_selection_labels()
        if hasattr(self, 'compare_mode_shortcut'):
            self._update_mode_shortcuts()

        if self.current_photo_id is None or not self.library.photos:
            self._refresh_strip_items()
            if not self._browse_mode:
                self._refresh_info_overlay()

            return

        self._refresh_strip_items()
        if not self._browse_mode:
            self._refresh_info_overlay()
