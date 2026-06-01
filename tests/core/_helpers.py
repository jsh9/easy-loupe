from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from PIL import Image

import easy_loupe.core.exif as core_exif_module
from easy_loupe.core.photo_library import PhotoLibrary

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def stub_read_exif(
        monkeypatch: pytest.MonkeyPatch,
        exif_map: dict[str, dict[str, object]],
) -> None:
    monkeypatch.setattr(
        core_exif_module, 'read_exif_metadata', lambda _files: exif_map
    )


def create_jpeg(path: Path, color: str) -> None:
    Image.new('RGB', (640, 480), color=color).save(path, format='JPEG')


def make_jpeg_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new('RGB', (12, 12), color=color).save(buffer, format='JPEG')
    return buffer.getvalue()


def assert_color_close(
        actual: tuple[int, int, int],
        expected: tuple[int, int, int],
        tolerance: int = 5,
) -> None:
    assert all(
        abs(actual[index] - expected[index]) <= tolerance for index in range(3)
    )


def load_raw_only_library(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw_name: str
) -> PhotoLibrary:
    (tmp_path / raw_name).write_bytes(b'raw')
    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    return library


def make_photo_record(
        photo_id: str,
        rating: int | None,
        color_label: str | None,
        flag: str | None,
) -> object:
    return type(
        'PhotoLike',
        (),
        {
            'photo_id': photo_id,
            'rating': rating,
            'color_label': color_label,
            'flag': flag,
        },
    )()


class FakeHash:
    def __init__(self, value: int) -> None:
        self.value = value

    def __sub__(self, other: object) -> int:
        if isinstance(other, FakeHash):
            return abs(self.value - other.value)

        return NotImplemented
