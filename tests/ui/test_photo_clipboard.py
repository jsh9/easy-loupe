from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest
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


@pytest.mark.parametrize(
    (
        'photo_id',
        'source_name',
        'source_color',
        'metadata_name',
        'has_jpeg',
        'has_raw',
        'has_heif',
        'preview_color',
        'expected_preview_calls',
    ),
    [
        pytest.param(
            'JPEG_ONLY',
            'JPEG_ONLY.JPG',
            (12, 34, 56),
            None,
            True,
            False,
            False,
            None,
            [],
            id='jpeg-only',
        ),
        pytest.param(
            'PAIR',
            'PAIR.JPG',
            (80, 20, 140),
            'PAIR.CR3',
            True,
            True,
            False,
            None,
            [],
            id='jpeg-raw-pair',
        ),
        pytest.param(
            'RAW_ONLY',
            'RAW_ONLY.CR3',
            None,
            None,
            False,
            True,
            False,
            (20, 130, 90),
            [('RAW_ONLY', 'viewer')],
            id='raw-only',
        ),
        pytest.param(
            'HEIC_ONLY',
            'HEIC_ONLY.HEIC',
            None,
            None,
            False,
            False,
            True,
            (140, 90, 20),
            [('HEIC_ONLY', 'viewer')],
            id='heic-only',
        ),
    ],
)
def test_copy_photo_pixels_selects_clipboard_source(
        tmp_path: Path,
        photo_id: str,
        source_name: str,
        source_color: tuple[int, int, int] | None,
        metadata_name: str | None,
        has_jpeg: bool,
        has_raw: bool,
        has_heif: bool,
        preview_color: tuple[int, int, int] | None,
        expected_preview_calls: list[tuple[str, str]],
) -> None:
    """
    Verify each record shape uses the expected clipboard image source.

    JPEG-backed records should copy their original JPEG pixels, while RAW-only
    and HEIC-only records should copy the pasteable rendered viewer preview.
    """
    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / source_name
    if source_color is None:
        source_path.write_bytes(source_name.lower().encode())
    else:
        _create_color_jpeg(source_path, source_color)

    metadata_path = None
    if metadata_name is not None:
        metadata_path = tmp_path / metadata_name
        metadata_path.write_bytes(b'raw')

    preview_paths = {}
    if preview_color is not None:
        preview_path = tmp_path / f'{photo_id}-preview.jpg'
        _create_color_jpeg(preview_path, preview_color)
        preview_paths[photo_id] = preview_path

    library = FakeLibrary(
        {
            photo_id: _photo_record(
                photo_id,
                preview_source=source_path,
                metadata_source=metadata_path,
                has_jpeg=has_jpeg,
                has_raw=has_raw,
                has_heif=has_heif,
            )
        },
        preview_paths,
    )
    expected_color = (
        source_color if source_color is not None else preview_color
    )
    assert expected_color is not None

    assert copy_photo_pixels_to_clipboard(cast('Any', library), photo_id)

    assert library.preview_calls == expected_preview_calls
    _assert_close_rgb(_clipboard_pixel(), expected_color)
    del app
