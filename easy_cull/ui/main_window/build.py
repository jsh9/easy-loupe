"""UI construction and event wiring helpers for :class:`MainWindow`."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from easy_cull.ui.identity import APP_NAME, APP_VERSION
from easy_cull.ui.theme import NO_METADATA_TEXT
from easy_cull.ui.viewers.main_photo_viewer import MainPhotoViewer
from easy_cull.ui.widgets import SceneListWidget

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtGui import QResizeEvent, QShowEvent
    from PySide6.QtWidgets import QMenu

    from easy_cull.ui.main_window.window import MainWindow


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
        self._update_progress_overlay_geometry()
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

        self.show_af_point_toggle = QCheckBox('Show AF point')
        self.show_af_point_toggle.setChecked(True)
        self.show_af_point_toggle.setToolTip(
            self._shortcut_tooltip('Show AF point', 'F')
        )
        self.show_af_point_toggle.toggled.connect(
            lambda checked: self.viewer.set_focus_point_marker_visible(
                enabled=checked
            )
        )
        top_bar.addWidget(self.show_af_point_toggle)

        self.folder_label = QLabel('Folder: No folder selected')
        self.folder_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.selection_label = QLabel('Selection: Nothing selected')
        self.metadata_label = QLabel(f'Metadata: {NO_METADATA_TEXT}')
        self.metadata_label.setTextFormat(Qt.RichText)
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
        self.thumbnail_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.thumbnail_list.setVerticalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.thumbnail_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.thumbnail_list.currentItemChanged.connect(
            self._left_list_selection_changed
        )
        content_splitter.addWidget(self.thumbnail_list)

        self.viewer = MainPhotoViewer()
        self.viewer.set_focus_point_marker_visible(
            enabled=self.show_af_point_toggle.isChecked()
        )
        self.viewer.visible_region_changed.connect(
            self._refresh_visible_region_overlay
        )
        content_splitter.addWidget(self.viewer)
        content_splitter.setStretchFactor(1, 1)

        self.browse_list = QListWidget()
        self.browse_list.setSpacing(10)
        self.browse_list.setViewMode(QListView.IconMode)
        self.browse_list.setResizeMode(QListView.Adjust)
        self.browse_list.setMovement(QListView.Static)
        self.browse_list.setFlow(QListWidget.LeftToRight)
        self.browse_list.setWrapping(True)
        self.browse_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.browse_list.setVerticalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.browse_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.browse_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.browse_list.currentItemChanged.connect(
            self._browse_list_selection_changed
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
        self.scene_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.scene_list.setHorizontalScrollMode(
            QAbstractItemView.ScrollPerPixel
        )
        self.scene_list.viewport().setFocusPolicy(Qt.StrongFocus)
        self.scene_list.currentItemChanged.connect(
            self._scene_list_selection_changed
        )
        self.scene_list.setVisible(False)
        root.addWidget(self.scene_list)

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

    def _build_menu(self: MainWindow) -> None:
        file_menu = self.menuBar().addMenu('&File')
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

        self.assign_photo_menu = self.menuBar().addMenu('Assign to &Photo')

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

        self.help_menu = self.menuBar().addMenu('&Help')
        self.about_action = QAction(f'About {APP_NAME}', self)
        self.about_action.setMenuRole(QAction.AboutRole)
        self.about_action.triggered.connect(self._show_about_dialog)
        self.help_menu.addAction(self.about_action)

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
        self.browse_mode_shortcut = self._make_shortcut(
            'G', self._enter_browse_mode
        )
        self.split_mode_shortcut = self._make_shortcut(
            Qt.Key_Backslash, self._handle_split_shortcut
        )
        self.show_af_point_shortcut = self._make_shortcut(
            'F', self._toggle_show_af_point
        )
        self._assignment_shortcuts = [
            self._make_shortcut(
                Qt.Key_QuoteLeft, lambda: self._set_color_label(None)
            )
        ]
        self._viewer_shortcuts = [
            self._make_shortcut('-', lambda: self.viewer.zoom_step(0.8)),
            self._make_shortcut('=', lambda: self.viewer.zoom_step(1.25)),
            self._make_shortcut(
                Qt.Key_Plus, lambda: self.viewer.zoom_step(1.25)
            ),
            self._make_shortcut('W', lambda: self.viewer.pan_by(0, -120)),
            self._make_shortcut('A', lambda: self.viewer.pan_by(-120, 0)),
            self._make_shortcut('S', lambda: self.viewer.pan_by(0, 120)),
            self._make_shortcut('D', lambda: self.viewer.pan_by(120, 0)),
        ]
        self._scene_nav_shortcuts = [
            self._make_shortcut(Qt.Key_Left, lambda: self._navigate_scene(-1)),
            self._make_shortcut(Qt.Key_Right, lambda: self._navigate_scene(1)),
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
        shortcuts_enabled = not self._browse_mode
        self.split_mode_shortcut.setEnabled(shortcuts_enabled)
        for shortcut in self._viewer_shortcuts:
            shortcut.setEnabled(shortcuts_enabled)

        for shortcut in self._scene_nav_shortcuts:
            shortcut.setEnabled(shortcuts_enabled)

    def _handle_space_shortcut(self: MainWindow) -> None:
        if self._browse_mode:
            self._exit_browse_mode(force_fit_photo=True)
            return

        self.viewer.toggle_focus_zoom()

    def _handle_split_shortcut(self: MainWindow) -> None:
        if self._browse_mode:
            return

        self.viewer.toggle_split_view()

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

    def resizeEvent(self: MainWindow, event: QResizeEvent) -> None:  # noqa: N802 - Qt API
        """Keep overlay geometry and browse layout in sync with window size."""
        super().resizeEvent(event)
        if hasattr(self, 'progress_overlay'):
            self._update_progress_overlay_geometry()

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
