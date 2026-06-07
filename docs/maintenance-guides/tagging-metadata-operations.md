# Tagging, Metadata, And Operations

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Metadata Persistence](#1-metadata-persistence)
- [2. Assignment Behavior](#2-assignment-behavior)
- [3. Organizer And XMP Workflows](#3-organizer-and-xmp-workflows)
- [4. Undo Behavior](#4-undo-behavior)
- [5. Verification Pointers](#5-verification-pointers)

______________________________________________________________________

<!--TOC-->

This guide covers rating/color/flag metadata, assignment UI behavior, organizer
output, shared XMP sidecars, and undo.

## 1. Metadata Persistence

Primary files:

- `easy_loupe/core/metadata.py`
- `easy_loupe/core/records.py`
- `easy_loupe/core/photo_library.py`
- `tests/core/test_metadata.py`

Major logic:

- Metadata is stored in `easy-loupe.json` inside the selected photo folder.
- Saved folder metadata uses a top-level `photos` object for per-photo entries
  and may include a top-level `scenes` object with `source` and `groups`.
- Saved metadata keys use the folder-relative visible stem format, for example
  `IMG_2000` or `subfolder/IMG_2000`, not `IMG_2000.JPG`.
- Valid dotted stems such as `IMG.0001` are current photo IDs and must be
  matched exactly before applying legacy extension-stripping migration.
- Legacy metadata forms remain supported: keys with extensions are reduced to
  stems, Windows separators are normalized to `/`, and flag value `"reject"`
  becomes `"rejected"`.
- Ratings are limited to integers `1..5` or `None`.
- Color labels are limited to `"red"`, `"yellow"`, `"green"`, `"blue"`,
  `"purple"`, or `None`.
- Flags are limited to `"picked"`, `"rejected"`, or `None`.
- Saved metadata entries may contain `rating`, `color_label`, and `flag`.
- Clearing all assigned metadata for a photo removes that photo's persisted
  entry from `easy-loupe.json`.

## 2. Assignment Behavior

Primary files:

- `easy_loupe/ui/main_window/window.py`
- `easy_loupe/ui/main_window/build.py`
- `easy_loupe/ui/main_window/presentation.py`
- `easy_loupe/ui/widgets.py`
- `tests/ui/main_window/`

Major logic:

- The top metadata label and thumbnail metadata badges show rating, color
  label, and pick/reject state together.
- The menu bar includes `Assign to Photo` with rating, color-label, and flag
  assignment actions for the current selection.
- Shortcut-backed assignment coverage includes ratings `1`-`5`, clear rating
  with `0`, red/yellow/green/blue labels with `6`-`9`, clear color label with
  `` ` ``, and pick/reject/clear flags with `P`, `X`, `U`.
- `Assign to Photo > Color Label > Purple` exists without a keyboard shortcut.
- `Assign to Photo` actions are disabled while the progress overlay/busy state
  is active.
- `Ctrl+Z` and `Ctrl+Y` undo and redo metadata assignment batches.
- In compare mode, metadata shortcuts and assignment menu actions target only
  the active compare pane, not every compared photo or the hidden restore
  selection.
- Metadata changes write immediately through `library.save_metadata()`.
- Metadata-only refreshes preserve current scroll position in the left
  thumbnail strip and browse grid.
- Explicit multi-selection is restored after repopulation. Single-item
  selection is left to `setCurrentRow` in populate methods so it integrates
  cleanly with Qt's selection model and does not create sticky selection state.
- Navigating within the scene strip without Shift/Ctrl gives the left thumbnail
  strip a clean single-item selection. Only Shift/Ctrl navigation preserves
  accumulated thumbnail selection across scene-strip moves.
- When scene stacks are shown in the left strip, metadata text is hidden for
  stacked scene items, the displayed scene label is `FIRST...LAST` when a scene
  contains more than one photo, the stack badge shows the number of photos, and
  a scene stack is visually rejected only when every photo in that multi-photo
  scene is rejected.

## 3. Organizer And XMP Workflows

Primary files:

- `easy_loupe/operations/common.py`
- `easy_loupe/operations/export.py`
- `easy_loupe/operations/xmp.py`
- `easy_loupe/ui/main_window/workflows.py`
- `tests/operations/test_export.py`
- `tests/operations/test_xmp.py`
- `tests/ui/main_window/test_dialogs.py`

Major logic:

- Shared XMP sidecars use the uppercase stem format `PHOTO_ID.XMP` and are
  placed beside the source photo group for subfolder photos.
- XMP writing manages only the app-owned rating/color-label/pick-reject fields
  and supports preserve-or-replace merge policies.
- Photo organization groups files by one metadata criterion at a time: `flag`,
  `color_label`, or `rating`.
- Photo organization supports `copy` and `move` actions plus conflict policies
  `fail`, `skip`, and `overwrite`.
- Photo organization preserves source subfolder paths inside each output bucket
  to avoid collisions between same-named files from different subfolders.
- The top bar and File menu include `Organize Photos`, with window shortcut
  `Ctrl+Shift+E`.
- `Organize Photos` opens a dialog with two mutually exclusive modes:
  `Reorganize Files` and `Write XMP`.
- Reorganize mode supports criterion, action, output parent selection, optional
  inclusion of untagged photos under `Untagged`, and conflict policy.
- Write XMP mode supports merge policies `preserve` and `replace`.
- Long-running organizer, XMP, and undo work runs off the UI thread through
  `OperationWorker` and `QThread`, using the same busy/progress overlay model
  as scene detection.
- While the overlay is active, interaction, assignment actions, and organizer
  entry points are disabled.
- Successful move-based reorganization reloads the current folder before the
  finished dialog is shown. Successful XMP writing does not reload the current
  folder.
- Completed organizer/XMP runs show a summary dialog with an immediate `Undo`
  action when an undo plan is available.

## 4. Undo Behavior

Primary files:

- `easy_loupe/operations/common.py`
- `easy_loupe/ui/main_window/workflows.py`
- `tests/operations/`
- `tests/ui/main_window/`

Major logic:

- Undo for organization/XMP workflows is explicit, filesystem-based, and a
  given `UndoPlan` is intended to be consumed at most once.
- Successful undo reloads the current folder and then shows confirmation.
- Undo plans should continue to describe the exact files created, moved, backed
  up, or removed by recursive operations.

## 5. Verification Pointers

- If metadata parsing or persistence changes, update or extend the
  normalization/serialization tests.
- Preserve the `color_label` field and allowed values unless the product
  requirement changes.
- Preserve the stem-based JSON contract unless the product requirement changes.
- If `MainWindow` selection/display logic changes, verify metadata text/markup
  still reflects rating, color label, and flag state.
- Verify menu-triggered assignment produces the same result as the
  corresponding keyboard shortcut for each rating, color label, and flag.
- Verify the `Assign to Photo` menu structure, action labels, and shortcut
  presence, including Purple as the only color label without a keyboard
  shortcut.
- Verify metadata refreshes preserve scroll position when the user tags photos
  in the thumbnail strip or browse grid.
- Verify tagging a single photo in the scene strip does not cause sticky
  selection. Navigating away after tagging should show only the navigated-to
  photo as selected, and subsequent tagging should apply only to that photo.
- Verify multi-selection tagging still applies to all selected photos and
  preserves the extended selection after refresh.
- If organizer, XMP, or undo behavior changes, test dialog defaults and typed
  option mapping when UI-facing behavior changes.
- Test copy-vs-move, conflict-policy, and sidecar-handling behavior for file
  organization changes.
- Test preserve-vs-replace behavior plus malformed-sidecar failures for XMP
  changes.
- Verify undo restores files and existing sidecars correctly and remains
  single-use.
- Verify move-based completion reloads the folder while XMP completion does
  not.
- Verify busy-state disabling and finished/error dialog titles still match the
  workflow being run.
