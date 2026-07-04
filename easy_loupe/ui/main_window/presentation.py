"""Presentation, list population, theming, and UI refresh helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QListWidget, QListWidgetItem

from easy_loupe.core.records import SceneGroup
from easy_loupe.ui.identity import APP_NAME
from easy_loupe.ui.main_window.build import (
    TRANSIENT_MESSAGE_FONT_SIZE_PX,
    TRANSIENT_MESSAGE_FONT_WEIGHT,
)
from easy_loupe.ui.main_window.filters import (
    PhotoFilterSelection,
    create_photo_filter_menu,
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
    from PySide6.QtWidgets import QMenu

    from easy_loupe.core.photo_library import PhotoRecord
    from easy_loupe.progress import CountedProgressStage, ProgressReporter
    from easy_loupe.ui.main_window.window import MainWindow

MULTI_PHOTO_SELECTION_COUNT = 2


class MainWindowPresentationMixin:
    """List population, presentation refresh, and theming helpers."""

    def _reset_photo_filter_selection(self: MainWindow) -> None:
        self._photo_filter_selection = PhotoFilterSelection.default()

    def _photo_filter_active(self: MainWindow) -> bool:
        return not self._photo_filter_selection.is_default()

    def _visible_photos(self: MainWindow) -> list[PhotoRecord]:
        return [
            photo
            for photo in self.library.get_photos()
            if self._photo_filter_selection.matches(photo)
        ]

    def _visible_scene_groups(self: MainWindow) -> list[SceneGroup]:
        visible_photo_ids = {
            photo.photo_id for photo in self._visible_photos()
        }
        visible_scenes: list[SceneGroup] = []
        for scene in self.library.get_scene_groups():
            photo_ids = [
                photo_id
                for photo_id in scene.photo_ids
                if photo_id in visible_photo_ids
            ]
            if photo_ids:
                visible_scenes.append(
                    SceneGroup(scene_id=scene.scene_id, photo_ids=photo_ids)
                )

        return visible_scenes

    def _visible_photo_id_after_filter(
            self: MainWindow, preferred_photo_id: str | None
    ) -> str | None:
        visible_photos = self._visible_photos()
        if not visible_photos:
            return None

        visible_photo_ids = {photo.photo_id for photo in visible_photos}
        if preferred_photo_id in visible_photo_ids:
            return preferred_photo_id

        ordered_photos = self.library.get_photos()
        ordered_photo_ids = [photo.photo_id for photo in ordered_photos]
        try:
            preferred_index = ordered_photo_ids.index(preferred_photo_id or '')
        except ValueError:
            return visible_photos[0].photo_id

        for photo in ordered_photos[preferred_index + 1 :]:
            if photo.photo_id in visible_photo_ids:
                return photo.photo_id

        for photo in reversed(ordered_photos[:preferred_index]):
            if photo.photo_id in visible_photo_ids:
                return photo.photo_id

        return visible_photos[0].photo_id

    def _build_photo_filter_menu(self: MainWindow) -> QMenu:
        return create_photo_filter_menu(
            self,
            self._photo_filter_selection,
            self._apply_photo_filter,
        )

    def _show_photo_filter_menu(self: MainWindow) -> None:
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or self._compare_mode
            or self._shortcut_help_modal_active()
            or not self.library.photos
        ):
            return

        menu = self._build_photo_filter_menu()
        menu_position = self.filter_button.mapToGlobal(
            self.filter_button.rect().bottomLeft()
        )
        menu.exec(menu_position)

    def _apply_photo_filter(
            self: MainWindow, selection: PhotoFilterSelection
    ) -> None:
        if (
            self._busy
            or self._main_view_frozen_after_move_organize
            or self._compare_mode
        ):
            return

        if selection == self._photo_filter_selection:
            self._refresh_photo_filter_button()
            return

        self._photo_filter_selection = selection
        self._preserved_scene_selection_photo_ids.clear()
        self._scene_selection_anchor_row = None
        self._thumbnail_selection_anchor_row = None
        self._rebuild_loaded_views(preserve_current_photo=True)
        self._restore_active_navigation_focus(defer=True)

    def _refresh_photo_filter_button(self: MainWindow) -> None:
        if not hasattr(self, 'filter_button'):
            return

        total_count = len(self.library.photos)
        visible_count = len(self._visible_photos()) if total_count else 0
        if self._photo_filter_active():
            self.filter_button.setText(
                f'Filter ({visible_count}/{total_count})'
            )
            self.filter_button.setToolTip(
                f'Showing {visible_count} of {total_count} photos'
            )
        else:
            self.filter_button.setText('Filter')
            self.filter_button.setToolTip(
                'Filter photos by rating, color label, and flag'
            )

        self.filter_button.setEnabled(
            not self._busy
            and not self._main_view_frozen_after_move_organize
            and not self._compare_mode
            and not self._shortcut_help_modal_active()
            and total_count > 0
        )

    def _rebuild_scene_lookup(self: MainWindow) -> None:
        self._scene_id_by_photo_id = {}
        self._scene_by_id = {}
        if not self.library.scene_detection_done:
            return

        for scene in self._visible_scene_groups():
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

    def _thumbnail_overlay_owner_photo_id(self: MainWindow) -> str | None:
        """
        Return the exact photo allowed to paint the vertical strip overlay.

        Scene-mode rows display cover photos, not every exact photo in the
        scene. Non-cover photos therefore keep their minimap on the horizontal
        strip only, so their visible region is not drawn on the wrong preview.
        """
        if (
            self._browse_mode
            or self._compare_mode
            or self.current_photo_id is None
        ):
            return None

        if not self.library.scene_detection_done:
            return self.current_photo_id

        current_scene = self._current_scene()
        if current_scene is None or not current_scene.photo_ids:
            return None

        cover_photo_id = current_scene.photo_ids[0]
        if self.current_photo_id != cover_photo_id:
            return None

        return self.current_photo_id

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
        self._refresh_photo_filter_button()
        self._refresh_file_actions(photo_actions_enabled=photo_actions_enabled)

        self._refresh_merge_scene_action(
            photo_actions_enabled=photo_actions_enabled
        )

        if hasattr(self, 'undo_metadata_action'):
            self._refresh_metadata_history_actions()

    def _refresh_selection_labels(self: MainWindow) -> None:
        if self.current_photo_id is None or not self.library.photos:
            if self.library.photos and not self._visible_photos():
                self.selection_label.setText(
                    'Selection: No photos match filter'
                )
            else:
                self.selection_label.setText('Selection: Nothing selected')

            self.metadata_label.setText(f'Metadata: {NO_METADATA_TEXT}')
            return

        photo = self.library.get_photo(self.current_photo_id)
        index = self._photo_position_by_id.get(photo.photo_id, 1)
        photo_count = (
            len(self._visible_photos())
            if self._photo_filter_active()
            else len(self.library.photos)
        )
        selected_count = len(self._resolved_selection_photo_ids())
        if self._compare_mode:
            self.selection_label.setText(
                f'Selection: {photo.display_name} ({index}/{photo_count})'
            )
            self.metadata_label.setText('')
        elif selected_count >= MULTI_PHOTO_SELECTION_COUNT:
            self.selection_label.setText(
                f'Selection: {selected_count} photos ({index}/{photo_count})'
            )
        else:
            self.selection_label.setText(
                f'Selection: {photo.display_name} ({index}/{photo_count})'
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
            progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self.thumbnail_list.blockSignals(True)
        self.thumbnail_list.clear()
        self._thumbnail_photo_rows = {}
        self._thumbnail_scene_rows = {}

        if not self.library.scene_detection_done:
            self._scene_id_by_photo_id = {}
            self._scene_by_id = {}
            photos = self._visible_photos()
            total = max(len(photos), 1)
            thumbnail_progress = None
            if show_progress:
                thumbnail_progress = self._start_list_population_progress(
                    progress_reporter=progress_reporter,
                    stage_id='thumbnails',
                    label='Preparing thumbnails',
                    total=len(photos),
                )

            for index, photo in enumerate(photos, start=1):
                self._add_photo_item(
                    self.thumbnail_list, photo, frame_size=QSize(220, 165)
                )
                if show_progress:
                    progress = 100 + int((index / total) * 100)
                    self._report_list_population_progress(
                        progress_stage=thumbnail_progress,
                        stage_id='thumbnails',
                        label='Preparing thumbnails',
                        current=index,
                        progress=progress,
                    )

                self._thumbnail_photo_rows[photo.photo_id] = index - 1
        else:
            self._rebuild_scene_lookup()
            scenes = self._visible_scene_groups()
            total = max(len(scenes), 1)
            thumbnail_progress = None
            if show_progress:
                thumbnail_progress = self._start_list_population_progress(
                    progress_reporter=progress_reporter,
                    stage_id='thumbnails',
                    label='Preparing scene stacks',
                    total=len(scenes),
                )

            for index, scene in enumerate(scenes, start=1):
                cover = self.library.get_photo(scene.photo_ids[0])
                scene_count = len(scene.photo_ids)
                all_rejected = scene_count > 1 and all(
                    self.library.get_photo(photo_id).flag == 'rejected'
                    for photo_id in scene.photo_ids
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
                if show_progress:
                    progress = 100 + int((index / total) * 100)
                    self._report_list_population_progress(
                        progress_stage=thumbnail_progress,
                        stage_id='thumbnails',
                        label='Preparing scene stacks',
                        current=index,
                        progress=progress,
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
            progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self.browse_list.blockSignals(True)
        self.browse_list.clear()
        self._browse_photo_rows = {}
        self._photo_position_by_id = {}

        photos = self._visible_photos()
        total = max(len(photos), 1)
        browse_progress = None
        if show_progress:
            browse_progress = self._start_list_population_progress(
                progress_reporter=progress_reporter,
                stage_id='browse',
                label='Preparing browse grid',
                total=len(photos),
            )

        for index, photo in enumerate(photos, start=1):
            self._add_photo_item(
                self.browse_list, photo, frame_size=QSize(220, 165)
            )
            if show_progress:
                progress = 100 + int((index / total) * 100)
                self._report_list_population_progress(
                    progress_stage=browse_progress,
                    stage_id='browse',
                    label='Preparing browse grid',
                    current=index,
                    progress=progress,
                )

            self._browse_photo_rows[photo.photo_id] = index - 1
            self._photo_position_by_id[photo.photo_id] = index

        self._select_browse_item_for_current_photo(
            scroll_into_view=scroll_current_item_into_view
        )
        self.browse_list.blockSignals(False)
        self._refresh_browse_layout()

    @staticmethod
    def _start_list_population_progress(
            *,
            progress_reporter: ProgressReporter | None,
            stage_id: str,
            label: str,
            total: int,
    ) -> CountedProgressStage | None:
        if progress_reporter is None:
            return None

        progress_stage = progress_reporter.counted_stage(
            stage_id,
            label=label,
            total=total,
            start_progress=100,
            end_progress=200,
            zero_progress=100,
        )
        progress_stage.start()
        return progress_stage

    def _report_list_population_progress(
            self: MainWindow,
            *,
            progress_stage: CountedProgressStage | None,
            stage_id: str,
            label: str,
            current: int,
            progress: int,
    ) -> None:
        """
        Report list-population progress after preview-backed work completes.

        ``_add_photo_item`` may render or load a thumbnail through
        ``get_preview_path``. Counts represent completed rows, not the row that
        is about to start.
        """
        del stage_id
        if progress_stage is not None:
            progress_stage.update(current)
            return

        self._show_progress(label, progress)

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

    def _clear_scene_list_for_current_state(self: MainWindow) -> None:
        """
        Clear scene-strip widgets after scene mode becomes ineligible.

        Signals are blocked because stale scene rows can otherwise emit
        selection changes while the list no longer represents the active state.
        The incremental overlay refresh preserves any valid vertical minimap
        while clearing the scene-strip overlay owner.
        """
        # Clear stale scene items without letting Qt emit selection changes
        # from rows that no longer belong to active scene mode.
        self.scene_list.blockSignals(True)
        self.scene_list.clear()
        self.scene_list.blockSignals(False)
        self.scene_list.setVisible(False)
        self._scene_photo_rows = {}
        self._scene_list_scene_id = None
        self._scene_overlay_photo_id = None
        # The scene strip was removed, so clear only the cached scene overlay
        # owner and let the incremental path preserve any valid vertical
        # thumbnail overlay without scanning the browse grid.
        self._refresh_visible_region_overlay()

    def _populate_scene_list(self: MainWindow) -> None:
        """
        Rebuild the horizontal strip for the current detected scene.

        The scene strip owns exact in-scene photo rows, so it must be rebuilt
        when the current scene changes. Overlay ownership is refreshed after
        rebuilding because the old thumbnail widgets have been discarded.
        """
        if (
            not self.library.scene_detection_done
            or self.current_photo_id is None
        ):
            self._clear_scene_list_for_current_state()
            return

        current_scene = self._current_scene()
        if current_scene is None:
            self._clear_scene_list_for_current_state()
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
        # Rebuilding replaced the widgets that can own scene-strip overlays.
        # Reapply the viewer rectangle through the incremental path so scene
        # navigation does not perform a full browse-grid overlay pass.
        self._refresh_visible_region_overlay()

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
        widget.image_position_clicked.connect(
            lambda x, y, source_list=list_widget, photo_id=photo.photo_id: (
                self._handle_thumbnail_image_clicked(
                    source_list, photo_id, x, y
                )
            )
        )
        widget.image_position_dragged.connect(
            lambda x, y, source_list=list_widget, photo_id=photo.photo_id: (
                self._handle_thumbnail_image_dragged(
                    source_list, photo_id, x, y
                )
            )
        )
        widget.visible_region_center_requested.connect(
            lambda x, y, source_list=list_widget, photo_id=photo.photo_id: (
                self._handle_minimap_center_requested(
                    source_list, photo_id, x, y
                )
            )
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
        QPushButton,
        QToolButton {{
            color: {self.current_theme.button_text_color};
            background-color: {self.current_theme.button_background};
            border: 1px solid {self.current_theme.button_border};
            border-radius: 6px;
            padding: 6px 12px;
        }}
        QPushButton:disabled,
        QToolButton:disabled {{
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
        QFrame#photoOpenGroup,
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
        self.filter_button.setStyleSheet(button_style)
        self.photo_open_group.setStyleSheet(sort_group_style)
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
        self.progress_stage_list.setStyleSheet(
            f"""
            QLabel#progressStageLabel {{
                color: {ttc};
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#progressStageCount {{
                color: {ttc};
                font-size: 13px;
            }}
            """
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
        self._apply_transient_message_overlay_theme(ttc)
        self._apply_move_organize_frozen_overlay_theme(ttc)
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
        self.show_clipping_toggle.setStyleSheet(self.theme_toggle.styleSheet())
        self.photo_load_recursively_checkbox.setStyleSheet(
            self.theme_toggle.styleSheet()
        )
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

    def _apply_transient_message_overlay_theme(
            self: MainWindow, text_color: str
    ) -> None:
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
                color: {text_color};
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

    def _apply_move_organize_frozen_overlay_theme(
            self: MainWindow, text_color: str
    ) -> None:
        self.move_organize_frozen_overlay.setStyleSheet(
            """
            QWidget#moveOrganizeFrozenOverlay {
                background-color: rgba(20, 24, 29, 125);
            }
            """
        )
        self.move_organize_frozen_panel.setStyleSheet(
            f"""
            QFrame#moveOrganizeFrozenPanel {{
                background-color: {self.current_theme.viewer_background};
                border: 1px solid {self.current_theme.button_border};
                border-radius: 12px;
            }}
            """
        )
        self.move_organize_frozen_title_label.setStyleSheet(
            f"""
            QLabel#moveOrganizeFrozenTitle {{
                color: {text_color};
                font-size: 18px;
                font-weight: 700;
                background: transparent;
            }}
            """
        )
        self.move_organize_frozen_detail_label.setStyleSheet(
            f"""
            QLabel#moveOrganizeFrozenDetail {{
                color: {text_color};
                font-size: 14px;
                font-weight: 500;
                background: transparent;
            }}
            """
        )

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

    def _handle_thumbnail_image_clicked(
            self: MainWindow,
            list_widget: QListWidget,
            photo_id: str,
            x: float,
            y: float,
    ) -> None:
        """
        Remember a spatial thumbnail click until normal selection completes.

        The preview widget must not consume non-overlay clicks because Qt still
        owns list selection. This stores the clicked image point so the later
        current-item handler can move the newly displayed zoomed photo there.
        """
        if (
            self._browse_mode
            or self._compare_mode
            or self.viewer.visible_region_rect() is None
        ):
            self._pending_thumbnail_click_center = None
            return

        if list_widget not in {self.thumbnail_list, self.scene_list}:
            self._pending_thumbnail_click_center = None
            return

        if list_widget is self.scene_list and not (
            self.library.scene_detection_done
        ):
            self._pending_thumbnail_click_center = None
            return

        self._pending_thumbnail_click_center = (
            list_widget,
            photo_id,
            (x, y),
        )

    def _handle_thumbnail_image_dragged(
            self: MainWindow,
            list_widget: QListWidget,
            photo_id: str,
            x: float,
            y: float,
    ) -> None:
        """
        Continue a spatial thumbnail click as a held-button pan gesture.

        The first press may still be waiting for Qt's selection change. While
        that happens, keep the pending center fresh; after selection, route
        drag updates directly to the now-current zoomed photo.
        """
        if (
            self._browse_mode
            or self._compare_mode
            or self.viewer.visible_region_rect() is None
        ):
            self._pending_thumbnail_click_center = None
            return

        if list_widget not in {self.thumbnail_list, self.scene_list}:
            self._pending_thumbnail_click_center = None
            return

        if list_widget is self.scene_list and not (
            self.library.scene_detection_done
        ):
            self._pending_thumbnail_click_center = None
            return

        if photo_id == self.current_photo_id:
            # Selection has caught up to the pressed thumbnail, so future drag
            # positions can directly pan the active viewer instead of waiting
            # in the pending handoff slot used for the initial press.
            self._pending_thumbnail_click_center = None
            self.viewer.set_normalized_viewport_center((x, y))
            return

        pending = self._pending_thumbnail_click_center
        if pending is None:
            return

        pending_widget, pending_photo_id, _center = pending
        if pending_widget is list_widget and pending_photo_id == photo_id:
            # Qt may deliver a move before currentItemChanged finishes loading
            # the new photo. Keep only the latest cursor position so the first
            # displayed view lands where the user is actually holding.
            self._pending_thumbnail_click_center = (
                list_widget,
                photo_id,
                (x, y),
            )
        else:
            self._pending_thumbnail_click_center = None

    def _handle_minimap_center_requested(
            self: MainWindow,
            list_widget: QListWidget,
            photo_id: str,
            x: float,
            y: float,
    ) -> None:
        """
        Route an active minimap request to the zoomed viewer.

        Thumbnail widgets emit generic normalized coordinates. MainWindow must
        still enforce which visible-region overlay owns the request so stale,
        hidden, browse-grid, or compare-mode thumbnails cannot pan the viewer.
        """
        if (
            self._browse_mode
            or self._compare_mode
            or self.viewer.visible_region_rect() is None
        ):
            return

        if list_widget is self.thumbnail_list:
            if photo_id != self._thumbnail_overlay_owner_photo_id():
                return
        elif list_widget is self.scene_list:
            if (
                not self.library.scene_detection_done
                or photo_id != self.current_photo_id
            ):
                return
        else:
            return

        self.viewer.set_normalized_viewport_center((x, y))

    def _refresh_visible_region_overlay(
            self: MainWindow, *, force_full: bool = False
    ) -> None:
        """
        Refresh strip minimap overlays after viewer or list state changes.

        ``force_full`` is reserved for broad restyles/rebuilds where any list
        item may hold stale overlay state. Normal scene-strip rebuilds use the
        cached-owner path to clear and repaint only affected rows.
        """
        visible_region = (
            None
            if self._browse_mode or self._compare_mode
            else self.viewer.visible_region_rect()
        )
        thumb_photo_id = self._thumbnail_overlay_owner_photo_id()
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
        photo_actions_enabled = (
            not self._background_task_active()
            and bool(self.library.photos)
            and not self._main_view_frozen_after_move_organize
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

        self._refresh_move_organize_frozen_overlay()
        if self.current_photo_id is None or not self.library.photos:
            self._refresh_strip_items()
            if not self._browse_mode:
                self._refresh_info_overlay()

            return

        self._refresh_strip_items()
        if not self._browse_mode:
            self._refresh_info_overlay()
