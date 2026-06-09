"""UI construction and event wiring helpers for :class:`MainWindow`."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSettings, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from easy_loupe.core.folder_loading import (
    DEFAULT_PHOTO_SORT_MODE,
    DEFAULT_PHOTO_SORT_REVERSED,
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
    normalize_sort_mode,
    normalize_sort_reversed,
)
from easy_loupe.core.histogram import compute_rgb_histogram
from easy_loupe.core.recursive_loading import (
    DEFAULT_LOAD_RECURSIVELY,
    normalize_load_recursively,
)
from easy_loupe.ui.defaults import DEFAULT_SHOW_AF_POINT
from easy_loupe.ui.identity import APP_NAME, APP_VERSION
from easy_loupe.ui.theme import NO_METADATA_TEXT
from easy_loupe.ui.viewers.compare_photo_viewer import (
    COMPARE_PHOTO_LIMIT_OPTIONS,
    DEFAULT_COMPARE_PHOTO_LIMIT,
    ComparePhotoViewer,
)
from easy_loupe.ui.viewers.exif_overlay import ExifOverlayWidget
from easy_loupe.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_loupe.ui.viewers.shell import (
    VIEWER_KEYBOARD_PAN_STEP,
    build_progress_overlay,
    build_transient_message_overlay,
    build_viewer_shortcuts,
    confirm_reset_zoom_centers,
    exif_overlay_geometry_ready,
    make_window_shortcut,
    update_exif_overlay_geometry,
)
from easy_loupe.ui.widgets import (
    SceneListWidget,
    ThumbnailListWidget,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QCloseEvent, QResizeEvent, QShowEvent

    from easy_loupe.ui.main_window.window import MainWindow

COMPARE_PHOTO_LIMIT_SETTINGS_KEY = 'compare/photo_limit'
PHOTO_SORT_MODE_SETTINGS_KEY = 'photos/sort_mode'
PHOTO_SORT_REVERSED_SETTINGS_KEY = 'photos/sort_reversed'
PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY = 'photos/load_recursively'
MIN_SCENE_MERGE_PHOTO_COUNT = 2
TRANSIENT_MESSAGE_FONT_SIZE_PX = 28
TRANSIENT_MESSAGE_FONT_WEIGHT = 600
TRANSIENT_MESSAGE_TIMEOUT_MS = 1600
INITIAL_FOLDER_PROMPT_GRACE_MS = 250


class MainWindowBuildMixin:
    """Build the MainWindow widget tree, actions, and shortcuts."""

    def _build_ui(self: MainWindow) -> None:
        central_widget = QWidget(self)
        central_widget.setObjectName('appRoot')
        self.setCentralWidget(central_widget)
        self.central_widget = central_widget
        root = QVBoxLayout(central_widget)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        self.top_bar_widget = QWidget(self.central_widget)
        top_bar = QHBoxLayout(self.top_bar_widget)
        top_bar.setContentsMargins(0, 0, 0, 0)
        top_bar.setSpacing(10)
        root.addWidget(self.top_bar_widget)
        self._build_top_bar(top_bar)
        self._build_view_mode_ui(root)
        self._build_progress_overlay()
        self._build_transient_message_overlay()
        self._update_progress_overlay_geometry()
        self._update_transient_message_overlay_geometry()
        self._apply_theme()

    def _build_top_bar(self: MainWindow, top_bar: QHBoxLayout) -> None:
        self._build_photo_open_group(top_bar)

        self.detect_button = QPushButton('Detect Scenes')
        self.detect_button.clicked.connect(self.detect_scenes)
        self.detect_button.setToolTip(
            self._shortcut_tooltip('Detect Scenes', 'Ctrl+D')
        )
        top_bar.addWidget(self.detect_button)

        self.organize_button = QPushButton('Organize')
        self.organize_button.clicked.connect(self.open_organizer_dialog)
        self.organize_button.setToolTip(
            self._shortcut_tooltip('Organize Photos', 'Ctrl+Shift+E')
        )
        top_bar.addWidget(self.organize_button)

        self.theme_toggle = QCheckBox('Dark theme')
        self.theme_toggle.setChecked(False)
        self.theme_toggle.toggled.connect(self._toggle_theme_checked)
        top_bar.addWidget(self.theme_toggle)
        top_bar.addSpacing(6)

        self.show_af_point_toggle = QCheckBox('Show AF point')
        self.show_af_point_toggle.setChecked(DEFAULT_SHOW_AF_POINT)
        self.show_af_point_toggle.setToolTip(
            self._shortcut_tooltip('Show AF point', 'F')
        )
        self.show_af_point_toggle.toggled.connect(
            lambda checked: self._set_focus_point_marker_visible(
                enabled=checked
            )
        )
        top_bar.addWidget(self.show_af_point_toggle)

        top_bar.addSpacing(8)
        self.photo_sort_group = QFrame()
        self.photo_sort_group.setObjectName('photoSortGroup')
        sort_control_row = QHBoxLayout(self.photo_sort_group)
        sort_control_row.setContentsMargins(0, 0, 0, 0)
        sort_control_row.setSpacing(6)
        self.sort_label = QLabel('Sort by:')
        sort_control_row.addWidget(self.sort_label)
        self._build_photo_sort_control(sort_control_row)
        self.photo_sort_reverse_checkbox = QCheckBox('Reverse order')
        self.photo_sort_reverse_checkbox.setObjectName(
            'photoSortReverseCheckbox'
        )
        self.photo_sort_reverse_checkbox.setFocusPolicy(Qt.NoFocus)
        self.photo_sort_reverse_checkbox.setToolTip(
            'Reverse the current sort order'
        )
        self.photo_sort_reverse_checkbox.toggled.connect(
            lambda checked: self._set_photo_sort_reversed(
                checked, persist=True
            )
        )
        sort_control_row.addWidget(self.photo_sort_reverse_checkbox)
        self._set_photo_sort_order(
            self._load_photo_sort_mode(),
            self._load_photo_sort_reversed(),
            persist=False,
        )
        top_bar.addWidget(self.photo_sort_group)
        top_bar.addSpacing(16)

        self.folder_label = QLabel('Folder: No folder selected')
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selection_label = QLabel('Selection: Nothing selected')
        self.metadata_label = QLabel(f'Metadata: {NO_METADATA_TEXT}')
        self.metadata_label.setTextFormat(Qt.RichText)
        for label in (
            self.folder_label,
            self.selection_label,
            self.metadata_label,
        ):
            label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        top_bar.addWidget(self.folder_label, 2)
        top_bar.addWidget(self.selection_label, 1)
        top_bar.addWidget(self.metadata_label, 1)

        self.progress_label = QLabel('')
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedWidth(220)
        top_bar.addWidget(self.progress_label)
        top_bar.addWidget(self.progress_bar)

    def _build_photo_open_group(
            self: MainWindow, target_layout: QHBoxLayout
    ) -> None:
        """Build the framed folder-opening controls in the top bar."""
        self.photo_open_group = QFrame()
        self.photo_open_group.setObjectName('photoOpenGroup')
        open_control_row = QHBoxLayout(self.photo_open_group)
        open_control_row.setContentsMargins(0, 0, 0, 0)
        open_control_row.setSpacing(6)
        self.open_button = QPushButton('Open Folder')
        self.open_button.clicked.connect(self.choose_folder)
        self.open_button.setToolTip(
            self._shortcut_tooltip('Open Folder', 'Ctrl+O')
        )
        open_control_row.addWidget(self.open_button)
        self._build_photo_load_recursively_control(open_control_row)
        target_layout.addWidget(self.photo_open_group)

    def _build_view_mode_ui(self: MainWindow, root: QVBoxLayout) -> None:
        content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter = content_splitter
        root.addWidget(content_splitter, 1)

        self.thumbnail_list = ThumbnailListWidget(self)
        self.thumbnail_list.setMinimumWidth(300)
        self.thumbnail_list.setSpacing(8)
        self.thumbnail_list.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self.thumbnail_list.setVerticalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.thumbnail_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.thumbnail_list.currentItemChanged.connect(
            self._left_list_selection_changed
        )
        self.thumbnail_list.itemSelectionChanged.connect(
            self._list_selection_changed
        )
        self.thumbnail_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.thumbnail_list.customContextMenuRequested.connect(
            self._show_thumbnail_context_menu
        )
        content_splitter.addWidget(self.thumbnail_list)

        self._build_viewer_stack(content_splitter)
        content_splitter.setStretchFactor(1, 1)

        self.browse_list = QListWidget()
        self.browse_list.setSpacing(10)
        self.browse_list.setViewMode(QListView.IconMode)
        self.browse_list.setResizeMode(QListView.Adjust)
        self.browse_list.setMovement(QListView.Static)
        self.browse_list.setFlow(QListWidget.LeftToRight)
        self.browse_list.setWrapping(True)
        self.browse_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.browse_list.setVerticalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.browse_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browse_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.browse_list.currentItemChanged.connect(
            self._browse_list_selection_changed
        )
        self.browse_list.itemSelectionChanged.connect(
            self._list_selection_changed
        )
        self.browse_list.itemDoubleClicked.connect(
            self._browse_item_double_clicked
        )
        self.browse_list.setVisible(False)
        root.addWidget(self.browse_list, 1)

        self.scene_list = SceneListWidget(self)
        self.scene_list.setFlow(QListWidget.LeftToRight)
        self.scene_list.setWrapping(False)
        self.scene_list.setSpacing(8)
        self.scene_list.setFixedHeight(215)
        self.scene_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.scene_list.setHorizontalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.scene_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.scene_list.currentItemChanged.connect(
            self._scene_list_selection_changed
        )
        self.scene_list.itemSelectionChanged.connect(
            self._list_selection_changed
        )
        self.scene_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.scene_list.customContextMenuRequested.connect(
            self._show_scene_context_menu
        )
        self.scene_list.setVisible(False)
        root.addWidget(self.scene_list)

    def _build_viewer_stack(
            self: MainWindow, content_splitter: QSplitter
    ) -> None:
        self.viewer = MainPhotoViewer()
        self.viewer.set_focus_point_marker_visible(
            enabled=self.show_af_point_toggle.isChecked()
        )
        self.viewer.visible_region_changed.connect(
            self._refresh_visible_region_overlay
        )
        self.compare_viewer = ComparePhotoViewer()
        self.compare_viewer.set_focus_point_marker_visible(
            enabled=self.show_af_point_toggle.isChecked()
        )
        self.compare_viewer.active_photo_changed.connect(
            self._compare_active_photo_changed
        )
        self.viewer_stack_widget = QWidget()
        self.viewer_stack = QStackedLayout(self.viewer_stack_widget)
        self.viewer_stack.setContentsMargins(0, 0, 0, 0)
        self.viewer_stack.addWidget(self.viewer)
        self.viewer_stack.addWidget(self.compare_viewer)
        content_splitter.addWidget(self.viewer_stack_widget)
        self.exif_overlay = ExifOverlayWidget(self.viewer_stack_widget)
        self.exif_overlay.hide()
        self.viewer_stack_widget.installEventFilter(self)

    def _build_progress_overlay(self: MainWindow) -> None:
        overlay = build_progress_overlay(self.central_widget)
        self.progress_overlay = overlay.overlay
        self.progress_panel = overlay.panel
        self.overlay_message_label = overlay.message_label
        self.overlay_progress_bar = overlay.progress_bar
        self.progress_stage_list = overlay.stage_list

    def _build_transient_message_overlay(self: MainWindow) -> None:
        overlay = build_transient_message_overlay(
            self.central_widget,
            timer_parent=self,
        )
        self.transient_message_overlay = overlay.overlay
        self.transient_message_panel = overlay.panel
        self.transient_message_label = overlay.message_label
        self.transient_message_timer = overlay.timer
        self.transient_message_timer.timeout.connect(
            self._hide_transient_message
        )

    def _build_menu(self: MainWindow) -> None:
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu('&File')
        self.open_action = QAction('Open Folder', self)
        self.open_action.setShortcut(QKeySequence('Ctrl+O'))
        self.open_action.setShortcutContext(Qt.WindowShortcut)
        self.open_action.triggered.connect(self.choose_folder)
        self.addAction(self.open_action)
        file_menu.addAction(self.open_action)

        self.detect_action = QAction('Detect Scenes', self)
        self.detect_action.setShortcut(QKeySequence('Ctrl+D'))
        self.detect_action.setShortcutContext(Qt.WindowShortcut)
        self.detect_action.setEnabled(False)
        self.detect_action.triggered.connect(self.detect_scenes)
        self.addAction(self.detect_action)
        file_menu.addAction(self.detect_action)

        self.organize_action = QAction('Organize Photos...', self)
        self.organize_action.setShortcut(QKeySequence('Ctrl+Shift+E'))
        self.organize_action.setShortcutContext(Qt.WindowShortcut)
        self.organize_action.setEnabled(False)
        self.organize_action.triggered.connect(self.open_organizer_dialog)
        self.addAction(self.organize_action)
        file_menu.addAction(self.organize_action)

        self.history_menu = menu_bar.addMenu('&History')
        self.undo_metadata_action = QAction('Undo', self)
        self.undo_metadata_action.setShortcut(QKeySequence('Ctrl+Z'))
        self.undo_metadata_action.setShortcutContext(Qt.WindowShortcut)
        self.undo_metadata_action.setEnabled(False)
        self.undo_metadata_action.triggered.connect(
            lambda *_: None if self._busy else self._undo_metadata_edit()
        )
        self.addAction(self.undo_metadata_action)
        self.history_menu.addAction(self.undo_metadata_action)

        self.redo_metadata_action = QAction('Redo', self)
        self.redo_metadata_action.setShortcut(QKeySequence('Ctrl+Y'))
        self.redo_metadata_action.setShortcutContext(Qt.WindowShortcut)
        self.redo_metadata_action.setEnabled(False)
        self.redo_metadata_action.triggered.connect(
            lambda *_: None if self._busy else self._redo_metadata_edit()
        )
        self.addAction(self.redo_metadata_action)
        self.history_menu.addAction(self.redo_metadata_action)

        self.compare_menu = menu_bar.addMenu('&Compare')
        self._build_compare_menu()

        self.scenes_menu = menu_bar.addMenu('&Scenes')
        self.merge_scene_action = QAction(
            'Merge Selected Photos into Scene', self
        )
        self.merge_scene_action.setShortcut(QKeySequence('Ctrl+Shift+M'))
        self.merge_scene_action.setShortcutContext(Qt.WindowShortcut)
        self.merge_scene_action.setEnabled(False)
        self.merge_scene_action.triggered.connect(
            lambda *_: (
                None
                if self._busy
                else self._merge_selected_photos_into_scene()
            )
        )
        self.addAction(self.merge_scene_action)
        self.scenes_menu.addAction(self.merge_scene_action)

        self.assign_photo_menu = menu_bar.addMenu('Assign to &Photo')

        self.rating_menu = self.assign_photo_menu.addMenu('&Rating')
        self.rating_actions = {
            1: self._create_assignment_action(
                self.rating_menu, '1 Star', '1', lambda: self._set_rating(1)
            ),
            2: self._create_assignment_action(
                self.rating_menu, '2 Stars', '2', lambda: self._set_rating(2)
            ),
            3: self._create_assignment_action(
                self.rating_menu, '3 Stars', '3', lambda: self._set_rating(3)
            ),
            4: self._create_assignment_action(
                self.rating_menu, '4 Stars', '4', lambda: self._set_rating(4)
            ),
            5: self._create_assignment_action(
                self.rating_menu, '5 Stars', '5', lambda: self._set_rating(5)
            ),
            None: self._create_assignment_action(
                self.rating_menu,
                'Clear Rating',
                '0',
                lambda: self._set_rating(None),
            ),
        }

        self.color_label_menu = self.assign_photo_menu.addMenu('Color &Label')
        self.color_label_actions = {
            'red': self._create_assignment_action(
                self.color_label_menu,
                'Red',
                '6',
                lambda: self._set_color_label('red'),
            ),
            'yellow': self._create_assignment_action(
                self.color_label_menu,
                'Yellow',
                '7',
                lambda: self._set_color_label('yellow'),
            ),
            'green': self._create_assignment_action(
                self.color_label_menu,
                'Green',
                '8',
                lambda: self._set_color_label('green'),
            ),
            'blue': self._create_assignment_action(
                self.color_label_menu,
                'Blue',
                '9',
                lambda: self._set_color_label('blue'),
            ),
            'purple': self._create_assignment_action(
                self.color_label_menu,
                'Purple',
                None,
                lambda: self._set_color_label('purple'),
            ),
            None: self._create_assignment_action(
                self.color_label_menu,
                'Clear Color Label',
                None,
                lambda: self._set_color_label(None),
                display_shortcut='`',
            ),
        }

        self.flag_menu = self.assign_photo_menu.addMenu('&Flag')
        self.flag_actions = {
            'picked': self._create_assignment_action(
                self.flag_menu, 'Pick', 'P', lambda: self._set_flag('picked')
            ),
            'rejected': self._create_assignment_action(
                self.flag_menu,
                'Reject',
                'X',
                lambda: self._set_flag('rejected'),
            ),
            None: self._create_assignment_action(
                self.flag_menu, 'Clear Flag', 'U', lambda: self._set_flag(None)
            ),
        }

        self.help_menu = menu_bar.addMenu('&Help')
        self.about_action = QAction(f'About {APP_NAME}', self)
        self.about_action.setMenuRole(QAction.AboutRole)
        self.about_action.triggered.connect(self._show_about_dialog)
        self.help_menu.addAction(self.about_action)

    def _build_compare_menu(self: MainWindow) -> None:
        self.compare_limit_menu = self.compare_menu.addMenu('&Limit')
        self.compare_limit_action_group = QActionGroup(self)
        self.compare_limit_action_group.setExclusive(True)
        self.compare_limit_actions: dict[int, QAction] = {}
        for limit in COMPARE_PHOTO_LIMIT_OPTIONS:
            action = QAction(f'{limit} Photos', self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda *_args, selected_limit=limit: (
                    self._set_compare_photo_limit(selected_limit, persist=True)
                )
            )
            self.compare_limit_action_group.addAction(action)
            self.compare_limit_menu.addAction(action)
            self.compare_limit_actions[limit] = action

        self._set_compare_photo_limit(
            self._load_compare_photo_limit(), persist=False
        )

    def _build_photo_sort_control(
            self: MainWindow, target_layout: QHBoxLayout
    ) -> None:
        self.photo_sort_segment = QFrame()
        self.photo_sort_segment.setObjectName('photoSortSegment')
        segment_layout = QHBoxLayout(self.photo_sort_segment)
        segment_layout.setContentsMargins(3, 3, 3, 3)
        segment_layout.setSpacing(2)

        self.photo_sort_button_group = QButtonGroup(self)
        self.photo_sort_button_group.setExclusive(True)
        self.photo_sort_buttons: dict[str, QPushButton] = {}
        button_specs = {
            PHOTO_SORT_MODE_FILENAME: (
                'File Name',
                'Sort photos by file name',
            ),
            PHOTO_SORT_MODE_CAPTURE_TIME: (
                'Capture Time',
                'Sort photos by EXIF capture time',
            ),
        }
        for sort_mode, (label, tooltip) in button_specs.items():
            button = QPushButton(label)
            button.setObjectName('photoSortButton')
            button.setCheckable(True)
            button.setFocusPolicy(Qt.NoFocus)
            button.setToolTip(tooltip)
            button.clicked.connect(
                lambda _checked=False, selected_mode=sort_mode: (
                    self._set_photo_sort_mode(selected_mode, persist=True)
                )
            )
            self.photo_sort_button_group.addButton(button)
            self.photo_sort_buttons[sort_mode] = button
            segment_layout.addWidget(button)

        target_layout.addWidget(self.photo_sort_segment)

    def _build_photo_load_recursively_control(
            self: MainWindow, target_layout: QHBoxLayout
    ) -> None:
        """
        Build and initialize the recursive-loading checkbox.

        Parameters
        ----------
        self : MainWindow
            Main window instance receiving the checkbox attribute.
        target_layout : QHBoxLayout
            Layout that should contain the checkbox.

        Returns
        -------
        None
            The checkbox is attached to ``self`` and added to
            ``target_layout``.
        """
        self.photo_load_recursively_checkbox = QCheckBox('Include subfolders')
        self.photo_load_recursively_checkbox.setObjectName(
            'photoLoadRecursivelyCheckbox'
        )
        self.photo_load_recursively_checkbox.setFocusPolicy(Qt.NoFocus)
        self.photo_load_recursively_checkbox.setToolTip(
            'Load supported photos from subfolders'
        )
        self.photo_load_recursively_checkbox.toggled.connect(
            lambda checked: self._set_photo_load_recursively(
                checked, persist=True
            )
        )
        self._set_photo_load_recursively(
            self._load_photo_load_recursively(), persist=False
        )
        target_layout.addWidget(self.photo_load_recursively_checkbox)

    @staticmethod
    def _settings() -> QSettings:
        return QSettings(APP_NAME, APP_NAME)

    def _load_compare_photo_limit(self: MainWindow) -> int:
        value = self._settings().value(
            COMPARE_PHOTO_LIMIT_SETTINGS_KEY,
            DEFAULT_COMPARE_PHOTO_LIMIT,
        )
        return self.compare_viewer.normalized_photo_limit(value)

    def _load_photo_sort_mode(self: MainWindow) -> str:
        value = self._settings().value(
            PHOTO_SORT_MODE_SETTINGS_KEY,
            DEFAULT_PHOTO_SORT_MODE,
        )
        return normalize_sort_mode(value)

    def _load_photo_sort_reversed(self: MainWindow) -> bool:
        value = self._settings().value(
            PHOTO_SORT_REVERSED_SETTINGS_KEY,
            DEFAULT_PHOTO_SORT_REVERSED,
        )
        return normalize_sort_reversed(value)

    def _load_photo_load_recursively(self: MainWindow) -> bool:
        value = self._settings().value(
            PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY,
            DEFAULT_LOAD_RECURSIVELY,
        )
        return normalize_load_recursively(value)

    def _set_photo_load_recursively(
            self: MainWindow,
            load_recursively: object,
            *,
            persist: bool,
    ) -> None:
        normalized = normalize_load_recursively(load_recursively)
        previous = self.library.load_recursively
        if persist and (self._busy or self._background_task_active()):
            self._check_photo_load_recursively_control(previous)
            return

        if persist and self.library.current_folder is not None:
            if normalized == previous:
                return

            if not self._confirm_recursive_load_reload():
                # Qt has already toggled the checkbox visually. Put it back so
                # the control continues to reflect the still-loaded library.
                self._check_photo_load_recursively_control(previous)
                return

            try:
                self._reload_current_folder_after_recursive_preference_change(
                    load_recursively=normalized
                )
            except Exception as exc:  # noqa: BLE001 - surface reload failures in the UI
                # The persisted preference should not advance if the reload
                # fails; otherwise the next app start would silently use a
                # mode that never successfully loaded in this window.
                self.library.set_load_recursively(previous)
                self._settings().setValue(
                    PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY, previous
                )
                self._check_photo_load_recursively_control(previous)
                self._hide_progress()
                QMessageBox.critical(self, 'Folder Reload Failed', str(exc))
                self._refresh_ui()
                return
        else:
            self.library.set_load_recursively(normalized)

        self._check_photo_load_recursively_control(normalized)
        if persist:
            self._settings().setValue(
                PHOTO_LOAD_RECURSIVELY_SETTINGS_KEY, normalized
            )

    def _confirm_recursive_load_reload(self: MainWindow) -> bool:
        dialog = QMessageBox(self)
        dialog.setWindowTitle('Reload Folder?')
        dialog.setText('Reload current folder?')
        dialog.setInformativeText(
            'Changing Include subfolders requires reloading the current'
            ' folder.'
        )
        reload_button = dialog.addButton(
            'Reload', QMessageBox.ButtonRole.AcceptRole
        )
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        return dialog.clickedButton() is reload_button

    def _set_photo_sort_mode(
            self: MainWindow,
            sort_mode: object,
            *,
            persist: bool,
    ) -> None:
        self._set_photo_sort_order(
            sort_mode,
            self.library.sort_reversed,
            persist=persist,
        )

    def _set_photo_sort_reversed(
            self: MainWindow,
            sort_reversed: object,
            *,
            persist: bool,
    ) -> None:
        self._set_photo_sort_order(
            self.library.sort_mode,
            sort_reversed,
            persist=persist,
        )

    def _set_photo_sort_order(
            self: MainWindow,
            sort_mode: object,
            sort_reversed: object,
            *,
            persist: bool,
    ) -> None:
        normalized_sort_mode = normalize_sort_mode(sort_mode)
        normalized_sort_reversed = normalize_sort_reversed(sort_reversed)
        if persist and (self._busy or self._background_task_active()):
            self._check_photo_sort_control(self.library.sort_mode)
            self._check_photo_sort_reverse_control(self.library.sort_reversed)
            return

        can_refresh_loaded_views = bool(self.library.photos) and hasattr(
            self, 'thumbnail_list'
        )
        selected_photo_ids = (
            self._resolved_selection_photo_ids()
            if can_refresh_loaded_views
            else []
        )
        compared_photo_ids = (
            self.compare_viewer.photo_ids()
            if can_refresh_loaded_views and self._compare_mode
            else []
        )
        active_compare_photo_id = (
            self.compare_viewer.active_photo_id()
            if can_refresh_loaded_views and self._compare_mode
            else None
        )
        self.library.set_sort_order(
            sort_mode=normalized_sort_mode,
            sort_reversed=normalized_sort_reversed,
        )
        self._check_photo_sort_control(normalized_sort_mode)
        self._check_photo_sort_reverse_control(normalized_sort_reversed)

        if persist:
            self._settings().setValue(
                PHOTO_SORT_MODE_SETTINGS_KEY, normalized_sort_mode
            )
            self._settings().setValue(
                PHOTO_SORT_REVERSED_SETTINGS_KEY, normalized_sort_reversed
            )

        if not can_refresh_loaded_views:
            return

        self._rebuild_loaded_views(preserve_current_photo=True)
        if selected_photo_ids:
            # Sorting changes row positions only; restore by photo id so sparse
            # multi-selections survive after the lists are rebuilt.
            self._restore_photo_selection(selected_photo_ids)

        if compared_photo_ids:
            self._refresh_compare_photos_after_sort_change(
                compared_photo_ids,
                active_photo_id=active_compare_photo_id,
            )

        self._restore_active_navigation_focus(defer=True)

    def _check_photo_sort_control(self: MainWindow, sort_mode: object) -> None:
        normalized_sort_mode = normalize_sort_mode(sort_mode)
        button = self.photo_sort_buttons.get(normalized_sort_mode)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def _check_photo_sort_reverse_control(
            self: MainWindow, sort_reversed: object
    ) -> None:
        normalized_sort_reversed = normalize_sort_reversed(sort_reversed)
        if (
            self.photo_sort_reverse_checkbox.isChecked()
            != normalized_sort_reversed
        ):
            self.photo_sort_reverse_checkbox.blockSignals(True)
            self.photo_sort_reverse_checkbox.setChecked(
                normalized_sort_reversed
            )
            self.photo_sort_reverse_checkbox.blockSignals(False)

    def _check_photo_load_recursively_control(
            self: MainWindow, load_recursively: object
    ) -> None:
        normalized = normalize_load_recursively(load_recursively)
        if self.photo_load_recursively_checkbox.isChecked() != normalized:
            self.photo_load_recursively_checkbox.blockSignals(True)
            self.photo_load_recursively_checkbox.setChecked(normalized)
            self.photo_load_recursively_checkbox.blockSignals(False)

    def _set_compare_photo_limit(
            self: MainWindow,
            limit: object,
            *,
            persist: bool,
    ) -> None:
        normalized_limit = self.compare_viewer.set_photo_limit(limit)
        action = self.compare_limit_actions.get(normalized_limit)
        if action is not None and not action.isChecked():
            action.setChecked(True)

        if persist:
            self._settings().setValue(
                COMPARE_PHOTO_LIMIT_SETTINGS_KEY, normalized_limit
            )

        if self._compare_limit_refresh_needed():
            self._show_progress(
                'Re-rendering comparison grid...',
                0,
                show_bar=False,
            )
            QTimer.singleShot(0, self._finish_compare_limit_refresh)

    def _show_about_dialog(self: MainWindow) -> None:
        QMessageBox.about(
            self,
            f'About {APP_NAME}',
            (
                f'{APP_NAME}\n\n'
                f'Version {APP_VERSION}\n\n'
                'Photo culling made easy.'
            ),
        )

    def _build_shortcuts(self: MainWindow) -> None:
        self.space_shortcut = self._make_shortcut(
            Qt.Key_Space, self._handle_space_shortcut
        )
        self.zoom_toggle_shortcut = self._make_shortcut(
            'Z', self._handle_zoom_toggle_shortcut
        )
        self.browse_mode_shortcut = self._make_shortcut(
            'G', self._enter_browse_mode
        )
        self.split_mode_shortcut = self._make_shortcut(
            Qt.Key_Backslash, self._handle_split_shortcut
        )
        self.show_af_point_shortcut = self._make_shortcut(
            'F', self._toggle_show_af_point
        )
        self.recenter_zoom_shortcut = self._make_shortcut(
            'Shift+F', self._handle_recenter_zoom_shortcut
        )
        self.reset_zoom_centers_shortcut = self._make_shortcut(
            'Ctrl+Shift+F', self._handle_reset_zoom_centers_shortcut
        )
        self.info_overlay_shortcut = self._make_shortcut(
            'I', self._toggle_info_overlay
        )
        self.compare_mode_shortcut = self._make_shortcut(
            'C', self._enter_compare_mode
        )
        self.exit_compare_shortcut = self._make_shortcut(
            Qt.Key_Escape, self._handle_escape_shortcut
        )
        self._assignment_shortcuts = [
            self._make_shortcut(
                Qt.Key_QuoteLeft, lambda: self._set_color_label(None)
            )
        ]
        self._viewer_shortcuts = build_viewer_shortcuts(
            self._make_shortcut,
            zoom_step=self._zoom_step,
            keyboard_pan_by=self._keyboard_pan_by,
        )
        self._scene_nav_shortcuts = [
            self._make_shortcut(Qt.Key_Left, lambda: self._navigate_scene(-1)),
            self._make_shortcut(Qt.Key_Right, lambda: self._navigate_scene(1)),
            self._make_shortcut(
                'Shift+Left', lambda: self._extend_scene_selection(-1)
            ),
            self._make_shortcut(
                'Shift+Right', lambda: self._extend_scene_selection(1)
            ),
        ]
        self._compare_nav_shortcuts = [
            self._make_shortcut(
                Qt.Key_Left, lambda: self._move_compare_selection(0, -1)
            ),
            self._make_shortcut(
                Qt.Key_Right, lambda: self._move_compare_selection(0, 1)
            ),
            self._make_shortcut(
                Qt.Key_Up, lambda: self._move_compare_selection(-1, 0)
            ),
            self._make_shortcut(
                Qt.Key_Down, lambda: self._move_compare_selection(1, 0)
            ),
        ]
        self._update_mode_shortcuts()

    def _make_shortcut(
            self: MainWindow,
            key: str | int,
            callback: Callable[[], None],
    ) -> QShortcut:
        return make_window_shortcut(
            self,
            key,
            callback,
            blocked=lambda: self._busy,
        )

    def _update_mode_shortcuts(self: MainWindow) -> None:
        normal_view_shortcuts_enabled = (
            not self._browse_mode and not self._compare_mode
        )
        viewer_shortcuts_enabled = not self._browse_mode or self._compare_mode
        self.split_mode_shortcut.setEnabled(
            normal_view_shortcuts_enabled or self._compare_mode
        )
        can_enter_browse = bool(self.library.photos)
        self.browse_mode_shortcut.setEnabled(can_enter_browse)
        self.compare_mode_shortcut.setEnabled(
            not self._compare_mode and bool(self.library.photos)
        )
        self.recenter_zoom_shortcut.setEnabled(
            normal_view_shortcuts_enabled and bool(self.library.photos)
        )
        self.reset_zoom_centers_shortcut.setEnabled(
            normal_view_shortcuts_enabled and bool(self.library.photos)
        )
        self.info_overlay_shortcut.setEnabled(bool(self.library.photos))
        self.exit_compare_shortcut.setEnabled(
            self._compare_mode or self.transient_message_overlay.isVisible()
        )
        for shortcut in self._viewer_shortcuts:
            shortcut.setEnabled(viewer_shortcuts_enabled)

        for shortcut in self._scene_nav_shortcuts:
            shortcut.setEnabled(normal_view_shortcuts_enabled)

        for shortcut in self._compare_nav_shortcuts:
            shortcut.setEnabled(self._compare_mode)

        self._refresh_assignment_controls()

    def _handle_space_shortcut(self: MainWindow) -> None:
        if self._compare_mode:
            self.compare_viewer.handle_space_shortcut()
            return

        if self._browse_mode:
            self._exit_browse_mode(force_fit_photo=True)
            return

        self.viewer.toggle_focus_zoom()

    def _handle_zoom_toggle_shortcut(self: MainWindow) -> None:
        if self._compare_mode:
            self.compare_viewer.handle_zoom_toggle_shortcut()
            return

        if self._browse_mode:
            return

        self.viewer.toggle_focus_zoom()

    def _handle_split_shortcut(self: MainWindow) -> None:
        if self._compare_mode:
            self._show_transient_message(
                'Split view is not available\nin the Compare mode',
            )
            return

        if self._browse_mode:
            return

        self.viewer.toggle_split_view()

    def _handle_recenter_zoom_shortcut(self: MainWindow) -> None:
        if self._browse_mode or self._compare_mode:
            return

        self.viewer.recenter_manual_view()

    def _handle_reset_zoom_centers_shortcut(self: MainWindow) -> None:
        if self._browse_mode or self._compare_mode:
            return

        if not confirm_reset_zoom_centers(self):
            return

        self.viewer.reset_manual_view_centers()

    def _handle_escape_shortcut(self: MainWindow) -> None:
        if self.transient_message_overlay.isVisible():
            self._hide_transient_message()
            return

        if self._compare_mode and self.compare_viewer.return_to_grid():
            return

        self._exit_compare_mode()

    def _move_compare_selection(
            self: MainWindow, row_delta: int, column_delta: int
    ) -> None:
        if self._compare_mode:
            self.compare_viewer.move_active_selection(row_delta, column_delta)

    def _set_focus_point_marker_visible(
            self: MainWindow, *, enabled: bool
    ) -> None:
        """Apply AF marker visibility to every viewer mode."""
        self.viewer.set_focus_point_marker_visible(enabled=enabled)
        if hasattr(self, 'compare_viewer'):
            self.compare_viewer.set_focus_point_marker_visible(enabled=enabled)

    def _zoom_step(self: MainWindow, multiplier: float) -> None:
        """Route zoom shortcuts to the active viewer mode."""
        if self._compare_mode:
            self.compare_viewer.zoom_step(multiplier)
            return

        self.viewer.zoom_step(multiplier)

    def _keyboard_pan_by(
            self: MainWindow, x_direction: int, y_direction: int
    ) -> None:
        """Pan by the keyboard step for the active viewer mode."""
        base_dx = x_direction * VIEWER_KEYBOARD_PAN_STEP
        base_dy = y_direction * VIEWER_KEYBOARD_PAN_STEP
        if self._compare_mode:
            self.compare_viewer.keyboard_pan_by(base_dx, base_dy)
            return

        self.viewer.keyboard_pan_by(base_dx, base_dy)

    def _toggle_show_af_point(self: MainWindow) -> None:
        """Toggle the autofocus point overlay checkbox."""
        self.show_af_point_toggle.setChecked(
            not self.show_af_point_toggle.isChecked()
        )

    def _toggle_info_overlay(self: MainWindow) -> None:
        """Toggle the EXIF and histogram overlay preference."""
        self._info_overlay_enabled = not self._info_overlay_enabled
        self._refresh_info_overlay()

    def _refresh_info_overlay(
            self: MainWindow, *, allow_defer: bool = True
    ) -> None:
        """Show or hide the EXIF/histogram pane for the active normal photo."""
        if not hasattr(self, 'exif_overlay'):
            return

        if (
            not self._info_overlay_enabled
            or self._busy
            or self._browse_mode
            or self._compare_mode
            or self.current_photo_id is None
            or not self.library.photos
            or self.viewer_stack.currentWidget() is not self.viewer
        ):
            self.exif_overlay.hide()
            return

        photo = self.library.get_photo(self.current_photo_id)
        histogram = None
        try:
            image_path = self.library.get_preview_path(
                photo.photo_id, 'viewer'
            )
            histogram = compute_rgb_histogram(image_path)
        except (OSError, RuntimeError, ValueError):
            histogram = None

        self.exif_overlay.set_content(photo.exif_display, histogram)
        if not self._info_overlay_geometry_ready():
            self.exif_overlay.hide()
            if allow_defer:
                self._defer_info_overlay_refresh()

            return

        self._update_info_overlay_geometry()
        self.exif_overlay.show()
        self.exif_overlay.raise_()

    def _info_overlay_geometry_ready(self: MainWindow) -> bool:
        """Return whether the viewer stack is large enough for the overlay."""
        return exif_overlay_geometry_ready(
            self.viewer_stack_widget, self.exif_overlay
        )

    def _defer_info_overlay_refresh(self: MainWindow) -> None:
        """Retry overlay refresh after Qt has settled the viewer geometry."""
        if self._info_overlay_refresh_deferred:
            return

        self._info_overlay_refresh_deferred = True
        QTimer.singleShot(0, self._finish_deferred_info_overlay_refresh)

    def _finish_deferred_info_overlay_refresh(self: MainWindow) -> None:
        self._info_overlay_refresh_deferred = False
        self._refresh_info_overlay(allow_defer=False)

    def _update_info_overlay_geometry(self: MainWindow) -> None:
        """Anchor the info overlay at the top right of the viewer stack."""
        if not hasattr(self, 'exif_overlay'):
            return

        update_exif_overlay_geometry(
            self.viewer_stack_widget, self.exif_overlay
        )

    def _create_assignment_action(
            self: MainWindow,
            menu: QMenu,
            label: str,
            shortcut: str | None,
            callback: Callable[[], None],
            *,
            display_shortcut: str | None = None,
    ) -> QAction:
        action = QAction(label, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
            action.setShortcutContext(Qt.WindowShortcut)
        elif display_shortcut is not None:
            action.setText(f'{label}\t{display_shortcut}')

        action.triggered.connect(lambda *_: None if self._busy else callback())
        self.addAction(action)
        menu.addAction(action)
        self._assignment_actions.append(action)
        return action

    def _refresh_assignment_controls(self: MainWindow) -> None:
        """Enable assignment controls only in culling-capable modes."""
        enabled = not self._busy
        for action in self._assignment_actions:
            action.setEnabled(enabled)

        for shortcut in self._assignment_shortcuts:
            shortcut.setEnabled(enabled)

    def _update_progress_overlay_geometry(self: MainWindow) -> None:
        """Match the progress overlay to the current central widget bounds."""
        self.progress_overlay.setGeometry(self.central_widget.rect())

    def _update_transient_message_overlay_geometry(self: MainWindow) -> None:
        """Match the transient message overlay to the central widget bounds."""
        self.transient_message_overlay.setGeometry(self.central_widget.rect())

    def _show_transient_message(
            self: MainWindow,
            message: str,
            *,
            timeout_ms: int = TRANSIENT_MESSAGE_TIMEOUT_MS,
    ) -> None:
        self.transient_message_label.setText(message)
        self._update_transient_message_overlay_geometry()
        self.transient_message_overlay.show()
        self.transient_message_overlay.raise_()
        self.transient_message_timer.start(timeout_ms)
        if hasattr(self, 'exit_compare_shortcut'):
            self.exit_compare_shortcut.setEnabled(True)

    def _hide_transient_message(self: MainWindow) -> None:
        self.transient_message_timer.stop()
        self.transient_message_overlay.hide()
        if hasattr(self, 'exit_compare_shortcut'):
            self._update_mode_shortcuts()

    def resizeEvent(self: MainWindow, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        """Keep overlay geometry and browse layout in sync with window size."""
        super().resizeEvent(event)
        if hasattr(self, 'progress_overlay'):
            self._update_progress_overlay_geometry()

        if hasattr(self, 'transient_message_overlay'):
            self._update_transient_message_overlay_geometry()

        if hasattr(self, 'exif_overlay'):
            self._update_info_overlay_geometry()

        if (
            getattr(self, '_browse_mode', False)
            and hasattr(self, 'browse_list')
            and self.browse_list.isVisible()
        ):
            self._refresh_browse_layout()

    def showEvent(self: MainWindow, event: QShowEvent) -> None:  # noqa: N802 - Qt API
        """Trigger the initial folder prompt when the window first shows."""
        super().showEvent(event)
        if (
            self._initial_folder_prompt_pending
            and self.library.current_folder is None
            and not self._initial_folder_prompt_timer.isActive()
        ):
            delay_ms = (
                INITIAL_FOLDER_PROMPT_GRACE_MS
                if sys.platform == 'darwin'
                else 0
            )
            self._initial_folder_prompt_timer.start(delay_ms)

    def _open_initial_folder_if_needed(self: MainWindow) -> None:
        if (
            self._initial_folder_prompt_pending
            and self.library.current_folder is None
        ):
            self._initial_folder_prompt_pending = False
            self.choose_folder()

    def closeEvent(self: MainWindow, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        """Stop pending prompts and wait for background work before closing."""
        self._initial_folder_prompt_pending = False
        self._initial_folder_prompt_timer.stop()
        if self._background_task_active():
            # Qt close would destroy child widgets while worker-thread signals
            # can still be queued. Ignore this event, request shutdown, and let
            # the QThread.finished cleanup path re-enter close once wrappers
            # have been cleared.
            event.ignore()
            self._closing = True
            self._close_after_background_tasks = True
            self._show_progress('Closing...', 0)
            self.overlay_progress_bar.setRange(0, 0)
            self._stop_main_window_background_tasks()
            return

        self._closing = True
        self._close_after_background_tasks = False
        super().closeEvent(event)

    def changeEvent(self: MainWindow, event: QEvent) -> None:  # noqa: N802 - Qt API
        """Restore navigation focus when the main window becomes active."""
        super().changeEvent(event)
        if event.type() != QEvent.ActivationChange:
            return

        if (
            not self.isActiveWindow()
            or self._busy
            or self._background_task_active()
            or not self.library.photos
            or QApplication.activeModalWidget() is not None
            or QApplication.activePopupWidget() is not None
        ):
            return

        QTimer.singleShot(0, self._restore_active_navigation_focus)

    def eventFilter(  # noqa: N802 - Qt API
            self: MainWindow, watched: object, event: QEvent
    ) -> bool:
        """Keep the viewer overlay geometry synchronized with stack resizes."""
        if (
            hasattr(self, 'viewer_stack_widget')
            and watched is self.viewer_stack_widget
            and event.type() == QEvent.Resize
        ):
            self._update_info_overlay_geometry()

        return super().eventFilter(watched, event)
