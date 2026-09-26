"""Worker progress callback routing and signature adapters."""

from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from easy_loupe.progress.callbacks import accepts_keyword_argument

if TYPE_CHECKING:
    from easy_loupe.core.photo_library import PhotoLibrary
    from easy_loupe.progress import (
        ProgressSnapshot,
        StructuredProgressCallback,
    )

ProgressCallback = Callable[[str, int], None]
OperationCallable = Callable[..., object]
StageSignature = tuple[tuple[object, ...], ...]

# Minimum spacing between forwarded same-stage snapshots. Fast loops such as
# scene grouping report once per photo within microseconds, and forwarding
# each one would queue a redundant overlay render per photo on the GUI thread.
WORKER_SNAPSHOT_MIN_INTERVAL_S = 0.05


class WorkerProgressRouter:
    """Route progress signals while preferring structured snapshots."""

    def __init__(
            self,
            progress_callback: ProgressCallback,
            snapshot_callback: StructuredProgressCallback,
            *,
            min_snapshot_interval_s: float = WORKER_SNAPSHOT_MIN_INTERVAL_S,
            clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._progress_callback = progress_callback
        self._snapshot_callback = snapshot_callback
        self._structured_seen = False
        self._min_snapshot_interval_s = min_snapshot_interval_s
        self._clock = clock
        self._last_snapshot_at: float | None = None
        self._last_stage_signature: StageSignature | None = None

    def emit_progress(self, message: str, progress: int) -> None:
        """Emit scalar progress until a structured snapshot is available."""
        if not self._structured_seen:
            self._progress_callback(message, progress)

    def emit_snapshot(self, snapshot: ProgressSnapshot) -> None:
        """
        Emit structured progress and suppress later paired scalar updates.

        ``ProgressReporter`` emits snapshots before legacy tuples, so this flag
        prevents one workflow update from rapidly switching the overlay between
        stage rows and the old aggregate bar. The flag is set even when a
        redundant snapshot is dropped so its paired tuple stays suppressed.
        """
        self._structured_seen = True
        now = self._clock()
        signature = _stage_signature(snapshot)
        if self._is_redundant_snapshot(snapshot, signature, now):
            return

        self._last_snapshot_at = now
        self._last_stage_signature = signature
        self._snapshot_callback(snapshot)

    def _is_redundant_snapshot(
            self,
            snapshot: ProgressSnapshot,
            signature: StageSignature | None,
            now: float,
    ) -> bool:
        """
        Return whether a snapshot only repeats a recent same-stage update.

        The first snapshot, stage status or total changes, and all-complete
        snapshots always pass, so throttling never hides a stage transition or
        the workflow's final state.
        """
        if self._last_snapshot_at is None:
            return False

        return (
            signature == self._last_stage_signature
            and not _all_stages_complete(snapshot)
            and now - self._last_snapshot_at < self._min_snapshot_interval_s
        )


def _stage_signature(snapshot: object) -> StageSignature | None:
    """Return the per-stage state whose changes are always forwarded."""
    # Worker test doubles may emit placeholder payloads without stages.
    stages = getattr(snapshot, 'stages', None)
    if stages is None:
        return None

    return tuple(
        (stage.stage_id, stage.status, stage.total) for stage in stages
    )


def _all_stages_complete(snapshot: object) -> bool:
    """Return whether a snapshot reports every workflow stage complete."""
    stages = getattr(snapshot, 'stages', None)
    return bool(stages) and all(stage.status == 'complete' for stage in stages)


def call_operation_with_progress(
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
    if accepts_keyword_argument(signature, 'progress_snapshot_callback'):
        return operation(
            progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )

    # OperationWorker is intentionally generic; one-callback callables remain
    # valid so older file-operation tests and simple adapters do not fail when
    # structured progress is unavailable.
    return operation(progress_callback)


def call_detect_scenes_with_progress(
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
    if accepts_keyword_argument(signature, 'progress_snapshot_callback'):
        detect_scenes(
            progress_callback=progress_callback,
            progress_snapshot_callback=progress_snapshot_callback,
        )
        return

    detect_scenes(progress_callback=progress_callback)
