# Code Review Findings

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Resolved Findings](#1-resolved-findings)
- [2. Comments And Docstrings](#2-comments-and-docstrings)
- [3. Verification](#3-verification)

______________________________________________________________________

<!--TOC-->

Review target: branch diff compared to `main`.

## 1. Resolved Findings

1. `easy_cull/ui/viewers/compare_photo_viewer.py:422`

   Resolved. Compare panes now use a constant border width and distinguish the
   active pane by border color only, preventing content shifts when active
   selection changes.

2. `easy_cull/ui/viewers/photo_viewer.py:467`

   Resolved. Compare-specific click/drag gesture handling now lives in
   `ComparePanePhotoViewer`, keeping the shared `PhotoViewer` focused on normal
   viewing, hold-zoom, zoom, pan, marker, and visible-region behavior.

3. `easy_cull/ui/main_window/workflows.py:553`

   Resolved. Metadata undo/redo stacks are now typed as `list[MetadataEdit]`,
   and the redundant runtime type asserts were removed.

## 2. Comments And Docstrings

I did not find comment or test-docstring issues against AGENTS.md section 10.
The new or changed tests generally explain both the behavior and why the
regression matters. The inline comments I saw are tied to non-obvious Qt
selection/focus behavior and are appropriate.

## 3. Verification

`uv run pytest -q` passed with `396 passed`.

Overall, I did not find a remaining blocking functional correctness bug in the
diff after these fixes.
