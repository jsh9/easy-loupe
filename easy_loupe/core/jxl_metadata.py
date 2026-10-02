"""JPEG XL container metadata helpers for EasyLoupe."""

from __future__ import annotations

import os
import struct
from typing import TYPE_CHECKING, Any, BinaryIO, cast

try:
    import brotli
except ImportError:  # pragma: no cover - handled by dependency installation
    brotli = cast('Any', None)

if TYPE_CHECKING:
    from pathlib import Path

JXL_CONTAINER_SIGNATURE = b'\x00\x00\x00\x0cJXL \r\n\x87\n'
# Real Exif payloads are kilobytes. These caps keep a corrupt box size or a
# Brotli bomb from making folder loading read or inflate huge buffers.
MAX_COMPRESSED_EXIF_BYTES = 16 * 1024 * 1024
MAX_DECOMPRESSED_EXIF_BYTES = 16 * 1024 * 1024

_BOX_HEADER_SIZE = 8
_LARGE_BOX_SIZE_FIELD_SIZE = 8
_LARGE_BOX_SIZE_MARKER = 1
_BOX_EXTENDS_TO_END_MARKER = 0
_BOX_TYPE_SIZE = 4
_EXIF_TIFF_OFFSET_SIZE = 4
_COMPRESSED_BOX_TYPE = b'brob'
_EXIF_BOX_TYPE = b'Exif'
_TIFF_HEADERS = (b'II*\x00', b'MM\x00*')


def extract_compressed_jxl_exif(path: Path) -> bytes | None:
    """
    Return TIFF-format EXIF bytes from a Brotli-compressed JPEG XL box.

    ``cjxl`` stores Exif in a ``brob`` box by default, including lossless JPEG
    transcodes. ExifTool can only read that box when Perl has
    ``IO::Uncompress::Brotli``, which macOS system Perl lacks, so packaged apps
    would otherwise show no EXIF for those files. The returned bytes start with
    a TIFF header and can be parsed by ExifTool as a standalone file.

    Returns ``None`` for bare codestreams, files without a compressed Exif box,
    unreadable files, and corrupt or oversized payloads.
    """
    if brotli is None:
        return None

    try:
        with path.open('rb') as file:
            compressed = _read_compressed_exif_payload(file)
    except OSError:
        return None

    if compressed is None:
        return None

    exif_box = _decompress_limited(compressed)
    if exif_box is None:
        return None

    return _tiff_bytes_from_exif_box(exif_box)


def _read_compressed_exif_payload(file: BinaryIO) -> bytes | None:
    """
    Return the compressed payload of the first ``brob`` Exif box.

    Boxes are visited by seeking past their payloads, because metadata boxes
    can sit between partial codestream (``jxlp``) boxes and the codestream
    itself can be many megabytes.
    """
    if file.read(len(JXL_CONTAINER_SIGNATURE)) != JXL_CONTAINER_SIGNATURE:
        return None

    file_size = os.fstat(file.fileno()).st_size
    position = len(JXL_CONTAINER_SIGNATURE)
    while position + _BOX_HEADER_SIZE <= file_size:
        file.seek(position)
        size, box_type = struct.unpack('>I4s', file.read(_BOX_HEADER_SIZE))
        header_size = _BOX_HEADER_SIZE
        if size == _LARGE_BOX_SIZE_MARKER:
            large_size = file.read(_LARGE_BOX_SIZE_FIELD_SIZE)
            if len(large_size) < _LARGE_BOX_SIZE_FIELD_SIZE:
                return None

            size = struct.unpack('>Q', large_size)[0]
            header_size += _LARGE_BOX_SIZE_FIELD_SIZE
        elif size == _BOX_EXTENDS_TO_END_MARKER:
            size = file_size - position

        if size < header_size:
            # A box smaller than its own header means the file is corrupt;
            # stop instead of looping on the same position.
            return None

        if box_type == _COMPRESSED_BOX_TYPE:
            payload_size = size - header_size - _BOX_TYPE_SIZE
            inner_type = file.read(_BOX_TYPE_SIZE)
            if (
                inner_type == _EXIF_BOX_TYPE
                and 0 < payload_size <= MAX_COMPRESSED_EXIF_BYTES
            ):
                payload = file.read(payload_size)
                return payload if len(payload) == payload_size else None

        position += size

    return None


def _decompress_limited(compressed: bytes) -> bytes | None:
    """Inflate a Brotli payload, rejecting corrupt or oversized output."""
    decompressor = brotli.Decompressor()
    try:
        output = decompressor.process(
            compressed, output_buffer_limit=MAX_DECOMPRESSED_EXIF_BYTES
        )
    except brotli.error:
        return None

    # ``is_finished`` stays false when the output limit stopped inflation
    # early or the stream was truncated; neither yields usable Exif. The
    # limit only stops buffer growth, so the length is checked as well.
    if (
        not decompressor.is_finished()
        or len(output) > MAX_DECOMPRESSED_EXIF_BYTES
    ):
        return None

    return output


def _tiff_bytes_from_exif_box(exif_box: bytes) -> bytes | None:
    """
    Strip the JPEG XL Exif box prefix and return the TIFF stream.

    JPEG XL Exif boxes begin with a 4-byte big-endian offset from the end of
    that field to the TIFF header, which is usually zero. Some writers,
    including ``pillow-jxl-plugin``, omit the offset field and start directly
    with the TIFF header, so that form is accepted too.
    """
    if exif_box[: len(_TIFF_HEADERS[0])] in _TIFF_HEADERS:
        return exif_box

    if len(exif_box) < _EXIF_TIFF_OFFSET_SIZE:
        return None

    offset = struct.unpack('>I', exif_box[:_EXIF_TIFF_OFFSET_SIZE])[0]
    tiff = exif_box[_EXIF_TIFF_OFFSET_SIZE + offset :]
    if tiff[: len(_TIFF_HEADERS[0])] not in _TIFF_HEADERS:
        return None

    return tiff
