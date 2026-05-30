# AGENTS.md

## 1. Purpose

This repository is a local desktop photo culling app for JPEG and RAW folders.
It is organized around a small set of top-level packages:

- `easy_cull/core/`: non-UI application logic for the photo library, records,
  EXIF, metadata, previews, and scene detection.
- `easy_cull/ui/`: PySide6 desktop UI built around `PhotoLibrary`.
- `easy_cull/analysis/`: scene-detection logic plus placeholder
  analysis-oriented feature modules.
- `easy_cull/operations/`: concrete batch file-operation modules for photo
  organization, XMP sidecars, and undo support.

The codebase is small, but a lot of behavior is still concentrated in a few
large modules and packages. Read the relevant section before editing; avoid
making UI or library changes based on assumptions.

## 2. Working Setup

- Python target: `>=3.12` from `pyproject.toml`
- Default local Python from `.python-version`: `3.12`
- Preferred environment manager: `uv`
- Install dependencies: `uv sync`
- Install build/test/dev dependencies: `uv sync --extra dev`
- Launch the app: `uv run python -m easy_cull`

### 2.1. Build Artifacts

- PyInstaller is a dev dependency. Build on the target operating system rather
  than cross-compiling app bundles.
- Build macOS with `uv run python scripts/build_app/build_app_macos.py`. The
  distributable artifact is `dist/EasyCull.app`.
- For macOS distribution, ship `dist/EasyCull.app`. If PyInstaller also leaves
  `dist/EasyCull/` beside it, that sibling one-folder output is not needed by
  users receiving the `.app` and should not be shipped in addition to the app
  bundle.
- A simple macOS zip can be produced with
  `ditto -c -k --keepParent dist/EasyCull.app EasyCull-macos.zip`.
- Build Windows with `uv run python scripts/build_app/build_app_windows.py`.
  The default output is the one-folder app `dist\EasyCull\`; distribute the
  whole folder, not just `EasyCull.exe`.
- Windows also supports
  `uv run python scripts/build_app/build_app_windows.py --onefile` for a
  movable single executable and `--console` for startup-debug builds.
- Both build scripts support `--diagnose`; use it to print Python, PySide6,
  PyInstaller, Qt, shiboken, and bundled ExifTool diagnostics for the built
  artifact.
- The build scripts stage official ExifTool payloads under ignored `build`
  cache/staging directories and bundle them under
  `easy_cull/vendor/exiftool/...` inside the PyInstaller artifact. Do not
  commit downloaded ExifTool payloads.

### 2.2. Windows Sessions

On Windows, `uv`, `python`, `pip`, and `tox` are often **not on PATH** in AI
agent shell sessions even when they are installed for the human user. This is
unlike macOS, where these tools are typically available immediately.

When you need to run tests on Windows:

1. Try `uv run pytest ...` first.
2. If `uv` is not found, do **not** spend time searching the filesystem for
   `uv.exe` or `python.exe` with `Get-ChildItem -Recurse` or similar
   approaches. These searches are slow on Windows and usually fruitless.
3. Instead, ask the user how they run tests locally and whether they can
   provide the path to their Python or `uv` executable. One quick attempt is
   acceptable; an extended search is not.
4. If no working interpreter can be found quickly, state that you cannot run
   tests in this session, explain the change you made, and suggest the user
   verify locally or let CI validate.

## 3. Verification

Use the existing pytest suite as the first-line verification step.

- Run tests: `uv run pytest`
- Alternate full-suite checks: `tox -e py312`, `tox -e py313`, `tox -e ty`,
  `tox -e muff-lint`, `tox -e muff-format`, `tox -e pre-commit`
- For every change, in addition to running tests, other non-pytest environments
  in `tox` must also be run (e.g., `tox -e ty`, `tox -e muff-lint`,
  `tox -e muff-format`, `tox -e pre-commit`), and any errors must be fixed. If
  `tox -e pre-commit` produces errors, run `pre-commit run -a` to auto-format.

Notes:

- Local verification should use the platform's normal Qt backend rather than
  forcing `QT_QPA_PLATFORM=offscreen`.
- GitHub Actions display behavior differs by OS:
  - Linux CI explicitly sets `QT_QPA_PLATFORM=offscreen`. This is the most
    masking-prone CI path in the repo: it avoids Linux runner display crashes,
    but it can hide window-manager, focus, activation, and popup behavior that
    would only appear on the normal Linux Qt backend.
  - macOS CI runs plain `tox` on Qt's native backend and has lower masking risk
    than Linux offscreen, but it can still miss purely visual or unasserted
    popup behavior because no human is watching the windows.
  - Windows CI also runs plain `tox` on Qt's native backend and has similar
    lower masking risk to macOS, with the same caveat about purely visual or
    unasserted popup behavior.
- If a bug smells display-, focus-, or popup-specific, prefer local manual
  verification on a visible desktop session in addition to automated tests.
- The suite is split across `tests/core/`, `tests/ui/`, `tests/analysis/`,
  `tests/operations/`, plus `tests/test_package_main.py`.
- On 2026-05-03, `uv run pytest -q` passed with `255 passed`.

## 4. Repository Map

- `easy_cull/core/`
  - Contains the non-UI implementation modules and packages: `photo_library`,
    `records`, `folder_loading`, `exif`, `autofocus_points`, `metadata`, and
    `preview`.
  - `photo_library.py` defines `PhotoLibrary` and delegates folder loading,
    metadata persistence, previews, and scene detection to the lower-level
    modules.
  - `autofocus_points/` owns AF/focus-point extraction. `exif.py` re-exports
    `extract_focus_point(...)` for compatibility, but new camera-brand-specific
    extraction logic belongs under `autofocus_points/brands/`.
  - `records.py` defines the shared constants plus the `PhotoRecord` and
    `SceneGroup` dataclasses.
- `easy_cull/ui/`
  - Defines the full PySide6 UI: browse mode, single-pane and split view modes,
    theming, thumbnail widgets, viewer, scene strip, worker thread, and the
    main window.
  - The UI is split primarily across `ui/main_window/`, `ui/viewers/`,
    `ui/widgets.py`, `ui/theme.py`, `ui/workers.py`, and `ui/app.py`.
  - `ui/identity.py` owns the user-facing app name, packaged icon lookup, Qt
    app identity, and best-effort macOS process/app-switcher identity hooks.
  - `ui/assets/` contains packaged EasyCull icon assets used by Qt and the
    PyInstaller build scripts; keep package-data configuration aligned when
    adding or renaming assets.
- `easy_cull/ui/main_window/`
  - Contains the `MainWindow` package: `window.py`, `build.py`, `workflows.py`,
    `navigation.py`, and `presentation.py`.
  - `MainWindow` remains the central stateful UI controller.
- `easy_cull/ui/viewers/`
  - Contains `PhotoViewer`, `MainPhotoViewer`, and `ExifOverlayWidget`.
- `easy_cull/analysis/`
  - Contains the concrete `scenes.py` scene-detection implementation plus
    placeholder `quality.py` and `faces.py` modules for future work.
- `easy_cull/operations/`
  - Contains concrete non-UI batch operations: `export.py` reorganizes tagged
    photo sets by metadata, `xmp.py` writes shared XMP sidecars, and
    `common.py` provides undo bookkeeping plus shared filesystem helpers.
- `easy_cull/__main__.py`
  - Package module entry point that delegates to `easy_cull.ui.app`.
- `tests/core/`
  - Core behavioral contract for folder loading, EXIF parsing, records,
    metadata, preview generation, autofocus-point extraction, and
    `PhotoLibrary`.
- `tests/ui/`
  - UI behavioral contract for app launch, widgets, workers, viewers, theming,
    and `MainWindow` behavior split across `main_window/`.
- `tests/analysis/`
  - Analysis package contract for scene grouping and placeholder-module API
    boundaries.
- `tests/operations/`
  - Operations package contract for file organization, XMP writing, and undo
    behavior.
- `tests/scripts/`
  - Packaging-script contract for PyInstaller command construction and build
    options.
- `tests/test_package_main.py`
  - Verifies the package entry point wiring.
- `tests/conftest.py`
  - Adds the repo root to `sys.path` for test imports.
- `scripts/build_app/`
  - PyInstaller build scripts and shared helpers for macOS/Windows artifacts,
    app icons, bundled ExifTool payloads, and packaging diagnostics.
- `README.md`
  - User-facing setup and feature summary.

## 5. Core Invariants

Preserve these behaviors unless the change explicitly intends to redefine the
product contract and the tests/docs are updated accordingly.

- Photos are grouped by shared filename stem across supported extensions.
- Supported extensions are currently:
  - JPEG: `.jpg`, `.jpeg`
  - RAW: `.cr3`, `.nef`
- A `PhotoRecord.photo_id` is the visible stem, not the filename with
  extension.
- Metadata is stored in `easy-cull.json` inside the selected photo folder.
- Saved folder metadata uses a top-level `photos` object for per-photo entries
  and may include a top-level `scenes` object with `source` and `groups`.
- Saved metadata keys use the visible stem format, for example `IMG_2000`, not
  `IMG_2000.JPG`.
- When reading metadata, legacy forms are normalized:
  - keys with extensions are reduced to stem
  - flag value `"reject"` becomes `"rejected"`
- Ratings are limited to integers `1..5` or `None`.
- Color labels are limited to `"red"`, `"yellow"`, `"green"`, `"blue"`,
  `"purple"`, or `None`.
- Flags are limited to `"picked"`, `"rejected"`, or `None`.
- Saved metadata entries may contain `rating`, `color_label`, and `flag`.
- Shared XMP sidecars use the uppercase stem format `PHOTO_ID.XMP`.
- XMP writing manages only the app-owned rating/color-label/pick-reject fields
  and supports preserve-or-replace merge policies.
- Photo organization groups files by one metadata criterion at a time: `flag`,
  `color_label`, or `rating`.
- Photo organization supports `copy` and `move` actions plus conflict policies
  `fail`, `skip`, and `overwrite`.
- Undo for organization/XMP workflows is explicit, filesystem-based, and a
  given `UndoPlan` is intended to be consumed at most once.
- Photos default to sorting by EXIF capture timestamp when available, then by
  display name. Users can change the global sort preference from the top-bar
  `Sort by:` visual group, which contains a segmented control between
  `File Name` and `Capture Time` plus the adjacent `Reverse order` checkbox.
  The choices are persisted with app settings and applied immediately to loaded
  folders.
- `get_preview_path()` supports exactly four kinds: `"thumb"`, `"fit"`,
  `"viewer"`, and `"full"`.
- For RAW files, `"thumb"`, `"fit"`, and `"viewer"` prefer the embedded RAW
  thumbnail when available.
- RAW `"full"` render is intentionally separate from the viewer/thumbnail
  pipeline.
- Missing focus metadata falls back to the image center `(0.5, 0.5)`.
- AF/focus-point extraction uses brand-specific maker-note logic before generic
  fallbacks. Canon, Sony, Panasonic, Fujifilm, Nikon, Olympus, and Pentax
  currently have dedicated paths in `autofocus_points/brands/`.
- Stored focus points are normalized `(x, y)` values intended to match the
  displayed, EXIF-transposed preview orientation.
- Pentax K-1/K-1 II DSLR phase-detect metadata exposes AF point ids rather than
  pixel coordinates. The app maps those few dozen centrally clustered AF points
  into an approximate central coverage box in
  `autofocus_points/brands/pentax.py`; do not treat those ids as full-frame
  coordinates.

## 6. External Dependencies And Runtime Assumptions

- `PySide6` powers the desktop UI.
- `Pillow` handles image loading/transforms.
- `rawpy` is required to render RAW previews.
- `imagehash` is required for scene detection.
- `exiftool` is used opportunistically via `subprocess.run(...)` after path
  resolution. The runtime lookup order is `EASY_CULL_EXIFTOOL`, a bundled
  PyInstaller payload, then `shutil.which("exiftool")`.

Important:

- `exiftool` is not declared in `pyproject.toml`; it is an external system
  dependency for source/development runs unless `EASY_CULL_EXIFTOOL` points to
  a local executable. Packaged app builds include their own ExifTool payload.
- If `exiftool` is missing or fails, the library falls back to empty EXIF
  metadata rather than crashing.
- On Windows packaged GUI builds, ExifTool subprocesses are launched with
  Windows-specific hidden-console options to avoid flashing a terminal window
  during metadata reads.
- If `rawpy` or `imagehash` is unavailable and the corresponding feature path
  is exercised, the library raises a runtime error.

## 7. Preview And Cache Behavior

`PhotoLibrary.get_preview_path()` caches rendered JPEG previews under a cache
directory derived from:

- current folder
- resolved preview source path
- source mtime via `preview_version`
- requested preview kind

Relevant details:

- Default cache path is `~/Library/Caches/easy-cull` on macOS when `~/Library`
  exists, otherwise `~/.cache/easy-cull`.
- If the preferred cache directory is not writable, the library falls back to a
  temp directory.
- Cache invalidation is currently mtime-based. If you change preview semantics,
  keep cache key behavior in mind.

## 8. UI Structure And Expectations

`MainWindow` is the central controller. Before modifying it, trace the current
flow:

1. `choose_folder()`
2. `PhotoLibrary.load_folder(...)`
3. `_populate_thumbnail_list()`
4. `_populate_browse_list()`
5. `_populate_scene_list()`
6. `_display_current_photo()`
7. `_refresh_ui()`

Scene detection runs off the UI thread through:

- `SceneDetectionWorker`
- `QThread`
- `_handle_scene_progress()`
- `_handle_scene_finished()` / `_handle_scene_failed()`

Current functionality is grouped below so UI changes can be evaluated against
the actual product behavior, not just the widget layout.

### 8.1. Modes, Behaviors, And Transitions

Mode summary:

- `View mode` is the normal working mode. It shows the left thumbnail strip and
  the main viewer, plus the horizontal scene strip when scene detection is
  available for the current photo.
- `Single-pane fit view` is the default viewer state inside view mode. The main
  viewer fits the current photo to the available space.
- `Single-pane manual/focus view` is the zoomed viewer state inside view mode.
  It is entered from single-pane fit view with `Space` and supports zoom/pan.
- `Split view` is an alternate view-mode layout entered with `\`. It shows a
  fit-view pane on the left and a zoom/focus pane on the right.
- `Browse mode` is the full-photo grid entered with `G`. It replaces the normal
  content splitter, hides the horizontal scene strip, and is exited with
  `Space` or by double-clicking a photo.
- `Selected-photo compare view` is entered from the compare grid with `Space`.
  It shows the active compared photo alone in fit-to-window size and supports
  toggling that photo between fit and 100%.

Mode-transition summary:

- `G` enters browse mode from normal view mode when photos are loaded.
- `Space` in browse mode exits browse mode and returns to single-pane fit view
  for the current photo.
- `Space` in single-pane fit view enters manual/focus zoom.
- `Space` in single-pane manual view returns to fit view.
- `\` toggles split view on and off while staying in normal view mode.
- `Space` in split view promotes the right zoomed pane into single-pane manual
  view.
- Scene-detection completion can also trigger transitions:
  - finish while in browse mode -> exit browse mode and fit the current photo
  - finish while already in split view -> keep split view and preserve its
    manual zoom state

#### 8.1.1. Folder Loading And Initial UI State

- When the main window first shows and no folder is loaded, `showEvent()`
  schedules the folder chooser automatically.
- Canceling the folder chooser leaves the UI idle: no current photo, no loaded
  photo list, no progress overlay, and no forced state change.
- If folder loading fails, the progress overlay is dismissed, controls are
  re-enabled, and a critical error dialog is shown.
- When folder loading succeeds, the window:
  - loads the folder through `PhotoLibrary.load_folder(...)`
  - selects the first photo when photos exist
  - populates the left strip, browse grid, and scene strip
  - displays the current photo in the main viewer
  - refreshes labels, selection state, and overlays
  - restores keyboard focus to the active navigation list after the UI becomes
    interactive again; in normal non-scene view mode this means the left
    thumbnail strip is ready to move on the first `Down` keypress
- `MainWindow._display_current_photo()` requests the `"viewer"` preview kind
  for the central image.
- Thumbnails request `"thumb"` previews.

#### 8.1.2. View Modes And Mode Transitions

- There are four user-visible presentation states:
  - normal view mode with the left thumbnail strip and a single-pane viewer
  - normal view mode with the left thumbnail strip and split view
  - browse mode with the full photo grid
  - compare mode with a capped side-by-side grid of selected photos
- Browse mode is entered with `G` only when photos are loaded.
- Compare mode is entered with `C` only when photos are loaded and at least two
  photos are selected or otherwise resolvable from the current item.
- Entering browse mode:
  - shows the browse grid
  - hides the normal content splitter
  - hides the horizontal scene strip
  - disables split/viewer/scene-navigation shortcuts
  - preserves the current photo selection
- Entering compare mode:
  - displays up to the configured compare photo limit from the resolved current
    selection
  - stores the full pre-compare selection for later restoration
  - hides the thumbnail, browse, and scene lists
  - makes the first compared photo current
  - starts with locked zoom/pan enabled
- Browse mode always shows every individual photo, even when normal view mode
  is currently using scene stacks in the left strip.
- Pressing `Space` while in browse mode exits browse mode and forces the main
  viewer back to fit view for the current photo.
- Pressing `Space` while in the compare grid opens the active compared photo
  alone in fit-to-window size.
- Pressing `Space` while that selected compare photo is open toggles that photo
  between fit view and 100% zoom. For a small photo that already fits at 100%,
  this changes internal fit/inspection state without a visible scale change.
- Pressing `Z` while in the compare grid toggles every compared pane between
  fit view and AF-centered 100% zoom.
- Pressing `Z` while a selected compare photo is open toggles that photo
  between fit view and 100% zoom. For a small photo that already fits at 100%,
  this changes internal fit/inspection state without a visible scale change.
- Pressing `Esc` while a selected compare photo is open returns to the
  comparison grid.
- Pressing `Esc` while in compare mode restores the previous view/browse state
  and the stored pre-compare selection.
- Pressing `G` while in compare mode enters browse mode and restores the stored
  pre-compare selection. If the user selected more photos than the configured
  compare limit, compare shows only the capped set but browse restores the
  whole original selection.
- Exiting browse mode:
  - restores the normal content splitter
  - re-selects the appropriate item in the left strip
  - repopulates the scene strip for the current scene when scene detection is
    available
  - restores focus to the active navigation list for the restored mode
- If the user enters browse mode from split view and then presses `Space`,
  browse mode exits to single-pane fit view, not back into split view.
- When the main window is reactivated with photos loaded and no progress/modal
  workflow active, keyboard focus returns to the active navigation list rather
  than remaining on top-bar controls.

#### 8.1.3. Single-Pane, Focus Zoom, And Split View Behavior

- Single-pane view has two logical states:
  - fit-to-window
  - manual/focus zoom
- Pressing `Space` while already in single-pane view toggles focus zoom.
- In single-pane view, `Space` behaves as:
  - fit view -> focus/manual zoom
  - manual zoom -> fit view
- Manual zoom state is remembered per photo. Returning to the same photo
  restores its last manual zoom center and scale; a different photo gets its
  own remembered state or falls back to the extracted AF point.
- The top bar includes `Show AF point`, checked by default. When checked, the
  main viewer shows a fixed-screen-size red square at the photo's extracted AF
  point in fit view, manual/focus zoom, and both panes of split view.
- The `I` shortcut toggles a floating EXIF and RGB histogram overlay in normal
  view mode. The overlay is anchored over the top-right of the main viewer,
  follows the current photo, hides automatically in browse mode, compare mode,
  and busy/progress states, and reappears when returning to eligible normal
  view state if the overlay preference remains enabled.
- The top bar includes a single `Sort by:` visual group with mutually exclusive
  `File Name` and `Capture Time` options plus a `Reverse order` checkbox. The
  sort-mode options are visually one track/pill segmented control with a
  brand-blue active option, and the whole sort area is framed with a distinct
  border as one group rather than loose controls. It is not exposed from the
  menu bar. The `Reverse order` checkbox flips the active sort direction. Sort
  changes immediately rebuild the vertical thumbnail strip, horizontal scene
  strip, browse grid, and compare grid while preserving selected photo IDs
  where those photos still exist.
- The `F` shortcut toggles `Show AF point`.
- A photo with no remembered manual view enters focus zoom around the extracted
  AF point. Remembered per-photo manual zoom state takes priority when
  returning to a photo.
- Pressing `\` in normal view mode toggles split view.
- Split view uses:
  - a fit-view pane on the left
  - a manual/focus-zoom pane on the right
- Viewer zoom and pan shortcuts target only the active zoomed pane. In split
  view, that means the right pane; the left fit pane remains unchanged.
- Pressing `Space` while in split view promotes the right pane into single-pane
  manual view, preserving its zoom and center.
- Pressing `Space` again from that promoted single-pane manual view returns to
  fit view.
- Toggling split view off after zooming/panning preserves the right-pane manual
  view in single-pane mode.
- Split/manual view state is remembered per photo across navigation.

#### 8.1.4. Browse Selection, Strip Selection, And Double-Click Behavior

- In normal view mode, the left strip selection tracks the current photo.
- When scene detection is complete, the left strip represents scene stacks, so
  the selected left item is the first photo of the current scene rather than
  necessarily the exact current photo.
- Multi-selection is preserved in thumbnail, browse, and scene workflows when
  the user extends selection with Shift or Control.
- In scene mode, `Shift+Left` and `Shift+Right` extend the horizontal in-scene
  selection, while `Shift+Up` and `Shift+Down` extend across vertical
  scene-stack rows and preserve exact hidden in-scene selections.
- `Shift+Up` and `Shift+Down` in the vertical thumbnail strip use anchored
  range selection. Reversing direction releases rows outside the current
  anchor-to-current range rather than leaving them stickily selected.
- In browse mode, selecting a grid item updates the current photo and keeps the
  left strip and scene strip synchronized in the background.
- Scene merges, breaks, and scene-edit undo/redo performed from browse mode
  keep keyboard focus on the browse grid after the lists are rebuilt.
- Scene merges from the vertical thumbnail strip expand selected scene stacks
  to all photos in those stacks. Scene merges from the horizontal scene strip
  use exact in-scene photo selection: selecting only part of the current scene
  is blocked as an attempted split, while selecting the full horizontal scene
  can merge that whole scene with selected vertical scene stacks.
- Double-clicking a browse-grid photo exits browse mode and opens that photo in
  normal view mode.
- Double-clicking from browse mode always returns to single-pane fit view.
- For a normal non-scene photo, the left strip selects that exact photo after
  browse-mode exit.
- For a photo inside a detected scene, the left strip selects the scene cover
  photo while the horizontal scene strip selects the exact photo opened.
- If a photo already had remembered manual zoom before entering browse mode,
  the user can return to that manual view after browse-mode exit by pressing
  `Space` again from fit view.

#### 8.1.5. Scene Detection And Scene-Oriented Navigation

- Scene detection runs asynchronously and uses the progress overlay/busy state.
- While the overlay is active:
  - interaction is disabled
  - assignment actions are disabled
  - keyboard shortcut handlers are effectively blocked
- On successful scene detection:
  - the left strip is rebuilt as scene stacks
  - the browse grid is rebuilt
  - the horizontal scene strip is rebuilt for the current scene
  - stale manual scene-edit undo/redo entries are cleared while ordinary
    metadata assignment history is preserved
- If scene detection finishes while the user is in browse mode:
  - browse mode is exited
  - the current photo remains selected
  - the main viewer is forced to fit view
- If scene detection finishes while the user is already in normal split view:
  - split view is preserved
  - the right-pane manual zoom is preserved
  - the scene strip appears without collapsing back to single-pane mode
- Left/right arrow shortcuts navigate within the current scene via the
  horizontal scene strip.
- Up/down key handling in `SceneListWidget` moves the left-strip scene-stack
  selection globally.

#### 8.1.6. Visible-Region Overlay Behavior

- While the main viewer is in manual zoom, the active strip thumbnail shows the
  current visible region with:
  - a darkened mask outside the visible region
  - a red edge around the visible region
- In non-scene mode, the visible-region overlay belongs on the active item in
  the left thumbnail strip.
- In scene mode, the visible-region overlay belongs on the horizontal
  `scene_list`, not on the left scene-stack strip.
- Browse mode never shows the visible-region overlay on browse-grid items.
- Returning to fit view clears the overlay.
- Re-entering manual view restores the corresponding overlay geometry for the
  current photo.

#### 8.1.7. Metadata And Assignment Behavior

- The top metadata label and thumbnail metadata badges show rating, color
  label, and pick/reject state together.
- The menu bar includes `Assign to Photo` with rating, color-label, and flag
  assignment actions for the current selection.
- Shortcut-backed assignment coverage includes:
  - ratings: `1`-`5`, clear with `0`
  - color labels: red/yellow/green/blue with `6`-`9`, clear with `` ` ``
  - flags: pick/reject/clear with `P`, `X`, `U`
- `Assign to Photo > Color Label > Purple` exists without a keyboard shortcut.
- `Ctrl+Z` and `Ctrl+Y` undo and redo metadata assignment batches.
- In compare mode, metadata shortcuts and assignment menu actions target only
  the active compare pane, not every compared photo or the hidden restore
  selection.
- Metadata changes write immediately through `library.save_metadata()`.
- Metadata-only refreshes preserve the current scroll position in the left
  thumbnail strip and browse grid. Explicit multi-selection (more than one
  selected item) is restored after repopulation; single-item selection is left
  to `setCurrentRow` in the populate methods so it integrates cleanly with Qt's
  selection model and does not create sticky selection state.
- Navigating within the scene strip without Shift/Ctrl gives the left thumbnail
  strip a clean single-item selection (the scene cover). Only Shift/Ctrl
  navigation preserves accumulated thumbnail selection across scene-strip
  moves.
- Clearing all assigned metadata for a photo removes that photo's persisted
  entry from `easy-cull.json`.
- When scene stacks are shown in the left strip:
  - the displayed scene label is `FIRST...LAST` when a scene contains more than
    one photo
  - the stack badge shows the number of photos in that scene
  - metadata text is hidden for stacked scene items
  - a scene stack is visually treated as rejected only when every photo in that
    multi-photo scene is rejected

#### 8.1.8. Organizer And XMP Workflow Behavior

- The top bar and File menu include `Organize Photos`, and the window shortcut
  is `Ctrl+Shift+E`.
- `Organize Photos` opens a dialog with two mutually exclusive modes:
  `Reorganize Files` and `Write XMP`.
- Reorganize mode supports:
  - criterion: picked/rejected, color label, or rating
  - action: copy or move
  - output parent selection
  - optional inclusion of untagged photos under `Untagged`
  - conflict policies `fail`, `skip`, and `overwrite`
- Write XMP mode supports merge policies `preserve` and `replace`.
- Long-running organizer, XMP, and undo work runs off the UI thread through
  `OperationWorker` and `QThread`, using the same busy/progress overlay model
  as scene detection.
- While the overlay is active:
  - interaction is disabled
  - assignment actions are disabled
  - organizer entry points are disabled
- Successful move-based reorganization reloads the current folder before the
  finished dialog is shown.
- Successful XMP writing does not reload the current folder.
- Completed organizer/XMP runs show a summary dialog with an immediate `Undo`
  action when an undo plan is available.
- Successful undo reloads the current folder and then shows confirmation.

Keep these expectations intact unless intentionally redesigning the UI:

- Browse mode shows all individual photos as a grid, even when the view-mode
  left strip is showing scene stacks.
- View mode is the vertical thumbnail strip, optional horizontal scene strip,
  and either a single-pane viewer or split view with fit-left and zoom-right
  panes.
- Compare mode is the side-by-side selected-photo grid entered with `C`; it
  caps display at the configured compare limit but preserves the full original
  selection when returning to browse or the previous mode. `Space` opens the
  active compared photo alone for fit/100% inspection, while `Z` performs the
  all-pane compare zoom in the grid and toggles fit/100% in selected-photo
  compare view. The default compare limit is 8, configurable from
  `Compare > Limit` with options 2, 3, 4, 6, 8, 10, 12, 16, and 20.
- When `Show AF point` is checked, the main viewer shows the fixed-size red AF
  point marker in fit view, manual/focus zoom, and both split-view panes.
- Pressing `I` toggles the viewer info overlay for the current normal-view
  photo. It shows load-time EXIF display rows and an RGB histogram when
  available, and is hidden during browse mode, compare mode, and busy/progress
  workflows.
- First-time manual/focus zoom starts at the extracted AF point. Remembered
  per-photo zoom/pan state takes priority.
- While the main viewer is in manual zoom, the active strip thumbnail shows the
  current visible region with a red box and a darkened mask outside the box.
- In scene mode, that visible-region overlay belongs on the horizontal
  `scene_list`, not on the left scene-stack strip.
- Scene detection progress disables interaction through the overlay/busy state.
- Organizer, XMP, and undo progress also disable interaction through the
  overlay/busy state.
- When scene detection finishes in view mode, the scene strip may appear
  without forcing split view back to single-pane mode.
- The top metadata label and thumbnail metadata badges show ratings, color
  labels, and pick/reject state together.
- The menu bar includes `Assign to Photo` with rating, color-label, and flag
  assignment actions for the current selection.
- In compare mode, the active pane is the current selection for assignment.
- Metadata changes write immediately through `library.save_metadata()`.
- Metadata assignment undo/redo uses `Ctrl+Z` / `Ctrl+Y` and preserves the
  usual selection refresh behavior.
- Metadata-only tagging refreshes must not cause implicit scroll jumps in the
  thumbnail strip or browse grid.
- Keyboard shortcuts are part of the product behavior, not incidental
  implementation.

Current shortcut coverage in code includes:

- `Ctrl+O`: open folder
- `Ctrl+D`: detect scenes
- `Ctrl+Shift+E`: open the organizer/XMP dialog
- `Ctrl+Shift+M`: merge selected photos into a scene
- `1`-`5`, `0`: rating changes
- `6`-`9`: red/yellow/green/blue color labels
- `` ` ``: clear color label
- `P`, `X`, `U`: picked/rejected/clear flag
- `Ctrl+Z`, `Ctrl+Y`: undo/redo metadata assignment batches
- `G`: enter browse mode
- `C`: enter compare mode
- `Esc`: exit compare mode and restore the prior selection/view state
- `F`: toggle the `Show AF point` overlay
- `I`: toggle the normal-view EXIF and RGB histogram overlay
- `Space`: exit browse mode into fit-to-window view mode, promote split view
  into full zoom, toggle focus zoom while already in single-pane view mode, or
  open/toggle the active photo in compare mode
- `Z`: mirror `Space` in view mode, toggle all compare-grid panes between fit
  view and AF-centered 100% zoom, or toggle the selected compare photo between
  fit view and 100% zoom
- `\`: toggle split view while in view mode
- `-`, `=`, `+`: zoom
- `W`, `A`, `S`, `D`: pan the active zoomed view
- left/right arrows: scene navigation in view mode; active-pane navigation in
  compare mode
- up/down arrows: active-pane navigation in compare mode

Additional assignment-menu behavior:

- `Assign to Photo > Color Label > Purple` exists without a keyboard shortcut.
- `Assign to Photo` actions are disabled while the progress overlay/busy state
  is active.

## 9. Testing Guidance By Change Type

- If you change metadata parsing or persistence:
  - update or extend the normalization/serialization tests
  - preserve the `color_label` field and allowed values unless the product
    requirement changes
  - preserve the stem-based JSON contract unless the product requirement
    changes
- If you change RAW rendering:
  - verify the distinction between embedded-thumbnail previews and full
    postprocessed renders
- If you change focus-point extraction:
  - make the change in `easy_cull/core/autofocus_points/`, keeping
    `easy_cull/core/exif.py` as the compatibility re-export layer
  - add new brand-specific extraction under
    `easy_cull/core/autofocus_points/brands/` and register it in the brand
    extractor order in `autofocus_points/extraction.py`
  - add targeted tests under `tests/core/autofocus_points/` for the metadata
    keys, brand detection, orientation handling, and fallback behavior you
    touched
  - validate against representative sample folders non-mutatingly when they are
    available
  - for Pentax DSLR point-id metadata, preserve the central-layout
    approximation unless new ground-truth samples justify changing the mapping
- If you change ExifTool resolution or invocation:
  - test `EASY_CULL_EXIFTOOL`, bundled PyInstaller lookup, and system `PATH`
    fallback behavior
  - preserve the missing/failing-ExifTool fallback to empty metadata
  - preserve Windows hidden-console subprocess options for GUI builds
- If you change app identity, icon assets, or PyInstaller packaging:
  - update `README.md` build/distribution guidance and this file
  - update or extend tests under `tests/scripts/` and `tests/ui/test_app.py`
  - keep `pyproject.toml` package-data entries aligned with assets under
    `easy_cull/ui/assets/`
  - verify the platform artifact shape: macOS ships `dist/EasyCull.app`, while
    Windows default distribution ships the whole `dist\EasyCull\` folder unless
    `--onefile` is used
- If you change scene detection:
  - test grouping behavior, not just helper functions
  - preserve ordering assumptions based on capture time
- If you change `MainWindow` selection/display logic:
  - verify which preview kind is requested
  - verify action shortcuts and enable/disable states where relevant
  - verify metadata text/markup still reflects rating, color label, and flag
    state
  - verify menu-triggered assignment produces the same result as the
    corresponding keyboard shortcut for each rating, color label, and flag
  - verify the `Assign to Photo` menu structure, action labels, and shortcut
    presence (in particular, Purple remains the only color label without a
    keyboard shortcut)
  - verify browse-mode entry/exit and selection synchronization when scene
    detection is active
  - verify browse-to-view transitions restore fit-to-window display while view
    mode still remembers the last manual zoom for the same photo
  - verify the `Show AF point` top-bar checkbox default, shortcut, and
    propagation to the single and split viewer panes when viewer behavior
    changes
  - verify AF point marker visibility in fit view, manual/focus zoom, and both
    split-view panes when marker behavior changes
  - verify the `I` info overlay toggles only in eligible normal view state,
    follows current-photo changes, hides during browse/compare/busy states, and
    remains readable when the viewer is resized
  - verify first-time focus zoom uses the AF point while remembered manual zoom
    remains higher priority
  - verify scene-detection completion preserves split view in normal view mode
    but still exits browse mode back to fit view
  - verify metadata refreshes preserve scroll position when the user tags
    photos in the thumbnail strip or browse grid
  - verify vertical thumbnail-strip Shift range selection releases rows outside
    the anchor-to-current range when the user reverses direction
  - verify scene merge selection resolution across the vertical thumbnail strip
    and horizontal scene strip: full horizontal-scene selection may merge with
    selected vertical stacks, but partial horizontal-scene selection remains
    blocked as an attempted split
  - verify that tagging a single photo in the scene strip does not cause sticky
    selection: navigating away after tagging should show only the navigated-to
    photo as selected, and subsequent tagging should apply to only that photo
  - verify that multi-selection tagging (Shift/Ctrl) still applies to all
    selected photos and preserves the extended selection after the refresh
- If you change organizer, XMP, or undo behavior:
  - test the dialog defaults and typed option mapping when UI-facing behavior
    changes
  - test copy-vs-move, conflict-policy, and sidecar-handling behavior for file
    organization changes
  - test preserve-vs-replace behavior plus malformed-sidecar failures for XMP
    changes
  - verify undo restores files and existing sidecars correctly and remains
    single-use
  - verify move-based completion reloads the folder while XMP completion does
    not
  - verify busy-state disabling and finished/error dialog titles still match
    the workflow being run
- If you change thumbnail visible-region overlay rendering:
  - preserve the normalized visible-region geometry contract from
    `PhotoViewer.visible_region_rect()`
  - verify the overlay still appears only for the active strip thumbnail in
    manual zoom
  - verify the left scene-stack strip stays overlay-free while scene mode uses
    the horizontal `scene_list`
  - prefer a render-to-image widget test when checking mask opacity, edge
    color, or other paint details

## 10. Editing Guidance

- Limit line length to 79 characters for Python code, docstrings, and inline
  comments (except for unbreakable lines and inline suppression of
  linters/formatters).
- Name functions and methods with verb phrases, and name classes with noun
  phrases.
- Prefer small, surgical changes. This repo still has a lot of behavior packed
  into `ui/main_window/` and the core loading/preview pipeline, so broad
  refactors can create regressions quickly.
- Read the affected method end-to-end before patching; several UI methods
  coordinate through shared mutable state such as `current_photo_id`, `_busy`,
  `_scene_thread`, and `scene_detection_done`.
- Keep README and tests aligned with any user-visible behavior change.
- After any UI, UX, feature, or bug-fix change, update `AGENTS.md` to reflect
  the new behavior (sections 8 and 9 in particular) and add an entry to
  `CHANGELOG.md` under `[Unreleased]`.
- When adding inline comments, explain both what the line or block is doing and
  why that line or block is necessary. Prefer this for non-obvious control
  flow, state preservation, timing, or framework behavior; avoid comments that
  only restate obvious code.
- When adding or materially changing a test, include a docstring or nearby
  comment that states what behavior the test verifies and why the test is
  necessary, especially for regression tests covering subtle UI state,
  threading, focus, or timing behavior.
- When multiple tests differ only by inputs and expected outputs for the same
  behavior, prefer `pytest.mark.parametrize` with clear case IDs instead of
  copying near-identical test bodies.
- When adding a feature, decide first whether it belongs in `PhotoLibrary` or
  in the UI layer. Business logic should usually land in `PhotoLibrary`, not in
  widget code.

## 11. Practical Pitfalls

- Do not assume EXIF metadata is always present.
- Do not assume every grouped photo has both JPEG and RAW; either can exist
  alone.
- Do not break the distinction between `preview_source` and `metadata_source`.
- Do not silently change the metadata filename or on-disk shape.
- Be careful with UI tests: `MainWindow.showEvent()` auto-triggers the folder
  chooser only when the window is shown and no folder is loaded. Tests that
  instantiate the window without showing it avoid that path.
