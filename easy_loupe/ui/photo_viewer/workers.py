"""Background workers owned by the standalone photo-viewer window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

import easy_loupe.core.exif as exif_module
from easy_loupe.core.folder_loading import (
    FOLDER_LOAD_PROGRESS_STAGES,
    build_photo_exif_display,
)
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.core.records import (
    HEIF_EXTENSIONS,
    JPEG_EXTENSIONS,
    RAW_EXTENSIONS,
)
from easy_loupe.core.recursive_loading import (
    exif_metadata_for_path,
)
from easy_loupe.progress import ProgressReporter, ProgressStageDefinition

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from pathlib import Path


class ViewerPrefetchWorker(QObject):
    """Warm viewer previews for nearby photos without blocking navigation."""

    finished = Signal()
    failed = Signal(str)

    def __init__(
            self, library: PhotoLibrary, photo_ids: Sequence[str]
    ) -> None:
        super().__init__()
        self._library = library
        self._photo_ids = list(photo_ids)
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation before the next preview render starts."""
        self._cancelled = True

    def run(self) -> None:
        """Render nearby viewer previews and ignore per-photo failures."""
        try:
            for photo_id in self._photo_ids:
                if self._cancelled:
                    break

                try:
                    self._library.get_preview_path(photo_id, 'viewer')
                except (KeyError, OSError, RuntimeError, ValueError):
                    continue
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - thread safety path
            self.failed.emit(str(exc))
            return

        self.finished.emit()


@dataclass(frozen=True, slots=True)
class PhotoViewerExifResult:
    """EXIF payload for updating one standalone viewer photo record."""

    focus_point: tuple[float, float]
    exif_display: dict[str, str]
    capture_at: datetime | None
    image_width: int | None
    image_height: int | None


class PhotoViewerExifWorker(QObject):
    """Read focus metadata for the active photo-viewer photo."""

    finished = Signal(int, str, object)
    failed = Signal(int, str)

    def __init__(
            self,
            request_id: int,
            photo_id: str,
            metadata_source: Path,
            preview_source: Path,
            photo_files: Sequence[Path],
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._photo_id = photo_id
        self._metadata_source = metadata_source
        self._preview_source = preview_source
        self._photo_files = list(photo_files)
        self._cancelled = False

    def cancel(self) -> None:
        """Request that a completed read does not update the UI."""
        self._cancelled = True

    def run(self) -> None:
        """Read one photo's EXIF and emit its normalized focus point."""
        try:
            sources = list(
                dict.fromkeys([
                    self._metadata_source,
                    self._preview_source,
                ])
            )
            exif_map = exif_module.read_exif_metadata(sources)
            if self._cancelled:
                self.finished.emit(self._request_id, self._photo_id, None)
                return

            metadata = (
                exif_metadata_for_path(exif_map, self._metadata_source)
                or exif_metadata_for_path(exif_map, self._preview_source)
                or {}
            )
            image_width, image_height = exif_module.resolve_image_size(
                metadata
            )
            focus_point = exif_module.extract_focus_point(
                metadata, image_width, image_height
            )
            jpeg_files = [
                path
                for path in self._photo_files
                if path.suffix.lower() in JPEG_EXTENSIONS
            ]
            heif_files = [
                path
                for path in self._photo_files
                if path.suffix.lower() in HEIF_EXTENSIONS
            ]
            raw_files = [
                path
                for path in self._photo_files
                if path.suffix.lower() in RAW_EXTENSIONS
            ]
            exif_display = build_photo_exif_display(
                metadata,
                jpeg_files=jpeg_files,
                heif_files=heif_files,
                raw_files=raw_files,
            )
            result = PhotoViewerExifResult(
                focus_point=focus_point,
                exif_display=exif_display.exif_display,
                capture_at=exif_display.capture_at,
                image_width=exif_display.image_width,
                image_height=exif_display.image_height,
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - thread safety path
            self.failed.emit(self._request_id, str(exc))
            return

        if self._cancelled:
            self.finished.emit(self._request_id, self._photo_id, None)
            return

        self.finished.emit(self._request_id, self._photo_id, result)


class FolderHydrationWorker(QObject):
    """Load a full folder library and prewarm browse/viewer previews."""

    progress = Signal(int, object, str, int)
    progress_snapshot = Signal(int, object, object)
    finished = Signal(int, object, object)
    failed = Signal(int, object, str)

    def __init__(
            self,
            request_id: int,
            folder: Path,
            *,
            cache_dir: Path,
            sort_mode: str,
            sort_reversed: bool,
            load_recursively: bool,
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._folder = folder
        self._cache_dir = cache_dir
        self._sort_mode = sort_mode
        self._sort_reversed = sort_reversed
        self._load_recursively = load_recursively
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation before the next preview render starts."""
        self._cancelled = True

    def _emit_progress(self, message: str, progress: int) -> None:
        """Emit progress with request context for queued GUI-thread slots."""
        self.progress.emit(self._request_id, self._folder, message, progress)

    def _emit_progress_snapshot(self, snapshot: object) -> None:
        """Emit structured progress with request context."""
        self.progress_snapshot.emit(self._request_id, self._folder, snapshot)

    def run(self) -> None:
        """Load the folder and warm thumbnail/viewer previews."""
        try:
            library = PhotoLibrary(
                cache_dir=self._cache_dir,
                sort_mode=self._sort_mode,
                sort_reversed=self._sort_reversed,
                load_recursively=self._load_recursively,
            )
            reporter = ProgressReporter(
                'Loading folder',
                (
                    *FOLDER_LOAD_PROGRESS_STAGES,
                    ProgressStageDefinition(
                        'viewer_cache', 'Preparing photo viewer cache'
                    ),
                ),
                progress_callback=self._emit_progress,
                snapshot_callback=self._emit_progress_snapshot,
            )
            library.load_folder(self._folder, progress_reporter=reporter)
            photos = library.get_photos()
            total = len(photos)
            viewer_cache_progress = reporter.counted_stage(
                'viewer_cache',
                label='Preparing photo viewer cache',
                total=total,
                start_progress=100,
                end_progress=200,
                zero_progress=200,
            )
            # Empty hydration skips the loop below, so close this zero-work
            # row immediately instead of leaving it active.
            viewer_cache_progress.start()
            for index, photo in enumerate(photos, start=1):
                if self._cancelled:
                    break

                try:
                    library.get_preview_path(photo.photo_id, 'thumb')
                    if self._cancelled:
                        break

                    library.get_preview_path(photo.photo_id, 'viewer')
                except (OSError, RuntimeError, ValueError):
                    pass

                # Counts reflect completed cache attempts. Canceling between
                # renders leaves the partial photo uncounted.
                viewer_cache_progress.update(index)
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - thread safety path
            self.failed.emit(self._request_id, self._folder, str(exc))
            return

        self.finished.emit(self._request_id, self._folder, library)
