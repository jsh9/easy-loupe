# EasyLoupe

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. What It Helps With](#1-what-it-helps-with)
- [2. Run From Source](#2-run-from-source)
- [3. User Guide](#3-user-guide)
- [4. Contributors](#4-contributors)
- [5. License](#5-license)

______________________________________________________________________

<!--TOC-->

EasyLoupe is a desktop photo culling app for JPEG, HEIC/HEIF, JPEG XL, PNG, and
RAW folders. It is built for quickly reviewing a shoot, marking keepers and
rejects, comparing similar frames, and carrying ratings or labels into the next
step of a photo workflow.

## 1. What It Helps With

- Open a folder of photos, including subfolders when needed.
- Review photos in a focused culling view, a full-folder browse grid, or a
  side-by-side compare view.
- See the neighboring photo or scene stack in your direction of travel: when
  navigating with the keyboard, the left thumbnail strip keeps it fully visible
  when space allows.
- Assign ratings, color labels, and picked/rejected flags from the keyboard.
- Detect and edit scene groups so burst or sequence photos stay together.
- Inspect focus and exposure with zoom, split view, AF point, EXIF/histogram,
  and clipping-warning overlays.
- Fit small photos to the viewer, toggle actual-size inspection, and adjust
  magnification with predictable zoom-in and zoom-out steps.
- Copy viewed photo pixels to the clipboard for pasting into other apps.
- Reorganize photos by metadata or write shared XMP sidecars for other photo
  apps.

## 2. Run From Source

Install dependencies:

```bash
uv sync
```

Start the app:

```bash
uv run python -m easy_loupe
```

After launch, choose a photo folder from the native folder picker. You can also
open a supported photo file directly from Finder, Explorer, or an argv path;
EasyLoupe opens that file in a lightweight photo viewer and can hand off to the
full culling workspace with `G` or `Enter`.

## 3. User Guide

Start with the [EasyLoupe User Guide](docs/user-guide/README.md) for a
walkthrough of the main views and workflows.

## 4. Contributors

Feature-level maintenance notes live in
[docs/maintenance-guides/](docs/maintenance-guides/README.md).

## 5. License

Copyright (C) 2026 jsh9

EasyLoupe is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [LICENSE](LICENSE) for the full license text.

EasyLoupe is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the GNU General Public License for more details.

Packaged EasyLoupe apps include third-party components under their own
licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The GPL covers EasyLoupe's code and files, including the icon files. As allowed
by section 7(e) of the GPL, it does not grant rights to use the EasyLoupe name
or icon as trademarks. If you distribute a modified version, give it a
different name and icon so it is not mistaken for the official app.
