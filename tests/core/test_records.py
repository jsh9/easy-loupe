from __future__ import annotations

from typing import TYPE_CHECKING

from easy_cull import core
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.core.records import SceneGroup
from tests.core._helpers import create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_records_module_exports_photo_record() -> None:
    assert core.records.PhotoRecord.__name__ == 'PhotoRecord'


def test_photo_record_to_api_dict_returns_expected_shape(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify API serialization exposes the supported source-type flags.

    Clients distinguish JPEG, HEIF, any raster, and RAW availability, so this
    catches regressions where the record model gains a source type but the API
    response shape is not kept in sync.
    """
    create_jpeg(tmp_path / 'IMG_9000.JPG', 'orange')
    stub_read_exif(
        monkeypatch,
        {'IMG_9000.JPG': {'ImageWidth': 4000, 'ImageHeight': 3000}},
    )

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.update_metadata('IMG_9000', rating=3, fields={'rating'})
    library.update_metadata(
        'IMG_9000', color_label='blue', fields={'color_label'}
    )
    library.update_metadata('IMG_9000', flag='picked', fields={'flag'})

    photo = library.get_photo('IMG_9000')
    api_dict = photo.to_api_dict()

    assert api_dict['photo_id'] == 'IMG_9000'
    assert api_dict['display_name'] == 'IMG_9000'
    assert api_dict['files'] == ['IMG_9000.JPG']
    assert api_dict['has_jpeg'] is True
    assert api_dict['has_heif'] is False
    assert api_dict['has_raster'] is True
    assert api_dict['has_raw'] is False
    assert api_dict['rating'] == 3
    assert api_dict['color_label'] == 'blue'
    assert api_dict['flag'] == 'picked'
    assert api_dict['focus_point'] == {'x': 0.5, 'y': 0.5}
    assert api_dict['scene_id'] is None
    assert api_dict['image_width'] == 4000
    assert api_dict['image_height'] == 3000
    assert isinstance(api_dict['preview_version'], str)


def test_scene_group_to_api_dict_returns_expected_shape() -> None:
    scene = SceneGroup(
        scene_id='scene-0001', photo_ids=['IMG_A', 'IMG_B', 'IMG_C']
    )
    api_dict = scene.to_api_dict()

    assert api_dict == {
        'scene_id': 'scene-0001',
        'photo_ids': ['IMG_A', 'IMG_B', 'IMG_C'],
        'count': 3,
        'cover_photo_id': 'IMG_A',
    }

    empty_scene = SceneGroup(scene_id='scene-empty', photo_ids=[])
    empty_dict = empty_scene.to_api_dict()

    assert empty_dict['count'] == 0
    assert empty_dict['cover_photo_id'] is None
