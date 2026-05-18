from __future__ import annotations

from typing import Any, Never

import easy_photo_culling.ui.workers as workers_module
from easy_photo_culling.operations.common import OperationSummary


def test_scene_detection_worker_emits_finished_and_failed() -> None:
    finished_events: list[str] = []
    progress_events: list[tuple[str, int]] = []
    failed_events: list[str] = []

    class GoodLibrary:
        @staticmethod
        def detect_scenes(*, progress_callback: Any) -> None:
            progress_callback('grouping scenes', 80)

    good_worker = workers_module.SceneDetectionWorker(GoodLibrary())
    good_worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    good_worker.finished.connect(lambda: finished_events.append('finished'))
    good_worker.failed.connect(failed_events.append)
    good_worker.run()

    assert progress_events == [('grouping scenes', 80)]
    assert finished_events == ['finished']
    assert failed_events == []

    class BadLibrary:
        @staticmethod
        def detect_scenes(*, progress_callback: Any) -> Never:
            del progress_callback
            raise RuntimeError('scene failure')

    bad_worker = workers_module.SceneDetectionWorker(BadLibrary())
    bad_worker.finished.connect(lambda: finished_events.append('bad-finished'))
    bad_worker.failed.connect(failed_events.append)
    bad_worker.run()

    assert failed_events == ['scene failure']
    assert finished_events == ['finished']


def test_operation_worker_emits_result_and_failed_state() -> None:
    finished_results: list[OperationSummary] = []
    progress_events: list[tuple[str, int]] = []
    failed_events: list[str] = []

    good_worker = workers_module.OperationWorker(_good_operation)
    good_worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    good_worker.finished.connect(finished_results.append)
    good_worker.failed.connect(failed_events.append)
    good_worker.run()

    assert progress_events == [('writing xmp', 75)]
    assert finished_results == [OperationSummary(written_sidecars=2)]
    assert failed_events == []

    bad_worker = workers_module.OperationWorker(_bad_operation)
    bad_worker.finished.connect(
        lambda _summary: finished_results.append(OperationSummary())
    )
    bad_worker.failed.connect(failed_events.append)
    bad_worker.run()

    assert failed_events == ['operation failure']
    assert finished_results == [OperationSummary(written_sidecars=2)]


def _good_operation(
        progress_callback: Any,
) -> OperationSummary:
    progress_callback('writing xmp', 75)
    return OperationSummary(written_sidecars=2)


def _bad_operation(progress_callback: Any) -> Never:
    del progress_callback
    raise RuntimeError('operation failure')
