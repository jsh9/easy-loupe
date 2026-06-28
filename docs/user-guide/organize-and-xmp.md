# Organize And XMP

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Reorganize Files](#1-reorganize-files)
- [2. Write XMP](#2-write-xmp)
- [3. Progress And Undo](#3-progress-and-undo)

______________________________________________________________________

<!--TOC-->

`Organize Photos` helps move culling decisions into the filesystem or another
photo app. Open it from the top bar, from the File menu, or with
`Ctrl+Shift+E`.

The dialog has two workflows: `Reorganize Files` and `Write XMP`.

## 1. Reorganize Files

Reorganizing copies or moves photo files into metadata-based folders.

Choose:

- The criterion: picked/rejected flag, color label, or rating.
- The action: copy into folders or move into folders.
- The output parent folder.
- The conflict policy: fail the whole run, skip conflicts, or overwrite
  conflicts.

Picked/rejected organization can route `Picked`, `Rejected`, `Untagged`, and
`Others` buckets. Color-label and rating organization can optionally include
untagged photos.

When photos came from subfolders, EasyLoupe preserves source subfolder paths
inside each output bucket so same-named files do not collide.

## 2. Write XMP

`Write XMP` creates shared uppercase `PHOTO_ID.XMP` sidecars beside the source
photo group. These sidecars carry EasyLoupe's rating, color-label, and
picked/rejected metadata for tools such as Lightroom or Capture One.

Choose whether to preserve existing supported XMP values or replace them with
the current EasyLoupe metadata.

## 3. Progress And Undo

Organizing and XMP writing run in the background while a progress overlay is
shown. Interaction and metadata assignment are paused until the operation
finishes.

When an operation can be undone, the finished dialog offers an immediate undo
action. Move-based organization reloads the current folder after completion or
undo so the visible folder state matches the filesystem.
