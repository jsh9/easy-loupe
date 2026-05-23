**Findings**

1. **Product docs are incomplete for the new user-visible behavior.** README
   and AGENTS still describe “two primary UI states” and omit compare mode,
   `C`, `Esc`, metadata undo/redo, multi-selection, and shift-selection
   shortcuts. See
   [README.md](/Users/jian/Documents/github/easy-cull/README.md:191) and
   [AGENTS.md](/Users/jian/Documents/github/easy-cull/AGENTS.md:538). Given
   Section 10 says docs/tests should stay aligned with user-visible changes,
   this should be updated before merge.

2. **Maintainability: compare and multi-selection logic make `navigation.py`
   much harder to reason about.** The mixin now owns compare mode, hidden scene
   selections, scene range selection, browse transitions, and selection
   resolution in one file. There are also small dead/confusing APIs:
   `_photo_ids_for_selected_item()` appears unused and still expands scene
   stacks at
   [navigation.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/navigation.py:643),
   `_pan_by()` appears unused at
   [build.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/build.py:516),
   and `ComparePhoto.display_name` is populated but not displayed. I’d extract
   compare mode/selection resolution into focused helpers before this grows
   further.

3. **Section 10 comment/docstring issue: mouse event docstrings are now
   stale.** `PhotoViewer.mousePressEvent`, `mouseMoveEvent`, and
   `mouseReleaseEvent` now also implement compare click/drag signaling, but
   their docstrings still only describe hold-zoom behavior at
   [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:441),
   [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:474),
   and
   [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:508).
   The new test docstrings are generally up to the repo standard.

4. **Naming clarity: `selected_photo_ids()` is misleading.** In
   [compare_photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/compare_photo_viewer.py:217),
   it returns every photo participating in compare, not a selected subset. That
   ambiguity already leaks into transition code. `compared_photo_ids()` or
   using `photo_ids()` directly would be clearer.

**Verification**

I attempted to run the relevant UI tests, but this shell does not have the
project test environment available: `uv` is not on PATH, `.venv` has no pytest,
and global pytest lacks PySide6.
