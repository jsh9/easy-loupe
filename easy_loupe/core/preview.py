"""Image rendering and preview cache management for EasyLoupe."""

from __future__ import annotations

import hashlib
import tempfile
import threading
import weakref
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageOps

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
_FLOAT_TO_EIGHT_BIT_SCALE = 255
_TRANSPARENCY_BACKGROUND = 'white'


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
            image = _flatten_to_rgb(_orient_raster(opened))
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
        return opened

    return ImageOps.exif_transpose(opened)


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """
    Convert any decoded raster mode to opaque 8-bit RGB for JPEG caching.

    Preview caches are JPEG, which has no alpha channel. A plain
    ``convert('RGB')`` discards alpha and exposes whatever color hides under
    transparent pixels, so transparency is composited onto white instead.
    Colors and transparency are resolved separately so high-bit-depth sources,
    such as 16-bit grayscale PNGs with a ``tRNS`` key, get both tone scaling
    and white compositing.
    """
    rgb = _convert_to_eight_bit_rgb(image)
    if not image.has_transparency_data:
        return rgb

    # Pillow derives alpha from alpha bands, palette transparency, and
    # ``tRNS`` color keys (including 16-bit keys) when converting to RGBA.
    # Reuse an existing alpha band directly to avoid copying large images.
    alpha = (
        image.getchannel('A')
        if 'A' in image.getbands()
        else image.convert('RGBA').getchannel('A')
    )
    background = Image.new('RGB', rgb.size, _TRANSPARENCY_BACKGROUND)
    background.paste(rgb, mask=alpha)
    return background


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
