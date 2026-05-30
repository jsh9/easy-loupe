from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

import easy_cull.ui.workers as workers_module
from easy_cull.operations.common import OperationSummary

if TYPE_CHECKING:
    from pathlib import Path


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


def test_viewer_prefetch_worker_warms_requested_viewer_previews() -> None:
    calls: list[tuple[str, str]] = []
    failed_events: list[str] = []
    finished_events: list[str] = []

    class Library:
        @staticmethod
        def get_preview_path(photo_id: str, kind: str) -> str:
            calls.append((photo_id, kind))
            if photo_id == 'missing':
                raise KeyError(photo_id)

            return '/tmp/preview.jpg'

    worker = workers_module.ViewerPrefetchWorker(
        Library(), ['A', 'missing', 'B']
    )
    worker.finished.connect(lambda: finished_events.append('finished'))
    worker.failed.connect(failed_events.append)
    worker.run()

    assert calls == [('A', 'viewer'), ('missing', 'viewer'), ('B', 'viewer')]
    assert finished_events == ['finished']
    assert failed_events == []


def test_viewer_prefetch_worker_cancel_skips_remaining_previews() -> None:
    calls: list[tuple[str, str]] = []
    finished_events: list[str] = []

    class Library:
        @staticmethod
        def get_preview_path(photo_id: str, kind: str) -> str:
            calls.append((photo_id, kind))
            return '/tmp/preview.jpg'

    worker = workers_module.ViewerPrefetchWorker(Library(), ['A'])
    worker.finished.connect(lambda: finished_events.append('finished'))
    worker.cancel()
    worker.run()

    assert calls == []
    assert finished_events == ['finished']


def test_folder_hydration_worker_loads_and_warms_folder(
        tmp_path: Path, monkeypatch: Any
) -> None:
    progress_events: list[tuple[str, int]] = []
    finished_results: list[object] = []

    @dataclass
    class Photo:
        photo_id: str

    class Library:
        def __init__(
                self,
                *,
                cache_dir: object,
                sort_mode: str,
                sort_reversed: bool,
        ) -> None:
            self.cache_dir = cache_dir
            self.sort_mode = sort_mode
            self.sort_reversed = sort_reversed
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self, folder: object, *, progress_callback: object
        ) -> None:
            del folder
            progress_callback('Scanning folder', 5)
            self.photos = [Photo('A'), Photo('B')]

        def get_photos(self) -> list[Photo]:
            return self.photos

        def get_preview_path(self, photo_id: str, kind: str) -> str:
            self.preview_calls.append((photo_id, kind))
            return '/tmp/preview.jpg'

    monkeypatch.setattr(workers_module, 'PhotoLibrary', Library)
    worker = workers_module.FolderHydrationWorker(
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=True,
    )
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.finished.connect(finished_results.append)

    worker.run()

    assert progress_events[0] == ('Scanning folder', 5)
    assert progress_events[-1] == ('Preparing photo viewer cache', 200)
    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == [
        ('A', 'thumb'),
        ('A', 'viewer'),
        ('B', 'thumb'),
        ('B', 'viewer'),
    ]


def test_folder_hydration_worker_cancel_skips_preview_warming(
        tmp_path: Path, monkeypatch: Any
) -> None:
    finished_results: list[object] = []

    @dataclass
    class Photo:
        photo_id: str

    class Library:
        def __init__(
                self,
                *,
                cache_dir: object,
                sort_mode: str,
                sort_reversed: bool,
        ) -> None:
            del cache_dir, sort_mode, sort_reversed
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self, folder: object, *, progress_callback: object
        ) -> None:
            del folder, progress_callback
            self.photos = [Photo('A')]

        def get_photos(self) -> list[Photo]:
            return self.photos

        def get_preview_path(self, photo_id: str, kind: str) -> str:
            self.preview_calls.append((photo_id, kind))
            return '/tmp/preview.jpg'

    monkeypatch.setattr(workers_module, 'PhotoLibrary', Library)
    worker = workers_module.FolderHydrationWorker(
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=False,
    )
    worker.finished.connect(finished_results.append)
    worker.cancel()
    worker.run()

    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == []


def _good_operation(
        progress_callback: Any,
) -> OperationSummary:
    progress_callback('writing xmp', 75)
    return OperationSummary(written_sidecars=2)


def _bad_operation(progress_callback: Any) -> Never:
    del progress_callback
    raise RuntimeError('operation failure')
