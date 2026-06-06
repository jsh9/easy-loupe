# Recursive Loading

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Folder Discovery And Scan Mode](#1-folder-discovery-and-scan-mode)
- [2. Folder-Relative Photo IDs And File Paths](#2-folder-relative-photo-ids-and-file-paths)
- [3. Metadata And Scene Migration](#3-metadata-and-scene-migration)
- [4. UI Preference And Reload Behavior](#4-ui-preference-and-reload-behavior)
- [5. Standalone Photo-Viewer Handoff](#5-standalone-photo-viewer-handoff)
- [6. Operations And Output Paths](#6-operations-and-output-paths)
- [7. Manual Verification Pointers](#7-manual-verification-pointers)

______________________________________________________________________

<!--TOC-->

Recursive loading lets culling-mode folder loads include supported photos from
subfolders while preserving stable folder-relative photo IDs. It is also tied
to metadata migration, organizer/XMP output paths, and the culling handoff from
standalone photo-viewer mode.

## 1. Folder Discovery And Scan Mode

Primary files:

- `easy_loupe/core/recursive_loading.py`
- `easy_loupe/core/folder_loading.py`
- `easy_loupe/core/photo_library.py`
- `tests/core/test_folder_loading.py`

Major logic:

- `PhotoLibrary.load_recursively` stores the active direct-vs-recursive scan
  preference. `PhotoLibrary.set_load_recursively(...)` normalizes raw values
  before the next folder load.
- `discover_photo_files(...)` performs the actual scan. Recursive scans walk
  subfolders with `os.walk(..., followlinks=False)` and prune symlinked
  directories so a selected folder cannot silently pull in files outside the
  selected root. Direct-only scans use only immediate child files.
- Folder scans sort discovered files by folder-relative POSIX path for stable
  ordering across platforms.
- Recursive grouping uses `relative_photo_group_key(...)`: it preserves the
  exact relative parent folder but case-folds the final stem. This keeps
  same-folder JPEG/RAW companion files grouped while preventing case-distinct
  folders such as `Trip/` and `trip/` from merging on case-sensitive
  filesystems.

## 2. Folder-Relative Photo IDs And File Paths

Primary files:

- `easy_loupe/core/recursive_loading.py`
- `easy_loupe/core/folder_loading.py`
- `easy_loupe/core/records.py`
- `tests/core/test_folder_loading.py`

Major logic:

- `relative_photo_id(folder, path)` creates the visible `PhotoRecord.photo_id`
  by removing the final file suffix from the folder-relative POSIX path.
- Root photos keep flat IDs such as `IMG_2000`; subfolder photos use IDs such
  as `subfolder/IMG_2000`, including on Windows.
- `PhotoRecord.files` stores folder-relative POSIX file paths with extensions.
  Code that needs concrete filesystem paths should resolve them through
  `resolve_relative_path(...)` rather than joining raw strings manually.
- `PhotoRecord.display_name` currently follows `photo_id`, so UI names expose
  the subfolder component for recursive photos.

## 3. Metadata And Scene Migration

Primary files:

- `easy_loupe/core/metadata.py`
- `easy_loupe/core/recursive_loading.py`
- `easy_loupe/core/folder_loading.py`
- `tests/core/test_metadata.py`

Major logic:

- Saved folder metadata lives in `easy-loupe.json` under top-level `photos` and
  optional `scenes` objects.
- `normalize_metadata_entries(..., valid_photo_ids=...)` and
  `normalize_scene_groups(...)` resolve persisted keys against the loaded photo
  IDs when possible. Exact current IDs win before legacy suffix stripping.
- This exact-first behavior is required for valid dotted stems such as
  `IMG.0001`. Without loaded-ID resolution, generic suffix stripping would
  shorten that ID to `IMG` and drop saved metadata or scene groups.
- Legacy metadata forms remain supported: filename keys with extensions are
  reduced to stems, Windows separators are normalized to `/`, and flag value
  `reject` becomes `rejected`.
- Folder loading builds photo records before applying saved metadata so
  migration can compare persisted keys to the concrete IDs discovered in the
  current folder.

## 4. UI Preference And Reload Behavior

Primary files:

- `easy_loupe/ui/main_window/build.py`
- `easy_loupe/ui/main_window/workflows.py`
- `easy_loupe/ui/main_window/presentation.py`
- `tests/ui/main_window/test_window.py`
- `tests/ui/main_window/test_workflows.py`

Major logic:

- The top-bar `Include subfolders` checkbox is grouped beside `Open Folder`. It
  persists to the `photos/load_recursively` `QSettings` key.
- Changing the preference while a folder is loaded asks for confirmation before
  reloading. Canceling the prompt restores the checkbox to the loaded library's
  existing setting.
- Confirmed reloads keep the previous photo selected when that photo still
  exists under the new scan mode; otherwise they fall back to the first loaded
  photo or to an empty idle state.
- If a confirmed reload succeeds but finds no eligible photos for the active
  scan mode, the normal `No Eligible Photos` dialog is shown after the UI is
  rebuilt and controls are restored.

## 5. Standalone Photo-Viewer Handoff

Primary files:

- `easy_loupe/ui/photo_viewer/window.py`
- `easy_loupe/ui/photo_viewer/workers.py`
- `easy_loupe/ui/launch.py`
- `tests/ui/photo_viewer/test_window.py`
- `tests/ui/test_workers.py`

Major logic:

- Standalone photo-viewer mode is scoped to the opened file's immediate folder.
  Background hydration must not replace the active viewer library or expand
  viewer navigation into subfolders.
- `FolderHydrationWorker` may prepare a culling-ready `PhotoLibrary` using the
  persisted culling recursive preference.
- `PhotoViewerWindow._handle_folder_hydration_finished(...)` stores that
  library in `_hydrated_library` only. It is handoff payload for `G` or
  `Enter`, not viewer navigation state.
- `CullingLaunchRequest.preloaded_library` carries the hydrated library into
  culling mode. Culling mode then reapplies its own persisted sort settings
  before rebuilding the main window lists.

## 6. Operations And Output Paths

Primary files:

- `easy_loupe/operations/common.py`
- `easy_loupe/operations/export.py`
- `easy_loupe/operations/xmp.py`
- `tests/operations/test_export.py`
- `tests/operations/test_xmp.py`

Major logic:

- `sidecar_path_for_photo(...)` writes shared XMP sidecars beside the source
  photo group. For subfolder photos, this means the sidecar is created inside
  the same subfolder.
- Organizer jobs resolve `PhotoRecord.files` through `resolve_relative_path`.
  Output buckets preserve source subfolder paths to avoid collisions between
  same-named files from different folders.
- Undo plans remain filesystem-based and should continue to describe the exact
  files created, moved, backed up, or removed by recursive operations.

## 7. Manual Verification Pointers

Useful manual scenarios:

- Open a folder with root and nested photos. Toggle `Include subfolders` off
  and confirm reload; nested photos should disappear and the current selection
  should remain valid.
- Open a folder containing only nested photos. Toggle `Include subfolders` off
  and confirm reload; the UI should become empty and show `No Eligible Photos`.
- Open a direct file from a folder that also has nested photos. Standalone
  viewer navigation should stay within the opened file's immediate folder, but
  `G` or `Enter` should hand off to recursive culling mode when the culling
  preference is enabled.
- Load metadata containing a dotted ID such as `IMG.0001`; the photo's saved
  rating, flag, color label, and scene membership should survive.
