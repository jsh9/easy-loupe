"""Clipping-warning overlay generation for displayed viewer previews."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from threading import Event, Lock
from typing import TYPE_CHECKING, Protocol

from PIL import Image, ImageChops
from PySide6.QtGui import QImage, QPixmap

if TYPE_CHECKING:
    from pathlib import Path

HIGHLIGHT_CLIPPING_THRESHOLD = 250
SHADOW_CLIPPING_THRESHOLD = 5
HIGHLIGHT_CLIPPING_RGBA = (255, 59, 48, 156)
SHADOW_CLIPPING_RGBA = (0, 122, 255, 156)
CLIPPING_ANALYSIS_MAX_LONG_EDGE = 3000
CLIPPING_OVERLAY_MAX_LONG_EDGE = CLIPPING_ANALYSIS_MAX_LONG_EDGE
CLIPPING_OVERLAY_CACHE_SIZE = 24


class ClippingImageDownsampler(Protocol):
    """Prepare a bounded RGB image for clipping-overlay analysis."""

    policy_id: str
    max_long_edge: int

    def downsample(self, image: Image.Image) -> Image.Image:
        """Return an independent RGB image ready for exposure analysis."""


class ExposureMaskDefinition(Protocol):
    """Build highlight and shadow clipping masks from an RGB image."""

    policy_id: str
    highlight_threshold: int
    shadow_threshold: int

    def masks(self, image: Image.Image) -> tuple[Image.Image, Image.Image]:
        """Return ``L`` mode highlight and shadow masks for ``image``."""


@dataclass(frozen=True, slots=True)
class FastPillowDownsampler:
    """Fast Pillow resize strategy used before clipping analysis."""

    max_long_edge: int = CLIPPING_ANALYSIS_MAX_LONG_EDGE
    policy_id: str = 'fast-pillow-bilinear-v1'

    def downsample(self, image: Image.Image) -> Image.Image:
        """Return a bounded RGB image, prioritizing speed over tiny hits."""
        rgb_image = image.convert('RGB')
        target_size = _bounded_size(
            rgb_image.size, max_long_edge=self.max_long_edge
        )
        if rgb_image.size == target_size:
            return rgb_image

        try:
            return rgb_image.resize(target_size, Image.Resampling.BILINEAR)
        finally:
            rgb_image.close()


@dataclass(frozen=True, slots=True)
class AnyChannelExposureMaskDefinition:
    """Treat any clipped RGB channel as an exposure warning."""

    highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD
    shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD
    policy_id: str = 'any-channel-v1'

    def masks(self, image: Image.Image) -> tuple[Image.Image, Image.Image]:
        """Return highlight and shadow masks using any-channel thresholds."""
        if image.mode == 'RGB':
            rgb_image = image
            close_rgb_image = False
        else:
            rgb_image = image.convert('RGB')
            close_rgb_image = True

        red, green, blue = rgb_image.split()
        highlight_channels = (
            _threshold_channel_at_or_above(red, self.highlight_threshold),
            _threshold_channel_at_or_above(green, self.highlight_threshold),
            _threshold_channel_at_or_above(blue, self.highlight_threshold),
        )
        shadow_channels = (
            _threshold_channel_at_or_below(red, self.shadow_threshold),
            _threshold_channel_at_or_below(green, self.shadow_threshold),
            _threshold_channel_at_or_below(blue, self.shadow_threshold),
        )
        try:
            return (
                _any_channels_mask(highlight_channels),
                _any_channels_mask(shadow_channels),
            )
        finally:
            if close_rgb_image:
                rgb_image.close()

            red.close()
            green.close()
            blue.close()
            for channel in (*highlight_channels, *shadow_channels):
                channel.close()


@dataclass(frozen=True, slots=True)
class ClippingOverlayBuilder:
    """Coordinate downsampling, mask generation, and overlay encoding."""

    downsampler: ClippingImageDownsampler = FastPillowDownsampler()
    exposure_definition: ExposureMaskDefinition = (
        AnyChannelExposureMaskDefinition()
    )

    def build_payload_for_path(
            self, image_path: str
    ) -> ClippingOverlayPayload:
        """Return encoded overlay data for a displayed preview path."""
        with Image.open(image_path) as opened:
            return self.build_payload(opened)

    def build_payload(self, image: Image.Image) -> ClippingOverlayPayload:
        """Return encoded overlay data for a PIL image."""
        overlay = self.build_overlay_image(image)
        try:
            return _payload_from_rgba_image(overlay)
        finally:
            overlay.close()

    def build_overlay_image(self, image: Image.Image) -> Image.Image:
        """Return an RGBA overlay for ``image`` after bounded analysis."""
        analysis_image = self.downsampler.downsample(image)
        highlight_mask, shadow_mask = self.exposure_definition.masks(
            analysis_image
        )
        try:
            return _overlay_image_from_masks(highlight_mask, shadow_mask)
        finally:
            analysis_image.close()
            highlight_mask.close()
            shadow_mask.close()


@dataclass(frozen=True, slots=True)
class ClippingOverlayCacheKey:
    """Stable cache key for one displayed preview's clipping overlay."""

    image_path: str
    mtime_ns: int
    size: int
    highlight_threshold: int
    shadow_threshold: int
    analysis_max_long_edge: int
    downsampler_policy_id: str
    exposure_policy_id: str


@dataclass(frozen=True, slots=True)
class ClippingOverlayPayload:
    """GUI-safe encoded clipping overlay data."""

    width: int
    height: int
    png_data: bytes


_CLIPPING_OVERLAY_CACHE_LOCK = Lock()
# Store encoded image bytes rather than QPixmaps so worker threads can fill
# the cache without touching GUI-thread-only Qt paint resources.
_CLIPPING_OVERLAY_CACHE: OrderedDict[
    ClippingOverlayCacheKey, ClippingOverlayPayload
] = OrderedDict()
_CLIPPING_OVERLAY_IN_FLIGHT: dict[ClippingOverlayCacheKey, Event] = {}


def clipping_overlay_pixmap(
        image_path: Path,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
        max_long_edge: int = CLIPPING_ANALYSIS_MAX_LONG_EDGE,
        downsampler: ClippingImageDownsampler | None = None,
        exposure_definition: ExposureMaskDefinition | None = None,
) -> QPixmap:
    """Return a cached clipping-warning pixmap for a displayed image path."""
    builder = _builder_for_options(
        highlight_threshold=highlight_threshold,
        shadow_threshold=shadow_threshold,
        max_long_edge=max_long_edge,
        downsampler=downsampler,
        exposure_definition=exposure_definition,
    )
    key = clipping_overlay_cache_key(image_path, builder=builder)
    return clipping_overlay_pixmap_from_payload(
        clipping_overlay_payload_for_key(key, builder=builder)
    )


def clipping_overlay_cache_key(
        image_path: Path,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
        max_long_edge: int = CLIPPING_ANALYSIS_MAX_LONG_EDGE,
        downsampler: ClippingImageDownsampler | None = None,
        exposure_definition: ExposureMaskDefinition | None = None,
        builder: ClippingOverlayBuilder | None = None,
) -> ClippingOverlayCacheKey:
    """Return the cache key for one displayed preview path."""
    if builder is None:
        builder = _builder_for_options(
            highlight_threshold=highlight_threshold,
            shadow_threshold=shadow_threshold,
            max_long_edge=max_long_edge,
            downsampler=downsampler,
            exposure_definition=exposure_definition,
        )

    stat = image_path.stat()
    exposure_policy = builder.exposure_definition
    return ClippingOverlayCacheKey(
        str(image_path),
        stat.st_mtime_ns,
        stat.st_size,
        exposure_policy.highlight_threshold,
        exposure_policy.shadow_threshold,
        builder.downsampler.max_long_edge,
        builder.downsampler.policy_id,
        exposure_policy.policy_id,
    )


def get_cached_clipping_overlay_payload(
        key: ClippingOverlayCacheKey,
) -> ClippingOverlayPayload | None:
    """Return a cached clipping overlay payload without generating one."""
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        payload = _CLIPPING_OVERLAY_CACHE.get(key)
        if payload is None:
            return None

        _CLIPPING_OVERLAY_CACHE.move_to_end(key)
        return payload


def clipping_overlay_payload_for_key(
        key: ClippingOverlayCacheKey,
        *,
        builder: ClippingOverlayBuilder | None = None,
) -> ClippingOverlayPayload:
    """Return a cached clipping overlay payload, generating it on misses."""
    payload = get_cached_clipping_overlay_payload(key)
    if payload is not None:
        return payload

    claimed_build, in_flight_event = _claim_in_flight_overlay_build(key)
    if not claimed_build and in_flight_event is None:
        # Another thread can fill the cache between the first lookup and the
        # in-flight claim, so retry the cache path before starting work.
        payload = get_cached_clipping_overlay_payload(key)
        if payload is not None:
            return payload

        return clipping_overlay_payload_for_key(key, builder=builder)

    if in_flight_event is not None:
        # Wait for the owner thread, then re-enter the normal cache path so
        # success, failure, and eviction handling stay centralized.
        in_flight_event.wait()
        return clipping_overlay_payload_for_key(key, builder=builder)

    try:
        payload = _build_clipping_overlay_payload(key, builder=builder)
        return _cache_clipping_overlay_payload(key, payload)
    finally:
        _finish_in_flight_overlay_build(key)


def clipping_overlay_pixmap_from_payload(
        payload: ClippingOverlayPayload,
) -> QPixmap:
    """Convert cached GUI-safe overlay bytes into a Qt pixmap."""
    qimage = QImage()
    if not qimage.loadFromData(payload.png_data, 'PNG'):
        return QPixmap()

    return QPixmap.fromImage(qimage)


def build_clipping_overlay_image(
        image: Image.Image,
        *,
        highlight_threshold: int = HIGHLIGHT_CLIPPING_THRESHOLD,
        shadow_threshold: int = SHADOW_CLIPPING_THRESHOLD,
        max_long_edge: int = CLIPPING_ANALYSIS_MAX_LONG_EDGE,
        downsampler: ClippingImageDownsampler | None = None,
        exposure_definition: ExposureMaskDefinition | None = None,
        builder: ClippingOverlayBuilder | None = None,
) -> Image.Image:
    """Return an RGBA overlay marking clipped highlights and shadows."""
    if builder is None:
        builder = _builder_for_options(
            highlight_threshold=highlight_threshold,
            shadow_threshold=shadow_threshold,
            max_long_edge=max_long_edge,
            downsampler=downsampler,
            exposure_definition=exposure_definition,
        )

    return builder.build_overlay_image(image)


def _builder_for_options(
        *,
        highlight_threshold: int,
        shadow_threshold: int,
        max_long_edge: int,
        downsampler: ClippingImageDownsampler | None,
        exposure_definition: ExposureMaskDefinition | None,
) -> ClippingOverlayBuilder:
    return ClippingOverlayBuilder(
        downsampler=downsampler
        or FastPillowDownsampler(max_long_edge=max_long_edge),
        exposure_definition=exposure_definition
        or AnyChannelExposureMaskDefinition(
            highlight_threshold=highlight_threshold,
            shadow_threshold=shadow_threshold,
        ),
    )


def _claim_in_flight_overlay_build(
        key: ClippingOverlayCacheKey,
) -> tuple[bool, Event | None]:
    """Claim this key's build slot, or return the existing owner event."""
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        payload = _CLIPPING_OVERLAY_CACHE.get(key)
        if payload is not None:
            return False, None

        event = _CLIPPING_OVERLAY_IN_FLIGHT.get(key)
        if event is not None:
            return False, event

        _CLIPPING_OVERLAY_IN_FLIGHT[key] = Event()
        return True, None


def _finish_in_flight_overlay_build(key: ClippingOverlayCacheKey) -> None:
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        event = _CLIPPING_OVERLAY_IN_FLIGHT.pop(key, None)
        if event is not None:
            event.set()


def _cache_clipping_overlay_payload(
        key: ClippingOverlayCacheKey,
        payload: ClippingOverlayPayload,
) -> ClippingOverlayPayload:
    with _CLIPPING_OVERLAY_CACHE_LOCK:
        cached_payload = _CLIPPING_OVERLAY_CACHE.get(key)
        if cached_payload is not None:
            _CLIPPING_OVERLAY_CACHE.move_to_end(key)
            return cached_payload

        _CLIPPING_OVERLAY_CACHE[key] = payload
        _CLIPPING_OVERLAY_CACHE.move_to_end(key)
        while len(_CLIPPING_OVERLAY_CACHE) > CLIPPING_OVERLAY_CACHE_SIZE:
            _CLIPPING_OVERLAY_CACHE.popitem(last=False)

    return payload


def _build_clipping_overlay_payload(
        key: ClippingOverlayCacheKey,
        *,
        builder: ClippingOverlayBuilder | None = None,
) -> ClippingOverlayPayload:
    if builder is None:
        builder = _default_builder_for_key(key)

    return builder.build_payload_for_path(key.image_path)


def _default_builder_for_key(
        key: ClippingOverlayCacheKey,
) -> ClippingOverlayBuilder:
    """Rebuild the default strategy set represented by a cache key."""
    downsampler = FastPillowDownsampler(
        max_long_edge=key.analysis_max_long_edge
    )
    exposure_definition = AnyChannelExposureMaskDefinition(
        highlight_threshold=key.highlight_threshold,
        shadow_threshold=key.shadow_threshold,
    )
    if (
        downsampler.policy_id != key.downsampler_policy_id
        or exposure_definition.policy_id != key.exposure_policy_id
    ):
        # Custom strategy keys need their original builder; falling back to the
        # defaults would populate a policy-specific key with the wrong pixels.
        raise ValueError('Non-default clipping cache key requires a builder')

    return ClippingOverlayBuilder(
        downsampler=downsampler,
        exposure_definition=exposure_definition,
    )


def _overlay_image_from_masks(
        highlight_mask: Image.Image,
        shadow_mask: Image.Image,
) -> Image.Image:
    overlay = Image.new('RGBA', highlight_mask.size, (0, 0, 0, 0))
    # Paint shadow first, then highlight, so pixels clipped in both directions
    # follow the product rule that overexposure wins ties.
    overlay.paste(
        Image.new('RGBA', shadow_mask.size, SHADOW_CLIPPING_RGBA),
        (0, 0),
        shadow_mask,
    )
    overlay.paste(
        Image.new('RGBA', highlight_mask.size, HIGHLIGHT_CLIPPING_RGBA),
        (0, 0),
        highlight_mask,
    )
    return overlay


def _bounded_size(
        size: tuple[int, int],
        *,
        max_long_edge: int,
) -> tuple[int, int]:
    width, height = size
    long_edge = max(width, height)
    if max_long_edge <= 0 or long_edge <= max_long_edge:
        return size

    scale = max_long_edge / long_edge
    return (
        max(1, round(width * scale)),
        max(1, round(height * scale)),
    )


def _any_channels_mask(channels: tuple[Image.Image, ...]) -> Image.Image:
    mask = channels[0].copy()
    for channel in channels[1:]:
        next_mask = ImageChops.lighter(mask, channel)
        mask.close()
        mask = next_mask

    return mask


def _threshold_channel_at_or_above(
        channel: Image.Image, threshold: int
) -> Image.Image:
    return channel.point(lambda value: 255 if value >= threshold else 0)


def _threshold_channel_at_or_below(
        channel: Image.Image, threshold: int
) -> Image.Image:
    return channel.point(lambda value: 255 if value <= threshold else 0)


def _payload_from_rgba_image(image: Image.Image) -> ClippingOverlayPayload:
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return ClippingOverlayPayload(
        width=image.width,
        height=image.height,
        png_data=buffer.getvalue(),
    )
