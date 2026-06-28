# Tagging And Filtering

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Ratings](#1-ratings)
- [2. Color Labels](#2-color-labels)
- [3. Flags](#3-flags)
- [4. Undo And Redo](#4-undo-and-redo)
- [5. Filtering](#5-filtering)
- [6. Metadata File](#6-metadata-file)

______________________________________________________________________

<!--TOC-->

EasyLoupe stores lightweight culling metadata: star ratings, color labels, and
picked/rejected flags. You can apply metadata from the keyboard or from
`Assign to Photo`.

## 1. Ratings

- Press `1`-`5` to assign a star rating.
- Press `0` to clear the rating.

## 2. Color Labels

- Press `6` for red.
- Press `7` for yellow.
- Press `8` for green.
- Press `9` for blue.
- Press `` ` `` to clear the color label.
- Use `Assign to Photo > Color Label > Purple` for purple.

## 3. Flags

- Press `P` to mark selected photos as picked.
- Press `X` to mark selected photos as rejected.
- Press `U` to clear the flag.

In normal culling and browse views, metadata applies to the current selection.
In compare view, metadata applies only to the active compare photo.

## 4. Undo And Redo

Use `Ctrl+Z` and `Ctrl+Y` to undo or redo metadata assignment batches.

## 5. Filtering

Use the `Filter` button to hide photos by rating, color label, or flag.
Filtering is session-only and display-only. It does not edit metadata, change
the saved photo list, or change organizer and XMP inputs.

Filters combine across groups: rating, color label, and flag choices all need
to match. Within a group, any checked choice can match. Empty states such as
not rated, no color label, and not flagged are explicit choices.

When a metadata edit makes the current photo disappear under the active filter,
EasyLoupe moves to the next visible photo when possible. If nothing matches,
the viewer clears until the filter is changed.

## 6. Metadata File

EasyLoupe writes metadata immediately to `easy-loupe.json` in the selected
folder. Root photos use their visible filename stem as the photo key. Photos
loaded from subfolders use folder-relative keys such as `subfolder/IMG_1234`.

The file stores per-photo `rating`, `color_label`, and `flag` values. Scene
groups may also be stored after scene detection or manual scene editing.
