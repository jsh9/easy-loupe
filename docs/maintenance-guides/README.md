# Maintenance Guides

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Feature Guides](#1-feature-guides)
- [2. Adding A Guide](#2-adding-a-guide)

______________________________________________________________________

<!--TOC-->

This folder contains feature-level maintenance guides for EasyLoupe. Each guide
maps a major product capability to the packages, modules, files, tests, and
behavior contracts that maintain it.

Use this index to find the right feature document before editing. Each feature
document follows the same structure: primary ownership areas, sub-functional
workflow slices, important invariants, and manual verification pointers.

## 1. Feature Guides

- [Packaging And Startup](packaging-and-startup.md): PyInstaller artifacts, app
  identity, direct-file-open startup routing, macOS folder access, and
  platform-specific verification.
- [Previews, EXIF, And Autofocus](previews-exif-autofocus.md): preview cache
  semantics, RAW/HEIF runtime dependencies, ExifTool lookup, EXIF display, and
  brand-specific AF-point extraction.
- [Recursive Loading](recursive-loading.md): culling-folder subfolder scanning,
  folder-relative photo IDs, metadata migration, recursive operation paths, and
  photo-viewer-to-culling handoff boundaries.
- [Tagging, Metadata, And Operations](tagging-metadata-operations.md):
  persisted metadata shape, assignment shortcuts, organizer/XMP workflows,
  sidecar output, and undo behavior.
- [UI Workflows](ui-workflows.md): culling mode, photo-viewer mode, browse and
  compare mode, scene workflows, zoom behavior, selection behavior, and
  shortcut contracts.

## 2. Adding A Guide

- Create one markdown file per major feature in this folder.
- Use a short kebab-case filename, for example `scene-editing.md`.
- Keep sections organized by sub-functionality with level-2 and level-3
  headings.
- List primary files, supporting tests, and the major logic or invariants that
  future changes must preserve.
- Add the new file to the feature list above.
