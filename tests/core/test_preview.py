from __future__ import annotations

import gc
import os
import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any, Never, Self

import numpy as np
import pytest
from PIL import Image

import easy_loupe.core.preview as core_preview_module
from easy_loupe.core.photo_library import PhotoLibrary
from tests.core._helpers import (
    assert_color_close,
    create_jpeg,
    load_raw_only_library,
    make_jpeg_bytes,
    stub_read_exif,
)

if TYPE_CHECKING:
    from types import TracebackType


def test_preview_module_exports_get_preview_path() -> None:
    assert hasattr(core_preview_module, 'get_preview_path')


def test_preview_locks_are_released_after_render_scope() -> None:
    """
    Verify per-preview locks do not stay strongly retained forever.

    Long viewer sessions can touch many cache keys, so the lock registry should
    keep only locks that are still in active use.
    """
    cache_key = 'test-preview-lock-release'
    lock = core_preview_module._preview_lock(cache_key)
    lock_ref = weakref.ref(lock)

    assert core_preview_module._PREVIEW_LOCKS[cache_key] is lock

    del lock
    gc.collect()

    assert lock_ref() is None
    assert cache_key not in core_preview_module._PREVIEW_LOCKS


@pytest.mark.parametrize(
    (
        'raw_name',
        'thumbnail_mode',
        'preview_kinds',
        'expected_colors',
        'expected_extract_calls',
        'expected_postprocess_calls',
        'assert_full_separate',
    ),
    [
        pytest.param(
            'IMG_5000.CR3',
            'embedded',
            ('viewer', 'fit', 'thumb', 'full'),
            {
                'viewer': (0, 0, 128),
                'fit': (0, 0, 128),
                'thumb': (0, 0, 128),
                'full': (240, 30, 30),
            },
            ['extract_thumb', 'extract_thumb', 'extract_thumb'],
            ['postprocess:False'],
            True,
            id='embedded-thumb',
        ),
        pytest.param(
            'IMG_5001.CR3',
            'missing',
            ('viewer',),
            {'viewer': (12, 140, 220)},
            ['extract_thumb'],
            ['postprocess:True'],
            False,
            id='postprocess-fallback',
        ),
    ],
)
def test_raw_viewer_preview_prefers_embedded_thumbnail_and_falls_back_when_missing(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        raw_name: str,
        thumbnail_mode: str,
        preview_kinds: tuple[str, ...],
        expected_colors: dict[str, tuple[int, int, int]],
        expected_extract_calls: list[str],
        expected_postprocess_calls: list[str],
        assert_full_separate: bool,
) -> None:
    library = load_raw_only_library(tmp_path, monkeypatch, raw_name)

    extract_calls: list[str] = []
    postprocess_calls: list[str] = []

    class FakeThumbFormat:
        JPEG = 'jpeg'

    class FakeNoThumbnailError(Exception):
        pass

    class FakeThumbnail:
        def __init__(self, data: bytes) -> None:
            self.format = FakeThumbFormat.JPEG
            self.data = data

    class FakeRaw:
        def __enter__(self) -> Self:
            return self

        def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
        ) -> bool:
            return False

        @staticmethod
        def extract_thumb() -> Any:
            extract_calls.append('extract_thumb')
            if thumbnail_mode == 'embedded':
                return FakeThumbnail(make_jpeg_bytes('navy'))

            raise FakeNoThumbnailError()

        @staticmethod
        def postprocess(*, use_camera_wb: bool, half_size: bool) -> Any:  # noqa: ARG004
            postprocess_calls.append(f'postprocess:{half_size}')
            if thumbnail_mode == 'embedded':
                return np.full(
                    (4, 4, 3), fill_value=(240, 30, 30), dtype=np.uint8
                )

            return np.full(
                (3, 3, 3), fill_value=(12, 140, 220), dtype=np.uint8
            )

    fake_rawpy = type(
        'FakeRawPy',
        (),
        {
            'ThumbFormat': FakeThumbFormat,
            'LibRawNoThumbnailError': FakeNoThumbnailError,
            'imread': staticmethod(lambda _path: FakeRaw()),
        },
    )()
    monkeypatch.setattr('easy_loupe.core.preview.rawpy', fake_rawpy)

    preview_paths = {
        kind: library.get_preview_path(Path(raw_name).stem, kind)
        for kind in preview_kinds
    }

    if assert_full_separate:
        assert preview_paths['viewer'] != preview_paths['full']

    assert extract_calls == expected_extract_calls
    assert postprocess_calls == expected_postprocess_calls

    for kind, expected_color in expected_colors.items():
        with Image.open(preview_paths[kind]) as image:
            assert_color_close(
                image.convert('RGB').getpixel((0, 0)), expected_color
            )


def test_jpeg_preview_variants_resize_and_validate_kind(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    large_path = tmp_path / 'IMG_6000.JPG'
    Image.new('RGB', (4000, 3000), color='orange').save(
        large_path, format='JPEG'
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    thumb_path = library.get_preview_path('IMG_6000', 'thumb')
    fit_path = library.get_preview_path('IMG_6000', 'fit')
    viewer_path = library.get_preview_path('IMG_6000', 'viewer')
    full_path = library.get_preview_path('IMG_6000', 'full')

    with Image.open(thumb_path) as image:
        assert max(image.size) <= 256

    with Image.open(fit_path) as image:
        assert max(image.size) <= 1800

    with Image.open(viewer_path) as image:
        assert image.size == (4000, 3000)

    with Image.open(full_path) as image:
        assert image.size == (4000, 3000)

    with pytest.raises(ValueError, match='Preview kind'):
        library.get_preview_path('IMG_6000', 'bogus')


def test_heic_preview_uses_pillow_heif_opener(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / 'IMG_6001.HEIC'
    Image.new('RGB', (32, 24), color='teal').save(source_path, format='HEIF')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    viewer_path = library.get_preview_path('IMG_6001', 'viewer')

    with Image.open(viewer_path) as image:
        assert image.size == (32, 24)
        assert_color_close(
            image.convert('RGB').getpixel((0, 0)), (0, 128, 128)
        )


@pytest.mark.parametrize(
    ('filename', 'save_options'),
    [
        pytest.param('IMG_6002.PNG', {'format': 'PNG'}, id='png'),
        pytest.param(
            'IMG_6002.JXL', {'format': 'JXL', 'lossless': True}, id='jxl'
        ),
    ],
)
def test_png_and_jxl_previews_render_source_pixels(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        save_options: dict[str, Any],
) -> None:
    """
    Verify PNG and JPEG XL files render through the raster preview path.

    PNG decodes with stock Pillow and JPEG XL relies on the opener that
    ``pillow-jxl-plugin`` registers, so this catches a missing plugin import or
    a format that falls through to the RAW renderer.
    """
    Image.new('RGB', (32, 24), color='teal').save(
        tmp_path / filename, **save_options
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    viewer_path = library.get_preview_path('IMG_6002', 'viewer')

    with Image.open(viewer_path) as image:
        assert image.size == (32, 24)
        assert_color_close(
            image.convert('RGB').getpixel((0, 0)), (0, 128, 128)
        )


def _half_transparent_image(
        mode: str,
        transparent_color: Any,
        opaque_color: Any,
) -> Image.Image:
    """Return a 32x16 image: left half transparent, right half opaque."""
    image = Image.new(mode, (32, 16), transparent_color)
    # Paste a filled image rather than a bare color: Pillow silently ignores
    # bare integer colors when pasting into ``I;16`` images.
    image.paste(Image.new(mode, (16, 16), opaque_color), (16, 0))
    return image


def _half_transparent_palette_image() -> Image.Image:
    """Return a palette image whose index 0 (left half) is transparent."""
    image = _half_transparent_image('P', 0, 1)
    image.putpalette([255, 0, 0, 0, 0, 255])
    image.info['transparency'] = 0
    return image


@pytest.mark.parametrize(
    ('filename', 'image_factory', 'save_options', 'opaque_rgb'),
    [
        pytest.param(
            'IMG_6003.PNG',
            lambda: _half_transparent_image(
                'RGBA', (255, 0, 0, 0), (0, 0, 255, 255)
            ),
            {'format': 'PNG'},
            (0, 0, 255),
            id='png-rgba',
        ),
        pytest.param(
            'IMG_6003.PNG',
            lambda: _half_transparent_image('LA', (0, 0), (0, 255)),
            {'format': 'PNG'},
            (0, 0, 0),
            id='png-la',
        ),
        pytest.param(
            'IMG_6003.PNG',
            _half_transparent_palette_image,
            {'format': 'PNG', 'transparency': 0},
            (0, 0, 255),
            id='png-palette-trns',
        ),
        pytest.param(
            'IMG_6003.PNG',
            lambda: _half_transparent_image('I;16', 0, 32768),
            {'format': 'PNG', 'transparency': 0},
            (128, 128, 128),
            id='png-16-bit-gray-trns',
        ),
        pytest.param(
            'IMG_6003.JXL',
            lambda: _half_transparent_image(
                'RGBA', (255, 0, 0, 0), (0, 0, 255, 255)
            ),
            {'format': 'JXL', 'lossless': True},
            (0, 0, 255),
            id='jxl-rgba',
        ),
    ],
)
def test_transparent_raster_previews_flatten_onto_white(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        image_factory: Any,
        save_options: dict[str, Any],
        opaque_rgb: tuple[int, int, int],
) -> None:
    """
    Verify transparent pixels render white while opaque pixels keep color.

    Preview caches are JPEG, so alpha must be flattened. A plain
    ``convert('RGB')`` drops alpha and shows the color hidden under transparent
    pixels (red here), which would mislead culling decisions. The 16-bit
    grayscale case also guards against tone scaling bypassing transparency
    compositing.
    """
    image_factory().save(tmp_path / filename, **save_options)
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    viewer_path = library.get_preview_path('IMG_6003', 'viewer')

    with Image.open(viewer_path) as image:
        rgb = image.convert('RGB')
        assert_color_close(rgb.getpixel((2, 8)), (255, 255, 255))
        assert_color_close(rgb.getpixel((29, 8)), opaque_rgb)


@pytest.mark.parametrize(
    ('filename', 'save_options'),
    [
        pytest.param('IMG_6004.PNG', {'format': 'PNG'}, id='png'),
        pytest.param(
            'IMG_6004.JXL', {'format': 'JXL', 'lossless': True}, id='jxl'
        ),
    ],
)
def test_sixteen_bit_grayscale_previews_scale_to_eight_bits(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        save_options: dict[str, Any],
) -> None:
    """
    Verify 16-bit grayscale sources keep their tones in 8-bit previews.

    Pillow decodes these as ``I;16``, and converting that straight to RGB clips
    every value above 255 to white. A mid-gray 16-bit value must stay mid-gray
    in the cached JPEG preview.
    """
    Image.new('I;16', (16, 16), 32768).save(
        tmp_path / filename, **save_options
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    viewer_path = library.get_preview_path('IMG_6004', 'viewer')

    with Image.open(viewer_path) as image:
        assert_color_close(
            image.convert('RGB').getpixel((8, 8)), (128, 128, 128)
        )


def _red_left_blue_right_image() -> Image.Image:
    """Return a landscape image whose orientation is visible in pixels."""
    image = Image.new('RGB', (40, 20), 'red')
    image.paste((0, 0, 255), (20, 0, 40, 20))
    return image


def _rotate_90_cw_exif() -> bytes:
    exif = Image.Exif()
    exif[0x0112] = 6  # EXIF Orientation: rotate 90 degrees clockwise.
    return exif.tobytes()


def test_jxl_pixel_preview_ignores_exif_orientation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify decoded JPEG XL pixels are not rotated again from EXIF.

    JPEG XL's codestream orientation is authoritative and libjxl applies it
    while decoding. This file's codestream says "identity" while its EXIF blob
    says "rotate 90 CW", so honoring EXIF would rotate the preview away from
    what spec-conforming decoders show, or double-rotate files whose EXIF and
    codestream orientations agree.
    """
    _red_left_blue_right_image().save(
        tmp_path / 'IMG_6005.JXL',
        format='JXL',
        lossless=True,
        exif=_rotate_90_cw_exif(),
    )
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    viewer_path = library.get_preview_path('IMG_6005', 'viewer')

    with Image.open(viewer_path) as image:
        assert image.size == (40, 20)
        assert_color_close(image.convert('RGB').getpixel((2, 10)), (254, 0, 0))


def test_transcoded_jxl_preview_honors_jpeg_exif_orientation(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Verify losslessly transcoded JPEG XL files keep JPEG EXIF orientation.

    The plugin reconstructs the original JPEG bytes for these files, so the
    pixels are unrotated sensor data exactly like the source JPEG. Skipping
    EXIF orientation here would show portrait shots sideways.
    """
    source_jpeg = tmp_path / 'IMG_6006.JPG'
    photo_folder = tmp_path / 'photos'
    photo_folder.mkdir()
    _red_left_blue_right_image().save(
        source_jpeg, format='JPEG', quality=95, exif=_rotate_90_cw_exif()
    )
    with Image.open(source_jpeg) as opened:
        opened.save(
            photo_folder / 'IMG_6006.JXL', format='JXL', lossless_jpeg=True
        )

    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(photo_folder)

    viewer_path = library.get_preview_path('IMG_6006', 'viewer')

    with Image.open(viewer_path) as image:
        assert image.size == (20, 40)
        # Rotating 90 degrees clockwise moves the red left half to the top.
        assert_color_close(image.convert('RGB').getpixel((10, 2)), (254, 0, 0))


def test_preview_cache_is_reused_and_invalidated_when_source_mtime_changes(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_path = tmp_path / 'IMG_6010.JPG'
    create_jpeg(source_path, 'orange')
    stub_read_exif(monkeypatch, {})

    library = PhotoLibrary(cache_dir=tmp_path / '.cache')
    library.load_folder(tmp_path)

    first_path = library.get_preview_path('IMG_6010', 'viewer')

    monkeypatch.setattr(
        core_preview_module,
        'render_source_image',
        lambda _source, _kind: (_ for _ in ()).throw(
            AssertionError('cache hit should not re-render')
        ),
    )
    second_path = library.get_preview_path('IMG_6010', 'viewer')

    assert second_path == first_path

    stat = source_path.stat()
    os.utime(
        source_path,
        ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000),
    )

    monkeypatch.setattr(
        core_preview_module,
        'render_source_image',
        lambda _source, _kind: Image.new('RGB', (8, 8), color='red'),
    )
    third_path = library.get_preview_path('IMG_6010', 'viewer')

    assert third_path != first_path
    assert third_path.exists()


def test_photo_library_falls_back_to_temp_cache_dir_when_default_is_not_writable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked_cache_dir = tmp_path / 'blocked-cache'
    temp_root = tmp_path / 'temp-root'
    original_mkdir = Path.mkdir

    def guarded_mkdir(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == blocked_cache_dir:
            raise PermissionError('blocked')

        original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(
        core_preview_module, '_default_cache_dir', lambda: blocked_cache_dir
    )
    monkeypatch.setattr(
        core_preview_module.tempfile, 'gettempdir', lambda: str(temp_root)
    )
    monkeypatch.setattr(Path, 'mkdir', guarded_mkdir)

    cache_dir = core_preview_module.make_cache_dir(None)

    assert cache_dir == temp_root / 'easy-loupe'
    assert cache_dir.is_dir()


def test_photo_library_falls_back_to_temp_cache_dir_when_existing_default_is_unwritable(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blocked_cache_dir = tmp_path / 'blocked-cache'
    blocked_cache_dir.mkdir()
    temp_root = tmp_path / 'temp-root'
    writable_checks: list[Path] = []

    monkeypatch.setattr(
        core_preview_module, '_default_cache_dir', lambda: blocked_cache_dir
    )
    monkeypatch.setattr(
        core_preview_module.tempfile, 'gettempdir', lambda: str(temp_root)
    )

    def fake_cache_dir_is_writable(cache_dir: Path) -> bool:
        writable_checks.append(cache_dir)
        return False

    monkeypatch.setattr(
        core_preview_module,
        '_cache_dir_is_writable',
        fake_cache_dir_is_writable,
    )

    cache_dir = core_preview_module.make_cache_dir(None)

    assert writable_checks == [blocked_cache_dir]
    assert cache_dir == temp_root / 'easy-loupe'
    assert cache_dir.is_dir()


def test_photo_library_init_uses_preview_make_cache_dir(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PhotoLibrary delegates cache-dir creation to the preview helper."""
    expected_cache_dir = tmp_path / 'delegated-cache'
    calls: list[Path | None] = []

    def fake_make_cache_dir(cache_dir: Path | None) -> Path:
        calls.append(cache_dir)
        return expected_cache_dir

    monkeypatch.setattr(
        core_preview_module, 'make_cache_dir', fake_make_cache_dir
    )

    explicit_cache_dir = tmp_path / 'explicit-cache'
    library = PhotoLibrary(cache_dir=explicit_cache_dir)

    assert calls == [explicit_cache_dir]
    assert library.cache_dir == expected_cache_dir


@pytest.mark.parametrize('has_library_dir', [True, False])
def test_default_cache_dir_prefers_library_directory_when_available(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        has_library_dir: bool,
) -> None:
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    if has_library_dir:
        (fake_home / 'Library').mkdir()

    monkeypatch.setattr(Path, 'home', staticmethod(lambda: fake_home))

    cache_dir = core_preview_module._default_cache_dir()

    expected = (
        fake_home / 'Library' / 'Caches' / 'easy-loupe'
        if has_library_dir
        else fake_home / '.cache' / 'easy-loupe'
    )
    assert cache_dir == expected


def test_raw_preview_requires_rawpy_when_missing(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = load_raw_only_library(tmp_path, monkeypatch, 'IMG_7320.CR3')
    monkeypatch.setattr('easy_loupe.core.preview.rawpy', None)

    with pytest.raises(RuntimeError, match='rawpy is required'):
        library.get_preview_path('IMG_7320', 'viewer')


def test_raw_thumbnail_extraction_handles_non_jpeg_bitmap_format(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = load_raw_only_library(tmp_path, monkeypatch, 'IMG_9030.CR3')

    class FakeThumbFormat:
        JPEG = 'jpeg'
        BITMAP = 'bitmap'

    class FakeNoThumbnailError(Exception):
        pass

    class FakeThumbnail:
        def __init__(self) -> None:
            self.format = FakeThumbFormat.BITMAP
            self.data = np.full(
                (10, 10, 3), fill_value=(50, 200, 100), dtype=np.uint8
            )

    class FakeRaw:
        def __enter__(self) -> Self:
            return self

        def __exit__(
                self,
                exc_type: type[BaseException] | None,
                exc: BaseException | None,
                tb: TracebackType | None,
        ) -> bool:
            return False

        @staticmethod
        def extract_thumb() -> FakeThumbnail:
            return FakeThumbnail()

        @staticmethod
        def postprocess(*, use_camera_wb: bool, half_size: bool) -> Never:
            del use_camera_wb, half_size
            raise AssertionError(
                'postprocess should not be called when thumb is available'
            )

    fake_rawpy = type(
        'FakeRawPy',
        (),
        {
            'ThumbFormat': FakeThumbFormat,
            'LibRawNoThumbnailError': FakeNoThumbnailError,
            'imread': staticmethod(lambda _path: FakeRaw()),
        },
    )()
    monkeypatch.setattr('easy_loupe.core.preview.rawpy', fake_rawpy)

    preview_path = library.get_preview_path('IMG_9030', 'viewer')

    with Image.open(preview_path) as image:
        rgb = image.convert('RGB')
        r, g, b = rgb.getpixel((0, 0))
        assert g > r
        assert g > b
