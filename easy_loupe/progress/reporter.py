"""Progress reporter and counted-stage helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from easy_loupe.progress.models import (
    LegacyProgressCallback,
    ProgressSnapshot,
    ProgressStageDefinition,
    ProgressStageSnapshot,
    ProgressStageStatus,
    StructuredProgressCallback,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


@dataclass(slots=True)
class _ProgressStageState:
    stage_id: str
    label: str
    current: int | None
    total: int | None
    status: ProgressStageStatus


class CountedProgressStage:
    """Small helper for loop-backed progress stages."""

    def __init__(
            self,
            reporter: ProgressReporter,
            stage_id: str,
            *,
            label: str,
            total: int,
            start_progress: int,
            end_progress: int,
            zero_progress: int | None = None,
            progress_value_fn: Callable[[int, int], int] | None = None,
    ) -> None:
        self._reporter = reporter
        self._stage_id = stage_id
        self._label = label
        self._total = max(0, total)
        self._start_progress = start_progress
        self._end_progress = end_progress
        self._zero_progress = zero_progress
        self._progress_value_fn = progress_value_fn

    @property
    def total(self) -> int:
        """Return the stage's determinate item count."""
        return self._total

    def start(self, *, message: str | None = None) -> ProgressSnapshot:
        """Emit the initial stage state, completing zero-work stages."""
        return self.update(0, message=message, complete=self._total == 0)

    def update(
            self,
            current: int,
            *,
            message: str | None = None,
            complete: bool | None = None,
    ) -> ProgressSnapshot:
        """Update the stage with a completed item count."""
        # Bound first because the same count drives completion, row text, and
        # aggregate progress; callers that over-report should not push the UI
        # past the determinate stage end.
        current = _bounded_stage_current(current, self._total)
        should_complete = (
            current >= self._total if complete is None else complete
        )
        return self._reporter.update_stage(
            self._stage_id,
            label=self._label,
            current=current,
            total=self._total,
            message=message,
            overall_progress=self._overall_progress(current),
            complete=should_complete,
        )

    def _overall_progress(self, current: int) -> int:
        if self._total <= 0:
            return (
                self._zero_progress
                if self._zero_progress is not None
                else self._end_progress
            )

        span = self._end_progress - self._start_progress
        if self._progress_value_fn is not None:
            return self._progress_value_fn(current, self._total)

        return self._start_progress + int((current / self._total) * span)


class ProgressReporter:
    """Emit legacy progress tuples and structured snapshots together."""

    def __init__(
            self,
            workflow_label: str,
            stages: Iterable[ProgressStageDefinition] = (),
            *,
            progress_callback: LegacyProgressCallback | None = None,
            snapshot_callback: StructuredProgressCallback | None = None,
    ) -> None:
        self.workflow_label = workflow_label
        self._progress_callback = progress_callback
        self._snapshot_callback = snapshot_callback
        self._stages: list[_ProgressStageState] = []
        self._stage_indexes: dict[str, int] = {}
        self._current_message = workflow_label
        self._overall_progress: int | None = None
        for stage in stages:
            self.add_stage(stage.stage_id, stage.label, total=stage.total)

    def add_stage(
            self,
            stage_id: str,
            label: str,
            *,
            total: int | None = None,
    ) -> None:
        """Add a pending stage if it is not already known."""
        if stage_id in self._stage_indexes:
            stage = self._stages[self._stage_indexes[stage_id]]
            stage.label = label
            if total is not None:
                stage.total = max(0, total)
                if stage.current is not None:
                    # Re-adding a stage can lower the total after current was
                    # set, so re-bound the cached count to keep labels and bars
                    # coherent.
                    stage.current = _bounded_stage_current(
                        stage.current, stage.total
                    )

            return

        self._stage_indexes[stage_id] = len(self._stages)
        self._stages.append(
            _ProgressStageState(
                stage_id=stage_id,
                label=label,
                current=None,
                total=max(0, total) if total is not None else None,
                status='pending',
            )
        )

    def counted_stage(
            self,
            stage_id: str,
            *,
            label: str,
            total: int,
            start_progress: int,
            end_progress: int,
            zero_progress: int | None = None,
            progress_value_fn: Callable[[int, int], int] | None = None,
    ) -> CountedProgressStage:
        """Return a helper for a determinate, loop-backed stage."""
        return CountedProgressStage(
            self,
            stage_id,
            label=label,
            total=total,
            start_progress=start_progress,
            end_progress=end_progress,
            zero_progress=zero_progress,
            progress_value_fn=progress_value_fn,
        )

    def start_stage(
            self,
            stage_id: str,
            *,
            label: str | None = None,
            current: int | None = None,
            total: int | None = None,
            message: str | None = None,
            overall_progress: int | None = None,
    ) -> ProgressSnapshot:
        """Mark a stage active and emit its current state."""
        return self.update_stage(
            stage_id,
            label=label,
            current=current,
            total=total,
            message=message,
            overall_progress=overall_progress,
        )

    def update_stage(
            self,
            stage_id: str,
            *,
            label: str | None = None,
            current: int | None = None,
            total: int | None = None,
            message: str | None = None,
            overall_progress: int | None = None,
            complete: bool = False,
    ) -> ProgressSnapshot:
        """Update one stage, infer its message, and emit callbacks."""
        if stage_id not in self._stage_indexes:
            self.add_stage(stage_id, label or stage_id, total=total)

        stage = self._stages[self._stage_indexes[stage_id]]
        if label is not None:
            stage.label = label

        if total is not None:
            stage.total = max(0, total)

        if current is not None:
            stage.current = current

        if stage.current is not None:
            # Normalize at the reporter boundary because snapshots and legacy
            # messages both render this mutable stage state.
            stage.current = _bounded_stage_current(stage.current, stage.total)

        if complete:
            self._mark_stage_complete(stage_id)
        else:
            self._mark_stage_active(stage_id)

        return self.report(
            message or stage_message(stage),
            overall_progress,
        )

    def complete_stage(
            self,
            stage_id: str,
            *,
            message: str | None = None,
            overall_progress: int | None = None,
    ) -> ProgressSnapshot:
        """Mark a stage complete and emit callbacks."""
        if stage_id not in self._stage_indexes:
            self.add_stage(stage_id, stage_id)

        stage = self._stages[self._stage_indexes[stage_id]]
        self._mark_stage_complete(stage_id)
        return self.report(message or stage_message(stage), overall_progress)

    def finish(
            self,
            message: str,
            overall_progress: int | None = 100,
    ) -> ProgressSnapshot:
        """Mark every stage complete and emit a final progress update."""
        for stage in self._stages:
            _mark_stage_state_complete(stage)

        return self.report(message, overall_progress)

    def report(
            self,
            message: str,
            overall_progress: int | None = None,
    ) -> ProgressSnapshot:
        """Emit a status update without changing stage state."""
        self._current_message = message
        self._overall_progress = overall_progress
        snapshot = self.snapshot()
        # UI worker routers mark a workflow as structured here, before the
        # matching scalar callback arrives. That prevents the old bar UI from
        # briefly replacing stage rows.
        if self._snapshot_callback is not None:
            self._snapshot_callback(snapshot)

        if (
            self._progress_callback is not None
            and overall_progress is not None
        ):
            self._progress_callback(message, overall_progress)

        return snapshot

    def snapshot(self) -> ProgressSnapshot:
        """Return the current structured progress snapshot."""
        return ProgressSnapshot(
            workflow_label=self.workflow_label,
            current_message=self._current_message,
            overall_progress=self._overall_progress,
            stages=tuple(
                ProgressStageSnapshot(
                    stage_id=stage.stage_id,
                    label=stage.label,
                    current=stage.current,
                    total=stage.total,
                    status=stage.status,
                )
                for stage in self._stages
            ),
        )

    def _mark_stage_active(self, stage_id: str) -> None:
        active_index = self._stage_indexes[stage_id]
        # Advancing to a later stage completes earlier rows so callers do not
        # need to explicitly close every previous loop before the UI can show
        # a stable multi-stage workflow.
        for index, stage in enumerate(self._stages):
            if index < active_index:
                _mark_stage_state_complete(stage)
            elif index == active_index:
                stage.status = 'active'
            elif stage.status != 'complete':
                stage.status = 'pending'

    def _mark_stage_complete(self, stage_id: str) -> None:
        complete_index = self._stage_indexes[stage_id]
        for index, stage in enumerate(self._stages):
            if index <= complete_index:
                _mark_stage_state_complete(stage)
            elif stage.status != 'complete':
                stage.status = 'pending'


def _mark_stage_state_complete(stage: _ProgressStageState) -> None:
    """Complete a stage without turning partial determinate work into full."""
    stage.status = 'complete'
    if stage.total is None:
        return

    if stage.current is None or stage.current >= stage.total:
        stage.current = stage.total


def _bounded_stage_current(current: int, total: int | None) -> int:
    """Return a UI-safe current value bounded by determinate totals."""
    if total is not None and total <= 0:
        return 0

    current = max(0, current)
    if total is None:
        return current

    return min(current, total)


def stage_message(stage: _ProgressStageState) -> str:
    """Return display text for a mutable progress stage."""
    snapshot = ProgressStageSnapshot(
        stage_id=stage.stage_id,
        label=stage.label,
        current=stage.current,
        total=stage.total,
        status=stage.status,
    )
    count_text = snapshot.count_text()
    if count_text:
        return f'{stage.label}, {count_text}'

    return stage.label
