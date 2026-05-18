from __future__ import annotations

from typing import TYPE_CHECKING
from xml.dom import Node, minidom  # noqa: S408

import pytest

import easy_cull.operations.xmp as xmp_module
from easy_cull.core.photo_library import PhotoLibrary
from easy_cull.operations.common import OperationError, undo_operation
from easy_cull.operations.xmp import (
    CAP1_NAMESPACE,
    RDF_NAMESPACE,
    XMP_NAMESPACE,
    XMPDM_NAMESPACE,
    WriteXmpOptions,
    write_xmp_sidecars,
)
from tests.core._helpers import create_jpeg, stub_read_exif

if TYPE_CHECKING:
    from pathlib import Path


def test_xmp_module_exports_write_xmp_sidecars() -> None:
    assert write_xmp_sidecars.__name__ == 'write_xmp_sidecars'


@pytest.mark.parametrize('merge_policy', ['preserve', 'replace'])
@pytest.mark.parametrize(
    (
        'rating',
        'color_label',
        'flag',
        'expected_label',
        'expected_good',
        'expected_pick',
        'expected_cap1',
    ),
    [
        pytest.param(
            5,
            'red',
            'picked',
            'Red',
            'true',
            '1',
            '1',
            id='picked',
        ),
        pytest.param(
            2,
            'blue',
            'rejected',
            'Blue',
            'false',
            '-1',
            '0',
            id='rejected',
        ),
        pytest.param(
            None,
            'green',
            None,
            'Green',
            None,
            '0',
            '0',
            id='no-flag',
        ),
    ],
)
@pytest.mark.parametrize('existing_sidecar', [False, True])
def test_write_xmp_sidecars_writes_expected_managed_fields(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        merge_policy: str,
        rating: int | None,
        color_label: str | None,
        flag: str | None,
        expected_label: str,
        expected_good: str | None,
        expected_pick: str,
        expected_cap1: str,
        existing_sidecar: bool,
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_5000',
        create_raw=True,
        create_jpeg_file=True,
    )
    sidecar_path = source_folder / 'IMG_5000.XMP'
    if existing_sidecar:
        sidecar_path.write_text(_existing_sidecar_xml(), encoding='utf-8')

    fields = {'rating', 'color_label', 'flag'}
    library.update_metadata(
        'IMG_5000',
        rating=rating,
        color_label=color_label,
        flag=flag,
        fields=fields,
    )

    summary = write_xmp_sidecars(
        source_folder,
        library.get_photos(),
        WriteXmpOptions(merge_policy=merge_policy),  # type: ignore[arg-type]
    )

    assert summary.processed_photos == 1
    assert summary.written_sidecars == 1
    assert summary.skipped_photos == 0
    assert sidecar_path.exists()

    description = _description_for(sidecar_path)
    assert description.getAttribute('xmlns:xmp') == XMP_NAMESPACE
    assert description.getAttribute('xmlns:xmpDM') == XMPDM_NAMESPACE
    assert description.getAttribute('xmlns:cap1') == CAP1_NAMESPACE
    assert _element_text(description, XMP_NAMESPACE, 'Rating') == str(
        rating or 0
    )
    assert _element_text(description, XMP_NAMESPACE, 'Label') == expected_label
    assert _element_text(description, XMPDM_NAMESPACE, 'good') == expected_good
    assert _element_text(description, XMPDM_NAMESPACE, 'pick') == expected_pick
    assert _element_text(description, CAP1_NAMESPACE, 'Flag') == expected_cap1
    sidecar_text = sidecar_path.read_text(encoding='utf-8')
    assert '\n  <rdf:RDF' in sidecar_text
    assert '\n    <rdf:Description' in sidecar_text
    assert sidecar_text.count('\n') > 4

    title = _element_text(
        description, 'http://purl.org/dc/elements/1.1/', 'title'
    )
    if existing_sidecar and merge_policy == 'preserve':
        assert title == 'Keep Me'
    else:
        assert title is None


@pytest.mark.parametrize('merge_policy', ['preserve', 'replace'])
def test_write_xmp_sidecars_clears_managed_fields_without_deleting_sidecar(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        merge_policy: str,
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_6000',
        create_raw=False,
        create_jpeg_file=True,
    )
    sidecar_path = source_folder / 'IMG_6000.XMP'
    sidecar_path.write_text(_existing_sidecar_xml(), encoding='utf-8')

    summary = write_xmp_sidecars(
        source_folder,
        library.get_photos(),
        WriteXmpOptions(merge_policy=merge_policy),  # type: ignore[arg-type]
    )

    assert summary.written_sidecars == 1
    assert sidecar_path.exists()
    description = _description_for(sidecar_path)
    assert _element_text(description, XMP_NAMESPACE, 'Rating') is None
    assert _element_text(description, XMP_NAMESPACE, 'Label') is None
    assert _element_text(description, XMPDM_NAMESPACE, 'good') is None
    assert _element_text(description, XMPDM_NAMESPACE, 'pick') is None
    assert _element_text(description, CAP1_NAMESPACE, 'Flag') is None
    title = _element_text(
        description, 'http://purl.org/dc/elements/1.1/', 'title'
    )
    if merge_policy == 'preserve':
        assert title == 'Keep Me'
    else:
        assert title is None


def test_write_xmp_sidecars_skips_untagged_photo_without_existing_sidecar(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_7000',
        create_raw=True,
        create_jpeg_file=False,
    )

    summary = write_xmp_sidecars(
        source_folder,
        library.get_photos(),
        WriteXmpOptions(merge_policy='preserve'),
    )

    assert summary.processed_photos == 1
    assert summary.written_sidecars == 0
    assert summary.skipped_photos == 1
    assert (source_folder / 'IMG_7000.XMP').exists() is False


def test_write_xmp_sidecars_fails_on_malformed_existing_sidecar(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_8000',
        create_raw=False,
        create_jpeg_file=True,
    )
    library.update_metadata('IMG_8000', rating=4, fields={'rating'})
    (source_folder / 'IMG_8000.XMP').write_text('<not-xmp', encoding='utf-8')

    with pytest.raises(OperationError, match='Malformed XMP sidecar'):
        write_xmp_sidecars(
            source_folder,
            library.get_photos(),
            WriteXmpOptions(merge_policy='preserve'),
        )


@pytest.mark.parametrize('merge_policy', ['preserve', 'replace'])
def test_write_xmp_sidecars_undo_removes_newly_created_sidecars(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        merge_policy: str,
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_8100',
        create_raw=True,
        create_jpeg_file=True,
    )
    library.update_metadata(
        'IMG_8100',
        rating=5,
        color_label='purple',
        flag='picked',
        fields={'rating', 'color_label', 'flag'},
    )

    summary = write_xmp_sidecars(
        source_folder,
        library.get_photos(),
        WriteXmpOptions(merge_policy=merge_policy),  # type: ignore[arg-type]
    )

    sidecar_path = source_folder / 'IMG_8100.XMP'
    assert sidecar_path.exists()

    undo_operation(summary.undo_plan)

    assert sidecar_path.exists() is False


@pytest.mark.parametrize('merge_policy', ['preserve', 'replace'])
@pytest.mark.parametrize('has_any_tags', [False, True])
def test_write_xmp_sidecars_undo_restores_existing_sidecar_bytes(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        merge_policy: str,
        has_any_tags: bool,
) -> None:
    source_folder, library = _make_library(
        tmp_path,
        monkeypatch,
        stem='IMG_8200',
        create_raw=False,
        create_jpeg_file=True,
    )
    sidecar_path = source_folder / 'IMG_8200.XMP'
    original_payload = _existing_sidecar_xml().encode('utf-8')
    sidecar_path.write_bytes(original_payload)
    if has_any_tags:
        library.update_metadata(
            'IMG_8200',
            rating=4,
            color_label='blue',
            flag='rejected',
            fields={'rating', 'color_label', 'flag'},
        )

    summary = write_xmp_sidecars(
        source_folder,
        library.get_photos(),
        WriteXmpOptions(merge_policy=merge_policy),  # type: ignore[arg-type]
    )

    assert sidecar_path.read_bytes() != original_payload

    undo_operation(summary.undo_plan)

    assert sidecar_path.read_bytes() == original_payload


def test_write_xmp_sidecars_rolls_back_partial_failures(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_folder = tmp_path / 'multi'
    source_folder.mkdir()
    create_jpeg(source_folder / 'IMG_8300.JPG', 'red')
    create_jpeg(source_folder / 'IMG_8301.JPG', 'blue')
    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / '.cache-multi')
    library.load_folder(source_folder)
    for photo_id in ('IMG_8300', 'IMG_8301'):
        library.update_metadata(
            photo_id,
            rating=3,
            fields={'rating'},
        )

    original_write_photo_sidecar = xmp_module._write_photo_sidecar
    write_calls = {'count': 0}

    def fail_second_sidecar(*args: object, **kwargs: object) -> None:
        write_calls['count'] += 1
        if write_calls['count'] == 2:
            raise RuntimeError('xmp boom')

        original_write_photo_sidecar(*args, **kwargs)

    monkeypatch.setattr(
        xmp_module,
        '_write_photo_sidecar',
        fail_second_sidecar,
    )

    with pytest.raises(RuntimeError, match='xmp boom'):
        write_xmp_sidecars(
            source_folder,
            library.get_photos(),
            WriteXmpOptions(merge_policy='preserve'),
        )

    assert (source_folder / 'IMG_8300.XMP').exists() is False
    assert (source_folder / 'IMG_8301.XMP').exists() is False


def _make_library(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        stem: str,
        create_raw: bool,
        create_jpeg_file: bool,
) -> tuple[Path, PhotoLibrary]:
    source_folder = tmp_path / stem.lower()
    source_folder.mkdir()
    if create_jpeg_file:
        create_jpeg(source_folder / f'{stem}.JPG', 'red')

    if create_raw:
        (source_folder / f'{stem}.CR3').write_bytes(b'raw')

    stub_read_exif(monkeypatch, {})
    library = PhotoLibrary(cache_dir=tmp_path / f'.cache-{stem}')
    library.load_folder(source_folder)
    return source_folder, library


def _description_for(sidecar_path: Path) -> minidom.Element:
    document = minidom.parseString(sidecar_path.read_bytes())  # noqa: S318
    descriptions = document.getElementsByTagNameNS(
        RDF_NAMESPACE, 'Description'
    )
    assert descriptions
    return descriptions[0]


def _element_text(
        description: minidom.Element, namespace: str, local_name: str
) -> str | None:
    for child in description.childNodes:
        if child.nodeType != Node.ELEMENT_NODE:
            continue

        if child.namespaceURI == namespace and child.localName == local_name:
            return ''.join(
                node.data
                for node in child.childNodes
                if node.nodeType == Node.TEXT_NODE
            )

    return None


def _existing_sidecar_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="XMP Core 6.0.0">
  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
    <rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">
      <dc:title>Keep Me</dc:title>
      <xmp:Rating xmlns:xmp="http://ns.adobe.com/xap/1.0/">1</xmp:Rating>
    </rdf:Description>
  </rdf:RDF>
</x:xmpmeta>
"""
