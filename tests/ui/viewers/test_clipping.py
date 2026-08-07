from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from threading import Event, Thread
from typing import TYPE_CHECKING

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

import easy_loupe.ui.viewers.clipping as clipping_module
from easy_loupe.ui.viewers.clipping import (
    CLIPPING_ANALYSIS_MAX_LONG_EDGE,
    COMPLETE_HIGHLIGHT_CLIPPING_RGBA,
    COMPLETE_SHADOW_CLIPPING_RGBA,
    PARTIAL_HIGHLIGHT_CLIPPING_RGBA,
    PARTIAL_SHADOW_CLIPPING_RGBA,
    AnyChannelExposureMaskDefinition,
    ClippingOverlayBuilder,
    ClippingOverlayPayload,
    ExposureMasks,
    build_clipping_overlay_image,
    clipping_overlay_cache_key,
    clipping_overlay_payload_for_key,
    clipping_overlay_pixmap,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize(
    ('rgb', 'expected'),
    [
        pytest.param(
            (255, 255, 255),
            COMPLETE_HIGHLIGHT_CLIPPING_RGBA,
            id='complete-highlight',
        ),
        pytest.param(
            (255, 255, 200),
            PARTIAL_HIGHLIGHT_CLIPPING_RGBA,
            id='two-highlight-channels',
        ),
        pytest.param(
            (255, 200, 200),
            PARTIAL_HIGHLIGHT_CLIPPING_RGBA,
            id='one-highlight-channel',
        ),
        pytest.param(
            (0, 0, 0),
            COMPLETE_SHADOW_CLIPPING_RGBA,
            id='complete-shadow',
        ),
        pytest.param(
            (0, 0, 8),
            PARTIAL_SHADOW_CLIPPING_RGBA,
            id='two-shadow-channels',
        ),
        pytest.param(
            (0, 8, 8),
            PARTIAL_SHADOW_CLIPPING_RGBA,
            id='one-shadow-channel',
        ),
        pytest.param((128, 128, 128), (0, 0, 0, 0), id='midtone'),
        pytest.param((254, 254, 254), (0, 0, 0, 0), id='near-highlight'),
        pytest.param((1, 1, 1), (0, 0, 0, 0), id='near-shadow'),
        pytest.param(
            (255, 0, 0),
            PARTIAL_HIGHLIGHT_CLIPPING_RGBA,
            id='mixed-endpoints-highlight-wins',
        ),
    ],
)
def test_clipping_overlay_marks_exact_channel_levels(
        rgb: tuple[int, int, int],
        expected: tuple[int, int, int, int],
) -> None:
    """
    Verify exact endpoints use distinct complete and partial warning colors.

    This protects against near-endpoint false positives and keeps high-side
    clipping dominant when different channels hit both endpoints.
    """
    image = Image.new('RGB', (1, 1), color=rgb)

    overlay = build_clipping_overlay_image(image)

    assert overlay.getpixel((0, 0)) == expected


def test_exposure_masks_partition_all_rgb_endpoint_combinations() -> None:
    """
    Verify complete and partial masks partition every RGB endpoint match.

    Checking every endpoint and midtone combination proves the masks remain
    mutually exclusive and exhaustive independently of overlay colors and paint
    precedence.
    """
    rgb_values = tuple(product((0, 128, 255), repeat=3))
    with Image.new('RGB', (len(rgb_values), 1)) as image:
        image.putdata(rgb_values)
        masks = AnyChannelExposureMaskDefinition().masks(image)
        try:
            for x, rgb in enumerate(rgb_values):
                highlight_count = rgb.count(255)
                shadow_count = rgb.count(0)
                assert masks.complete_highlight.getpixel((x, 0)) == (
                    255 if highlight_count == 3 else 0
                )
                assert masks.partial_highlight.getpixel((x, 0)) == (
                    255 if 0 < highlight_count < 3 else 0
                )
                assert masks.complete_shadow.getpixel((x, 0)) == (
                    255 if shadow_count == 3 else 0
                )
                assert masks.partial_shadow.getpixel((x, 0)) == (
                    255 if 0 < shadow_count < 3 else 0
                )
        finally:
            masks.close()


def test_clipping_overlay_pixmap_uses_displayed_image_path(
        tmp_path: Path,
) -> None:
    """
    Verify the Qt overlay pixmap matches the supplied displayed preview file.

    This protects the feature boundary: clipping is derived from the image
    loaded into the viewer, not from source metadata or a separate render path.
    """
    image_path = tmp_path / 'preview.png'
    image = Image.new('RGB', (4, 1))
    image.putdata([
        (255, 255, 255),
        (255, 200, 200),
        (0, 0, 0),
        (0, 8, 8),
    ])
    image.save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)
    rendered = pixmap.toImage()

    assert pixmap.width() == 4
    assert pixmap.height() == 1
    expected_colors = (
        COMPLETE_HIGHLIGHT_CLIPPING_RGBA,
        PARTIAL_HIGHLIGHT_CLIPPING_RGBA,
        COMPLETE_SHADOW_CLIPPING_RGBA,
        PARTIAL_SHADOW_CLIPPING_RGBA,
    )
    for x, expected in enumerate(expected_colors):
        actual = rendered.pixelColor(x, 0).getRgb()
        assert actual[:3] == pytest.approx(expected[:3], abs=1)
        assert actual[3] == expected[3]

    del app


def test_clipping_overlay_pixmap_caps_analysis_long_edge(
        tmp_path: Path,
) -> None:
    """
    Verify clipping overlays are generated from bounded analysis images.

    The default implementation downsamples before thresholding so large viewer
    previews do not allocate full-resolution RGB channel masks.
    """
    image_path = tmp_path / 'large_preview.jpg'
    Image.new('RGB', (4000, 1000), color='white').save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path)

    assert pixmap.width() == CLIPPING_ANALYSIS_MAX_LONG_EDGE
    assert pixmap.height() == 750
    del app


def test_clipping_overlay_pixmap_can_drop_tiny_hits_after_downsampling(
        tmp_path: Path,
) -> None:
    """
    Verify the fast path accepts losing tiny clipped regions.

    Speed is preferred over preserving every single-pixel warning, so the image
    is resized before thresholding and small hits can average away.
    """
    image_path = tmp_path / 'tiny_hits_preview.png'
    image = Image.new('RGB', (100, 100), color=(128, 128, 128))
    image.putpixel((0, 0), (255, 255, 255))
    image.putpixel((99, 99), (0, 0, 0))
    image.save(image_path)

    app = QApplication.instance() or QApplication([])
    pixmap = clipping_overlay_pixmap(image_path, max_long_edge=2)
    rendered = pixmap.toImage()

    assert pixmap.width() == 2
    assert pixmap.height() == 2
    for x in range(2):
        for y in range(2):
            assert rendered.pixelColor(x, y).alpha() == 0

    del app


class RecordingDownsampler:
    policy_id = 'recording-downsampler'
    max_long_edge = 2

    def __init__(self) -> None:
        self.received_size: tuple[int, int] | None = None

    def downsample(self, image: Image.Image) -> Image.Image:
        self.received_size = image.size
        return Image.new('RGB', (2, 1), color='white')


class RecordingExposureDefinition:
    policy_id = 'recording-exposure'
    highlight_threshold = 255
    shadow_threshold = 0

    def __init__(self) -> None:
        self.received_size: tuple[int, int] | None = None

    def masks(self, image: Image.Image) -> ExposureMasks:
        self.received_size = image.size
        return ExposureMasks(
            complete_highlight=Image.new('L', image.size, color=255),
            partial_highlight=Image.new('L', image.size, color=0),
            complete_shadow=Image.new('L', image.size, color=0),
            partial_shadow=Image.new('L', image.size, color=0),
        )


def test_clipping_overlay_builder_injects_downsampler_before_masks() -> None:
    """
    Verify strategy injection keeps downsampling separate from mask policy.

    This guards the modular boundary so later downsampling or exposure
    definitions can be swapped without changing viewer code.
    """
    downsampler = RecordingDownsampler()
    exposure_definition = RecordingExposureDefinition()
    builder = ClippingOverlayBuilder(
        downsampler=downsampler,
        exposure_definition=exposure_definition,
    )

    overlay = builder.build_overlay_image(
        Image.new('RGB', (10, 5), color='black')
    )

    assert downsampler.received_size == (10, 5)
    assert exposure_definition.received_size == (2, 1)
    assert overlay.size == (2, 1)
    assert overlay.getpixel((0, 0)) == COMPLETE_HIGHLIGHT_CLIPPING_RGBA


@dataclass(frozen=True, slots=True)
class IdentityDownsampler:
    policy_id: str
    max_long_edge: int = CLIPPING_ANALYSIS_MAX_LONG_EDGE

    @staticmethod
    def downsample(image: Image.Image) -> Image.Image:
        return image.convert('RGB')


@dataclass(frozen=True, slots=True)
class TransparentExposureDefinition:
    policy_id: str
    highlight_threshold: int = 255
    shadow_threshold: int = 0

    @staticmethod
    def masks(image: Image.Image) -> ExposureMasks:
        return ExposureMasks(
            complete_highlight=Image.new('L', image.size, color=0),
            partial_highlight=Image.new('L', image.size, color=0),
            complete_shadow=Image.new('L', image.size, color=0),
            partial_shadow=Image.new('L', image.size, color=0),
        )


def test_clipping_overlay_cache_key_includes_strategy_policy_ids(
        tmp_path: Path,
) -> None:
    """
    Verify cache entries are isolated by downsampler and exposure strategies.

    Cached payloads must not be reused after swapping the modular policy that
    controls analysis size or clipping semantics.
    """
    image_path = tmp_path / 'preview.png'
    Image.new('RGB', (4, 4), color='white').save(image_path)

    first_downsampler_key = clipping_overlay_cache_key(
        image_path, downsampler=IdentityDownsampler('downsampler-a')
    )
    second_downsampler_key = clipping_overlay_cache_key(
        image_path, downsampler=IdentityDownsampler('downsampler-b')
    )
    first_exposure_key = clipping_overlay_cache_key(
        image_path,
        exposure_definition=TransparentExposureDefinition('exposure-a'),
    )
    second_exposure_key = clipping_overlay_cache_key(
        image_path,
        exposure_definition=TransparentExposureDefinition('exposure-b'),
    )

    assert first_downsampler_key != second_downsampler_key
    assert first_exposure_key != second_exposure_key


def test_clipping_overlay_cache_key_uses_exact_endpoint_policy(
        tmp_path: Path,
) -> None:
    """
    Verify default cache keys identify the exact four-level mask policy.

    This prevents payload reuse if clipping semantics change independently of
    the displayed preview file.
    """
    image_path = tmp_path / 'preview.png'
    Image.new('RGB', (1, 1), color='white').save(image_path)

    key = clipping_overlay_cache_key(image_path)

    assert key.highlight_threshold == 255
    assert key.shadow_threshold == 0
    assert key.exposure_policy_id == 'any-channel-levels-v2'


def test_clipping_overlay_payload_coalesces_in_flight_builds(
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify concurrent requests for the same cache key share one build.

    Split view can request the same preview path in both panes, so the cache
    layer needs to block duplicate work while the first build is still running.
    """
    image_path = tmp_path / 'coalesce.png'
    Image.new('RGB', (4, 4), color='white').save(image_path)
    key = clipping_overlay_cache_key(image_path)
    build_started = Event()
    release_build = Event()
    build_count = 0
    errors: list[BaseException] = []
    payloads: list[ClippingOverlayPayload] = []

    def fake_build(
            *_args: object, **_kwargs: object
    ) -> ClippingOverlayPayload:
        nonlocal build_count
        build_count += 1
        build_started.set()
        if not release_build.wait(timeout=2):
            raise TimeoutError('Timed out waiting to release overlay build')

        return ClippingOverlayPayload(1, 1, b'not used by this test')

    def request_payload() -> None:
        try:
            payloads.append(clipping_overlay_payload_for_key(key))
        except BaseException as exc:  # noqa: BLE001 - report thread errors.
            errors.append(exc)

    monkeypatch.setattr(
        clipping_module, '_build_clipping_overlay_payload', fake_build
    )
    first_thread = Thread(target=request_payload)
    second_thread = Thread(target=request_payload)

    # Hold the first build open while the second request starts, forcing the
    # in-flight wait path instead of an ordinary post-build cache hit.
    first_thread.start()
    assert build_started.wait(timeout=2)
    second_thread.start()
    release_build.set()
    first_thread.join(timeout=2)
    second_thread.join(timeout=2)

    assert first_thread.is_alive() is False
    assert second_thread.is_alive() is False
    assert errors == []
    assert build_count == 1
    assert len(payloads) == 2
