# UI Workflows

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Main Window Flow](#1-main-window-flow)
- [2. Modes And Transitions](#2-modes-and-transitions)
- [3. Zoom, AF Marker, And Info Overlay](#3-zoom-af-marker-and-info-overlay)
- [4. Selection And Browse Behavior](#4-selection-and-browse-behavior)
- [5. Scene Workflows](#5-scene-workflows)
- [6. Shortcut Contract](#6-shortcut-contract)
- [7. Verification Pointers](#7-verification-pointers)

______________________________________________________________________

<!--TOC-->

This guide covers the culling workspace, standalone photo-viewer handoff
boundaries, browse/compare mode, scene workflows, zoom behavior, selection
behavior, and shortcut contracts.

## 1. Main Window Flow

Primary files:

- `easy_loupe/ui/main_window/window.py`
- `easy_loupe/ui/main_window/build.py`
- `easy_loupe/ui/main_window/workflows.py`
- `easy_loupe/ui/main_window/navigation.py`
- `easy_loupe/ui/main_window/presentation.py`
- `tests/ui/main_window/`

Main flow:

1. `choose_folder()`
2. `PhotoLibrary.load_folder(...)`
3. `_populate_thumbnail_list()`
4. `_populate_browse_list()`
5. `_populate_scene_list()`
6. `_display_current_photo()`
7. `_refresh_ui()`

Major logic:

- `MainWindow` is the central stateful UI controller. Read affected methods
  end-to-end before editing because several flows coordinate through shared
  state such as `current_photo_id`, `_busy`, `_scene_thread`, and
  `scene_detection_done`.
- When the main window first shows and no folder is loaded, `showEvent()`
  schedules the folder chooser automatically.
- Canceling the folder chooser leaves the UI idle: no current photo, no loaded
  photo list, no progress overlay, and no forced state change.
- If folder loading fails, the progress overlay is dismissed, controls are
  re-enabled, and a critical error dialog is shown.
- If a manual folder load succeeds but finds no eligible photos, the UI is
  rebuilt into the loaded-empty idle state before showing the
  `No Eligible Photos` dialog.
- Successful folder loading selects the first photo when photos exist,
  populates the left strip, browse grid, and scene strip, displays the current
  photo, refreshes labels/selection/overlays, and restores keyboard focus to
  the active navigation list after the UI becomes interactive.
- Folder loading, standalone hydration handoff waits, scene detection,
  organizer/XMP work, and undo use structured progress snapshots rendered as
  stage rows with per-loop counts such as `4 of 37`. Preserve the legacy
  `(message, percent)` callbacks for non-UI callers and tests when changing
  progress reporting. Item counts represent completed rows/cache attempts, so
  preview-backed stages must advance only after the relevant preview work
  returns. Worker workflows prefer structured snapshots after one has been
  emitted; legacy scalar progress is a fallback only for producers that never
  emit snapshots. Generic operation and scene workers accept legacy
  progress-only callables as well as structured progress producers. Zero-total
  stages render as status-only rows without per-stage bars; active stages with
  unknown totals still show an indeterminate bar. Empty folder loads complete
  the zero-total EXIF and photo-list stages explicitly, and standalone
  hydration completes the zero-total viewer-cache stage explicitly. Scene
  detection completion preserves active structured rows while rebuilding scene
  lists; only legacy-only progress should fall back to the scalar bar.
  Determinate structured counts are bounded at reporter/model boundaries so
  progress rows cannot show impossible labels such as `4 of 3`. Standalone
  photo-viewer culling handoff shows scalar hydration progress until the first
  structured hydration snapshot is available.
- Folder-load scanning reports discovered grouped-photo and supported-file
  counts after discovery finishes. Do not add fake scan item counts; the total
  is not known until the filesystem walk is done. The EXIF row counts ExifTool
  batches, shows the adaptive batch size in the row label, and keeps the
  current batch count beside that row.
- In normal non-scene view mode after a successful load, the left thumbnail
  strip should be ready to move on the first `Down` keypress.
- Photos default to sorting by EXIF capture timestamp when available, then by
  display name.
- Users can change the global sort preference from the top-bar `Sort by:`
  visual group, which contains a segmented control between `File Name` and
  `Capture Time` plus the adjacent `Reverse order` checkbox.
- The choices are persisted with app settings and applied immediately to loaded
  folders. Sort changes rebuild the vertical thumbnail strip, horizontal scene
  strip, browse grid, and compare grid while preserving selected photo IDs
  where those photos still exist.
- The top bar keeps `Open Folder` and `Include subfolders` together in a framed
  group.
- The sort-mode options are visually one track/pill segmented control with a
  brand-blue active option, and the whole sort area is framed with a distinct
  border as one group rather than loose controls.
- Sort controls are not exposed from the menu bar.

## 2. Modes And Transitions

Primary files:

- `easy_loupe/ui/main_window/navigation.py`
- `easy_loupe/ui/main_window/presentation.py`
- `easy_loupe/ui/photo_viewer/window.py`
- `tests/ui/main_window/test_navigation.py`
- `tests/ui/main_window/test_compare_mode.py`
- `tests/ui/photo_viewer/test_window.py`

Mode summary:

- `Culling mode` is the full EasyLoupe workspace used for selecting, comparing,
  assigning metadata, organizing, scene workflows, and browse-grid review.
- `Photo viewer mode` is the lightweight startup mode used when a specific file
  is opened from Finder, Explorer, or argv. It shows only the opened photo
  fit-to-window at first, supports adjacent-photo navigation within the opened
  file's immediate folder, and keeps culling chrome hidden until `G` or `Enter`
  enters culling mode.
- `View mode` shows the left thumbnail strip and main viewer, plus the
  horizontal scene strip when scene detection is available for the current
  photo.
- `Single-pane fit view` is the default viewer state inside view mode.
- `Single-pane manual/focus view` is entered from fit view with `Space` and
  supports zoom/pan.
- `Split view` is entered with `\` and shows a fit-view pane on the left and a
  zoom/focus pane on the right.
- `Browse mode` is the full-photo grid entered with `G`. It replaces the normal
  content splitter, hides the horizontal scene strip, and is exited with
  `Space` or by double-clicking a photo.
- `Compare mode` is the side-by-side selected-photo grid entered with `C`. It
  caps display at the configured compare limit but preserves the full original
  selection when returning to browse or the previous mode.
- The default compare limit is 8, configurable from `Compare > Limit` with
  options 2, 3, 4, 6, 8, 10, 12, 16, and 20.
- `Selected-photo compare view` is entered from the compare grid with `Space`.
  It shows the active compared photo alone in fit-to-window size and supports
  toggling that photo between fit and 100%.

Transition summary:

- `G` enters browse mode from normal view mode when photos are loaded.
- `Space` in browse mode exits browse mode and returns to single-pane fit view
  for the current photo.
- `Space` in single-pane fit view enters manual/focus zoom.
- `Space` in single-pane manual view returns to fit view.
- `\` toggles split view on and off while staying in normal view mode.
- `Space` in split view promotes the right zoomed pane into single-pane manual
  view.
- `Space` in compare grid opens the active compared photo alone in
  fit-to-window size.
- `Space` or `Z` in selected-photo compare view toggles that photo between fit
  view and 100% zoom. For a small photo that already fits at 100%, this changes
  internal fit/inspection state without a visible scale change.
- `Z` in compare grid toggles every compared pane between fit view and
  AF-centered 100% zoom.
- `Esc` while a selected compare photo is open returns to the comparison grid.
- `Esc` while in compare mode restores the previous view/browse state and the
  stored pre-compare selection.
- After `Esc` returns from compare to normal view, the active compare photo
  remains current. The normal viewer image, vertical strip current item, and
  visible-region overlay target must all realign to that photo while the stored
  pre-compare selection remains selected.
- `G` while in compare mode enters browse mode and restores the stored
  pre-compare selection, even when compare displayed only a capped subset.
- Entering browse mode from split view and pressing `Space` exits to
  single-pane fit view, not back into split view.
- When the main window is reactivated with photos loaded and no progress/modal
  workflow active, keyboard focus returns to the active navigation list.

Entering browse mode:

- Shows the browse grid.
- Hides the normal content splitter.
- Hides the horizontal scene strip.
- Disables split/viewer/scene-navigation shortcuts.
- Preserves the current photo selection.

Exiting browse mode:

- Restores the normal content splitter.
- Reselects the appropriate item in the left strip.
- Repopulates the scene strip for the current scene when scene detection is
  available.
- Restores focus to the active navigation list for the restored mode.

Entering compare mode:

- Displays up to the configured compare photo limit from the resolved current
  selection.
- Stores the full pre-compare selection for later restoration.
- Hides the thumbnail, browse, and scene lists.
- Makes the first compared photo current.
- Starts with locked zoom/pan enabled.

## 3. Zoom, AF Marker, And Info Overlay

Primary files:

- `easy_loupe/ui/viewers/`
- `easy_loupe/ui/main_window/presentation.py`
- `easy_loupe/ui/main_window/navigation.py`
- `tests/ui/viewers/`
- `tests/ui/main_window/test_presentation.py`

Major logic:

- Manual zoom state is remembered per photo. Returning to the same photo
  restores its last manual zoom center and scale; a different photo gets its
  own remembered state or falls back to the extracted AF point.
- A photo with no remembered manual view enters focus zoom around the extracted
  AF point or image center. Remembered per-photo manual zoom state takes
  priority when returning to a photo.
- `Show AF point` is unchecked by default. When checked, the main viewer shows
  a fixed-screen-size red square at the photo's extracted AF point in fit view,
  manual/focus zoom, and both panes of split view.
- The `F` shortcut toggles `Show AF point`.
- In fit-to-window panes, left click-and-hold temporarily zooms to 100% while
  anchoring the clicked image point under the cursor when possible. Near the
  photo edges and corners, the viewport clamps inward to keep the zoomed view
  inside the image bounds.
- `Shift+F` in manual zoom temporarily recenters the active zoomed pane on the
  photo's AF point or image center without replacing remembered manual zoom
  memory. Pressing `Shift+F` again restores the remembered manual center when
  one exists.
- If centering an edge AF point requires extra live zoom, that temporary scale
  must not be saved unless the user explicitly pans.
- `Ctrl+Shift+F` resets remembered manual zoom centers to each photo's AF point
  or image center while preserving remembered zoom levels. A remembered center
  of `None` means resolve to the current photo's AF/default center, so the
  intent survives late-loading AF metadata.
- Viewer zoom and pan shortcuts target only the active zoomed pane. In split
  view, that means the right pane; the left fit pane remains unchanged.
- Pressing `Space` while in split view promotes the right pane into single-pane
  manual view, preserving zoom and center.
- Toggling split view off after zooming/panning preserves the right-pane manual
  view in single-pane mode.
- The `I` shortcut toggles a floating EXIF and RGB histogram overlay in normal
  view mode. The overlay is anchored over the top-right of the main viewer,
  shows load-time EXIF display rows and an RGB histogram when available,
  follows the current photo, hides automatically in browse mode, compare mode,
  and busy/progress states, and reappears when returning to eligible normal
  view state if the overlay preference remains enabled.

## 4. Selection And Browse Behavior

Primary files:

- `easy_loupe/ui/widgets.py`
- `easy_loupe/ui/main_window/navigation.py`
- `easy_loupe/ui/main_window/presentation.py`
- `tests/ui/main_window/test_navigation.py`
- `tests/ui/main_window/test_workflows.py`
- `tests/ui/test_widgets.py`

Major logic:

- In normal view mode, the left strip selection tracks the current photo.
- When scene detection is complete, the left strip represents scene stacks, so
  the selected left item is the first photo of the current scene rather than
  necessarily the exact current photo.
- Browse mode always shows every individual photo, even when normal view mode
  is using scene stacks in the left strip.
- In browse mode, selecting a grid item updates the current photo and keeps the
  left strip and scene strip synchronized in the background.
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
- Multi-selection is preserved in thumbnail, browse, and scene workflows when
  the user extends selection with Shift or Control.
- `Shift+Up` and `Shift+Down` in the vertical thumbnail strip use anchored
  range selection. Reversing direction releases rows outside the current
  anchor-to-current range rather than leaving them stickily selected.
- While the main viewer is in manual zoom, the active strip thumbnail shows the
  current visible region with a darkened mask outside the visible region and a
  red edge around it.
- Left-clicking a visible-region minimap recenters the zoomed viewer on the
  clicked image position. Holding the left button and dragging within the
  minimap continuously pans the zoomed viewer; dragging beyond the minimap
  clamps the request to the nearest displayed image edge or corner.
- While the main viewer is in manual zoom, a plain left-click on another strip
  thumbnail's image area selects that photo and recenters the zoomed viewer on
  the clicked relative image position. Holding the left button and dragging
  continues panning that newly selected photo without needing to release and
  click the red box again. Modifier-assisted selection, keyboard navigation,
  browse-grid clicks, and clicks outside the thumbnail image area keep the
  normal remembered-center behavior.
- In non-scene mode, the visible-region overlay belongs on the active item in
  the left thumbnail strip.
- In scene mode, the exact current photo's interactive overlay belongs on the
  horizontal `scene_list`. The left scene-stack strip may show and control the
  overlay only when the current photo is that stack's cover photo.
- Browse mode never shows the visible-region overlay on browse-grid items.
- Returning to fit view clears the overlay. Re-entering manual view restores
  the corresponding overlay geometry for the current photo.

## 5. Scene Workflows

Primary files:

- `easy_loupe/analysis/scenes.py`
- `easy_loupe/ui/workers.py`
- `easy_loupe/ui/progress_overlay.py`
- `easy_loupe/ui/progress_routing.py`
- `easy_loupe/progress/`
- `easy_loupe/ui/main_window/workflows.py`
- `easy_loupe/ui/main_window/navigation.py`
- `tests/analysis/`
- `tests/ui/main_window/`

Major logic:

- Scene detection runs asynchronously through `SceneDetectionWorker`,
  `QThread`, `_handle_scene_progress()`, and `_handle_scene_finished()` /
  `_handle_scene_failed()`.
- While the overlay is active, interaction and assignment actions are disabled,
  and keyboard shortcut handlers are effectively blocked.
- On successful scene detection, the left strip is rebuilt as scene stacks, the
  browse grid is rebuilt, the horizontal scene strip is rebuilt for the current
  scene, and stale manual scene-edit undo/redo entries are cleared while
  ordinary metadata assignment history is preserved.
- If scene detection finishes while the user is in browse mode, browse mode is
  exited, the current photo remains selected, and the main viewer is forced to
  fit view.
- If scene detection finishes while the user is already in normal split view,
  split view and right-pane manual zoom are preserved.
- Left/right arrow shortcuts navigate within the current scene via the
  horizontal scene strip.
- Up/down key handling in `SceneListWidget` moves the left-strip scene-stack
  selection globally.
- In scene mode, `Shift+Left` and `Shift+Right` extend the horizontal in-scene
  selection, while `Shift+Up` and `Shift+Down` extend across vertical
  scene-stack rows and preserve exact hidden in-scene selections.
- Scene merges, breaks, and scene-edit undo/redo performed from browse mode
  keep keyboard focus on the browse grid after the lists are rebuilt.
- Scene merges from the vertical thumbnail strip expand selected scene stacks
  to all photos in those stacks.
- Scene merges from the horizontal scene strip use exact in-scene photo
  selection: selecting only part of the current scene is blocked as an
  attempted split, while selecting the full horizontal scene can merge that
  whole scene with selected vertical scene stacks.

## 6. Shortcut Contract

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
- `Shift+F`: temporarily recenter the active manual zoom view on the AF point
  or image center, then toggle back to the remembered manual center when one
  exists
- `Ctrl+Shift+F`: reset remembered manual zoom centers to AF points or image
  centers while preserving remembered zoom levels
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

Keyboard shortcuts are part of the product behavior, not incidental
implementation.

Window close while scene detection or organizer/undo work is active must hide
the visible window immediately, request best-effort worker shutdown, and defer
the actual Qt teardown until the relevant `QThread.finished` cleanup clears the
stored thread slot. Standalone photo-viewer close follows the same visible hide
plus deferred-teardown rule for EXIF refresh, prefetch, and folder-hydration
threads. Only workers with an explicit `cancel()` hook are cooperatively
cancellable; file-operation workers drain to completion while teardown remains
deferred invisibly.

`WindowManager` owns application quit deferral for these hidden-close paths:
the app disables implicit last-visible-window quit and exits only after the
manager has forgotten every destroyed window. Preserve that boundary so
`QThread` child objects are not destroyed by PySide application finalization
while their worker code is still running.

## 7. Verification Pointers

- For shutdown fixes involving `QThread` cleanup, verify both source runs and
  the packaged app by closing and using `Cmd+Q` while scene detection,
  organizer/undo work, standalone EXIF refresh, prefetch, or folder hydration
  is active.
- If scene detection changes, test grouping behavior, not just helper
  functions, and preserve ordering assumptions based on capture time.
- If progress reporting changes, verify both legacy progress tuples and the
  structured stage-row overlay for folder loading, standalone hydration
  handoff, scene detection, organizer/XMP work, and undo. Worker workflows must
  connect legacy scalar progress as a fallback, but paired scalar updates must
  not clear structured stage rows after a snapshot has been emitted.
- If `MainWindow` selection/display logic changes, verify which preview kind is
  requested and verify action shortcuts plus enable/disable states where
  relevant.
- Verify browse-mode entry/exit and selection synchronization when scene
  detection is active.
- Verify browse-to-view transitions restore fit-to-window display while view
  mode still remembers the last manual zoom for the same photo.
- Verify the `Show AF point` top-bar checkbox default, shortcut, and
  propagation to the single and split viewer panes when viewer behavior
  changes.
- Verify AF point marker visibility in fit view, manual/focus zoom, and both
  split-view panes when marker behavior changes.
- Verify the `I` info overlay toggles only in eligible normal view state,
  follows current-photo changes, hides during browse/compare/busy states, and
  remains readable when the viewer is resized.
- Verify first-time focus zoom uses the AF point while remembered manual zoom
  remains higher priority.
- Verify `Shift+F` is view-only unless the user pans, including edge AF points
  that require extra live zoom and resize while temporarily recentered.
- Verify `Ctrl+Shift+F` preserves remembered zoom levels, resets centers to
  photo-relative AF/default centers, and survives late AF metadata loading.
- Verify scene-detection completion preserves split view in normal view mode
  but still exits browse mode back to fit view.
- Verify vertical thumbnail-strip Shift range selection releases rows outside
  the anchor-to-current range when the user reverses direction.
- Verify scene merge selection resolution across the vertical thumbnail strip
  and horizontal scene strip: full horizontal-scene selection may merge with
  selected vertical stacks, but partial horizontal-scene selection remains
  blocked as an attempted split.
- If thumbnail visible-region overlay rendering changes, preserve the
  normalized visible-region geometry contract from
  `PhotoViewer.visible_region_rect()`.
- Verify the overlay appears only for the active strip thumbnail in manual zoom
  and that scene mode uses the horizontal `scene_list`.
- Verify compare-mode exit keeps the active compare photo aligned across
  `current_photo_id`, the normal viewer image, the active strip item, and the
  visible-region overlay after pressing `Space`.
- Prefer a render-to-image widget test when checking mask opacity, edge color,
  or other paint details.
