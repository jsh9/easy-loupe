# Code Review Findings

Review target: branch diff compared to `main`.

## Findings

1. `easy_cull/ui/viewers/compare_photo_viewer.py:422`

   Active compare panes use a `4px` border while inactive panes use a `1px`
   border. That can shift pane contents as the active pane changes. The
   thumbnail code already avoids this pattern by reserving a transparent border;
   compare panes should probably use a constant border width and only change
   color.

2. `easy_cull/ui/viewers/photo_viewer.py:467`

   Compare-specific click/drag gesture handling now lives in the generic
   `PhotoViewer` and is active for all instances, while only compare viewers
   connect the emitted signals. This is a maintainability risk and can swallow
   left-button drag/release events in normal viewers. Make this opt-in, or
   isolate it in a compare-specific viewer wrapper/subclass.

3. `easy_cull/ui/main_window/workflows.py:553`

   Metadata undo/redo is implemented inline in `workflows.py`, with stacks
   typed as `list[object]` in `window.py` and runtime `assert isinstance(...)`
   checks. It works, but for this repo's maintainability bar the stacks should
   be typed as `list[MetadataEdit]`. Consider a small history helper if this
   grows further.

## Comments And Docstrings

I did not find comment or test-docstring issues against AGENTS.md section 10.
The new or changed tests generally explain both the behavior and why the
regression matters. The inline comments I saw are tied to non-obvious Qt
selection/focus behavior and are appropriate.

## Verification

`uv run pytest -q` passed with `395 passed`.

Overall, I did not find a blocking functional correctness bug in the diff. The
main concerns are UI stability and keeping compare-specific behavior from
leaking too deeply into shared viewer code.
