from __future__ import annotations

from pathlib import Path

from easy_loupe.core.photo_groups import PHOTO_FORMATS, classify_photo_files
from easy_loupe.core.records import RAW_EXTENSIONS, SUPPORTED_EXTENSIONS


def test_photo_formats_cover_every_supported_extension_once() -> None:
    """
    Verify the format table classifies each supported extension exactly once.

    Preview priority and both culling and photo-viewer EXIF file-size rows
    classify files only through ``PHOTO_FORMATS``. A supported extension
    missing from the table would load but never become a preview source or
    appear in file sizes, and overlapping entries would count a file twice.
    """
    extension_sets = [extensions for _, extensions in PHOTO_FORMATS]

    assert set().union(*extension_sets) == SUPPORTED_EXTENSIONS
    assert sum(len(extensions) for extensions in extension_sets) == len(
        SUPPORTED_EXTENSIONS
    )
    # RAW must stay last so any raster format wins the preview source.
    assert PHOTO_FORMATS[-1] == ('RAW', RAW_EXTENSIONS)


def test_classify_photo_files_keeps_priority_labels_and_input_order() -> None:
    """
    Verify classification output shape relied on by its callers.

    Callers take the first non-empty label as the preview format and render
    file-size rows by iterating the result, so every label must be present
    in table order, files must keep their input order within a label, and
    unsupported files must be ignored rather than raising.
    """
    files = [
        Path('b.PNG'),
        Path('a.arw'),
        Path('a.png'),
        Path('notes.txt'),
        Path('a.jxl'),
    ]

    files_by_format = classify_photo_files(files)

    assert list(files_by_format) == [label for label, _ in PHOTO_FORMATS]
    assert files_by_format == {
        'JPG': [],
        'HEIF': [],
        'JXL': [Path('a.jxl')],
        'PNG': [Path('b.PNG'), Path('a.png')],
        'RAW': [Path('a.arw')],
    }
