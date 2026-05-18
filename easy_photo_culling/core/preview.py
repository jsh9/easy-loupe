"""Image rendering and preview cache management for easy-photo-culling."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageOps

from easy_photo_culling.core.records import (
    FIT_MAX_SIZE,
    JPEG_EXTENSIONS,
    THUMB_MAX_SIZE,
    PhotoRecord,
)

try:
    import rawpy
except ImportError:  # pragma: no cover - handled by dependency installation
    rawpy = cast('Any', None)


def _default_cache_dir() -> Path:
    """Return the platform-appropriate default preview cache directory."""
    if (home := Path.home()) and (home / 'Library').exists():
        return home / 'Library' / 'Caches' / 'easy-photo-culling'

    return Path.home() / '.cache' / 'easy-photo-culling'


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

    image = render_source_image(photo.preview_source, kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format='JPEG', quality=92, optimize=True)
    image.close()
    return target


def render_source_image(source: Path, kind: str) -> Image.Image:
    """Open and optionally resize a source image for the requested kind."""
    if source.suffix.lower() in JPEG_EXTENSIONS:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGB')
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
    fallback = Path(tempfile.gettempdir()) / 'easy-photo-culling'
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _cache_dir_is_writable(cache_dir: Path) -> bool:
    try:
        with tempfile.NamedTemporaryFile(dir=cache_dir, delete=True):
            return True
    except OSError:
        return False
