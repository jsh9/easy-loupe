# Change Log

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
