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

Desktop photo culling app for JPEG, HEIC/HEIF, and RAW photo folders.

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
pip install PySide6 imagehash pillow pillow-heif rawpy
```

Start the app:

```bash
python -m easy_cull
```

### 1.3. Open the App

Launch the desktop app and use the native folder picker to choose a photo
folder.

You can also open a supported photo file directly from Finder, Explorer, or an
argv path. EasyCull starts in a lightweight photo-viewer window for that file,
loads neighboring photos from the same folder in the background when folder
access is available, and can enter the full culling workspace with `G` or
`Enter`.

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
- Opens individual photo files directly into a lightweight photo-viewer mode
  with adjacent-folder navigation and handoff into the full culling workspace.
- Groups JPEG, HEIC/HEIF, and multiple camera RAW formats by shared filename
  stem.
- Shows view mode, browse mode, and compare mode: view mode uses the vertical
  thumbnail strip, central photo viewer, optional split view, and scene strip;
  browse mode shows a full-photo grid; compare mode displays up to the
  configured number of selected photos side by side.
- Supports scene detection that rebuilds the left strip into scene stacks while
  keeping browse mode as a full per-photo grid.
- Supports manual scene editing with `Ctrl+Shift+M`, including merging whole
  selected scene stacks with a fully selected horizontal scene strip.
- Supports multi-selection plus keyboard-based ratings, color labels,
  picked/reject flags, metadata undo/redo, and an `Assign to Photo` menu for
  the current selection.
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

- `Photo viewer mode` opens when a supported photo file is launched directly.
  It shows the opened photo first, supports neighboring-photo navigation after
  background folder hydration, and uses `G` or `Enter` to hand off to culling
  mode on the same monitor.
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
- `Compare mode` is a side-by-side inspection grid entered from the current
  selection. It displays up to the configured compare limit, tracks one active
  pane for tagging, can open that active photo alone for fit/100% inspection,
  and can lock zoom/pan across panes. The default limit is 8 photos,
  configurable from `Compare > Limit` with options 2, 3, 4, 6, 8, 10, 12, 16,
  and 20.

Common transitions:

- Press `G` or `Enter` in photo viewer mode to enter the full culling workspace
  for the current folder and photo.
- Press `G` to enter browse mode from normal view mode.
- Press `C` to enter compare mode for the current selection when at least two
  photos are selected.
- Press `Esc` in the compare grid to restore the previous view or browse
  selection.
- Press `Esc` while a single compare photo is open to return to the comparison
  grid.
- Press `G` in compare mode to enter browse mode with the original pre-compare
  selection restored. If more photos were selected than the configured compare
  limit, compare displays only the capped set, but browse restores the full
  original selection.
- Press `Space` in browse mode to return to single-pane fit view for the
  current photo.
- Press `Space` in the compare grid to open the active photo in fit-to-window
  size, then press `Space` again to toggle that photo between fit and 100%.
- Press `Z` in the compare grid to toggle focus zoom for all compared panes, or
  while a single compare photo is open to toggle that photo between fit and
  100%. If a small photo already displays at 100% in fit-to-window mode, that
  selected-photo toggle changes the internal fit/inspection state without a
  visible scale change.
- Press `Space` in single-pane fit view to enter manual/focus zoom.
- Press `Space` in single-pane manual view to return to fit view.
- Press `Z` in normal view mode as an alternate shortcut for the same
  fit/manual zoom toggle as `Space`.
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
- Metadata history: `Ctrl+Z` undoes the last metadata assignment batch,
  `Ctrl+Y` redoes it
- Organizer: `Ctrl+Shift+E` opens the organizer/XMP dialog
- Scene editing: `Ctrl+Shift+M` merges selected photos into a scene; selecting
  only part of the horizontal scene strip is treated as an attempted split and
  is blocked, while selecting the full strip can merge that scene with selected
  vertical scene stacks
- Browse, view, and compare mode: `G` enters browse mode, `C` enters compare
  mode, `Esc` exits compare mode or returns from selected-photo compare view to
  the grid, `Space` exits browse mode into fit-to-window view mode, promotes
  split view into full zoom, toggles focus zoom in single-pane view mode, or
  opens/toggles the active compare photo, `Z` mirrors `Space` in view mode and
  toggles the active compare zoom target, and double-clicking a browse
  thumbnail opens that photo in fit-to-window view mode
- Selection: use normal extended-selection gestures in the thumbnail and browse
  lists; after scene detection, `Shift+Left` / `Shift+Right` extends the
  horizontal scene-strip selection and `Shift+Up` / `Shift+Down` extends across
  scene-stack rows using an anchored range that releases rows outside the range
  when you reverse direction
- Zoom and pan: `\` toggles split view, `-` zooms out, `=` / `+` zoom in,
  `W/A/S/D` pan the active zoomed view or compare pane set, the strip thumbnail
  overlay tracks the current visible region while zoomed, left/right arrows
  move within the current scene in view mode, and arrow keys move the active
  pane in compare mode

## 6. Metadata File

The app stores per-photo metadata in `easy-cull.json` inside the selected
folder under a top-level `photos` object. Photo keys use the visible photo
stem, not the filename with extension.

You can also export the current rating, color label, and pick/reject state to
shared uppercase `PHOTO_ID.XMP` sidecars through `Organize Photos`.

Example:

```json
{
  "photos": {
    "IMG_2000": {
      "rating": 4,
      "color_label": "red",
      "flag": "picked"
    }
  },
  "scenes": {
    "source": "manual",
    "groups": [
      ["IMG_2000", "IMG_2001"],
      ["IMG_2002"]
    ]
  }
}
```

Rules:

- `rating` is `1`-`5` or omitted
- `color_label` is one of `red`, `yellow`, `green`, `blue`, `purple`, or
  omitted
- `flag` is `picked`, `rejected`, or omitted
- `scenes` is omitted until scenes are detected or manually edited; when
  present, `source` records whether the saved groups came from `detected` or
  `manual` scene grouping, and `groups` stores ordered photo-id lists
