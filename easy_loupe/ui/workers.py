"""Background worker threads for the desktop UI."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from easy_loupe.core.photo_library import PhotoLibrary

ProgressCallback = Callable[[str, int], None]
OperationCallable = Callable[[ProgressCallback], object]


class OperationWorker(QObject):
    """Generic background worker for file-organization tasks."""

    progress = Signal(str, int)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: OperationCallable) -> None:
        super().__init__()
        self._operation = operation

    def run(self) -> None:
        """Run an operation and emit its result or failure text."""
        try:
            result = self._operation(self.progress.emit)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - UI thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit(result)


class SceneDetectionWorker(QObject):
    """Background scene-detection worker with progress signals."""

    progress = Signal(str, int)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, library: PhotoLibrary) -> None:
        super().__init__()
        self._library = library

    def run(self) -> None:
        """Run scene detection and translate failures into worker signals."""
        try:
            self._library.detect_scenes(progress_callback=self.progress.emit)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - UI thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit()
