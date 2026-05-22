**Findings**

1. **Bug: compare metadata labels are unstyled when panes are created after a theme change.**  
   In [compare_photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/compare_photo_viewer.py:161), labels are created without applying the `compareMetadataLabel` stylesheet. `set_theme()` only styles labels already in `self._metadata_labels` at [compare_photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/compare_photo_viewer.py:294). If the user switches to dark theme before entering compare mode, the new labels can render with default text colors on a dark background.

2. **Bug/behavior gap: `G` from compare can select photos that were not actually compared.**  
   `_enter_compare_mode()` limits displayed photos to `photo_limit`, but stores the full original selection at [navigation.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/navigation.py:429). `_enter_browse_mode_from_compare()` then prefers that full restore selection over `compared_photo_ids` at [navigation.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/navigation.py:701). So if 10 photos are selected and compare shows the first 8, pressing `G` from compare will select all 10 in browse. Existing tests cover the limit and `G` separately, but not together.

3. **Product docs are incomplete for the new user-visible behavior.**  
   README and AGENTS still describe “two primary UI states” and omit compare mode, `C`, `Esc`, metadata undo/redo, multi-selection, and shift-selection shortcuts. See [README.md](/Users/jian/Documents/github/easy-cull/README.md:191) and [AGENTS.md](/Users/jian/Documents/github/easy-cull/AGENTS.md:538). Given Section 10 says docs/tests should stay aligned with user-visible changes, this should be updated before merge.

4. **Maintainability: compare and multi-selection logic make `navigation.py` much harder to reason about.**  
   The mixin now owns compare mode, hidden scene selections, scene range selection, browse transitions, and selection resolution in one file. There are also small dead/confusing APIs: `_photo_ids_for_selected_item()` appears unused and still expands scene stacks at [navigation.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/navigation.py:643), `_pan_by()` appears unused at [build.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/main_window/build.py:516), and `ComparePhoto.display_name` is populated but not displayed. I’d extract compare mode/selection resolution into focused helpers before this grows further.

5. **Section 10 comment/docstring issue: mouse event docstrings are now stale.**  
   `PhotoViewer.mousePressEvent`, `mouseMoveEvent`, and `mouseReleaseEvent` now also implement compare click/drag signaling, but their docstrings still only describe hold-zoom behavior at [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:441), [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:474), and [photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/photo_viewer.py:508). The new test docstrings are generally up to the repo standard.

6. **Naming clarity: `selected_photo_ids()` is misleading.**  
   In [compare_photo_viewer.py](/Users/jian/Documents/github/easy-cull/easy_cull/ui/viewers/compare_photo_viewer.py:217), it returns every photo participating in compare, not a selected subset. That ambiguity already leaks into transition code. `compared_photo_ids()` or using `photo_ids()` directly would be clearer.

**Verification**

I attempted to run the relevant UI tests, but this shell does not have the project test environment available: `uv` is not on PATH, `.venv` has no pytest, and global pytest lacks PySide6.