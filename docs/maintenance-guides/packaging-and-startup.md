# Packaging And Startup

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Build Artifacts](#1-build-artifacts)
- [2. App Identity And Assets](#2-app-identity-and-assets)
- [3. Startup Routing](#3-startup-routing)
- [4. macOS Folder Access](#4-macos-folder-access)
- [5. Verification Pointers](#5-verification-pointers)

______________________________________________________________________

<!--TOC-->

This guide covers packaging, application identity, direct-file-open startup,
and platform access behavior. Keep user-facing build instructions in
`README.md` aligned with changes here.

## 1. Build Artifacts

Primary files:

- `scripts/build_app/build_app_macos.py`
- `scripts/build_app/build_app_windows.py`
- `scripts/build_app/common.py`
- `tests/scripts/`
- `README.md`

Major logic:

- PyInstaller is a dev dependency. Build on the target operating system rather
  than cross-compiling app bundles.
- Build macOS with `uv run python scripts/build_app/build_app_macos.py`. The
  distributable artifact is `dist/EasyLoupe.app`.
- For macOS distribution, ship `dist/EasyLoupe.app`. If PyInstaller also leaves
  `dist/EasyLoupe/` beside it, that sibling one-folder output is not needed by
  users receiving the `.app`.
- A simple macOS zip can be produced with
  `ditto -c -k --keepParent dist/EasyLoupe.app EasyLoupe-macos.zip`.
- Build Windows with `uv run python scripts/build_app/build_app_windows.py`.
  The default output is the one-folder app `dist\EasyLoupe\`; distribute the
  whole folder, not just `EasyLoupe.exe`.
- Windows also supports
  `uv run python scripts/build_app/build_app_windows.py --onefile` for a
  movable single executable and `--console` for startup-debug builds.
- Both build scripts support `--diagnose`; use it to print Python, PySide6,
  PyInstaller, Qt, shiboken, and bundled ExifTool diagnostics for the built
  artifact.
- The build scripts stage official ExifTool payloads under ignored `build`
  cache/staging directories and bundle them under
  `easy_loupe/vendor/exiftool/...` inside the PyInstaller artifact. Do not
  commit downloaded ExifTool payloads.

## 2. App Identity And Assets

Primary files:

- `easy_loupe/ui/identity.py`
- `easy_loupe/ui/assets/`
- `easy_loupe/ui/app.py`
- `pyproject.toml`
- `tests/ui/test_app.py`

Major logic:

- `ui/identity.py` owns the user-facing app name, packaged icon lookup, Qt app
  identity, and best-effort macOS process/app-switcher identity hooks.
- Keep package-data configuration aligned when adding or renaming assets under
  `easy_loupe/ui/assets/`.
- The active app icon artifacts are committed as `EasyLoupe.png`,
  `EasyLoupe.ico`, `EasyLoupe.icns`, and `EasyLoupe.svg`. Regenerate them
  together from the approved source artwork so runtime Qt identity, Windows
  packaging, and macOS packaging use the same visual.
- For macOS document-open behavior, keep the bundle identifier stable
  (`com.easyloupe.EasyLoupe`) and keep the signed app valid after Info.plist
  changes.

## 3. Startup Routing

Primary files:

- `easy_loupe/ui/app.py`
- `easy_loupe/ui/photo_viewer/window.py`
- `easy_loupe/ui/photo_viewer/workers.py`
- `easy_loupe/ui/launch.py`
- `tests/ui/test_app.py`
- `tests/ui/photo_viewer/test_window.py`
- `tests/ui/test_workers.py`

Major logic:

- `StartupCoordinator` resolves argv, queued macOS `FileOpen`, and live
  system-open events before asking `WindowManager` to create windows.
- On macOS, Finder may launch EasyLoupe before delivering the matching
  `FileOpen` event. Startup briefly resolves launch intent before creating a
  normal no-file culling window, so photo-open launches do not also create a
  hidden culling window with a folder chooser.
- Multiple system-opened photos create multiple independent EasyLoupe windows.
  Each photo-viewer window owns its own `MainWindow`, `PhotoLibrary`,
  background workers, folder hydration, close lifecycle, title, and mode state.
- Photo-viewer background hydration may prepare a recursive culling library,
  but it must not replace standalone viewer navigation. See
  [Recursive Loading](recursive-loading.md) for that handoff boundary.

## 4. macOS Folder Access

Primary files:

- `easy_loupe/ui/folder_access.py`
- `easy_loupe/ui/photo_viewer/window.py`
- `scripts/build_app/build_app_macos.py`
- `tests/ui/photo_viewer/test_window.py`

Major logic:

- macOS folder access is controlled by TCC, Apple's Transparency, Consent, and
  Control privacy database.
- EasyLoupe's own `QSettings` approved-root list only records product intent.
  Real access to protected folders such as `~/Desktop`, `~/Documents`,
  `~/Downloads`, and File Provider roots under
  `~/Library/CloudStorage/<provider>` comes from the macOS TCC/File Provider
  prompt, a native file/folder chooser, or manual Full Disk Access.
- Denied access should leave the standalone photo viewer usable for the opened
  photo instead of failing the window outright.

## 5. Verification Pointers

- If you change app identity, icon assets, or PyInstaller packaging, update
  `README.md` build/distribution guidance and this guide.
- Update or extend tests under `tests/scripts/` and `tests/ui/test_app.py`.
- Verify the platform artifact shape: macOS ships `dist/EasyLoupe.app`, while
  Windows default distribution ships the whole `dist\EasyLoupe\` folder unless
  `--onefile` is used.
- Verify macOS photo document type registration and protected-folder privacy
  strings when changing direct-file-open behavior.
- If you change photo-viewer startup or handoff behavior, test argv, live
  system-open events, and queued macOS `FileOpen` events.
- Verify multiple opened photos create independent photo-viewer windows.
- Verify `G` and `Enter` wait for folder hydration when needed, then open
  culling mode for the current photo.
- Verify photo-viewer-to-culling handoff opens the culling window on the same
  monitor as the photo-viewer window.
- Verify worker signals are routed back to the GUI thread before UI state is
  rebuilt.
- If you change macOS folder-access behavior, test protected-folder roots, File
  Provider roots under `~/Library/CloudStorage`, chooser fallback, denied
  access, and remembered approved roots.
