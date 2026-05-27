"""UI construction and event wiring helpers for :class:`MainWindow`."""

from __future__ import annotations

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

from easy_cull.core.folder_loading import (
    DEFAULT_PHOTO_SORT_MODE,
    DEFAULT_PHOTO_SORT_REVERSED,
    PHOTO_SORT_MODE_CAPTURE_TIME,
    PHOTO_SORT_MODE_FILENAME,
    normalize_sort_mode,
    normalize_sort_reversed,
)
from easy_cull.ui.identity import APP_NAME, APP_VERSION
from easy_cull.ui.theme import NO_METADATA_TEXT
from easy_cull.ui.viewers.compare_photo_viewer import (
    COMPARE_PHOTO_LIMIT_OPTIONS,
    DEFAULT_COMPARE_PHOTO_LIMIT,
    ComparePhotoViewer,
)
from easy_cull.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_cull.ui.widgets import SceneListWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QResizeEvent, QShowEvent

    from easy_cull.ui.main_window.window import MainWindow

VIEWER_KEYBOARD_PAN_STEP = 120
COMPARE_PHOTO_LIMIT_SETTINGS_KEY = 'compare/photo_limit'
PHOTO_SORT_MODE_SETTINGS_KEY = 'photos/sort_mode'
PHOTO_SORT_REVERSED_SETTINGS_KEY = 'photos/sort_reversed'
MIN_SCENE_MERGE_PHOTO_COUNT = 2
TRANSIENT_MESSAGE_FONT_SIZE_PX = 28
TRANSIENT_MESSAGE_FONT_WEIGHT = 600
TRANSIENT_MESSAGE_TIMEOUT_MS = 1600


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

        top_bar = QHBoxLayout()
        top_bar.setSpacing(10)
        root.addLayout(top_bar)
        self._build_top_bar(top_bar)
        self._build_view_mode_ui(root)
        self._build_progress_overlay()
        self._build_transient_message_overlay()
        self._update_progress_overlay_geometry()
        self._update_transient_message_overlay_geometry()
        self._apply_theme()

    def _build_top_bar(self: MainWindow, top_bar: QHBoxLayout) -> None:
        self.open_button = QPushButton('Open Folder')
        self.open_button.clicked.connect(self.choose_folder)
        self.open_button.setToolTip(
            self._shortcut_tooltip('Open Folder', 'Ctrl+O')
        )
        top_bar.addWidget(self.open_button)

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
        self.show_af_point_toggle.setChecked(True)
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

    def _build_view_mode_ui(self: MainWindow, root: QVBoxLayout) -> None:
        content_splitter = QSplitter(Qt.Horizontal)
        self.content_splitter = content_splitter
        root.addWidget(content_splitter, 1)

        self.thumbnail_list = QListWidget()
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

    def _build_progress_overlay(self: MainWindow) -> None:
        self.progress_overlay = QWidget(self.central_widget)
        self.progress_overlay.setObjectName('progressOverlay')
        self.progress_overlay.hide()
        overlay_layout = QVBoxLayout(self.progress_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch(1)
        overlay_center = QHBoxLayout()
        overlay_center.addStretch(1)
        self.progress_panel = QFrame(self.progress_overlay)
        self.progress_panel.setObjectName('progressPanel')
        panel_layout = QVBoxLayout(self.progress_panel)
        panel_layout.setContentsMargins(24, 20, 24, 20)
        panel_layout.setSpacing(14)
        self.overlay_message_label = QLabel('', self.progress_panel)
        self.overlay_message_label.setAlignment(Qt.AlignCenter)
        panel_layout.addWidget(self.overlay_message_label)
        self.overlay_progress_bar = QProgressBar(self.progress_panel)
        self.overlay_progress_bar.setRange(0, 100)
        self.overlay_progress_bar.setFixedWidth(360)
        panel_layout.addWidget(self.overlay_progress_bar)
        overlay_center.addWidget(self.progress_panel)
        overlay_center.addStretch(1)
        overlay_layout.addLayout(overlay_center)
        overlay_layout.addStretch(1)

    def _build_transient_message_overlay(self: MainWindow) -> None:
        self.transient_message_overlay = QWidget(self.central_widget)
        self.transient_message_overlay.setObjectName('transientMessageOverlay')
        self.transient_message_overlay.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents
        )
        self.transient_message_overlay.setFocusPolicy(Qt.NoFocus)
        self.transient_message_overlay.hide()
        overlay_layout = QVBoxLayout(self.transient_message_overlay)
        overlay_layout.setContentsMargins(0, 0, 0, 0)
        overlay_layout.addStretch(1)
        overlay_center = QHBoxLayout()
        overlay_center.addStretch(1)
        self.transient_message_panel = QFrame(self.transient_message_overlay)
        self.transient_message_panel.setObjectName('transientMessagePanel')
        self.transient_message_panel.setFocusPolicy(Qt.NoFocus)
        panel_layout = QVBoxLayout(self.transient_message_panel)
        panel_layout.setContentsMargins(22, 16, 22, 16)
        self.transient_message_label = QLabel('', self.transient_message_panel)
        self.transient_message_label.setAlignment(Qt.AlignCenter)
        self.transient_message_label.setWordWrap(True)
        self.transient_message_label.setFocusPolicy(Qt.NoFocus)
        panel_layout.addWidget(self.transient_message_label)
        overlay_center.addWidget(self.transient_message_panel)
        overlay_center.addStretch(1)
        overlay_layout.addLayout(overlay_center)
        overlay_layout.addStretch(1)
        self.transient_message_timer = QTimer(self)
        self.transient_message_timer.setSingleShot(True)
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
        self._viewer_shortcuts = [
            self._make_shortcut('-', lambda: self._zoom_step(0.8)),
            self._make_shortcut('=', lambda: self._zoom_step(1.25)),
            self._make_shortcut(Qt.Key_Plus, lambda: self._zoom_step(1.25)),
            self._make_shortcut('W', lambda: self._keyboard_pan_by(0, -1)),
            self._make_shortcut('A', lambda: self._keyboard_pan_by(-1, 0)),
            self._make_shortcut('S', lambda: self._keyboard_pan_by(0, 1)),
            self._make_shortcut('D', lambda: self._keyboard_pan_by(1, 0)),
        ]
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
        shortcut = QShortcut(QKeySequence(key), self)
        shortcut.setContext(Qt.WindowShortcut)
        shortcut.activated.connect(lambda: None if self._busy else callback())
        return shortcut

    def _update_mode_shortcuts(self: MainWindow) -> None:
        normal_view_shortcuts_enabled = (
            not self._browse_mode and not self._compare_mode
        )
        viewer_shortcuts_enabled = not self._browse_mode or self._compare_mode
        self.split_mode_shortcut.setEnabled(
            normal_view_shortcuts_enabled or self._compare_mode
        )
        self.browse_mode_shortcut.setEnabled(bool(self.library.photos))
        self.compare_mode_shortcut.setEnabled(
            not self._compare_mode and bool(self.library.photos)
        )
        self.exit_compare_shortcut.setEnabled(
            self._compare_mode or self.transient_message_overlay.isVisible()
        )
        for shortcut in self._viewer_shortcuts:
            shortcut.setEnabled(viewer_shortcuts_enabled)

        for shortcut in self._scene_nav_shortcuts:
            shortcut.setEnabled(normal_view_shortcuts_enabled)

        for shortcut in self._compare_nav_shortcuts:
            shortcut.setEnabled(self._compare_mode)

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
        ):
            self._initial_folder_prompt_pending = False
            QTimer.singleShot(0, self.choose_folder)

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
