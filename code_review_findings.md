**Findings**

No remaining findings from the prior review after the follow-up cleanup.

Resolved items:

1. README and AGENTS now document compare mode, `C`, `Esc`, metadata undo/redo,
   multi-selection, and shift-selection behavior.
2. Compare and selection logic were extracted out of `navigation.py` into
   focused main-window mixins, and the unused/confusing APIs were removed.
3. `PhotoViewer` mouse event docstrings now cover both hold-zoom and compare
   click/drag signaling.
4. `ComparePhotoViewer.selected_photo_ids()` was removed; compare transitions
   now use `photo_ids()` directly.

**Verification**

- `uv run pytest -q tests/ui/main_window/test_compare_mode.py tests/ui/main_window/test_navigation.py tests/ui/viewers/test_compare_photo_viewer.py tests/ui/viewers/test_photo_viewer.py tests/ui/main_window/test_window.py`
  passed with 73 tests.
- `python -m py_compile easy_cull/ui/main_window/build.py easy_cull/ui/main_window/compare.py easy_cull/ui/main_window/navigation.py easy_cull/ui/main_window/selection.py easy_cull/ui/main_window/window.py easy_cull/ui/viewers/compare_photo_viewer.py easy_cull/ui/viewers/photo_viewer.py`
  passed.
- `git diff --check` passed.
