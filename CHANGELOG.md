# Change Log

## [Unreleased]

- Added
  - Left-mouse drag-to-pan support in manual zoom mode, allowing users to pan
    photos by holding the left button and dragging (affects split-view right
    panel and single-pane manual zoom mode)
- Changed
  - Increased split-view separation line thickness from 3 to 6 pixels

## [0.1.4] - 2026-05-23

- Added
  - Compare mode for selected photos with configurable limits, adaptive grids,
    active-pane tagging, synchronized zoom/pan, live grid refreshes, and
    transient in-mode guidance
  - Native `About EasyCull` menu item and dialog showing branded app details
    plus the installed package version
- Changed
  - PyInstaller build commands now copy EasyCull package metadata so packaged
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
  - Packaged EasyCull icon assets and runtime app identity setup so the app
    name and icon are applied through Qt and native platform surfaces where
    supported
  - Bundled ExifTool payload support for packaged macOS and Windows builds,
    with runtime lookup through `EASY_CULL_EXIFTOOL`, bundled app resources,
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
    EasyCull after the app loses focus, fixing unwanted focus stealing during
    AltTab switching (#1)
- Added
  - Regression tests covering inactive-window focus restoration and ensuring
    navigation focus restoration does not call `activateWindow()` or `raise_()`
