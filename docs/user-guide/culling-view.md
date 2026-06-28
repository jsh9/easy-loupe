# Culling View

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Layout](#1-layout)
- [2. Opening And Sorting](#2-opening-and-sorting)
- [3. Filtering](#3-filtering)
- [4. Moving To Other Views](#4-moving-to-other-views)

______________________________________________________________________

<!--TOC-->

Culling view is the main EasyLoupe workspace. Use it when you want to move
photo by photo, inspect details, tag keepers, and start deeper workflows such
as scene detection or organizing.

## 1. Layout

- The left thumbnail strip shows the loaded photos, or scene stacks after scene
  detection.
- The main viewer shows the current photo.
- The horizontal scene strip appears when the current photo belongs to a
  detected or manually edited scene.
- The top bar shows folder controls, sort controls, filtering, organizing, and
  current metadata.

Use normal click, Shift-click, and modifier-assisted selection gestures in the
thumbnail strip. Keyboard focus returns to the active photo list after loading
so you can start navigating without clicking into the list first.

## 2. Opening And Sorting

Use `Open Folder` or `Ctrl+O` to choose another folder. The
`Include subfolders` checkbox controls whether culling mode scans nested
folders.

Use the `Sort by:` controls to choose `File Name` or `Capture Time`. The
`Reverse order` checkbox flips the current sort. Sort changes rebuild the
thumbnail strip, browse grid, scene strip, and compare grid while keeping the
current selection where possible.

## 3. Filtering

The `Filter` button hides photos by rating, color label, and flag. Filters are
session-only: they change what is visible, but they do not edit metadata or
change the photo library on disk.

Each filter group starts with all choices enabled, including empty states such
as not rated, no color label, and not flagged. Apply the popup to rebuild the
visible lists.

## 4. Moving To Other Views

- Press `G` to enter browse view.
- Select at least two photos and press `C` to enter compare view.
- Press `Space` or `Z` in normal view to switch between fit view and manual
  zoom.
- Press `\` to toggle split view.

Press `?` at any time for view-specific shortcuts.
