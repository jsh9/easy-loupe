"""Background workers owned by the standalone photo-viewer window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

import easy_cull.core.exif as exif_module
from easy_cull.core.photo_library import PhotoLibrary

if TYPE_CHECKING:
    from collections.abc import Sequence
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
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._photo_id = photo_id
        self._metadata_source = metadata_source
        self._preview_source = preview_source
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
                exif_map.get(self._metadata_source.name)
                or exif_map.get(self._preview_source.name)
                or {}
            )
            image_width, image_height = exif_module.resolve_image_size(
                metadata
            )
            focus_point = exif_module.extract_focus_point(
                metadata, image_width, image_height
            )
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - thread safety path
            self.failed.emit(self._request_id, str(exc))
            return

        if self._cancelled:
            self.finished.emit(self._request_id, self._photo_id, None)
            return

        self.finished.emit(self._request_id, self._photo_id, focus_point)


class FolderHydrationWorker(QObject):
    """Load a full folder library and prewarm browse/viewer previews."""

    progress = Signal(int, object, str, int)
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
    ) -> None:
        super().__init__()
        self._request_id = request_id
        self._folder = folder
        self._cache_dir = cache_dir
        self._sort_mode = sort_mode
        self._sort_reversed = sort_reversed
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation before the next preview render starts."""
        self._cancelled = True

    def _emit_progress(self, message: str, progress: int) -> None:
        """Emit progress with request context for queued GUI-thread slots."""
        self.progress.emit(self._request_id, self._folder, message, progress)

    def run(self) -> None:
        """Load the folder and warm thumbnail/viewer previews."""
        try:
            library = PhotoLibrary(
                cache_dir=self._cache_dir,
                sort_mode=self._sort_mode,
                sort_reversed=self._sort_reversed,
            )
            library.load_folder(
                self._folder, progress_callback=self._emit_progress
            )
            photos = library.get_photos()
            total = max(len(photos), 1)
            for index, photo in enumerate(photos, start=1):
                if self._cancelled:
                    break

                progress = 100 + int((index / total) * 100)
                self._emit_progress('Preparing photo viewer cache', progress)
                try:
                    library.get_preview_path(photo.photo_id, 'thumb')
                    if self._cancelled:
                        break

                    library.get_preview_path(photo.photo_id, 'viewer')
                except (OSError, RuntimeError, ValueError):
                    continue
        except Exception as exc:  # noqa: BLE001  # pragma: no cover - thread safety path
            self.failed.emit(self._request_id, self._folder, str(exc))
            return

        self.finished.emit(self._request_id, self._folder, library)
