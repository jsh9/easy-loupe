from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

import easy_cull.ui.photo_viewer.workers as photo_viewer_workers_module
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

    worker = photo_viewer_workers_module.ViewerPrefetchWorker(
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

    worker = photo_viewer_workers_module.ViewerPrefetchWorker(Library(), ['A'])
    worker.finished.connect(lambda: finished_events.append('finished'))
    worker.cancel()
    worker.run()

    assert calls == []
    assert finished_events == ['finished']


def test_photo_viewer_exif_worker_emits_current_photo_focus_point(
        tmp_path: Path, monkeypatch: Any
) -> None:
    finished_events: list[tuple[int, str, object]] = []
    failed_events: list[tuple[int, str]] = []
    metadata_source = tmp_path / 'A.CR3'
    preview_source = tmp_path / 'A.JPG'
    metadata_source.write_bytes(b'raw')
    preview_source.write_bytes(b'jpeg')
    monkeypatch.setattr(
        photo_viewer_workers_module.exif_module,
        'read_exif_metadata',
        lambda _sources: {
            'A.CR3': {
                'ImageWidth': 1000,
                'ImageHeight': 500,
                'AFAreaXPosition': 250,
                'AFAreaYPosition': 300,
                'DateTimeOriginal': '2024:05:01 10:00:00',
                'Model': 'Z 8',
                'LensModel': 'NIKKOR Z 50mm f/1.8 S',
                'FNumber': '2.8',
                'ExposureTime': '0.004',
                'ISO': 800,
                'FocalLength': '50',
            }
        },
    )

    worker = photo_viewer_workers_module.PhotoViewerExifWorker(
        3,
        'A',
        metadata_source,
        preview_source,
        [metadata_source, preview_source],
    )
    worker.finished.connect(
        lambda request_id, photo_id, focus_point: finished_events.append((
            request_id,
            photo_id,
            focus_point,
        ))
    )
    worker.failed.connect(
        lambda request_id, error: failed_events.append((request_id, error))
    )
    worker.run()

    assert failed_events == []
    assert len(finished_events) == 1
    request_id, photo_id, result = finished_events[0]
    assert request_id == 3
    assert photo_id == 'A'
    assert isinstance(
        result, photo_viewer_workers_module.PhotoViewerExifResult
    )
    assert result.focus_point == (0.25, 0.6)
    assert result.image_width == 1000
    assert result.image_height == 500
    assert result.exif_display == {
        'Captured': '2024-05-01, 10:00:00 AM',
        'Camera Model': 'Z 8',
        'Lens Model': 'NIKKOR Z 50mm f/1.8 S',
        'Focal Length': '50\u00a0mm',
        'Aperture': '\u0192/2.8',
        'Shutter Speed': '1/250\u00a0s',
        'ISO': '800',
        'Resolution': '1000 x 500 pixels (0.5 MP)',
        'File Size': 'JPG: 1 KB, RAW: 1 KB',
    }


def test_photo_viewer_exif_worker_cancel_suppresses_focus_result(
        tmp_path: Path, monkeypatch: Any
) -> None:
    finished_events: list[tuple[int, str, object]] = []
    metadata_source = tmp_path / 'A.CR3'
    preview_source = tmp_path / 'A.JPG'
    metadata_source.write_bytes(b'raw')
    preview_source.write_bytes(b'jpeg')
    monkeypatch.setattr(
        photo_viewer_workers_module.exif_module,
        'read_exif_metadata',
        lambda _sources: {'A.CR3': {'AFAreaXPosition': 250}},
    )

    worker = photo_viewer_workers_module.PhotoViewerExifWorker(
        4,
        'A',
        metadata_source,
        preview_source,
        [metadata_source, preview_source],
    )
    worker.finished.connect(
        lambda request_id, photo_id, focus_point: finished_events.append((
            request_id,
            photo_id,
            focus_point,
        ))
    )
    worker.cancel()
    worker.run()

    assert finished_events == [(4, 'A', None)]


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

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=True,
    )
    worker.progress.connect(
        lambda _request_id, _folder, message, progress: (
            progress_events.append((message, progress))
        )
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )

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

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=False,
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )
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
