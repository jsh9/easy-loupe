from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from PIL import Image
from PySide6.QtWidgets import QApplication

from easy_loupe.core.records import PhotoRecord
from easy_loupe.ui.photo_clipboard import copy_photo_pixels_to_clipboard

if TYPE_CHECKING:
    from pathlib import Path


class FakeLibrary:
    """Small PhotoLibrary stand-in for clipboard source-selection tests."""

    def __init__(
            self,
            photos: dict[str, PhotoRecord],
            preview_paths: dict[str, Path] | None = None,
    ) -> None:
        self.photos = list(photos.values())
        self._photos = photos
        self._preview_paths = preview_paths or {}
        self.preview_calls: list[tuple[str, str]] = []

    def get_photo(self, photo_id: str) -> PhotoRecord:
        return self._photos[photo_id]

    def get_preview_path(self, photo_id: str, kind: str) -> Path:
        self.preview_calls.append((photo_id, kind))
        return self._preview_paths[photo_id]


def _create_color_jpeg(path: Path, color: tuple[int, int, int]) -> None:
    Image.new('RGB', (12, 8), color=color).save(
        path, format='JPEG', quality=100, subsampling=0
    )


def _photo_record(
        photo_id: str,
        *,
        preview_source: Path,
        metadata_source: Path | None = None,
        has_jpeg: bool,
        has_raw: bool,
        has_heif: bool = False,
) -> PhotoRecord:
    return PhotoRecord(
        photo_id=photo_id,
        display_name=photo_id,
        files=[preview_source.name],
        has_jpeg=has_jpeg,
        has_raw=has_raw,
        preview_source=preview_source,
        metadata_source=metadata_source or preview_source,
        focus_point=(0.5, 0.5),
        has_heif=has_heif,
        has_raster=has_jpeg or has_heif,
    )


def _clipboard_pixel() -> tuple[int, int, int]:
    image = QApplication.clipboard().image()
    assert not image.isNull()
    color = image.pixelColor(0, 0)
    return (color.red(), color.green(), color.blue())


def _assert_close_rgb(
        actual: tuple[int, int, int], expected: tuple[int, int, int]
) -> None:
    for actual_value, expected_value in zip(actual, expected, strict=True):
        assert abs(actual_value - expected_value) <= 3


def test_copy_photo_pixels_uses_original_jpeg_without_rendering(
        tmp_path: Path,
) -> None:
    """
    Verify JPEG-backed records copy source pixels without cache rendering.

    This guards the user-facing contract that a folder JPEG is copied directly
    instead of EasyLoupe's re-encoded viewer preview.
    """
    app = QApplication.instance() or QApplication([])
    jpeg_path = tmp_path / 'JPEG_ONLY.JPG'
    expected_color = (12, 34, 56)
    _create_color_jpeg(jpeg_path, expected_color)
    library = FakeLibrary({
        'JPEG_ONLY': _photo_record(
            'JPEG_ONLY',
            preview_source=jpeg_path,
            has_jpeg=True,
            has_raw=False,
        )
    })

    assert copy_photo_pixels_to_clipboard(cast('Any', library), 'JPEG_ONLY')

    assert library.preview_calls == []
    _assert_close_rgb(_clipboard_pixel(), expected_color)
    del app


def test_copy_photo_pixels_prefers_jpeg_companion_over_raw_preview(
        tmp_path: Path,
) -> None:
    """Verify JPEG+RAW pairs still copy the original JPEG companion."""
    app = QApplication.instance() or QApplication([])
    jpeg_path = tmp_path / 'PAIR.JPG'
    raw_path = tmp_path / 'PAIR.CR3'
    raw_path.write_bytes(b'raw')
    expected_color = (80, 20, 140)
    _create_color_jpeg(jpeg_path, expected_color)
    library = FakeLibrary({
        'PAIR': _photo_record(
            'PAIR',
            preview_source=jpeg_path,
            metadata_source=raw_path,
            has_jpeg=True,
            has_raw=True,
        )
    })

    assert copy_photo_pixels_to_clipboard(cast('Any', library), 'PAIR')

    assert library.preview_calls == []
    _assert_close_rgb(_clipboard_pixel(), expected_color)
    del app


def test_copy_photo_pixels_uses_viewer_preview_without_jpeg(
        tmp_path: Path,
) -> None:
    """Verify RAW-only records copy the rendered viewer preview pixels."""
    app = QApplication.instance() or QApplication([])
    raw_path = tmp_path / 'RAW_ONLY.CR3'
    preview_path = tmp_path / 'preview.jpg'
    raw_path.write_bytes(b'raw')
    expected_color = (20, 130, 90)
    _create_color_jpeg(preview_path, expected_color)
    library = FakeLibrary(
        {
            'RAW_ONLY': _photo_record(
                'RAW_ONLY',
                preview_source=raw_path,
                has_jpeg=False,
                has_raw=True,
            )
        },
        {'RAW_ONLY': preview_path},
    )

    assert copy_photo_pixels_to_clipboard(cast('Any', library), 'RAW_ONLY')

    assert library.preview_calls == [('RAW_ONLY', 'viewer')]
    _assert_close_rgb(_clipboard_pixel(), expected_color)
    del app
