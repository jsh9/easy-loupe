from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never

import easy_loupe.ui.photo_viewer.workers as photo_viewer_workers_module
import easy_loupe.ui.workers as workers_module
from easy_loupe.operations.common import OperationSummary
from easy_loupe.progress import ProgressReporter, ProgressStageDefinition

if TYPE_CHECKING:
    from pathlib import Path


def test_scene_detection_worker_emits_finished_and_failed() -> None:
    """
    Verify scene workers forward legacy and structured progress signals.

    This protects the worker-thread boundary so progress snapshots reach the
    main window through Qt signals while failures still suppress completion.
    """
    finished_events: list[str] = []
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[tuple[int, object, Any]] = []
    failed_events: list[str] = []

    class GoodLibrary:
        @staticmethod
        def detect_scenes(
                *,
                progress_callback: Any,
                progress_snapshot_callback: Any = None,
        ) -> None:
            progress_callback('grouping scenes', 80)
            if progress_snapshot_callback is not None:
                progress_snapshot_callback('snapshot')

    good_worker = workers_module.SceneDetectionWorker(GoodLibrary())
    good_worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    good_worker.progress_snapshot.connect(snapshot_events.append)
    good_worker.finished.connect(lambda: finished_events.append('finished'))
    good_worker.failed.connect(failed_events.append)
    good_worker.run()

    assert progress_events == [('grouping scenes', 80)]
    assert snapshot_events == ['snapshot']
    assert finished_events == ['finished']
    assert failed_events == []

    class BadLibrary:
        @staticmethod
        def detect_scenes(
                *,
                progress_callback: Any,
                progress_snapshot_callback: Any = None,
        ) -> Never:
            del progress_callback, progress_snapshot_callback
            raise RuntimeError('scene failure')

    bad_worker = workers_module.SceneDetectionWorker(BadLibrary())
    bad_worker.finished.connect(lambda: finished_events.append('bad-finished'))
    bad_worker.failed.connect(failed_events.append)
    bad_worker.run()

    assert failed_events == ['scene failure']
    assert finished_events == ['finished']


def test_scene_detection_worker_suppresses_paired_structured_scalar_progress() -> (
    None
):
    """
    Verify structured scene progress does not emit paired scalar progress.

    ``ProgressReporter`` emits legacy tuples for compatibility, but the worker
    must suppress those paired tuples so MainWindow does not alternate between
    the stage-row overlay and the old progress bar.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_messages: list[str] = []
    finished_events: list[str] = []

    class StructuredLibrary:
        @staticmethod
        def detect_scenes(
                *,
                progress_callback: Any,
                progress_snapshot_callback: Any = None,
        ) -> None:
            reporter = ProgressReporter(
                'Detecting scenes',
                (
                    ProgressStageDefinition(
                        'features', 'Extracting preview features'
                    ),
                ),
                progress_callback=progress_callback,
                snapshot_callback=progress_snapshot_callback,
            )
            reporter.update_stage(
                'features',
                current=1,
                total=2,
                overall_progress=50,
            )

    worker = workers_module.SceneDetectionWorker(StructuredLibrary())
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(
        lambda snapshot: snapshot_messages.append(snapshot.current_message)
    )
    worker.finished.connect(lambda: finished_events.append('finished'))

    worker.run()

    assert progress_events == []
    assert snapshot_messages == ['Extracting preview features, 1 of 2']
    assert finished_events == ['finished']


def test_scene_detection_worker_preserves_legacy_only_progress() -> None:
    """
    Verify scalar scene progress still works when no snapshots are emitted.

    This keeps the fallback path available for legacy or test-only producers
    while structured producers avoid flicker.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[object] = []

    class LegacyLibrary:
        @staticmethod
        def detect_scenes(
                *,
                progress_callback: Any,
                progress_snapshot_callback: Any = None,
        ) -> None:
            del progress_snapshot_callback
            progress_callback('legacy scene progress', 40)

    worker = workers_module.SceneDetectionWorker(LegacyLibrary())
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(snapshot_events.append)

    worker.run()

    assert progress_events == [('legacy scene progress', 40)]
    assert snapshot_events == []


def test_scene_detection_worker_accepts_legacy_progress_only_library() -> None:
    """
    Verify scene workers still support one-callback library adapters.

    ``SceneDetectionWorker`` is used with ``PhotoLibrary`` in production, but
    tests and simple adapters may expose only the legacy progress callback.
    """
    progress_events: list[tuple[str, int]] = []
    failed_events: list[str] = []
    finished_events: list[str] = []

    class LegacyOnlyLibrary:
        @staticmethod
        def detect_scenes(*, progress_callback: Any) -> None:
            progress_callback('legacy scene progress', 25)

    worker = workers_module.SceneDetectionWorker(LegacyOnlyLibrary())
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.finished.connect(lambda: finished_events.append('finished'))
    worker.failed.connect(failed_events.append)

    worker.run()

    assert progress_events == [('legacy scene progress', 25)]
    assert finished_events == ['finished']
    assert failed_events == []


def test_scene_detection_worker_passes_snapshot_callback_to_kwargs_library() -> (
    None
):
    """
    Verify ``**kwargs`` scene adapters receive structured callbacks.

    Small adapters may forward keyword arguments without naming the structured
    callback explicitly. The worker should still pass the snapshot callback so
    those adapters do not fall back to scalar-only progress.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[object] = []
    finished_events: list[str] = []
    seen_kwargs: list[set[str]] = []

    class KwargsLibrary:
        @staticmethod
        def detect_scenes(**kwargs: Any) -> None:
            seen_kwargs.append(set(kwargs))
            kwargs['progress_snapshot_callback']('scene snapshot')
            kwargs['progress_callback']('legacy scene progress', 55)

    worker = workers_module.SceneDetectionWorker(KwargsLibrary())
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(snapshot_events.append)
    worker.finished.connect(lambda: finished_events.append('finished'))

    worker.run()

    assert seen_kwargs == [{'progress_callback', 'progress_snapshot_callback'}]
    assert snapshot_events == ['scene snapshot']
    assert progress_events == []
    assert finished_events == ['finished']


def test_operation_worker_emits_result_and_failed_state() -> None:
    finished_results: list[OperationSummary] = []
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[str] = []
    failed_events: list[str] = []

    good_worker = workers_module.OperationWorker(_good_operation)
    good_worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    good_worker.progress_snapshot.connect(snapshot_events.append)
    good_worker.finished.connect(finished_results.append)
    good_worker.failed.connect(failed_events.append)
    good_worker.run()

    assert progress_events == [('writing xmp', 75)]
    assert snapshot_events == ['operation snapshot']
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


def test_operation_worker_accepts_legacy_one_callback_operation() -> None:
    """
    Verify generic operation workers preserve one-callback compatibility.

    Existing worker callables may only accept legacy scalar progress, so adding
    structured progress support must not turn those operations into failures.
    """
    progress_events: list[tuple[str, int]] = []
    finished_results: list[OperationSummary] = []
    failed_events: list[str] = []

    worker = workers_module.OperationWorker(_legacy_good_operation)
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.finished.connect(finished_results.append)
    worker.failed.connect(failed_events.append)

    worker.run()

    assert progress_events == [('legacy operation', 30)]
    assert finished_results == [OperationSummary(processed_photos=1)]
    assert failed_events == []


def test_operation_worker_preserves_legacy_optional_second_argument() -> None:
    """
    Verify optional second positional parameters are not treated as snapshots.

    ``OperationWorker`` is generic enough for small adapters. A legacy callable
    may use its second argument for unrelated settings, so structured progress
    must be opted into by the ``progress_snapshot_callback`` parameter name.
    """
    dry_run_values: list[object] = []
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[object] = []
    finished_results: list[OperationSummary] = []

    def legacy_operation(
            progress_callback: Any,
            dry_run: bool = False,  # noqa: FBT002
    ) -> OperationSummary:
        dry_run_values.append(dry_run)
        progress_callback('legacy optional operation', 45)
        return OperationSummary(processed_photos=1)

    worker = workers_module.OperationWorker(legacy_operation)
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(snapshot_events.append)
    worker.finished.connect(finished_results.append)

    worker.run()

    assert dry_run_values == [False]
    assert progress_events == [('legacy optional operation', 45)]
    assert snapshot_events == []
    assert finished_results == [OperationSummary(processed_photos=1)]


def test_operation_worker_passes_snapshot_callback_to_kwargs_operation() -> (
    None
):
    """
    Verify ``**kwargs`` operation adapters receive structured callbacks.

    Operation callables may accept the legacy callback positionally and forward
    newer keyword callbacks through ``**kwargs``. The worker should preserve
    that compatibility while still preferring structured progress output.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[object] = []
    finished_results: list[OperationSummary] = []
    seen_kwargs: list[set[str]] = []

    def kwargs_operation(
            progress_callback: Any, **kwargs: Any
    ) -> OperationSummary:
        seen_kwargs.append(set(kwargs))
        kwargs['progress_snapshot_callback']('operation snapshot')
        progress_callback('legacy operation progress', 65)
        return OperationSummary(processed_photos=1)

    worker = workers_module.OperationWorker(kwargs_operation)
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(snapshot_events.append)
    worker.finished.connect(finished_results.append)

    worker.run()

    assert seen_kwargs == [{'progress_snapshot_callback'}]
    assert snapshot_events == ['operation snapshot']
    assert progress_events == []
    assert finished_results == [OperationSummary(processed_photos=1)]


def test_operation_worker_suppresses_paired_structured_scalar_progress() -> (
    None
):
    """
    Verify structured operation progress does not emit paired scalar progress.

    Organizer and undo workflows emit both callback styles from
    ``ProgressReporter``. The worker router must keep only the structured UI
    path visible when both arrive for the same update.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_messages: list[str] = []
    finished_results: list[OperationSummary] = []

    def structured_operation(
            progress_callback: Any,
            progress_snapshot_callback: Any,
    ) -> OperationSummary:
        reporter = ProgressReporter(
            'Organizing photos',
            (ProgressStageDefinition('organize', 'Organizing photo files'),),
            progress_callback=progress_callback,
            snapshot_callback=progress_snapshot_callback,
        )
        reporter.update_stage(
            'organize',
            current=1,
            total=2,
            overall_progress=50,
        )
        return OperationSummary(processed_photos=2)

    worker = workers_module.OperationWorker(structured_operation)
    worker.progress.connect(
        lambda message, progress: progress_events.append((message, progress))
    )
    worker.progress_snapshot.connect(
        lambda snapshot: snapshot_messages.append(snapshot.current_message)
    )
    worker.finished.connect(finished_results.append)

    worker.run()

    assert progress_events == []
    assert snapshot_messages == ['Organizing photo files, 1 of 2']
    assert finished_results == [OperationSummary(processed_photos=2)]


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
    """
    Verify the viewer EXIF worker emits focus and full file-size display data.

    The standalone viewer loads metadata asynchronously, so this protects the
    worker path that fills in focus points plus JPEG, HEIF, and RAW size rows
    after the initial lightweight record has already been shown.
    """
    finished_events: list[tuple[int, str, object]] = []
    failed_events: list[tuple[int, str]] = []
    metadata_source = tmp_path / 'A.CR3'
    preview_source = tmp_path / 'A.JPG'
    heif_source = tmp_path / 'A.HEIC'
    metadata_source.write_bytes(b'raw')
    preview_source.write_bytes(b'jpeg')
    heif_source.write_bytes(b'heif')
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
        [metadata_source, preview_source, heif_source],
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
        'File Size': 'JPG: 1 KB, HEIF: 1 KB, RAW: 1 KB',
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
    """
    Verify hydration builds a library with caller-provided scan preferences.

    The worker runs before photo-viewer handoff, so it must pass the recursive
    setting into the preloaded culling library it returns. The structured
    progress signal also carries request context so stale hydration updates can
    be ignored safely by the viewer window.
    """
    progress_events: list[tuple[str, int]] = []
    snapshot_events: list[tuple[int, Path, Any]] = []
    cache_progress_before_preview: list[tuple[str, str, int | None]] = []
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
                load_recursively: bool,
        ) -> None:
            self.cache_dir = cache_dir
            self.sort_mode = sort_mode
            self.sort_reversed = sort_reversed
            self.load_recursively = load_recursively
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self,
                folder: object,
                *,
                progress_callback: Any | None = None,
                progress_reporter: Any | None = None,
        ) -> None:
            del folder, progress_callback
            assert progress_reporter is not None
            progress_reporter.start_stage('scan', overall_progress=5)
            progress_reporter.complete_stage(
                'records',
                message='Finished loading folder',
                overall_progress=100,
            )
            self.photos = [Photo('A'), Photo('B')]

        def get_photos(self) -> list[Photo]:
            return self.photos

        def get_preview_path(self, photo_id: str, kind: str) -> str:
            latest_snapshot = snapshot_events[-1][2]
            viewer_cache_stage = next(
                stage
                for stage in latest_snapshot.stages
                if stage.stage_id == 'viewer_cache'
            )
            cache_progress_before_preview.append((
                photo_id,
                kind,
                viewer_cache_stage.current,
            ))
            self.preview_calls.append((photo_id, kind))
            return '/tmp/preview.jpg'

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=True,
        load_recursively=False,
    )
    worker.progress.connect(
        lambda _request_id, _folder, message, progress: (
            progress_events.append((message, progress))
        )
    )
    worker.progress_snapshot.connect(
        lambda request_id, folder, snapshot: snapshot_events.append((
            request_id,
            folder,
            snapshot,
        ))
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )

    worker.run()

    assert progress_events[0] == ('Scanning folder', 5)
    assert progress_events[-1] == ('Preparing photo viewer cache, 2 of 2', 200)
    assert snapshot_events[-1][0] == 12
    assert snapshot_events[-1][1] == tmp_path
    assert snapshot_events[-1][2].stages[-1].count_text() == '2 of 2'
    assert snapshot_events[-1][2].stages[-1].status == 'complete'
    assert cache_progress_before_preview == [
        ('A', 'thumb', 0),
        ('A', 'viewer', 0),
        ('B', 'thumb', 1),
        ('B', 'viewer', 1),
    ]
    assert len(finished_results) == 1
    assert finished_results[0].load_recursively is False
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
                load_recursively: bool,
        ) -> None:
            del cache_dir, sort_mode, sort_reversed, load_recursively
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self,
                folder: object,
                *,
                progress_callback: Any | None = None,
                progress_reporter: Any | None = None,
        ) -> None:
            del folder, progress_callback, progress_reporter
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
        load_recursively=True,
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )
    worker.cancel()
    worker.run()

    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == []


def test_folder_hydration_worker_preview_failure_still_counts_cache_attempt(
        tmp_path: Path, monkeypatch: Any
) -> None:
    """
    Verify failed cache renders still advance the viewer-cache progress row.

    Hydration treats preview warming as best-effort. A bad thumbnail or viewer
    render should not leave the handoff overlay stuck at the previous count.
    """
    snapshot_events: list[tuple[int, Path, Any]] = []
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
                load_recursively: bool,
        ) -> None:
            del cache_dir, sort_mode, sort_reversed, load_recursively
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self,
                folder: object,
                *,
                progress_callback: Any | None = None,
                progress_reporter: Any | None = None,
        ) -> None:
            del folder, progress_callback, progress_reporter
            self.photos = [Photo('A')]

        def get_photos(self) -> list[Photo]:
            return self.photos

        def get_preview_path(self, photo_id: str, kind: str) -> str:
            self.preview_calls.append((photo_id, kind))
            if kind == 'viewer':
                raise RuntimeError('viewer render failed')

            return '/tmp/preview.jpg'

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=False,
        load_recursively=True,
    )
    worker.progress.connect(
        lambda _request_id, _folder, message, progress: (
            progress_events.append((message, progress))
        )
    )
    worker.progress_snapshot.connect(
        lambda request_id, folder, snapshot: snapshot_events.append((
            request_id,
            folder,
            snapshot,
        ))
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )

    worker.run()

    viewer_cache_stage = next(
        stage
        for stage in snapshot_events[-1][2].stages
        if stage.stage_id == 'viewer_cache'
    )
    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == [
        ('A', 'thumb'),
        ('A', 'viewer'),
    ]
    assert progress_events[-1] == ('Preparing photo viewer cache, 1 of 1', 200)
    assert viewer_cache_stage.status == 'complete'
    assert viewer_cache_stage.count_text() == '1 of 1'


def test_folder_hydration_worker_empty_folder_completes_zero_cache_stage(
        tmp_path: Path, monkeypatch: Any
) -> None:
    """
    Verify empty hydration completes the zero-work viewer cache stage.

    The standalone viewer can hand off a hydrated library with no loaded photos
    after a direct-vs-recursive preference change. The progress row should
    close as a status-only zero-total stage instead of staying active.
    """
    snapshot_events: list[tuple[int, Path, Any]] = []
    progress_events: list[tuple[str, int]] = []
    finished_results: list[object] = []

    class Library:
        def __init__(
                self,
                *,
                cache_dir: object,
                sort_mode: str,
                sort_reversed: bool,
                load_recursively: bool,
        ) -> None:
            del cache_dir, sort_mode, sort_reversed, load_recursively
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self,
                folder: object,
                *,
                progress_callback: Any | None = None,
                progress_reporter: Any | None = None,
        ) -> None:
            del folder, progress_callback
            assert progress_reporter is not None
            progress_reporter.complete_stage(
                'records',
                message='Finished loading folder',
                overall_progress=100,
            )
            self.photos: list[object] = []

        def get_photos(self) -> list[object]:
            return self.photos

        @staticmethod
        def get_preview_path(photo_id: str, kind: str) -> str:
            raise AssertionError(
                f'empty hydration should not warm {photo_id} {kind}'
            )

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=False,
        load_recursively=True,
    )
    worker.progress.connect(
        lambda _request_id, _folder, message, progress: (
            progress_events.append((message, progress))
        )
    )
    worker.progress_snapshot.connect(
        lambda request_id, folder, snapshot: snapshot_events.append((
            request_id,
            folder,
            snapshot,
        ))
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )

    worker.run()

    viewer_cache_stage = next(
        stage
        for stage in snapshot_events[-1][2].stages
        if stage.stage_id == 'viewer_cache'
    )
    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == []
    assert progress_events[-1] == ('Preparing photo viewer cache', 200)
    assert viewer_cache_stage.status == 'complete'
    assert viewer_cache_stage.current == 0
    assert viewer_cache_stage.total == 0
    assert viewer_cache_stage.count_text() == ''


def test_folder_hydration_worker_cancel_between_cache_renders_is_uncounted(
        tmp_path: Path, monkeypatch: Any
) -> None:
    """
    Verify cancellation between thumbnail and viewer renders stays uncounted.

    The hydration overlay reports completed cache attempts, so a partial photo
    must remain at ``0 of 1`` instead of appearing complete during shutdown.
    """
    snapshot_events: list[tuple[int, Path, Any]] = []
    finished_results: list[object] = []
    worker_ref: list[Any] = []

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
                load_recursively: bool,
        ) -> None:
            del cache_dir, sort_mode, sort_reversed, load_recursively
            self.preview_calls: list[tuple[str, str]] = []

        def load_folder(
                self,
                folder: object,
                *,
                progress_callback: Any | None = None,
                progress_reporter: Any | None = None,
        ) -> None:
            del folder, progress_callback, progress_reporter
            self.photos = [Photo('A')]

        def get_photos(self) -> list[Photo]:
            return self.photos

        def get_preview_path(self, photo_id: str, kind: str) -> str:
            self.preview_calls.append((photo_id, kind))
            if kind == 'thumb':
                worker_ref[0].cancel()

            return '/tmp/preview.jpg'

    monkeypatch.setattr(photo_viewer_workers_module, 'PhotoLibrary', Library)
    worker = photo_viewer_workers_module.FolderHydrationWorker(
        12,
        tmp_path,
        cache_dir=tmp_path / '.cache',
        sort_mode='filename',
        sort_reversed=False,
        load_recursively=True,
    )
    worker_ref.append(worker)
    worker.progress_snapshot.connect(
        lambda request_id, folder, snapshot: snapshot_events.append((
            request_id,
            folder,
            snapshot,
        ))
    )
    worker.finished.connect(
        lambda _request_id, _folder, library: finished_results.append(library)
    )

    worker.run()

    viewer_cache_stage = next(
        stage
        for stage in snapshot_events[-1][2].stages
        if stage.stage_id == 'viewer_cache'
    )
    assert len(finished_results) == 1
    assert finished_results[0].preview_calls == [('A', 'thumb')]
    assert viewer_cache_stage.count_text() == '0 of 1'


def _good_operation(
        progress_callback: Any,
        progress_snapshot_callback: Any,
) -> OperationSummary:
    progress_callback('writing xmp', 75)
    progress_snapshot_callback('operation snapshot')
    return OperationSummary(written_sidecars=2)


def _legacy_good_operation(progress_callback: Any) -> OperationSummary:
    progress_callback('legacy operation', 30)
    return OperationSummary(processed_photos=1)


def _bad_operation(
        progress_callback: Any,
        progress_snapshot_callback: Any,
) -> Never:
    del progress_callback, progress_snapshot_callback
    raise RuntimeError('operation failure')
