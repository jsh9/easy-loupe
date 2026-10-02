from __future__ import annotations

import struct
from typing import TYPE_CHECKING

import brotli
import pytest
from PIL import Image

import easy_loupe.core.jxl_metadata as jxl_metadata_module
import easy_loupe.core.preview  # noqa: F401 - registers the JPEG XL plugin

if TYPE_CHECKING:
    from pathlib import Path


def _camera_exif() -> Image.Exif:
    exif = Image.Exif()
    exif[0x010F] = 'Canon'  # Make
    exif[0x0110] = 'EOS R5'  # Model
    exif[0x0112] = 6  # Orientation: rotate 90 degrees clockwise.
    return exif


def _tiff_bytes() -> bytes:
    """Return the camera EXIF as a bare TIFF stream."""
    return _camera_exif().tobytes().removeprefix(b'Exif\x00\x00')


def _box(box_type: bytes, payload: bytes, *, large: bool = False) -> bytes:
    if large:
        # Size 1 means a 64-bit size follows the box type.
        return struct.pack('>I4sQ', 1, box_type, 16 + len(payload)) + payload

    return struct.pack('>I4s', 8 + len(payload), box_type) + payload


def _container(*boxes: bytes) -> bytes:
    return jxl_metadata_module.JXL_CONTAINER_SIGNATURE + b''.join(boxes)


def _compressed_exif_box(exif_box: bytes, *, large: bool = False) -> bytes:
    return _box(b'brob', b'Exif' + brotli.compress(exif_box), large=large)


def test_extract_compressed_jxl_exif_reads_plugin_brob_box(
        tmp_path: Path,
) -> None:
    """
    Verify Brotli-compressed Exif from a real JPEG XL file is recovered.

    ``cjxl`` and ``pillow-jxl-plugin`` both write ``brob`` Exif boxes, which
    the macOS packaged ExifTool cannot decompress. The extracted stream must be
    a TIFF stream that still carries the camera tags.
    """
    path = tmp_path / 'IMG_7000.JXL'
    Image.new('RGB', (8, 8), 'red').save(
        path,
        format='JXL',
        lossless=True,
        exif=_camera_exif().tobytes(),
        compress_metadata=True,
    )

    tiff = jxl_metadata_module.extract_compressed_jxl_exif(path)

    assert tiff is not None
    assert tiff[:4] in {b'II*\x00', b'MM\x00*'}
    exif = Image.Exif()
    exif.load(tiff)
    assert exif[0x010F] == 'Canon'
    assert exif[0x0112] == 6


@pytest.mark.parametrize(
    'large_box',
    [
        pytest.param(False, id='regular-box'),
        pytest.param(True, id='64-bit-box-size'),
    ],
)
def test_extract_compressed_jxl_exif_skips_codestream_and_honors_offset(
        tmp_path: Path,
        large_box: bool,
) -> None:
    """
    Verify box walking past codestream boxes and the Exif TIFF offset.

    Metadata boxes can follow partial codestream boxes, box sizes can use the
    64-bit form, and the Exif box starts with an offset to the TIFF header that
    must be skipped rather than assumed to be zero.
    """
    tiff = _tiff_bytes()
    padding = b'\x00\x00'
    exif_box = struct.pack('>I', len(padding)) + padding + tiff
    path = tmp_path / 'IMG_7001.JXL'
    path.write_bytes(
        _container(
            _box(b'ftyp', b'jxl \x00\x00\x00\x00jxl '),
            _box(b'jxlp', b'\x00' * 64),
            _compressed_exif_box(exif_box, large=large_box),
        )
    )

    assert jxl_metadata_module.extract_compressed_jxl_exif(path) == tiff


@pytest.mark.parametrize(
    'payload',
    [
        pytest.param(b'\xff\x0a' + b'\x00' * 16, id='bare-codestream'),
        pytest.param(b'not a jpeg xl file', id='not-jxl'),
        pytest.param(
            _container(_box(b'Exif', b'\x00\x00\x00\x00' + _tiff_bytes())),
            id='uncompressed-exif-box',
        ),
        pytest.param(
            _container(_box(b'brob', b'Exif' + b'not brotli data')),
            id='corrupt-brotli',
        ),
        pytest.param(
            _container(_compressed_exif_box(b'\x00\x00\x00\x00not-tiff')),
            id='not-tiff',
        ),
        pytest.param(
            _container(struct.pack('>I4s', 4, b'jxlp')),
            id='box-smaller-than-header',
        ),
        pytest.param(
            jxl_metadata_module.JXL_CONTAINER_SIGNATURE + b'\x00\x00',
            id='truncated-box-header',
        ),
    ],
)
def test_extract_compressed_jxl_exif_returns_none_without_usable_box(
        tmp_path: Path, payload: bytes
) -> None:
    """
    Verify files without a usable compressed Exif box yield no fallback data.

    ExifTool already reads uncompressed boxes itself, and corrupt files must
    not raise inside folder loading or loop on a malformed box size.
    """
    path = tmp_path / 'IMG_7002.JXL'
    path.write_bytes(payload)

    assert jxl_metadata_module.extract_compressed_jxl_exif(path) is None


def test_extract_compressed_jxl_exif_rejects_oversized_output(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify a Brotli payload that inflates past the cap is ignored.

    The cap protects folder loading from decompression bombs hidden in a
    small compressed box.
    """
    monkeypatch.setattr(jxl_metadata_module, 'MAX_DECOMPRESSED_EXIF_BYTES', 16)
    path = tmp_path / 'IMG_7003.JXL'
    path.write_bytes(
        _container(_compressed_exif_box(b'\x00\x00\x00\x00' + _tiff_bytes()))
    )

    assert jxl_metadata_module.extract_compressed_jxl_exif(path) is None


def test_extract_compressed_jxl_exif_returns_none_for_missing_file(
        tmp_path: Path,
) -> None:
    """Verify unreadable files are treated as having no compressed Exif."""
    assert (
        jxl_metadata_module.extract_compressed_jxl_exif(tmp_path / 'gone.jxl')
        is None
    )
