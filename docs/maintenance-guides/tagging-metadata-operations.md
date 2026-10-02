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
- `easy_loupe/core/rotation.py`
- `easy_loupe/core/photo_library.py`
- `tests/core/test_metadata.py`
- `tests/core/test_rotation.py`

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
- View rotation is limited to clockwise degrees `0`, `90`, `180`, or `270`.
  `normalize_rotation()` rejects every other value, including `bool`, which is
  an `int` subclass. Invalid saved values are ignored on load and rejected with
  `ValueError` by `update_metadata()`.
- Saved metadata entries may contain `rating`, `color_label`, `flag`, and
  `rotation`. `rotation` is written only when it is non-zero, so unrotated
  photos keep the historical entry shape. It travels with the rest of the entry
  through legacy-key and case-only key migration.
- Rotation is view-only: it never changes source files, cached previews, scene
  detection, organizer output, or XMP sidecars.
- Clearing all assigned metadata for a photo, including turning it back to
  rotation `0`, removes that photo's persisted entry from `easy-loupe.json`.
- Older EasyLoupe builds do not know `rotation` and drop it the next time they
  save the folder metadata.

## 2. Assignment Behavior

Primary files:

- `easy_loupe/ui/main_window/window.py`
- `easy_loupe/ui/main_window/build.py`
- `easy_loupe/ui/main_window/presentation.py`
- `easy_loupe/ui/main_window/rotation.py`
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
- `Assign to Photo > Rotate` holds `Clockwise` (`]`) and `Counterclockwise`
  (`[`). They use the same selection rules, busy/frozen/help gating, and
  metadata undo history as tag assignments. Each photo turns by one quarter
  turn from its own current rotation, so the undo record stores per-photo
  before/after values.
- Rotation never changes filter membership, sort order, or card geometry.
  `MainWindowRotationMixin._refresh_rotated_photos()` therefore turns the
  existing thumbnail, browse, and scene-strip cards, compare panes, and the
  main viewer (whenever it holds a rotated photo, visible or not) in place
  instead of rebuilding lists. Undo/redo dispatches through
  `MainWindow._metadata_edit_refreshers`, which maps `rotation` to that
  in-place refresh; unregistered fields use `_after_metadata_change()`, so the
  undo code itself has no per-field branches.
- Metadata saves from assignments, rotation, scene merge/break, and undo/redo
  go through `_save_metadata_or_warn()`. If writing `easy-loupe.json` raises
  `OSError` (for example on a read-only card or share), the edit stays applied
  in memory and undoable, the display still refreshes, and a transient warning
  says the change applies to this session only. Letting the error escape the Qt
  slot would skip the refresh and leave the screen out of sync with the
  records.
- `Assign to Photo` actions are disabled while the progress overlay/busy state
  is active.
- `Ctrl+Z` and `Ctrl+Y` undo and redo metadata assignment batches.
- In compare mode, metadata shortcuts and assignment menu actions target only
  the active compare pane, not every compared photo or the hidden restore
  selection.
- Metadata changes write immediately through `library.save_metadata()`.
- Metadata-only refreshes preserve current scroll position in the left
  thumbnail strip and browse grid.
- Culling filters are display-only metadata filters. They may hide photos by
  rating, color label, or flag, including empty states, but they do not alter
  saved metadata, undo history, organizer inputs, or XMP sidecar output.
- Under an active filter, metadata edits can make the current photo disappear
  from the visible lists. The UI should rebuild from matching photos and move
  to the next visible photo, or clear the viewer when no photos still match. In
  scene view, the replacement stays in the current scene while any of its
  photos remain visible, so rejecting the last photos of a scene does not jump
  to the next scene. See the filter rules in `ui-workflows.md`.
- Explicit multi-selection is restored after repopulation when at least two of
  its rows are still visible. Single-item selection is left to `setCurrentRow`
  in populate methods so it integrates cleanly with Qt's selection model and
  does not create sticky selection state. When a filtered edit hides the
  selected rows, the rebuilt lists therefore keep the replacement photo as the
  single selection, so the next assignment targets the photo shown instead of
  falling back to the scene cover.
- Filtered edits that add or remove list rows restart Shift-range anchors, as
  filter changes do, because anchors are row numbers that could otherwise point
  at photos the user never selected.
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
- Reorganize mode supports criterion, action, output parent selection, and
  conflict policy. Picked/rejected organization exposes explicit child folder
  modes for `Picked`, `Rejected`, `Untagged`, `Not picked`, and `Not rejected`
  buckets. Color-label and rating organization each expose their own optional
  `Untagged` checkbox.
- Reorganize mode can optionally split JPG/JPEG and RAW outputs when both
  formats exist in the loaded folder. The split keeps metadata buckets first,
  then writes files under `jpg` or `raw` child folders. HEIC/HEIF, JPEG XL, and
  PNG files are not split and stay directly in the metadata bucket. Shared XMP
  sidecars for RAW-backed photos follow the RAW output.
- Starting an organizer workflow remembers its mode, criterion-specific
  controls, action, JPG/RAW split, conflict policy, and XMP merge policy across
  sessions. Canceling does not replace those choices, and the output parent
  always starts from the currently loaded folder instead of a remembered path.
- New organizer UI code should prefer criterion-specific option types; the
  legacy `OrganizeFilesOptions(...)` constructor remains for direct callers.
- Write XMP mode supports merge policies `preserve` and `replace`.
- Long-running organizer, XMP, and undo work runs off the UI thread through
  `OperationWorker` and `QThread`, using the same busy/progress overlay model
  as scene detection.
- While the overlay is active, interaction, assignment actions, and organizer
  entry points are disabled.
- Successful move-based reorganization does not reload the current folder, but
  it freezes the main photo workspace with a visible message because loaded
  photo paths may now point at moved files. The frozen state blocks navigation,
  tagging, filtering, sorting, scene detection, and organizer entry until the
  user opens another folder or immediately undoes the move.
- Successful copy-based reorganization and XMP writing keep the current folder
  loaded and interactive because source photo paths remain valid.
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
- Empty undo plans still emit a completed zero-total undo progress stage before
  cleanup so the overlay receives a terminal update.
- Undo plans should continue to describe the exact files created, moved, backed
  up, or removed by recursive operations.
- Metadata undo/redo (`Ctrl+Z`/`Ctrl+Y`) covers ratings, color labels, flags,
  view rotations, and scene edits. It is in-memory and separate from organizer
  undo plans.

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
  shortcut and the `Rotate` submenu with `]` and `[`.
- If rotation persistence changes, verify zero and invalid rotations are
  omitted, saved rotations survive reload and key migration, and undo/redo
  turns the viewer and existing cards back without rebuilding lists.
- Verify metadata refreshes preserve scroll position when the user tags photos
  in the thumbnail strip or browse grid.
- Verify tagging a single photo in the scene strip does not cause sticky
  selection. Navigating away after tagging should show only the navigated-to
  photo as selected, and subsequent tagging should apply only to that photo.
- Verify multi-selection tagging still applies to all selected photos and
  preserves the extended selection after refresh. Under an active filter, when
  the tagged selection disappears, verify that the next tag targets the
  replacement photo shown in the main view.
- If organizer, XMP, or undo behavior changes, test dialog defaults and typed
  option mapping when UI-facing behavior changes.
- When organizer controls change, verify accepted choices persist, canceled or
  invalid choices preserve safe defaults, and output paths remain folder-local.
- Test copy-vs-move, conflict-policy, and sidecar-handling behavior for file
  organization changes.
- Test preserve-vs-replace behavior plus malformed-sidecar failures for XMP
  changes.
- Verify undo restores files and existing sidecars correctly and remains
  single-use.
- Verify optional JPG/RAW splitting keeps buckets first, preserves source
  subfolder paths, and places shared XMP sidecars with RAW output.
- Verify move-based organization and XMP completion do not reload the folder.
- Verify busy-state disabling and finished/error dialog titles still match the
  workflow being run.
