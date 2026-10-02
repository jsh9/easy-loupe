# Getting Started

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Run The App](#1-run-the-app)
- [2. Supported Photos](#2-supported-photos)
- [3. Include Subfolders](#3-include-subfolders)
- [4. Opening A Photo File Directly](#4-opening-a-photo-file-directly)
- [5. Shortcut Help](#5-shortcut-help)

______________________________________________________________________

<!--TOC-->

EasyLoupe can start from a folder or from a single photo file. A folder opens
the full culling workspace. A direct photo file opens a lightweight photo
viewer first, then lets you enter the culling workspace for that photo's
folder.

## 1. Run The App

From a source checkout:

```bash
uv sync
uv run python -m easy_loupe
```

When the main window opens, choose a photo folder from the native folder
picker. If you cancel the picker, the app stays open and waits for you to open
a folder later.

## 2. Supported Photos

EasyLoupe is intended for JPEG, HEIC/HEIF, JPEG XL (`.jxl`), PNG, and RAW photo
folders. When files of different formats share the same filename stem, such as
`IMG_0001.JPG` and `IMG_0001.CR3`, the app treats them as one photo for culling
and metadata. Letter case in the stem does not matter.

For a photo with several formats, EasyLoupe shows the first available format in
this order: JPEG, HEIC/HEIF, JPEG XL, PNG, then RAW. Camera details and focus
points come from the RAW file when there is one. Transparent areas in PNG and
JPEG XL images show as a near-white background.

If a selected folder has no supported photos for the current scan mode,
EasyLoupe shows `No Eligible Photos`.

## 3. Include Subfolders

The `Include subfolders` checkbox sits beside `Open Folder`. It is enabled by
default for culling folders and lets EasyLoupe load supported photos under the
selected folder tree.

Turn it off when you only want files directly inside the selected folder. If a
folder is already loaded, changing the checkbox asks before reloading the
folder.

## 4. Opening A Photo File Directly

You can open a supported photo file from Finder, Explorer, or an argv path. In
that mode EasyLoupe shows the opened photo first and keeps the full culling
workspace hidden.

Navigate neighboring photos within the opened file's immediate folder, then
press `G` or `Enter` to enter the full culling workspace for that folder and
current photo. Background loading may prepare the culling folder, but the
standalone photo viewer itself stays scoped to the opened file's folder.

The photo viewer shows rotations saved in that folder's `easy-loupe.json`.
Press `]` or `[` to turn a photo while you look at it; this rotation lasts only
until the photo viewer closes. It is not saved and does not carry into the
culling workspace. Rotations saved from a culling session that included
subfolders live in the parent folder's file, so the photo viewer does not show
them.

## 5. Shortcut Help

Press `?` or choose `Help > Keyboard Shortcuts` to show the shortcuts that
apply to the current view.
