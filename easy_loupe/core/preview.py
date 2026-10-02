"""Image rendering and preview cache management for EasyLoupe."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import threading
import weakref
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageChops, ImageMath, ImageOps

from easy_loupe.core.records import (
    FIT_MAX_SIZE,
    HEIF_EXTENSIONS,
    JXL_EXTENSIONS,
    RASTER_EXTENSIONS,
    THUMB_MAX_SIZE,
    PhotoRecord,
)

try:
    import rawpy
except ImportError:  # pragma: no cover - handled by dependency installation
    rawpy = cast('Any', None)

try:
    from pillow_heif import register_heif_opener
except ImportError:  # pragma: no cover - handled by dependency installation
    register_heif_opener = cast('Any', None)
else:
    register_heif_opener()

try:
    # Importing the plugin registers Pillow's JPEG XL opener as a side effect.
    import pillow_jxl
except ImportError:  # pragma: no cover - handled by dependency installation
    pillow_jxl = cast('Any', None)

# 16-bit and 32-bit grayscale modes need explicit scaling because Pillow's
# plain ``convert('RGB')`` clips them instead of mapping them to 8 bits.
_HIGH_BIT_DEPTH_GRAY_MODES = {'I', 'I;16', 'I;16B', 'I;16L', 'I;16N'}
_SIXTEEN_BIT_TO_EIGHT_BIT_DIVISOR = 256
_SIXTEEN_BIT_HIGH_BYTE_SHIFT = 8
_FLOAT_TO_EIGHT_BIT_SCALE = 255
_OPAQUE_ALPHA = 255
_ALPHA_BAND_MODES = {'RGBA', 'LA'}
_SIXTEEN_BIT_DEPTH = 16
_SIXTEEN_BIT_GRAY_ALPHA_BYTES_PER_PIXEL = 4
_PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_PNG_IHDR_TYPE = slice(12, 16)
_PNG_IHDR_BIT_DEPTH_OFFSET = 24
# Transparent pixels are flattened onto near-white instead of pure white. The
# clipping warning in ``ui/viewers/clipping.py`` flags 255 as a blown
# highlight, and this value stays below 255 even after JPEG caching, so
# transparent areas never read as clipped.
TRANSPARENCY_BACKGROUND_RGB = (250, 250, 250)


_PREVIEW_LOCKS_GUARD = threading.Lock()
# Keep one lock per cache key only while a render is in flight. The guard
# protects registry mutation; the weak values prevent long sessions from
# retaining locks for every preview key ever visited.
_PREVIEW_LOCKS: weakref.WeakValueDictionary[str, threading.Lock] = (
    weakref.WeakValueDictionary()
)


def _preview_lock(cache_key: str) -> threading.Lock:
    with _PREVIEW_LOCKS_GUARD:
        lock = _PREVIEW_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _PREVIEW_LOCKS[cache_key] = lock

        return lock


def _default_cache_dir() -> Path:
    """Return the platform-appropriate default preview cache directory."""
    if (home := Path.home()) and (home / 'Library').exists():
        return home / 'Library' / 'Caches' / 'easy-loupe'

    return Path.home() / '.cache' / 'easy-loupe'


def get_preview_path(
        photo: PhotoRecord,
        current_folder: Path | None,
        cache_dir: Path,
        kind: str,
) -> Path:
    """Render or reuse a cached preview image for the requested photo."""
    if kind not in {'thumb', 'fit', 'viewer', 'full'}:
        raise ValueError('Preview kind must be thumb, fit, viewer, or full')

    key = hashlib.sha256(
        f'{current_folder}::{photo.preview_source.resolve()}::{photo.preview_version}::{kind}'.encode()
    ).hexdigest()
    target = cache_dir / f'{key}.jpg'
    if target.exists():
        return target

    with _preview_lock(key):
        if target.exists():
            return target

        image = render_source_image(photo.preview_source, kind)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f'.{key}.',
            suffix='.tmp',
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)

        try:
            image.save(temp_path, format='JPEG', quality=92, optimize=True)
            temp_path.replace(target)
        finally:
            image.close()
            if temp_path.exists():
                temp_path.unlink()

    return target


def render_source_image(source: Path, kind: str) -> Image.Image:
    """Open and optionally resize a source image for the requested kind."""
    suffix = source.suffix.lower()
    if suffix in RASTER_EXTENSIONS:
        if suffix in HEIF_EXTENSIONS and register_heif_opener is None:
            raise RuntimeError(
                'pillow-heif is required to render HEIC/HEIF previews'
            )

        if suffix in JXL_EXTENSIONS and pillow_jxl is None:
            raise RuntimeError(
                'pillow-jxl-plugin is required to render JPEG XL previews'
            )

        with Image.open(source) as opened:
            image = _flatten_to_rgb(
                _orient_raster(opened),
                sixteen_bit_png=(
                    opened.format == 'PNG'
                    and _png_bit_depth(source) == _SIXTEEN_BIT_DEPTH
                ),
            )
    else:
        image = _render_raw_image(source, kind)

    max_size = None
    if kind == 'thumb':
        max_size = THUMB_MAX_SIZE
    elif kind == 'fit':
        max_size = FIT_MAX_SIZE

    if max_size is not None:
        image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    return image


def _orient_raster(opened: Image.Image) -> Image.Image:
    """
    Return raster pixels in display orientation.

    JPEG XL stores orientation in its codestream, and libjxl applies it while
    decoding pixels, so honoring an EXIF orientation too would rotate twice.
    Losslessly transcoded JPEGs are the exception: the plugin reconstructs the
    original JPEG bytes (``jpeg`` is true), whose pixels still need EXIF
    orientation like any other JPEG.
    """
    if opened.format == 'JXL' and not getattr(opened, 'jpeg', False):
        return _repair_jxl_sixteen_bit_gray_alpha(opened)

    return ImageOps.exif_transpose(opened)


def _repair_jxl_sixteen_bit_gray_alpha(opened: Image.Image) -> Image.Image:
    """
    Rebuild 16-bit grayscale+alpha JPEG XL pixels mislabeled as 8-bit ``LA``.

    pillow-jxl-plugin 1.3.8 returns 16-bit little-endian gray+alpha samples but
    declares the 8-bit ``LA`` mode, so Pillow reads the wrong bytes and the
    preview is garbled. The buffer is then twice the expected size, and reading
    it as 8-bit RGBA puts each sample's high byte in the G (gray) and A (alpha)
    bands. Correctly sized buffers pass through unchanged, so this becomes a
    no-op once the plugin is fixed.
    """
    raw = getattr(opened, '_data', None)
    width, height = opened.size
    if (
        opened.mode != 'LA'
        or sys.byteorder != 'little'
        or not isinstance(raw, bytes)
        or len(raw) != width * height * _SIXTEEN_BIT_GRAY_ALPHA_BYTES_PER_PIXEL
    ):
        return opened

    sample_bytes = Image.frombytes('RGBA', opened.size, raw)
    return Image.merge(
        'LA', (sample_bytes.getchannel('G'), sample_bytes.getchannel('A'))
    )


def _flatten_to_rgb(
        image: Image.Image, *, sixteen_bit_png: bool = False
) -> Image.Image:
    """
    Convert any decoded raster mode to opaque 8-bit RGB for JPEG caching.

    Preview caches are JPEG, which has no alpha channel. A plain
    ``convert('RGB')`` discards alpha and exposes whatever color hides under
    transparent pixels, so transparency is composited onto
    ``TRANSPARENCY_BACKGROUND_RGB`` instead. Colors and transparency are
    resolved separately so high-bit-depth sources, such as 16-bit grayscale
    PNGs with a ``tRNS`` key, get both tone scaling and compositing.

    ``sixteen_bit_png`` marks 16-bit RGB PNGs, whose ``tRNS`` key is stored at
    16 bits while Pillow has already reduced the pixels to 8 bits.
    """
    if image.mode in _ALPHA_BAND_MODES:
        return _composite_alpha_band(image)

    if not image.has_transparency_data:
        return _convert_to_eight_bit_rgb(image)

    if image.mode in _HIGH_BIT_DEPTH_GRAY_MODES:
        rgb = _convert_to_eight_bit_rgb(image)
        mask = _gray_color_key_mask(image)
        return rgb if mask is None else _composite_with_mask(rgb, mask)

    if image.mode == 'RGB' and sixteen_bit_png:
        mask = _sixteen_bit_rgb_color_key_mask(image)
        return (
            image.convert('RGB')
            if mask is None
            else _composite_with_mask(image, mask)
        )

    # Palette, 1-bit, and 8-bit gray or RGB keys, plus premultiplied or
    # palette-alpha modes: Pillow's RGBA conversion derives their alpha
    # exactly, and one conversion avoids its palette-transparency warning.
    return _composite_alpha_band(image.convert('RGBA'))


def _composite_alpha_band(image: Image.Image) -> Image.Image:
    """Composite an ``RGBA`` or ``LA`` image onto the preview background."""
    # Fully opaque images, common for exported PNGs, skip compositing. The
    # alpha band copy is freed before conversion, so it does not raise peak
    # memory, and scanning one band is about 4x faster than all of them.
    lowest_alpha, _ = image.getchannel('A').getextrema()
    if lowest_alpha == _OPAQUE_ALPHA:
        return image.convert('RGB')

    # Pillow pastes ``LA`` onto RGB by copying raw pixel bytes, and images
    # built by merging bands leave the duplicated gray bytes empty, so gray
    # would turn red. RGBA is pasted as is with itself as the mask, which uses
    # its alpha band directly instead of separate RGB and alpha copies.
    if image.mode != 'RGBA':
        image = image.convert('RGBA')

    return _composite_with_mask(image, image)


def _composite_with_mask(image: Image.Image, mask: Image.Image) -> Image.Image:
    background = Image.new('RGB', image.size, TRANSPARENCY_BACKGROUND_RGB)
    background.paste(image, mask=mask)
    return background


def _gray_color_key_mask(image: Image.Image) -> Image.Image | None:
    """
    Return an exact alpha mask for a high-bit-depth grayscale color key.

    Pillow's RGBA conversion compares clipped 8-bit values with the key's low
    byte, so a 16-bit key such as 65535 would mark every bright pixel as
    transparent. Comparing the full-depth values keeps only exact matches.
    """
    key = image.info.get('transparency')
    if not isinstance(key, int):
        return None

    mask = ImageMath.lambda_eval(
        lambda args: (args['pixels'] != key) * _OPAQUE_ALPHA,
        pixels=image.convert('I'),
    )
    return mask.convert('L')


def _sixteen_bit_rgb_color_key_mask(image: Image.Image) -> Image.Image | None:
    """
    Return an alpha mask for a 16-bit RGB PNG color key.

    Pillow keeps only the high byte of each 16-bit sample and never compares
    pixels with the full key, so the mask compares those high bytes with the
    key's high bytes. Colors within 1/256 of the key therefore also become
    transparent, which is the closest match the 8-bit pixels allow.
    """
    key = image.info.get('transparency')
    if not isinstance(key, tuple):
        return None

    high_bytes = [
        sample >> _SIXTEEN_BIT_HIGH_BYTE_SHIFT
        for sample in key
        if isinstance(sample, int)
    ]
    if len(high_bytes) != len(image.getbands()):
        return None

    band_matches = [
        band.point(
            lambda value, high_byte=high_byte: (
                _OPAQUE_ALPHA if value == high_byte else 0
            )
        )
        for band, high_byte in zip(image.split(), high_bytes, strict=True)
    ]
    transparent = band_matches[0]
    for band_match in band_matches[1:]:
        transparent = ImageChops.multiply(transparent, band_match)

    return ImageChops.invert(transparent)


def _png_bit_depth(source: Path) -> int | None:
    """Return the per-sample bit depth from a PNG file's IHDR chunk."""
    try:
        with source.open('rb') as file:
            header = file.read(_PNG_IHDR_BIT_DEPTH_OFFSET + 1)
    except OSError:
        return None

    if (
        len(header) <= _PNG_IHDR_BIT_DEPTH_OFFSET
        or not header.startswith(_PNG_SIGNATURE)
        or header[_PNG_IHDR_TYPE] != b'IHDR'
    ):
        return None

    return header[_PNG_IHDR_BIT_DEPTH_OFFSET]


def _convert_to_eight_bit_rgb(image: Image.Image) -> Image.Image:
    """Convert decoded pixels to 8-bit RGB, ignoring transparency."""
    if image.mode in _HIGH_BIT_DEPTH_GRAY_MODES:
        return (
            image
            .convert('I')
            .point(lambda value: value / _SIXTEEN_BIT_TO_EIGHT_BIT_DIVISOR)
            .convert('L')
            .convert('RGB')
        )

    if image.mode == 'F':
        return (
            image
            .point(lambda value: value * _FLOAT_TO_EIGHT_BIT_SCALE)
            .convert('L')
            .convert('RGB')
        )

    return image.convert('RGB')


def _render_raw_image(source: Path, kind: str) -> Image.Image:
    if rawpy is None:
        raise RuntimeError('rawpy is required to render RAW previews')

    with rawpy.imread(str(source)) as raw:
        if kind in {'thumb', 'fit', 'viewer'}:
            thumbnail = _extract_raw_thumbnail(raw)
            if thumbnail is not None:
                return thumbnail

        rgb = raw.postprocess(use_camera_wb=True, half_size=(kind != 'full'))
        return Image.fromarray(rgb).convert('RGB')


def _extract_raw_thumbnail(raw: Any) -> Image.Image | None:
    try:
        thumbnail = raw.extract_thumb()
    except rawpy.LibRawNoThumbnailError:
        return None

    if thumbnail.format == rawpy.ThumbFormat.JPEG:
        with Image.open(_bytes_buffer(thumbnail.data)) as opened:
            return ImageOps.exif_transpose(opened).convert('RGB')

    return Image.fromarray(thumbnail.data).convert('RGB')


def _bytes_buffer(payload: bytes) -> BytesIO:
    return BytesIO(payload)


def sort_timestamp(capture_at: datetime | None) -> tuple[int, datetime]:
    """Return a sort key that places photos without timestamps last."""
    fallback_timestamp = datetime.max.replace(tzinfo=UTC)
    return (1, fallback_timestamp) if capture_at is None else (0, capture_at)


def make_cache_dir(cache_dir: Path | None) -> Path:
    """Create and return the cache directory, falling back to temp on error."""
    preferred = cache_dir or _default_cache_dir()
    try:
        preferred.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        return _fallback_cache_dir()
    else:
        if _cache_dir_is_writable(preferred):
            return preferred

        return _fallback_cache_dir()


def _fallback_cache_dir() -> Path:
    fallback = Path(tempfile.gettempdir()) / 'easy-loupe'
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _cache_dir_is_writable(cache_dir: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, delete=True):
            return True
    except OSError:
        return False
