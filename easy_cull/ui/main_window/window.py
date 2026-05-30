"""Public MainWindow class for EasyCull."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.ui.folder_access import FolderAccessManager
from easy_cull.ui.identity import APP_NAME, easy_cull_icon
from easy_cull.ui.main_window.build import MainWindowBuildMixin
from easy_cull.ui.main_window.compare import MainWindowCompareMixin
from easy_cull.ui.main_window.navigation import (
    MainWindowNavigationMixin,
)
from easy_cull.ui.main_window.presentation import (
    MainWindowPresentationMixin,
)
from easy_cull.ui.main_window.selection import MainWindowSelectionMixin
from easy_cull.ui.main_window.workflows import MainWindowWorkflowMixin
from easy_cull.ui.theme import THEMES

if TYPE_CHECKING:
    from PySide6.QtCore import QThread

    from easy_cull.ui.main_window.dialogs import OrganizerDialogResult
    from easy_cull.ui.main_window.workflows import MetadataEdit, SceneEdit
    from easy_cull.ui.workers import (
        FolderHydrationWorker,
        OperationWorker,
        SceneDetectionWorker,
        ViewerPrefetchWorker,
    )


class MainWindow(
    MainWindowBuildMixin,
    MainWindowWorkflowMixin,
    MainWindowCompareMixin,
    MainWindowSelectionMixin,
    MainWindowNavigationMixin,
    MainWindowPresentationMixin,
    QMainWindow,
):
    """Desktop photo-culling main window and view-state controller."""

    def __init__(self, startup_file: Path | None = None) -> None:  # noqa: PLR0915
        super().__init__()
        self.library = PhotoLibrary()
        self.folder_access_manager = FolderAccessManager()
        self.current_photo_id: str | None = None
        self.current_theme = THEMES['light']
        self._busy = False
        self._photo_viewer_mode = False
        self._photo_viewer_folder_access_granted = True
        self._pending_browse_after_hydration = False
        self._folder_hydration_message = ''
        self._folder_hydration_progress = 0
        self._browse_mode = False
        self._compare_mode = False
        self._compare_restore_browse_mode = False
        self._compare_restore_scene_visible = False
        self._compare_restore_selection_photo_ids: list[str] = []
        self._scene_selection_anchor_row: int | None = None
        self._extending_scene_selection = False

        # Anchor state for app-owned Shift+Up/Down selection in the vertical
        # thumbnail strip. This is separate from scene-strip Shift+Left/Right
        # because the vertical strip selects scene covers/stacks while the
        # horizontal strip selects exact photos within one scene.
        self._thumbnail_selection_anchor_row: int | None = None
        self._extending_thumbnail_selection = False
        self._scene_merge_selection_source: str | None = None
        self._info_overlay_enabled = False
        self._info_overlay_refresh_deferred = False

        # Stores selected non-cover photo IDs from a scene strip that is no
        # longer visible. This is needed because the horizontal scene strip
        # only shows the current scene, so moving to another scene stack
        # rebuilds the strip and would otherwise drop those exact selections.
        self._preserved_scene_selection_photo_ids: set[str] = set()

        self._initial_folder_prompt_pending = True
        self._scene_thread: QThread | None = None
        self._scene_worker: SceneDetectionWorker | None = None
        self._folder_hydration_thread: QThread | None = None
        self._folder_hydration_worker: FolderHydrationWorker | None = None
        self._viewer_prefetch_thread: QThread | None = None
        self._viewer_prefetch_worker: ViewerPrefetchWorker | None = None
        self._operation_thread: QThread | None = None
        self._operation_worker: OperationWorker | None = None
        self._operation_kind: str | None = None
        self._organizer_request: OrganizerDialogResult | None = None
        self._assignment_actions: list[QAction] = []
        self._assignment_shortcuts: list[QShortcut] = []
        self._viewer_shortcuts: list[QShortcut] = []
        self._scene_nav_shortcuts: list[QShortcut] = []
        self._photo_viewer_nav_shortcuts: list[QShortcut] = []
        self._compare_nav_shortcuts: list[QShortcut] = []
        self._browse_photo_rows: dict[str, int] = {}
        self._thumbnail_photo_rows: dict[str, int] = {}
        self._thumbnail_scene_rows: dict[str, int] = {}
        self._scene_photo_rows: dict[str, int] = {}
        self._photo_position_by_id: dict[str, int] = {}
        self._scene_id_by_photo_id: dict[str, str] = {}
        self._scene_by_id: dict[str, object] = {}
        self._scene_list_scene_id: str | None = None
        self._thumbnail_overlay_photo_id: str | None = None
        self._scene_overlay_photo_id: str | None = None
        self._metadata_undo_stack: list[MetadataEdit | SceneEdit] = []
        self._metadata_redo_stack: list[MetadataEdit | SceneEdit] = []

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(easy_cull_icon())
        self.resize(1600, 980)

        self._build_ui()
        self._build_menu()
        self._build_shortcuts()
        if startup_file is not None:
            self._initial_folder_prompt_pending = False
            self._startup_file = Path(startup_file)
        else:
            self._startup_file = None

        self._refresh_ui()

    @staticmethod
    def _shortcut_tooltip(label: str, shortcut: str) -> str:
        native_shortcut = QKeySequence(shortcut).toString(
            QKeySequence.NativeText
        )
        return f'{label} ({native_shortcut})'

    def _background_task_active(self) -> bool:
        """Return True while any background operation thread is active."""
        return (
            self._scene_thread is not None
            or self._folder_hydration_thread is not None
            or self._operation_thread is not None
        )
