"""Background worker threads for the desktop UI."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from easy_loupe.core.photo_library import PhotoLibrary
    from easy_loupe.progress import (
        ProgressSnapshot,
        StructuredProgressCallback,
    )

ProgressCallback = Callable[[str, int], None]
OperationCallable = Callable[..., object]


class _WorkerProgressRouter:
    """Route progress signals while preferring structured snapshots."""

    def __init__(
            self,
            progress_callback: ProgressCallback,
            snapshot_callback: StructuredProgressCallback,
    ) -> None:
        self._progress_callback = progress_callback
        self._snapshot_callback = snapshot_callback
        self._structured_seen = False

    def emit_progress(self, message: str, progress: int) -> None:
        """Emit scalar progress until a structured snapshot is available."""
        if not self._structured_seen:
            self._progress_callback(message, progress)

    def emit_snapshot(self, snapshot: ProgressSnapshot) -> None:
        """
        Emit structured progress and suppress later paired scalar updates.

        ``ProgressReporter`` emits snapshots before legacy tuples, so this flag
        prevents one workflow update from rapidly switching the overlay between
        stage rows and the old aggregate bar.
        """
        self._structured_seen = True
        self._snapshot_callback(snapshot)


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
        progress_router = _WorkerProgressRouter(
            self.progress.emit,
            self.progress_snapshot.emit,
        )
        try:
            result = _call_operation_with_progress(
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
        progress_router = _WorkerProgressRouter(
            self.progress.emit,
            self.progress_snapshot.emit,
        )
        try:
            _call_detect_scenes_with_progress(
                self._library,
                progress_callback=progress_router.emit_progress,
                progress_snapshot_callback=progress_router.emit_snapshot,
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - UI thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit()


def _call_operation_with_progress(
        operation: OperationCallable,
        progress_callback: ProgressCallback,
        progress_snapshot_callback: StructuredProgressCallback,
) -> object:
    """Call operation callables with legacy or structured progress support."""
    try:
        signature = inspect.signature(operation)
    except (TypeError, ValueError):
        return operation(progress_callback)

    # Structured operation callables opt in by parameter name. Do not infer
    # support from positional arity because older callables may use an optional
    # second positional argument for unrelated settings such as dry-run mode.
    if _accepts_keyword_arg(signature, 'progress_snapshot_callback'):
        return operation(
            progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )

    # OperationWorker is intentionally generic; one-callback callables remain
    # valid so older file-operation tests and simple adapters do not fail when
    # structured progress is unavailable.
    return operation(progress_callback)


def _call_detect_scenes_with_progress(
        library: PhotoLibrary,
        *,
        progress_callback: ProgressCallback,
        progress_snapshot_callback: StructuredProgressCallback,
) -> None:
    """Call scene detection on libraries with either progress signature."""
    detect_scenes = library.detect_scenes
    try:
        signature = inspect.signature(detect_scenes)
    except (TypeError, ValueError):
        detect_scenes(
            progress_callback=progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )
        return

    # Real PhotoLibrary instances accept structured snapshots, but small test
    # doubles often expose only the legacy callback. Inspecting here keeps the
    # worker boundary compatible without weakening production progress.
    if _accepts_keyword_arg(signature, 'progress_snapshot_callback'):
        detect_scenes(
            progress_callback=progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )
        return

    detect_scenes(progress_callback=progress_callback)


def _accepts_keyword_arg(signature: inspect.Signature, name: str) -> bool:
    for parameter in signature.parameters.values():
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True

        if parameter.name == name and parameter.kind in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            return True

    return False
