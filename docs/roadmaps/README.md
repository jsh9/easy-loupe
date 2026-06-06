# Maintenance Roadmaps

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Feature Roadmaps](#1-feature-roadmaps)
- [2. Adding A Roadmap](#2-adding-a-roadmap)

______________________________________________________________________

<!--TOC-->

This folder contains feature-level maintenance roadmaps for EasyLoupe. Each
roadmap maps a major product capability to the packages, modules, files, tests,
and behavior contracts that maintain it.

Use this index to find the right feature document before editing. Each feature
document follows the same structure: primary ownership areas, sub-functional
workflow slices, important invariants, and manual verification pointers.

## 1. Feature Roadmaps

- [Recursive Loading](recursive-loading.md): culling-folder subfolder scanning,
  folder-relative photo IDs, metadata migration, recursive operation paths, and
  photo-viewer-to-culling handoff boundaries.

## 2. Adding A Roadmap

- Create one markdown file per major feature in this folder.
- Use a short kebab-case filename, for example `scene-editing.md`.
- Keep sections organized by sub-functionality with level-2 and level-3
  headings.
- List primary files, supporting tests, and the major logic or invariants that
  future changes must preserve.
- Add the new file to the feature list above.
