# Change Log

## [Unreleased]

- Changed

  - Long-running progress overlays now show granular counted stages for folder
    loading, hydration, scene detection, organization, XMP writing, and undo
    workflows.
  - Folder metadata loading now sends one primary ExifTool source per grouped
    photo, falls back to companion previews only when needed, and reports
    explicit EXIF batch counts in the progress overlay.

- Fixed

  - Folder-loading EXIF reader injection remains compatible with one-argument
    readers, and progress counts now advance after preview-backed work
    completes.
  - Scene and operation progress overlays no longer flicker between scalar
    progress bars and structured stage rows.
  - Scene detection completion no longer briefly replaces structured progress
    rows with the scalar progress bar while rebuilding scene lists.
  - Folder-load EXIF progress now shows the photos-per-batch detail in the
    metadata row label beside the batch progress bar.
  - Failed ExifTool batches now split and retry smaller chunks so one bad file
    no longer drops EXIF metadata for the rest of the configured batch.
  - Stopped ExifTool reads no longer report skipped batches as completed, and
    later progress stages preserve the last completed EXIF batch count.
  - Partially completed primary ExifTool reads no longer start preview fallback
    reads.
  - Folder-loading EXIF reader wrappers that accept `**kwargs` now preserve
    callback-aware stopped-batch progress instead of being treated as legacy
    readers.
  - Scene and operation workers remain compatible with legacy progress-only
    callables while still supporting structured progress snapshots.
  - Empty progress stages now render as complete status-only rows instead of
    showing incomplete `0 of 0` progress bars.
  - Direct empty-folder loader progress now completes the zero-work photo list
    stage instead of leaving it active.
  - Empty undo plans now emit completed zero-work progress before cleanup.

## [1.1.3] - 2026-06-07

- Added

  - Visible-region minimaps now pan zoomed photos: click to recenter the red
    box, or drag it with edge/corner clamping.
  - In manual zoom, clicking another strip thumbnail's image now opens that
    photo at the clicked relative position and can continue panning while the
    mouse button remains held.

- Fixed

  - Exiting compare mode now realigns the main viewer, vertical strip focus,
    and visible-region overlay to the active compare photo before Space enters
    focus zoom.
  - Closing culling or standalone photo-viewer windows while background work is
    active now defers native Qt teardown until tracked thread-slot cleanup has
    finished.

- Changed

  - Moved feature-level maintenance notes out of `AGENTS.md` and into dedicated
    maintenance guides under `docs/maintenance-guides/`

## [1.1.2] - 2026-06-06

- Fixed

  - Standalone photo-viewer folder hydration no longer expands viewer
    navigation into subfolders; recursive hydration is kept for culling handoff
    only
  - Saved metadata and scene groups now preserve dotted photo IDs such as
    `IMG.0001` instead of treating the final dotted segment as an extension
  - Recursive folder loading no longer groups photos from case-distinct
    subfolders such as `Trip/IMG_1000` and `trip/IMG_1000`
  - Confirmed `Include subfolders` reloads that find no eligible direct-child
    photos now show the `No Eligible Photos` dialog

## [1.1.1] - 2026-06-06

- Fixed

  - Breaking a scene into individual photos from the context menu no longer
    leaves keyboard navigation and viewer shortcuts inert until the next mouse
    click
  - Breaking a visible scene stack now preserves the vertical thumbnail strip
    position instead of jumping the first split photo to the bottom of the
    viewport

## [1.1.0] - 2026-06-06

- Added

  - Folder loading now includes subfolders by default and has a persisted
    `Include subfolders` toggle next to `Open Folder` in the top bar
  - Empty manual folder loads now show a `No Eligible Photos` dialog when the
    selected folder contains no supported photos for the active scan mode

- Changed

  - `easy-loupe.json` now stores subfolder photos with folder-relative POSIX
    photo IDs such as `subfolder_1/IMG_1234`, while root-folder photos keep
    flat IDs such as `IMG_5678`
  - Reorganizing photos and writing shared XMP sidecars now preserve relative
    subfolder paths so same-named photos in different folders do not collide

## [1.0.5] - 2026-06-04

- Fixed

  - In culling scene mode, red visible-region boxes now stay visible on the
    horizontal scene strip and on the vertical scene-stack strip when the
    current photo is the scene cover

## [1.0.4] - 2026-06-04

- Fixed

  - Standalone photo-viewer fast navigation no longer requests early EXIF
    worker-thread shutdown while a previous EXIF refresh may still be running,
    reducing the risk of native Qt/PySide teardown crashes when navigating
    photos very rapidly

## [1.0.3] - 2026-06-04

- Changed

  - The AF point marker now starts hidden by default in culling and standalone
    photo-viewer modes; press `F` or use `Show AF point` in culling mode to
    show it

## [1.0.2] - 2026-06-03

- Added

  - `Shift+F` now temporarily recenters the active manual zoom view on the
    photo's AF point or image center, and pressing it again restores the
    remembered manual center when one exists
  - `Ctrl+Shift+F` now resets remembered zoom centers to each photo's AF point
    or image center while preserving remembered zoom levels across culling and
    standalone photo-viewer navigation

## [1.0.1] = 2026-06-01

- Changed
  - Renamed/rebranded `EasyCull` into `EasyLoupe` because now this app is no
    longer just a photo culling tool, but also a photo viewer

## [1.0.0] - 2026-06-01

- Adds a direct-file-open photo viewer for photos launched from Finder,
  Explorer, or argv. The viewer opens the selected photo immediately, hydrates
  the surrounding folder in the background when access is available, supports
  adjacent-photo navigation, EXIF and histogram display, AF-point loading,
  zoom/pan inspection, transient status messages, and `G` / `Enter` handoff
  into the full culling workspace.
- Startup routing now distinguishes plain app launches from file-open launches,
  including macOS `FileOpen` events that arrive shortly after Finder starts the
  app. Multiple opened photos create independent photo-viewer windows, and
  photo-viewer-to-culling handoff keeps the culling window on the viewer's
  monitor.
- Folder loading and previews now support HEIC/HEIF plus a broader set of RAW
  extensions. JPEG remains the preferred preview source when grouped with other
  formats, HEIF is preferred over slower RAW rendering when no JPEG is present,
  and shared EXIF/file-size display rows cover JPEG, HEIF, and RAW members of a
  photo group.
- macOS photo-viewer startup now has explicit protected-folder access handling
  for Desktop, Documents, Downloads, and File Provider cloud-storage roots. It
  uses native TCC/File Provider prompts where possible, falls back to a folder
  chooser for other inaccessible roots, and keeps denied-access launches in a
  usable single-photo viewer instead of failing the window outright.
- macOS packaging now registers EasyLoupe as a photo document viewer and adds
  the privacy usage strings needed for protected-folder access.
- Internally, file-open photo viewing is separated from the main culling window
  with dedicated worker and folder-access modules, plus shared viewer-window
  shortcut, overlay, and screen-resolution helpers.

## [0.2.3] - 2026-05-30

- Fixed
  - Scene groups
    - `Ctrl+Shift+M` now merges selected vertical scene stacks with a fully
      selected horizontal scene strip instead of treating that full-strip
      selection as a no-op
    - Partial horizontal scene-strip selections remain blocked as attempted
      scene splits, even when vertical scene stacks are also selected
  - Vertical thumbnail-strip `Shift+Up` / `Shift+Down` range selection now
    releases rows outside the current anchor-to-current range when reversing
    direction

## [0.2.2] - 2026-05-29

- Added
  - EXIF and RGB histogram viewer overlay toggled with `I`

## [0.2.1] - 2026-05-27

- Added
  - A new feature to sort photos by file name or EXIF capture time, and a
    toggle to reverse the photos' order

## [0.2.0] - 2026-05-25

- Added
  - Manual scene merging
    - Manual scene editing with `Scenes > Merge Selected Photos into Scene`
      (`Ctrl+Shift+M`) and context-menu actions to break a multi-photo scene
      into individual photos
    - Undo/redo support for manual scene merge and break actions through the
      existing metadata history shortcuts
    - Scene groups are saved in `easy-loupe.json` and restored when the folder
      is loaded again
  - Compare mode can open the active photo alone with `Space`, toggle that
    photo between fit and 100%, return to the grid with `Esc`, and use `Z` for
    the previous all-photo compare zoom or selected-photo fit/100% zoom
  - Left-mouse drag-to-pan support in manual zoom mode, allowing users to pan
    photos by holding the left button and dragging (affects split-view right
    panel and single-pane manual zoom mode)
- Changed
  - Scene groups
    - Folder metadata now uses a top-level `photos` object for per-photo
      ratings, labels, and flags, plus an optional top-level `scenes` object
      for saved scene groups
    - Running scene detection when scenes already exist now prompts before
      replacing the saved groups
  - Increased split-view separation line thickness from 3 to 6 pixels
- Fixed
  - Scene groups
    - Scene detection now clears stale manual scene-edit undo/redo entries so
      `Ctrl+Z` cannot restore an older scene layout over newly detected scenes
    - Invalid saved scene groups that contain no current photo IDs no longer
      make a folder appear to have scene detection completed
    - Browse-mode scene edits now restore keyboard focus to the browse grid
      after merge, break, undo, or redo rebuilds the scene lists
  - Selected-photo compare view now keeps the correct internal zoom state for
    small photos that already display at 100% in fit-to-window mode: pressing
    `Space` or `Z` advances the state as
    `fit 100% -> 100% inspection -> fit 100%`, even though users will not see a
    visual scale change in that case
  - Tagging a photo in the horizontal scene strip no longer causes sticky
    selection; navigating away after tagging now shows only the navigated-to
    photo as selected and subsequent tags apply to only that photo

## [0.1.4] - 2026-05-23

- Added
  - Compare mode for selected photos with configurable limits, adaptive grids,
    active-pane tagging, synchronized zoom/pan, live grid refreshes, and
    transient in-mode guidance
  - Native `About EasyLoupe` menu item and dialog showing branded app details
    plus the installed package version
- Changed
  - PyInstaller build commands now copy EasyLoupe package metadata so packaged
    apps can resolve and display the installed version

## [0.1.3] - 2026-05-20

- Added
  - Temporary click-and-hold 100% zoom for fit-to-window photo views, including
    drag panning while the left mouse button is held
  - Split-view support for click-and-hold inspection in the left fit-to-window
    pane without changing the right zoomed pane
- Fixed
  - Preserved remembered manual zoom state when using temporary click-and-hold
    inspection

## [0.1.2] - 2026-05-19

- Added
  - Native PyInstaller build scripts for macOS and Windows, including shared
    build helpers, diagnostic modes, and Windows `--onefile` / `--console`
    build options
  - Packaged EasyLoupe icon assets and runtime app identity setup so the app
    name and icon are applied through Qt and native platform surfaces where
    supported
  - Bundled ExifTool payload support for packaged macOS and Windows builds,
    with runtime lookup through `EASY_LOUPE_EXIFTOOL`, bundled app resources,
    then system `PATH`
  - Packaging tests for build command construction and UI identity/icon assets
- Changed
  - Documented app-binary build, distribution, ExifTool, and packaging
    diagnostics in `README.md` and agent-facing build guidance in `AGENTS.md`
  - Added Python 3.12 to CI coverage and pinned the local project Python
    version to 3.12
- Fixed
  - Windows packaged GUI builds now launch ExifTool without flashing a console
    window during metadata reads

## [0.1.1] - 2026-05-18

- Fixed
  - Prevented deferred navigation-focus restoration from activating or raising
    EasyLoupe after the app loses focus, fixing unwanted focus stealing during
    AltTab switching (#1)
- Added
  - Regression tests covering inactive-window focus restoration and ensuring
    navigation focus restoration does not call `activateWindow()` or `raise_()`
