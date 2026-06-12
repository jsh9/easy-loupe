"""Background worker threads for the desktop UI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

from easy_loupe.ui.progress_routing import (
    OperationCallable,
    WorkerProgressRouter,
    call_detect_scenes_with_progress,
    call_operation_with_progress,
)

if TYPE_CHECKING:
    from easy_loupe.core.photo_library import PhotoLibrary


class OperationWorker(QObject):
    """Generic background worker for file-organization tasks."""

    progress = Signal(str, int)
    progress_snapshot = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: OperationCallable) -> None:
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        """Run an operation and emit its result or failure text."""
        progress_router = WorkerProgressRouter(
            self.progress.emit,
            self.progress_snapshot.emit,
        )
        try:
            result = call_operation_with_progress(
                self._operation,
                progress_router.emit_progress,
                progress_router.emit_snapshot,
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - UI thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit(result)


class SceneDetectionWorker(QObject):
    """Background scene-detection worker with progress signals."""

    progress = Signal(str, int)
    progress_snapshot = Signal(object)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, library: PhotoLibrary) -> None:
        super().__init__()
        self._library = library

    def run(self) -> None:
        """Run scene detection and translate failures into worker signals."""
        progress_router = WorkerProgressRouter(
            self.progress.emit,
            self.progress_snapshot.emit,
        )
        try:
            call_detect_scenes_with_progress(
                self._library,
                progress_callback=progress_router.emit_progress,
                progress_snapshot_callback=progress_router.emit_snapshot,
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - UI thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit()
