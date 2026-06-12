from __future__ import annotations

import inspect

from easy_loupe.progress import (
    ProgressReporter,
    ProgressStageDefinition,
    accepted_keyword_arguments,
    accepts_keyword_argument,
)


def test_progress_reporter_emits_legacy_and_stage_snapshots() -> None:
    """
    Verify legacy tuples and structured stage state stay in sync.

    This protects callers that still consume percent tuples while the UI reads
    the richer snapshot payload for multi-stage progress rows.
    """
    legacy_updates: list[tuple[str, int]] = []
    snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        (
            ProgressStageDefinition('scan', 'Scanning folder'),
            ProgressStageDefinition('records', 'Building photo list'),
            ProgressStageDefinition('browse', 'Preparing browse grid'),
        ),
        progress_callback=lambda message, progress: legacy_updates.append((
            message,
            progress,
        )),
        snapshot_callback=snapshots.append,
    )

    reporter.start_stage('scan', overall_progress=5)
    reporter.update_stage('records', current=4, total=37, overall_progress=50)
    reporter.update_stage(
        'records',
        current=37,
        total=37,
        overall_progress=90,
        complete=True,
    )

    assert legacy_updates[0] == ('Scanning folder', 5)
    assert legacy_updates[1] == ('Building photo list, 4 of 37', 50)
    assert snapshots[1].current_message == 'Building photo list, 4 of 37'
    assert [stage.status for stage in snapshots[1].stages] == [
        'complete',
        'active',
        'pending',
    ]
    assert snapshots[1].stages[1].count_text() == '4 of 37'
    assert snapshots[1].stages[1].progress_value() == 4
    assert snapshots[2].stages[1].status == 'complete'
    assert snapshots[2].stages[1].progress_value() == 37
    assert snapshots[2].stages[2].status == 'pending'


def test_progress_reporter_handles_unknown_total_stage() -> None:
    """
    Verify active unknown-total stages are represented without counts.

    This covers status-only stages so the overlay can show indeterminate work
    without inventing fake item counts.
    """
    snapshots = []
    reporter = ProgressReporter(
        'Preparing',
        (ProgressStageDefinition('prepare', 'Preparing files'),),
        snapshot_callback=snapshots.append,
    )

    reporter.start_stage('prepare', overall_progress=5)
    reporter.finish('Done', 100)

    assert snapshots[0].stages[0].count_text() == ''
    assert snapshots[0].stages[0].progress_value() == 0
    assert snapshots[0].stages[0].status == 'active'
    assert snapshots[1].stages[0].status == 'complete'
    assert snapshots[1].stages[0].progress_value() == 100


def test_progress_reporter_handles_zero_total_stage_without_counts() -> None:
    """
    Verify zero-work stages render as status-only progress.

    Empty folders and empty operation lists should not display ``0 of 0`` or
    look incomplete after their stage is marked complete.
    """
    snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        (ProgressStageDefinition('records', 'Building photo list'),),
        snapshot_callback=snapshots.append,
    )

    reporter.update_stage('records', current=0, total=0, overall_progress=35)
    reporter.complete_stage('records', overall_progress=100)

    assert snapshots[0].stages[0].count_text() == ''
    assert snapshots[0].stages[0].progress_value() == 0
    assert snapshots[0].stages[0].status == 'active'
    assert snapshots[1].stages[0].count_text() == ''
    assert snapshots[1].stages[0].progress_value() == 100
    assert snapshots[1].stages[0].status == 'complete'


def test_progress_reporter_preserves_partial_determinate_completion() -> None:
    """
    Verify skipped determinate work is not reported as fully counted.

    Metadata reads can stop early after a tool launch failure. The reporter may
    still advance to later stages, but it must preserve the last completed
    batch count instead of turning ``1 of 3`` into ``3 of 3``.
    """
    snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        (
            ProgressStageDefinition('metadata', 'Loading EXIF data'),
            ProgressStageDefinition('records', 'Building photo list'),
        ),
        snapshot_callback=snapshots.append,
    )

    reporter.update_stage('metadata', current=1, total=3, overall_progress=25)
    reporter.update_stage('records', current=0, total=2, overall_progress=35)
    reporter.finish('Done', 100)

    metadata_stage = snapshots[1].stages[0]
    assert metadata_stage.status == 'complete'
    assert metadata_stage.count_text() == '1 of 3'
    assert metadata_stage.progress_value() == 1
    assert snapshots[-1].stages[0].count_text() == '1 of 3'


def test_counted_progress_stage_completes_zero_work_with_configured_progress() -> (
    None
):
    """
    Verify counted stages centralize no-op completion semantics.

    Different workflows preserve different progress values for zero-work
    stages, so callers need an explicit zero-progress override.
    """
    snapshots = []
    reporter = ProgressReporter(
        'Loading folder',
        (ProgressStageDefinition('records', 'Building photo list'),),
        snapshot_callback=snapshots.append,
    )
    records = reporter.counted_stage(
        'records',
        label='Building photo list',
        total=0,
        start_progress=35,
        end_progress=90,
        zero_progress=35,
    )

    records.start()

    stage = snapshots[-1].stages[0]
    assert snapshots[-1].overall_progress == 35
    assert stage.status == 'complete'
    assert stage.current == 0
    assert stage.total == 0
    assert stage.count_text() == ''


def test_counted_progress_stage_accepts_custom_progress_formula() -> None:
    """Verify unusual progress curves can still use shared count handling."""
    snapshots = []
    reporter = ProgressReporter(
        'Detecting scenes',
        (ProgressStageDefinition('grouping', 'Grouping scenes'),),
        snapshot_callback=snapshots.append,
    )
    grouping = reporter.counted_stage(
        'grouping',
        label='Grouping scenes',
        total=3,
        start_progress=80,
        end_progress=99,
        progress_value_fn=lambda current, _total: 80 if current == 1 else 99,
    )

    grouping.update(1)
    grouping.update(3)

    assert snapshots[0].overall_progress == 80
    assert snapshots[0].stages[0].count_text() == '1 of 3'
    assert snapshots[1].overall_progress == 99
    assert snapshots[1].stages[0].status == 'complete'


def test_progress_callback_signature_helpers_accept_kwargs() -> None:
    """
    Verify shared callback introspection treats ``**kwargs`` as opt-in.

    EXIF readers and UI workers both rely on this rule to forward structured
    progress callbacks through wrapper functions.
    """

    def callback_adapter(files: object, **kwargs: object) -> None:
        del files, kwargs

    signature = inspect.signature(callback_adapter)
    kwargs = {
        'batch_size': 20,
        'batch_progress_callback': object(),
    }

    assert accepts_keyword_argument(signature, 'batch_progress_callback')
    assert accepted_keyword_arguments(signature, kwargs) == kwargs
