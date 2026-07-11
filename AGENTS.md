# AGENTS.md

## 1. Purpose

This repository is a local desktop photo culling app for JPEG, HEIC/HEIF, and
RAW folders. It is organized around a small set of top-level packages:

- `easy_loupe/core/`: non-UI application logic for the photo library, records,
  EXIF, metadata, previews, and scene detection.
- `easy_loupe/ui/`: PySide6 desktop UI built around `PhotoLibrary`.
- `easy_loupe/analysis/`: scene-detection logic plus placeholder
  analysis-oriented feature modules.
- `easy_loupe/operations/`: concrete batch file-operation modules for photo
  organization, XMP sidecars, and undo support.

The codebase is small, but a lot of behavior is still concentrated in a few
large modules and packages. Read the relevant maintenance guide before editing;
avoid making UI or library changes based on assumptions.

Feature-level maintenance notes live under `docs/maintenance-guides/`:

- `docs/maintenance-guides/packaging-and-startup.md`
- `docs/maintenance-guides/previews-exif-autofocus.md`
- `docs/maintenance-guides/recursive-loading.md`
- `docs/maintenance-guides/tagging-metadata-operations.md`
- `docs/maintenance-guides/ui-workflows.md`

## 2. Working Setup

- Python target: `>=3.12` from `pyproject.toml`
- Default local Python from `.python-version`: `3.12`
- Preferred environment manager: `uv`
- Install dependencies: `uv sync`
- Install build/test/dev dependencies: `uv sync --extra dev`
- Launch the app: `uv run python -m easy_loupe`

### 2.1. Build Artifacts

- PyInstaller is a dev dependency. Build on the target operating system.
- macOS: `uv run python scripts/build_app/build_app_macos.py`
- Windows: `uv run python scripts/build_app/build_app_windows.py`
- Detailed artifact shape, ExifTool bundling, app identity, document-open, and
  macOS folder-access notes live in
  `docs/maintenance-guides/packaging-and-startup.md`.

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
- Alternate full-suite checks: `tox -e py312`, `tox -e ty`, `tox -e muff-lint`,
  `tox -e muff-format`, `tox -e pre-commit`
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

- `easy_loupe/core/`
  - Contains the non-UI implementation modules and packages: `photo_library`,
    `records`, `folder_loading`, `recursive_loading`, `exif`,
    `autofocus_points`, `metadata`, and `preview`.
  - `photo_library.py` defines `PhotoLibrary` and delegates folder loading,
    metadata persistence, previews, and scene detection to the lower-level
    modules.
  - `recursive_loading.py` owns direct-vs-recursive folder discovery and
    folder-relative POSIX photo IDs.
  - `autofocus_points/` owns AF/focus-point extraction. `exif.py` re-exports
    `extract_focus_point(...)` for compatibility, but new camera-brand-specific
    extraction logic belongs under `autofocus_points/brands/`.
  - `records.py` defines the shared constants plus the `PhotoRecord` and
    `SceneGroup` dataclasses.
- `easy_loupe/ui/`
  - Defines the full PySide6 UI: browse mode, single-pane and split view modes,
    theming, thumbnail widgets, viewer, scene strip, worker thread, and the
    main window.
  - `ui/app.py` owns application startup orchestration. `StartupCoordinator`
    resolves argv, queued macOS `FileOpen`, and live system-open events before
    asking `WindowManager` to create windows.
  - `ui/photo_viewer/` owns the lightweight direct-file-open photo viewer,
    background folder hydration, neighbor navigation, EXIF/focus loading, and
    culling-window handoff.
  - `ui/folder_access.py` owns macOS protected-folder and cloud-storage access
    prompts used by photo-viewer startup before scanning neighboring files.
  - `ui/launch.py` defines `CullingLaunchRequest`, the handoff payload used
    when a photo-viewer window opens the full culling workspace.
  - The UI is split primarily across `ui/main_window/`, `ui/viewers/`,
    `ui/photo_viewer/`, `ui/widgets.py`, `ui/theme.py`, `ui/workers.py`, and
    `ui/app.py`.
  - `ui/viewers/shell.py` contains shared viewer-window scaffolding such as
    zoom/pan shortcut wiring, progress/transient overlays, and screen
    resolution helpers for same-monitor handoff.
  - `ui/identity.py` owns the user-facing app name, packaged icon lookup, Qt
    app identity, and best-effort macOS process/app-switcher identity hooks.
  - `ui/assets/` contains packaged EasyLoupe icon assets used by Qt and the
    PyInstaller build scripts; keep package-data configuration aligned when
    adding or renaming assets.
- `easy_loupe/ui/main_window/`
  - Contains the `MainWindow` package: `window.py`, `build.py`, `workflows.py`,
    `navigation.py`, and `presentation.py`.
  - `MainWindow` remains the central stateful UI controller.
- `easy_loupe/ui/viewers/`
  - Contains `PhotoViewer`, `MainPhotoViewer`, shared viewer shell helpers, and
    `ExifOverlayWidget`.
- `easy_loupe/ui/photo_viewer/`
  - Contains `PhotoViewerWindow` and worker code for file-open photo viewer
    mode. It is intentionally separate from `MainWindow`; handoff into culling
    mode goes through `CullingLaunchRequest` and `WindowManager`.
- `easy_loupe/analysis/`
  - Contains the concrete `scenes.py` scene-detection implementation plus
    placeholder `quality.py` and `faces.py` modules for future work.
- `easy_loupe/operations/`
  - Contains concrete non-UI batch operations: `export.py` reorganizes tagged
    photo sets by metadata, `xmp.py` writes shared XMP sidecars, and
    `common.py` provides undo bookkeeping plus shared filesystem helpers.
- `easy_loupe/__main__.py`
  - Package module entry point that delegates to `easy_loupe.ui.app`.
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

## 5. Maintenance Guides And Product Contracts

Preserve product contracts unless the change intentionally redefines them and
tests/docs are updated accordingly. Feature-level invariants and verification
pointers are maintained in `docs/maintenance-guides/`; read the relevant
maintenance guide before editing behavior.

- Recursive folder loading, folder-relative photo IDs, metadata migration, and
  recursive operation paths: `docs/maintenance-guides/recursive-loading.md`
- Culling mode, standalone photo-viewer boundaries, browse/compare mode, scene
  workflows, zoom behavior, selection behavior, visible-region overlays, and
  shortcut contracts: `docs/maintenance-guides/ui-workflows.md`
- Metadata persistence, assignment actions, organizer/XMP workflows, and undo:
  `docs/maintenance-guides/tagging-metadata-operations.md`
- Preview cache semantics, HEIC/RAW dependencies, ExifTool behavior, and
  AF/focus-point extraction:
  `docs/maintenance-guides/previews-exif-autofocus.md`
- PyInstaller artifacts, app identity, document-open startup, and macOS folder
  access: `docs/maintenance-guides/packaging-and-startup.md`

## 6. External Dependencies And Runtime Assumptions

- `PySide6` powers the desktop UI.
- `Pillow`, `pillow-heif`, `rawpy`, `imagehash`, and `exiftool` support image
  loading, RAW/HEIF rendering, scene detection, and metadata extraction. See
  `docs/maintenance-guides/previews-exif-autofocus.md` for runtime behavior and
  fallback contracts.
- Packaged builds bundle ExifTool payloads. Source/development runs rely on
  `EASY_LOUPE_EXIFTOOL` or a system `exiftool`. See
  `docs/maintenance-guides/packaging-and-startup.md` for build artifact notes.

## 7. UI And Worker Boundaries

- `MainWindow` is the central stateful UI controller. Before modifying it, read
  `docs/maintenance-guides/ui-workflows.md` and trace the relevant method flow.
- Scene detection, photo-viewer hydration, organizer/XMP, and undo work run off
  the UI thread. Worker signals must be routed back to the GUI thread before
  list, viewer, or widget state is rebuilt.
- Do not connect worker-thread signals through lambdas that call UI-update
  methods directly.

## 8. Testing Guidance By Change Type

Use the maintenance-guide verification pointers for the area being changed:

- `docs/maintenance-guides/recursive-loading.md`
- `docs/maintenance-guides/ui-workflows.md`
- `docs/maintenance-guides/tagging-metadata-operations.md`
- `docs/maintenance-guides/previews-exif-autofocus.md`
- `docs/maintenance-guides/packaging-and-startup.md`

Keep tests focused on the behavior changed, and broaden coverage when touching
shared contracts, UI state transitions, threading, or filesystem operations.

## 9. Documentation Updates

- Keep `README.md` and tests aligned with any user-visible behavior change.
- After any UI, UX, feature, or bug-fix change, update the relevant maintenance
  guide in `docs/maintenance-guides/` and add an entry to `CHANGELOG.md` under
  `[Unreleased]`.
- Update this file only when contributor workflow, repository structure, or the
  maintenance-guide index changes.

## 10. Editing Guidance

- Limit line length to 79 characters for Python code, docstrings, and inline
  comments (except for unbreakable lines and inline suppression of
  linters/formatters).
- Name functions and methods with verb phrases, and name classes with noun
  phrases.
- Prefer small, surgical changes. This repo still has a lot of behavior packed
  into `ui/main_window/` and the core loading/preview pipeline, so broad
  refactors can create regressions quickly.
- Prefer modular, decoupled changes that keep new behavior isolated behind
  clear interfaces instead of spreading feature logic across unrelated modules.
- For big-ish new features, prefer creating a dedicated module for the feature
  and importing its components from existing modules. This helps keep existing
  modules focused and improves long-term modularity.
- After making changes, do not automatically stage or unstage files for the
  user. Leave index state untouched unless the user explicitly requests a git
  staging operation.
- Read the affected method end-to-end before patching; several UI methods
  coordinate through shared mutable state such as `current_photo_id`, `_busy`,
  `_scene_thread`, and `scene_detection_done`.
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
