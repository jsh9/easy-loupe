# Previews, EXIF, And Autofocus

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Preview And Cache Behavior](#1-preview-and-cache-behavior)
- [2. Runtime Dependencies](#2-runtime-dependencies)
- [3. ExifTool Metadata](#3-exiftool-metadata)
- [4. Autofocus Extraction](#4-autofocus-extraction)
- [5. Verification Pointers](#5-verification-pointers)

______________________________________________________________________

<!--TOC-->

This guide covers preview rendering, EXIF metadata, histogram display inputs,
and AF/focus-point extraction.

## 1. Preview And Cache Behavior

Primary files:

- `easy_loupe/core/preview.py`
- `easy_loupe/core/photo_library.py`
- `easy_loupe/ui/main_window/window.py`
- `easy_loupe/ui/viewers/`
- `tests/core/test_preview.py`
- `tests/core/test_photo_library.py`

Major logic:

- `PhotoLibrary.get_preview_path()` supports exactly four kinds: `"thumb"`,
  `"fit"`, `"viewer"`, and `"full"`.
- `MainWindow._display_current_photo()` requests the `"viewer"` preview kind
  for the central image. Thumbnails request `"thumb"` previews.
- For RAW files, `"thumb"`, `"fit"`, and `"viewer"` prefer the embedded RAW
  thumbnail when available.
- RAW `"full"` render is intentionally separate from the viewer/thumbnail
  pipeline.
- Rendered JPEG previews are cached under a cache directory derived from the
  current folder, resolved preview source path, source mtime via
  `preview_version`, and requested preview kind.
- Default cache path is `~/Library/Caches/easy-loupe` on macOS when `~/Library`
  exists, otherwise `~/.cache/easy-loupe`.
- If the preferred cache directory is not writable, the library falls back to a
  temp directory.
- Cache invalidation is currently mtime-based. If preview semantics change,
  keep cache key behavior in mind.

## 2. Runtime Dependencies

Primary files:

- `pyproject.toml`
- `easy_loupe/core/preview.py`
- `easy_loupe/core/exif.py`
- `easy_loupe/analysis/scenes.py`

Major logic:

- `Pillow` handles image loading/transforms.
- `pillow-heif` registers HEIC/HEIF image support for Pillow.
- `rawpy` is required to render RAW previews.
- `imagehash` is required for scene detection.
- If `rawpy` or `imagehash` is unavailable and the corresponding feature path
  is exercised, the library raises a runtime error.
- If `pillow-heif` is unavailable, HEIC/HEIF preview rendering raises a runtime
  error instead of silently producing an invalid preview.

## 3. ExifTool Metadata

Primary files:

- `easy_loupe/core/exif.py`
- `easy_loupe/core/metadata.py`
- `scripts/build_app/`
- `tests/core/test_metadata.py`

Major logic:

- `exiftool` is used opportunistically via `subprocess.run(...)` after path
  resolution. The runtime lookup order is `EASY_LOUPE_EXIFTOOL`, a bundled
  PyInstaller payload, then `shutil.which("exiftool")`.
- `exiftool` is not declared in `pyproject.toml`; it is an external system
  dependency for source/development runs unless `EASY_LOUPE_EXIFTOOL` points to
  a local executable.
- Packaged app builds include their own ExifTool payload.
- If `exiftool` is missing or fails, the library falls back to empty EXIF
  metadata rather than crashing.
- On Windows packaged GUI builds, ExifTool subprocesses are launched with
  Windows-specific hidden-console options to avoid flashing a terminal window
  during metadata reads.

## 4. Autofocus Extraction

Primary files:

- `easy_loupe/core/autofocus_points/`
- `easy_loupe/core/autofocus_points/brands/`
- `easy_loupe/core/exif.py`
- `tests/core/autofocus_points/`

Major logic:

- Missing focus metadata falls back to the image center `(0.5, 0.5)`.
- AF/focus-point extraction uses brand-specific maker-note logic before generic
  fallbacks.
- Canon, Sony, Panasonic, Fujifilm, Nikon, Olympus, and Pentax currently have
  dedicated paths in `autofocus_points/brands/`.
- `easy_loupe/core/exif.py` re-exports `extract_focus_point(...)` for
  compatibility, but new camera-brand-specific extraction logic belongs under
  `autofocus_points/brands/`.
- Stored focus points are normalized `(x, y)` values intended to match the
  displayed, EXIF-transposed preview orientation.
- Pentax K-1/K-1 II DSLR phase-detect metadata exposes AF point ids rather than
  pixel coordinates. The app maps those centrally clustered AF points into an
  approximate central coverage box in `autofocus_points/brands/pentax.py`; do
  not treat those ids as full-frame coordinates.

## 5. Verification Pointers

- If you change RAW rendering, verify the distinction between
  embedded-thumbnail previews and full postprocessed renders.
- If you change ExifTool resolution or invocation, test `EASY_LOUPE_EXIFTOOL`,
  bundled PyInstaller lookup, and system `PATH` fallback behavior.
- Preserve the missing/failing-ExifTool fallback to empty metadata.
- Preserve Windows hidden-console subprocess options for GUI builds.
- If you change focus-point extraction, make the change in
  `easy_loupe/core/autofocus_points/`, keeping `easy_loupe/core/exif.py` as the
  compatibility re-export layer.
- Add new brand-specific extraction under
  `easy_loupe/core/autofocus_points/brands/` and register it in the brand
  extractor order in `autofocus_points/extraction.py`.
- Add targeted tests under `tests/core/autofocus_points/` for the metadata
  keys, brand detection, orientation handling, and fallback behavior touched.
- Validate against representative sample folders non-mutatingly when they are
  available.
- For Pentax DSLR point-id metadata, preserve the central-layout approximation
  unless new ground-truth samples justify changing the mapping.
