from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from easy_loupe import core
from easy_loupe.core.metadata import (
    normalize_metadata_entries,
    normalize_scene_groups,
    serialize_folder_metadata,
    serialize_metadata_entries,
)
from easy_loupe.core.photo_library import PhotoLibrary
from easy_loupe.core.records import METADATA_FILENAME
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
            'photos': {
                'IMG_1000.JPG': {
                    'flag': 'reject',
                    'rating': 5,
                    'color_label': 'purple',
                }
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
        'photos': {
            'IMG_2000': {
                'color_label': 'red',
                'flag': 'rejected',
                'rating': 4,
            }
        }
    }


def test_recursive_metadata_uses_posix_relative_photo_ids(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify recursive metadata reads legacy separators and writes POSIX IDs.

    Saved metadata must be portable across platforms while still identifying
    nested photos unambiguously.
    """
    subfolder = tmp_path / 'subfolder_1'
    subfolder.mkdir()
    create_jpeg(subfolder / 'IMG_1234.JPG', 'green')
    metadata_path = tmp_path / METADATA_FILENAME
    metadata_path.write_text(
        json.dumps({
            'photos': {
                'subfolder_1\\IMG_1234.JPG': {
                    'rating': 5,
                    'flag': 'picked',
                }
            }
        }),
        encoding='utf-8',
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    photo = library.get_photo('subfolder_1/IMG_1234')
    assert photo.rating == 5
    assert photo.flag == 'picked'

    library.update_metadata(
        'subfolder_1/IMG_1234',
        color_label='blue',
        fields={'color_label'},
    )
    library.save_metadata()

    data = json.loads(metadata_path.read_text(encoding='utf-8'))
    assert data == {
        'photos': {
            'subfolder_1/IMG_1234': {
                'color_label': 'blue',
                'flag': 'picked',
                'rating': 5,
            }
        }
    }


def test_load_folder_preserves_dotted_photo_id_metadata(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify dotted stems are treated as photo IDs before legacy filenames.

    A saved key such as ``IMG.0001`` is already an extensionless current photo
    ID and should not be stripped to ``IMG`` during metadata loading.
    """
    create_jpeg(tmp_path / 'IMG.0001.JPG', 'green')
    metadata_path = tmp_path / METADATA_FILENAME
    metadata_path.write_text(
        json.dumps({
            'photos': {
                'IMG.0001': {
                    'rating': 5,
                    'flag': 'picked',
                }
            }
        }),
        encoding='utf-8',
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    photo = library.get_photo('IMG.0001')
    assert photo.rating == 5
    assert photo.flag == 'picked'


def test_metadata_normalization_and_serialization() -> None:
    normalized = normalize_metadata_entries({
        'photos': {
            'IMG_1000.JPG': {
                'files': ['IMG_1000.JPG'],
                'rating': 4,
                'flag': 'reject',
                'color_label': 'yellow',
            },
            'IMG_1001': {'flag': 'picked', 'color_label': 'purple'},
            'IMG_1002.NEF': {'rating': 8, 'color_label': 'orange'},
        }
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


def test_flat_metadata_payload_is_ignored() -> None:
    assert (
        normalize_metadata_entries({
            'IMG_1000.JPG': {'rating': 4, 'flag': 'picked'}
        })
        == {}
    )


def test_scene_group_normalization_repairs_folder_changes() -> None:
    source, scenes = normalize_scene_groups(
        {
            'scenes': {
                'source': 'manual',
                'groups': [
                    ['IMG_1000', 'MISSING', 'IMG_1001', 'IMG_1001'],
                    ['IMG_1002'],
                ],
            }
        },
        ['IMG_1000', 'IMG_1001', 'IMG_1002', 'IMG_1003'],
    )

    assert source == 'manual'
    assert [scene.scene_id for scene in scenes] == [
        'scene-0001',
        'scene-0002',
        'scene-0003',
    ]
    assert [scene.photo_ids for scene in scenes] == [
        ['IMG_1000', 'IMG_1001'],
        ['IMG_1002'],
        ['IMG_1003'],
    ]


def test_scene_group_normalization_preserves_relative_photo_ids() -> None:
    """
    Verify saved scene groups normalize subfolder IDs without flattening them.

    Scene edits are persisted by photo ID, so recursive scenes need the same
    portable path normalization as per-photo metadata.
    """
    source, scenes = normalize_scene_groups(
        {
            'scenes': {
                'source': 'manual',
                'groups': [['subfolder_1\\IMG_1000.JPG', 'IMG_1001.JPG']],
            }
        },
        ['subfolder_1/IMG_1000', 'IMG_1001'],
    )

    assert source == 'manual'
    assert [scene.photo_ids for scene in scenes] == [
        ['subfolder_1/IMG_1000', 'IMG_1001']
    ]


def test_scene_group_normalization_preserves_dotted_photo_ids() -> None:
    """
    Verify saved scene IDs with dotted stems are not extension-stripped.

    Dotted camera sequence names such as ``IMG.0001`` are valid current photo
    IDs, so they should match exactly before legacy filename fallback runs.
    """
    source, scenes = normalize_scene_groups(
        {
            'scenes': {
                'source': 'manual',
                'groups': [['IMG.0001', 'IMG.0002']],
            }
        },
        ['IMG.0001', 'IMG.0002'],
    )

    assert source == 'manual'
    assert [scene.photo_ids for scene in scenes] == [['IMG.0001', 'IMG.0002']]


def test_scene_group_normalization_rejects_only_missing_photo_ids() -> None:
    """
    Ignore saved scene groups when none of their photo IDs exist now.

    Without this guard, loading an unrelated folder with stale scene data would
    mark scene detection as done and create singleton scene groups for every
    current photo.
    """
    source, scenes = normalize_scene_groups(
        {
            'scenes': {
                'source': 'manual',
                'groups': [['MISSING_1000'], ['MISSING_1001']],
            }
        },
        ['IMG_1000', 'IMG_1001'],
    )

    assert source is None
    assert scenes == []


@pytest.mark.parametrize(
    ('saved_photos', 'valid_photo_ids', 'expected'),
    [
        pytest.param(
            {'DSC01234': {'rating': 5}},
            ['dsc01234'],
            {'dsc01234': {'rating': 5}},
            id='stem-case-change',
        ),
        pytest.param(
            {'DSC01234.ARW': {'flag': 'picked'}},
            ['dsc01234'],
            {'dsc01234': {'flag': 'picked'}},
            id='legacy-filename-key-with-case-change',
        ),
        pytest.param(
            {'dsc01234': {'rating': 2}, 'DSC01234': {'rating': 5}},
            ['dsc01234'],
            {'dsc01234': {'rating': 2}},
            id='exact-key-wins-over-case-variant',
        ),
        pytest.param(
            {'Trip/IMG_1000': {'rating': 4}},
            ['trip/img_1000'],
            {},
            id='parent-folder-case-must-match',
        ),
        pytest.param(
            {'Img_1000': {'rating': 4}},
            ['img_1000', 'IMG_1000'],
            {},
            id='ambiguous-case-variants-are-not-guessed',
        ),
    ],
)
def test_metadata_normalization_falls_back_to_stem_case_changes(
        saved_photos: dict[str, dict[str, object]],
        valid_photo_ids: list[str],
        expected: dict[str, dict[str, object]],
) -> None:
    """
    Verify saved metadata follows a photo whose ID changed only in case.

    A photo ID is the stem of the companion that wins preview priority, so
    ``DSC01234.ARW`` gaining ``dsc01234.png`` renames the photo. Without this
    fallback its rating would vanish and be dropped on the next save. Exact
    keys must still win, and parent folders stay case-sensitive because
    recursive loads can contain ``Trip/`` and ``trip/`` as different folders.
    """
    assert (
        normalize_metadata_entries(
            {'photos': saved_photos}, valid_photo_ids=valid_photo_ids
        )
        == expected
    )


def test_scene_group_normalization_follows_stem_case_changes() -> None:
    """
    Verify saved scene groups keep photos whose ID changed only in case.

    Scene membership is stored by photo ID, so it needs the same case-only
    fallback as per-photo metadata to survive a new companion file.
    """
    source, scenes = normalize_scene_groups(
        {
            'scenes': {
                'source': 'manual',
                'groups': [['DSC01234', 'DSC01235']],
            }
        },
        ['dsc01234', 'DSC01235', 'DSC01236'],
    )

    assert source == 'manual'
    assert [scene.photo_ids for scene in scenes] == [
        ['dsc01234', 'DSC01235'],
        ['DSC01236'],
    ]


def test_load_folder_keeps_rating_when_png_companion_renames_photo(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a new PNG companion with a lowercase stem keeps a RAW's rating.

    PNG now outranks RAW as the preview source, so ``dsc01234.png`` changes the
    photo ID of an already rated ``DSC01234.ARW``. The rating must load under
    the new ID and be saved there instead of being erased.
    """
    stub_read_exif(monkeypatch, {})
    (tmp_path / 'DSC01234.ARW').write_bytes(b'raw')
    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.update_metadata('DSC01234', rating=5, fields={'rating'})
    library.save_metadata()

    (tmp_path / 'dsc01234.png').write_bytes(b'png')
    reloaded = PhotoLibrary(cache_dir=tmp_path / '.cache')
    reloaded.load_folder(tmp_path)
    reloaded.save_metadata()

    assert [photo.photo_id for photo in reloaded.photos] == ['dsc01234']
    assert reloaded.photos[0].rating == 5
    saved = json.loads((tmp_path / METADATA_FILENAME).read_text())
    assert saved['photos'] == {'dsc01234': {'rating': 5}}


def test_folder_metadata_serializes_photos_and_scenes() -> None:
    photos = [
        make_photo_record(
            'IMG_1000', rating=4, color_label='yellow', flag='rejected'
        ),
        make_photo_record(
            'IMG_1001', rating=None, color_label=None, flag=None
        ),
    ]
    _, scenes = normalize_scene_groups(
        {'scenes': {'source': 'manual', 'groups': [['IMG_1000', 'IMG_1001']]}},
        ['IMG_1000', 'IMG_1001'],
    )

    assert serialize_folder_metadata(
        photos, scenes, scene_source='manual'
    ) == {
        'photos': {
            'IMG_1000': {
                'rating': 4,
                'color_label': 'yellow',
                'flag': 'rejected',
            }
        },
        'scenes': {
            'source': 'manual',
            'groups': [['IMG_1000', 'IMG_1001']],
        },
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


def test_load_folder_reads_saved_rotation_and_ignores_invalid_values(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify saved view rotations load, including through legacy keys.

    Rotation lives in the same per-photo entry as tags, so it must follow
    legacy filename-key migration. Invalid values must be ignored instead of
    blocking the folder load, matching how bad ratings are handled.
    """
    for photo_id in ('IMG_3000', 'IMG_3001', 'IMG_3002', 'IMG_3003'):
        create_jpeg(tmp_path / f'{photo_id}.JPG', 'green')

    (tmp_path / METADATA_FILENAME).write_text(
        json.dumps({
            'photos': {
                'IMG_3000': {'rotation': 90},
                'IMG_3001.JPG': {'rotation': 270, 'rating': 2},
                'IMG_3002': {'rotation': 45},
                'IMG_3003': {'rotation': True},
            }
        }),
        encoding='utf-8',
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    assert library.get_photo('IMG_3000').rotation == 90
    assert library.get_photo('IMG_3001').rotation == 270
    assert library.get_photo('IMG_3001').rating == 2
    assert library.get_photo('IMG_3002').rotation == 0
    assert library.get_photo('IMG_3003').rotation == 0


def test_save_metadata_writes_only_nonzero_rotation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify rotation persists as an optional key that disappears at zero.

    Unrotated photos must keep the historical on-disk shape, and turning a
    photo back to 0 must remove an entry that has no other metadata.
    """
    create_jpeg(tmp_path / 'IMG_3100.JPG', 'blue')
    create_jpeg(tmp_path / 'IMG_3101.JPG', 'red')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)
    library.update_metadata('IMG_3100', rotation=90, fields={'rotation'})
    library.update_metadata('IMG_3101', rating=3, fields={'rating'})
    library.save_metadata()

    metadata_path = tmp_path / METADATA_FILENAME
    assert json.loads(metadata_path.read_text(encoding='utf-8')) == {
        'photos': {
            'IMG_3100': {'rotation': 90},
            'IMG_3101': {'rating': 3},
        }
    }

    reloaded = PhotoLibrary(cache_dir=tmp_path / '.cache')
    reloaded.load_folder(tmp_path)
    assert reloaded.get_photo('IMG_3100').rotation == 90

    reloaded.update_metadata('IMG_3100', rotation=0, fields={'rotation'})
    reloaded.save_metadata()

    assert json.loads(metadata_path.read_text(encoding='utf-8')) == {
        'photos': {'IMG_3101': {'rating': 3}}
    }


def test_metadata_normalization_and_serialization_handle_rotation() -> None:
    """
    Verify the pure normalize/serialize pair round-trips rotation.

    Zero and invalid rotations are dropped on both sides so the persisted entry
    shape only grows when a photo is actually turned.
    """
    normalized = normalize_metadata_entries({
        'photos': {
            'IMG_3200': {'rotation': 180},
            'IMG_3201': {'rotation': 0},
            'IMG_3202': {'rotation': 'sideways', 'flag': 'picked'},
        }
    })

    assert normalized == {
        'IMG_3200': {'rotation': 180},
        'IMG_3202': {'flag': 'picked'},
    }

    photos = [
        make_photo_record(
            'IMG_3200', rating=None, color_label=None, flag=None, rotation=180
        ),
        make_photo_record(
            'IMG_3201', rating=None, color_label=None, flag=None, rotation=0
        ),
    ]
    assert serialize_metadata_entries(photos) == {
        'IMG_3200': {'rotation': 180}
    }


@pytest.mark.parametrize(
    'rotation',
    [45, -90, 360, '90', True],
    ids=['not-quarter-turn', 'negative', 'full-turn', 'string', 'bool'],
)
def test_update_metadata_rejects_invalid_rotation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, rotation: object
) -> None:
    """
    Verify rotation updates are validated like the other metadata fields.

    UI code only produces quarter turns, but the library API is shared and must
    refuse values that the loader would later discard.
    """
    create_jpeg(tmp_path / 'IMG_3300.JPG', 'purple')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    with pytest.raises(ValueError, match='rotation'):
        library.update_metadata(
            'IMG_3300', rotation=rotation, fields={'rotation'}
        )

    cleared = library.update_metadata(
        'IMG_3300', rotation=None, fields={'rotation'}
    )
    assert cleared.rotation == 0
