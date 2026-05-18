from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from easy_cull import core
from easy_cull.core.metadata import (
    normalize_metadata_entries,
    serialize_metadata_entries,
)
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.core.records import METADATA_FILENAME
from tests.core._helpers import create_jpeg, make_photo_record, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path


def test_metadata_module_exports_normalize_metadata_entries() -> None:
    assert hasattr(core.metadata, 'normalize_metadata_entries')


def test_load_folder_reads_existing_metadata_file(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_1000.JPG', 'green')
    metadata_path = tmp_path / METADATA_FILENAME
    metadata_path.write_text(
        json.dumps({
            'IMG_1000.JPG': {
                'flag': 'reject',
                'rating': 5,
                'color_label': 'purple',
            }
        }),
        encoding='utf-8',
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    assert library.photos[0].photo_id == 'IMG_1000'
    assert library.photos[0].flag == 'rejected'
    assert library.photos[0].rating == 5
    assert library.photos[0].color_label == 'purple'


def test_save_metadata_uses_visible_stem_key_format(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_2000.JPG', 'purple')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.update_metadata('IMG_2000', rating=4, fields={'rating'})
    library.update_metadata(
        'IMG_2000', color_label='red', fields={'color_label'}
    )
    library.update_metadata('IMG_2000', flag='rejected', fields={'flag'})
    library.save_metadata()

    data = json.loads(
        (tmp_path / METADATA_FILENAME).read_text(encoding='utf-8')
    )
    assert data == {
        'IMG_2000': {'color_label': 'red', 'flag': 'rejected', 'rating': 4}
    }


def test_metadata_normalization_and_serialization() -> None:
    normalized = normalize_metadata_entries({
        'IMG_1000.JPG': {
            'files': ['IMG_1000.JPG'],
            'rating': 4,
            'flag': 'reject',
            'color_label': 'yellow',
        },
        'IMG_1001': {'flag': 'picked', 'color_label': 'purple'},
        'IMG_1002.NEF': {'rating': 8, 'color_label': 'orange'},
    })

    assert normalized == {
        'IMG_1000': {'rating': 4, 'color_label': 'yellow', 'flag': 'rejected'},
        'IMG_1001': {'flag': 'picked', 'color_label': 'purple'},
    }

    photos = [
        make_photo_record(
            'IMG_1000', rating=4, color_label='yellow', flag='rejected'
        ),
        make_photo_record(
            'IMG_1001', rating=None, color_label='purple', flag='picked'
        ),
        make_photo_record(
            'IMG_1002', rating=None, color_label=None, flag=None
        ),
    ]
    assert serialize_metadata_entries(photos) == {
        'IMG_1000': {'rating': 4, 'color_label': 'yellow', 'flag': 'rejected'},
        'IMG_1001': {'color_label': 'purple', 'flag': 'picked'},
    }


def test_update_metadata_validates_color_labels(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_2001.JPG', 'purple')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    updated = library.update_metadata(
        'IMG_2001', color_label='blue', fields={'color_label'}
    )
    assert updated.color_label == 'blue'

    cleared = library.update_metadata(
        'IMG_2001', color_label=None, fields={'color_label'}
    )
    assert cleared.color_label is None

    with pytest.raises(ValueError, match='color_label'):
        library.update_metadata(
            'IMG_2001', color_label='orange', fields={'color_label'}
        )


@pytest.mark.parametrize(
    'payload',
    ['{not valid json', json.dumps(['not', 'a', 'dict'])],
)
def test_load_folder_ignores_invalid_metadata_file_payloads(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        payload: str,
) -> None:
    create_jpeg(tmp_path / 'IMG_2300.JPG', 'green')
    (tmp_path / METADATA_FILENAME).write_text(payload, encoding='utf-8')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    photo = library.photos[0]
    assert photo.rating is None
    assert photo.color_label is None
    assert photo.flag is None


def test_update_metadata_validates_ratings_and_flags(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_2400.JPG', 'purple')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    updated = library.update_metadata('IMG_2400', rating=5, fields={'rating'})
    assert updated.rating == 5

    cleared_rating = library.update_metadata(
        'IMG_2400', rating=None, fields={'rating'}
    )
    assert cleared_rating.rating is None

    with pytest.raises(ValueError, match='rating'):
        library.update_metadata('IMG_2400', rating=0, fields={'rating'})

    rejected = library.update_metadata(
        'IMG_2400', flag='reject', fields={'flag'}
    )
    assert rejected.flag == 'rejected'

    picked = library.update_metadata(
        'IMG_2400', flag='picked', fields={'flag'}
    )
    assert picked.flag == 'picked'

    cleared_flag = library.update_metadata(
        'IMG_2400', flag=None, fields={'flag'}
    )
    assert cleared_flag.flag is None

    with pytest.raises(ValueError, match='flag'):
        library.update_metadata('IMG_2400', flag='maybe', fields={'flag'})


def test_export_metadata_delegates_to_serialize(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    create_jpeg(tmp_path / 'IMG_9070.JPG', 'blue')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.update_metadata('IMG_9070', rating=2, fields={'rating'})

    exported = library.export_metadata()

    assert exported == {'IMG_9070': {'rating': 2}}
