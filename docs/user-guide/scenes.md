# Scenes

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Detect Scenes](#1-detect-scenes)
- [2. Navigate Scenes](#2-navigate-scenes)
- [3. Edit Scenes](#3-edit-scenes)

______________________________________________________________________

<!--TOC-->

Scenes group related photos, such as burst sequences or repeated shots of the
same subject. Scene mode helps you move through those groups without losing
access to the individual photos.

## 1. Detect Scenes

Use `Detect Scenes` or `Ctrl+D` after loading a folder. EasyLoupe analyzes the
loaded photos in the background and shows progress while interactions are
paused.

When detection finishes:

- The left strip becomes scene stacks.
- The browse grid still shows individual photos.
- The horizontal scene strip shows the photos inside the current scene.

If detection finishes while you are in browse view, EasyLoupe returns to
fit-to-window culling view for the current photo. If you are already in split
view, split view stays active.

## 2. Navigate Scenes

Use the left strip to move between scene stacks. Use the horizontal scene strip
or left/right arrow keys to move within the current scene.

Selection can extend inside a scene with `Shift+Left` and `Shift+Right`.
Selection can extend across scene stacks with `Shift+Up` and `Shift+Down`.

## 3. Edit Scenes

Use `Ctrl+Shift+M` to merge selected photos into a scene.

When selecting from the vertical scene-stack strip, EasyLoupe treats selected
stacks as all photos in those scenes. When selecting from the horizontal scene
strip, selection is exact: selecting the full horizontal scene can merge it
with selected vertical stacks, while selecting only part of the horizontal
scene is treated as an attempted split and is blocked.

Use the scene context menu to break a scene into single photos.

Scene edits are saved in `easy-loupe.json` alongside photo metadata.
