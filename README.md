# EasyCull

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Setup and Run](#1-setup-and-run)
  - [1.1. Option A: `uv`](#11-option-a-uv)
  - [1.2. Option B: Anaconda](#12-option-b-anaconda)
  - [1.3. Open the App](#13-open-the-app)
- [2. Build App Binary](#2-build-app-binary)
  - [2.1. macOS](#21-macos)
  - [2.2. Windows](#22-windows)
- [3. Features](#3-features)
- [4. Modes and Transitions](#4-modes-and-transitions)
- [5. Keyboard Shortcuts](#5-keyboard-shortcuts)
- [6. Metadata File](#6-metadata-file)

______________________________________________________________________

<!--TOC-->

Desktop photo culling app for JPEG and RAW photo folders.

## 1. Setup and Run

### 1.1. Option A: `uv`

Install dependencies:

```bash
uv sync
```

Type check the application package:

```bash
tox -e ty
```

Start the app:

```bash
uv run python -m easy_cull
```

### 1.2. Option B: Anaconda

Create and activate an environment:

```bash
conda create -n easy-cull python=3.12
conda activate easy-cull
```

Install dependencies:

```bash
pip install PySide6 imagehash pillow rawpy
```

Start the app:

```bash
python -m easy_cull
```

### 1.3. Open the App

Launch the desktop app and use the native folder picker to choose a photo
folder.

## 2. Build App Binary

EasyCull uses PyInstaller for native app bundles. Build on the target operating
system: the macOS app should be built on macOS, and a Windows executable should
be built on Windows.

Packaged builds include an ExifTool payload for camera maker-note metadata used
by autofocus-point detection. At runtime EasyCull checks `EASY_CULL_EXIFTOOL`
first, then a bundled ExifTool payload when running from a packaged app, then
`exiftool` from the system `PATH`. To point EasyCull at a specific local
ExifTool binary while developing, set `EASY_CULL_EXIFTOOL` to that executable
path before launching the app.

### 2.1. macOS

When EasyCull is launched as `python -m easy_cull`, macOS still sees the
underlying Python executable as the running application. The in-app window
title is correct, but app-level switchers can still show `python3.13` or the
Python icon.

Build and launch the macOS app bundle for native Finder, Dock, app switcher,
and AltTab behavior:

```bash
uv sync --extra dev
uv run python scripts/build_app/build_app_macos.py
open dist/EasyCull.app
```

The generated `EasyCull.app` is a PyInstaller bundle with its own Python
runtime, dependencies, bundled ExifTool payload, `Info.plist`, and
`EasyCull.icns` app icon. It is much larger than a launcher stub because it
contains the application runtime.

For macOS distribution, ship `dist/EasyCull.app`. PyInstaller may also leave a
separate `dist/EasyCull/` one-folder output beside the app bundle; users do not
need that folder when receiving the `.app`, and shipping both duplicates the
runtime payload. A simple zip package can be created with:

```bash
ditto -c -k --keepParent dist/EasyCull.app EasyCull-macos.zip
```

For macOS packaging diagnostics:

```bash
uv run python scripts/build_app/build_app_macos.py --diagnose
```

The diagnostic command prints the Python/PySide6/PyInstaller versions plus Qt,
shiboken, and bundled ExifTool paths found inside `dist/EasyCull.app`.

### 2.2. Windows

Build the Windows executable on Windows:

```powershell
uv python pin 3.12
uv sync --extra dev
uv run python scripts/build_app/build_app_windows.py
```

The default output is a one-folder PyInstaller app at `dist\EasyCull\`. Run the
executable from inside that folder:

```powershell
.\dist\EasyCull\EasyCull.exe
```

Do not copy only `EasyCull.exe` out of `dist\EasyCull\`. In the default
one-folder build, the `.exe` is only the launcher; Qt, PySide6, Python, and
other DLLs live next to it under the same output folder. If you want one file
that can be moved by itself, build a single executable instead:

```powershell
uv run python scripts/build_app/build_app_windows.py --onefile
```

The one-file build should be much larger than the launcher `.exe` from the
one-folder build because it embeds the dependency payload.

The script creates `easy_cull\ui\assets\EasyCull.ico` from the packaged PNG
when the `.ico` asset is missing.

The Windows and macOS build scripts download the official ExifTool release
payload from <https://exiftool.org/> / SourceForge into the ignored `build`
cache when the local cache is missing, then package it into the app bundle. The
downloaded payload is not committed to the repository.

Both scripts embed the packaged EasyCull icon assets. Runtime Qt app identity
also uses the same assets so Finder, Dock, app switcher, AltTab, Windows
taskbar, and window chrome have the EasyCull name and icon where the platform
allows it.

PySide6, Pillow, rawpy, and imagehash are all PyInstaller-compatible in
principle, but RAW support should be verified with sample RAW files on Windows.
If `QtWidgets` still fails to import on a packaged build, first confirm that
the whole `dist\EasyCull\` folder is intact and that the test machine is a
supported Windows 10/11 system for the bundled Qt/PySide6 version.

For packaging diagnostics on Windows:

```powershell
uv run python scripts/build_app/build_app_windows.py --diagnose
uv run python scripts/build_app/build_app_windows.py --console
.\dist\EasyCull\EasyCull.exe
```

The diagnostic command prints the Python/PySide6/PyInstaller versions plus the
Qt DLLs and Windows platform plugin found under `dist\EasyCull\`. The console
build keeps a terminal attached so startup errors include a normal traceback.

## 3. Features

- Opens folders through the native desktop folder picker.
- Groups JPEG and RAW files by shared filename stem.
- Shows two primary UI states: browse mode for the full-grid thumbnail view,
  and view mode for the vertical thumbnail strip, central photo viewer,
  optional split view, and scene strip after scene detection.
- Supports scene detection that rebuilds the left strip into scene stacks while
  keeping browse mode as a full per-photo grid.
- Supports keyboard-based ratings, color labels, picked/reject flags, and an
  `Assign to Photo` menu for the current selection.
- Supports an `Organize Photos` workflow from the top bar, File menu, or
  `Ctrl+Shift+E` to either reorganize files by one tag criterion or write
  shared XMP sidecars for Lightroom/Capture One style metadata exchange, then
  immediately undo the completed operation from the finished dialog if needed.
- Displays metadata in the top bar and thumbnail strips using star ratings, a
  colored label dot, and pick/reject indicators.
- Supports autofocus-point/manual zoom, split view, per-photo remembered manual
  zoom state, and `W/A/S/D` panning.
- Shows the current visible region on strip thumbnails while zoomed in, using a
  red zoom box and a darkened mask outside the box.
- In scene mode, the visible-region overlay moves to the horizontal scene strip
  rather than the left scene-stack strip.
- Keeps split view active when scene detection finishes in view mode, while
  still exiting browse mode back to a fit view.
- Uses a progress overlay during long-running work such as folder loading and
  scene detection, photo organization, and XMP writing, temporarily disabling
  interactions and assignment actions.
- Writes visible metadata immediately to `easy-cull.json` in the selected
  folder.

## 4. Modes and Transitions

- `View mode` is the normal working mode. It shows the left thumbnail strip,
  the main viewer, and the horizontal scene strip when scene detection is
  available for the current photo.
- When photos are loaded, keyboard focus returns to the active navigation list
  for the current mode so list navigation works immediately without first
  tabbing away from the top bar.
- `Single-pane fit view` is the default viewer state inside view mode.
- `Single-pane manual/focus view` is the zoomed viewer state inside view mode.
- `Split view` is an alternate view-mode layout with a fit-view pane on the
  left and a zoom/focus pane on the right.
- `Browse mode` is the full-photo grid view.

Common transitions:

- Press `G` to enter browse mode from normal view mode.
- Press `Space` in browse mode to return to single-pane fit view for the
  current photo.
- Press `Space` in single-pane fit view to enter manual/focus zoom.
- Press `Space` in single-pane manual view to return to fit view.
- Press `\` in normal view mode to toggle split view on or off.
- Press `Space` in split view to promote the right zoomed pane into single-pane
  manual view.
- Double-clicking a browse-grid photo exits browse mode and opens that photo in
  single-pane fit view.
- If scene detection finishes while you are in browse mode, the app exits
  browse mode and returns to fit view for the current photo.
- If scene detection finishes while you are already in split view, split view
  stays active and preserves its manual zoom state.
- If you switch away from the app and come back while a folder is loaded,
  keyboard focus returns to the active navigation list instead of staying on
  the top-bar buttons.

## 5. Keyboard Shortcuts

- Ratings: `1`-`5` assign, `0` clears
- Color labels: `6` red, `7` yellow, `8` green, `9` blue, `` ` `` clears, and
  purple is available from `Assign to Photo > Color Label`
- Flags: `P` pick, `X` reject, `U` clear
- Organizer: `Ctrl+Shift+E` opens the organizer/XMP dialog
- Browse and view mode: `G` enters browse mode, `Space` exits browse mode into
  fit-to-window view mode, promotes split view into full zoom, or toggles focus
  zoom while already in single-pane view mode, and double-clicking a browse
  thumbnail opens that photo in fit-to-window view mode
- Zoom and pan in view mode: `\` toggles split view, `-` zooms out, `=` / `+`
  zoom in, `W/A/S/D` pan the active zoomed view, the strip thumbnail overlay
  tracks the current visible region while zoomed, and left/right arrows move
  within the current scene

## 6. Metadata File

The app stores per-photo metadata in `easy-cull.json` inside the selected
folder. Keys use the visible photo stem, not the filename with extension.

You can also export the current rating, color label, and pick/reject state to
shared uppercase `PHOTO_ID.XMP` sidecars through `Organize Photos`.

Example:

```json
{
  "IMG_2000": {
    "rating": 4,
    "color_label": "red",
    "flag": "picked"
  }
}
```

Rules:

- `rating` is `1`-`5` or omitted
- `color_label` is one of `red`, `yellow`, `green`, `blue`, `purple`, or
  omitted
- `flag` is `picked`, `rejected`, or omitted
