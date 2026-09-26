from __future__ import annotations

from typing import TYPE_CHECKING

from easy_loupe.progress import ProgressReporter, ProgressStageDefinition
from easy_loupe.ui.progress_routing import (
    WORKER_SNAPSHOT_MIN_INTERVAL_S,
    WorkerProgressRouter,
)

if TYPE_CHECKING:
    from easy_loupe.progress import ProgressSnapshot


class FakeClock:
    """Manually advanced monotonic clock for deterministic throttling."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_worker_progress_router_coalesces_rapid_same_stage_snapshots() -> None:
    """
    Verify same-stage snapshots are forwarded at most once per interval.

    Scene grouping reports once per photo within microseconds. Forwarding every
    snapshot queues one overlay render per photo on the GUI thread, so the
    router must drop same-stage repeats inside the interval while still
    suppressing the paired scalar tuples of the dropped snapshots.
    """
    clock = FakeClock()
    forwarded_messages: list[str] = []
    scalar_events: list[tuple[str, int]] = []

    def record_snapshot(snapshot: ProgressSnapshot) -> None:
        forwarded_messages.append(snapshot.current_message)

    router = WorkerProgressRouter(
        lambda message, progress: scalar_events.append((message, progress)),
        record_snapshot,
        clock=clock,
    )
    reporter = ProgressReporter(
        'Detecting scenes',
        (ProgressStageDefinition('grouping', 'Grouping scenes'),),
        progress_callback=router.emit_progress,
        snapshot_callback=router.emit_snapshot,
    )

    for index in range(1, 101):
        reporter.update_stage(
            'grouping', current=index, total=200, overall_progress=80
        )

    clock.now = WORKER_SNAPSHOT_MIN_INTERVAL_S
    reporter.update_stage(
        'grouping', current=101, total=200, overall_progress=90
    )

    assert forwarded_messages == [
        'Grouping scenes, 1 of 200',
        'Grouping scenes, 101 of 200',
    ]
    assert scalar_events == []


def test_worker_progress_router_forwards_stage_changes_and_completion() -> (
    None
):
    """
    Verify throttling never drops stage transitions or the final snapshot.

    A whole multi-stage workflow can finish within one throttle interval. Only
    same-stage count repeats may be dropped, so each stage start, completion,
    and the workflow's final message must still reach the overlay.
    """
    clock = FakeClock()
    forwarded_messages: list[str] = []

    def record_snapshot(snapshot: ProgressSnapshot) -> None:
        forwarded_messages.append(snapshot.current_message)

    router = WorkerProgressRouter(
        lambda _message, _progress: None,
        record_snapshot,
        clock=clock,
    )
    reporter = ProgressReporter(
        'Detecting scenes',
        (
            ProgressStageDefinition('features', 'Extracting preview features'),
            ProgressStageDefinition('grouping', 'Grouping scenes'),
        ),
        progress_callback=router.emit_progress,
        snapshot_callback=router.emit_snapshot,
    )
    feature_progress = reporter.counted_stage(
        'features',
        label='Extracting preview features',
        total=3,
        start_progress=5,
        end_progress=75,
    )
    grouping_progress = reporter.counted_stage(
        'grouping',
        label='Grouping scenes',
        total=2,
        start_progress=80,
        end_progress=99,
    )

    # The frozen clock keeps every snapshot inside one throttle interval.
    for index in range(1, 4):
        feature_progress.update(index)

    for index in range(1, 3):
        grouping_progress.update(index)

    reporter.finish('done', 100)

    assert forwarded_messages == [
        'Extracting preview features, 1 of 3',
        'Extracting preview features, 3 of 3',
        'Grouping scenes, 1 of 2',
        'Grouping scenes, 2 of 2',
        'done',
    ]
