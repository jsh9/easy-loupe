# Change Log

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
- Full diff
  - https://github.com/jsh9/easy-cull/compare/17dc35d692cf45990fd3b1a2decf2f8a83c6e7a3...18c2a5ee4d5fd76eb00f10c53066fceeb91c7795

## [0.1.1] - 2026-05-18

- Fixed
  - Prevented deferred navigation-focus restoration from activating or raising
    EasyCull after the app loses focus, fixing unwanted focus stealing during
    AltTab switching (#1)
- Added
  - Regression tests covering inactive-window focus restoration and ensuring
    navigation focus restoration does not call `activateWindow()` or `raise_()`
- Full diff
  - https://github.com/jsh9/easy-cull/compare/3ad430e5e29c17f58687fa657f20dbf5cff48b13...17dc35d692cf45990fd3b1a2decf2f8a83c6e7a3
