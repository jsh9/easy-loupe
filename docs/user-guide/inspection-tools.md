# Inspection Tools

<!--TOC-->

______________________________________________________________________

**Table of Contents**

- [1. Fit View And Manual Zoom](#1-fit-view-and-manual-zoom)
- [2. Split View](#2-split-view)
- [3. AF Point](#3-af-point)
- [4. EXIF And Histogram](#4-exif-and-histogram)
- [5. Clipping Warnings](#5-clipping-warnings)
- [6. Visible-Region Minimap](#6-visible-region-minimap)

______________________________________________________________________

<!--TOC-->

EasyLoupe includes several tools for checking focus, framing, and exposure
while culling.

## 1. Fit View And Manual Zoom

Photos open fit-to-window by default. Press `Space` or `Z` to enter manual
zoom, then press it again to return to fit view.

Manual zoom is remembered per photo. Returning to a photo restores its last
manual zoom position and scale.

Use:

- `-` to zoom out.
- `=` or `+` to zoom in.
- `W`, `A`, `S`, and `D` to pan.

In fit view, click and hold on the photo to temporarily inspect that point at
100 percent.

## 2. Split View

Press `\` to toggle split view. The left pane stays fit-to-window, and the
right pane is the zoom/focus pane. Press `Space` in split view to promote the
right pane into single-pane manual zoom.

## 3. AF Point

`Show AF point` is off by default. Turn it on from the top bar or press `F` to
show a red marker at the extracted autofocus point. If no focus point is
available, EasyLoupe falls back to the image center.

Press `Shift+F` in manual zoom to temporarily recenter on the AF point or image
center. Press `Ctrl+Shift+F` to reset remembered zoom centers while preserving
zoom levels.

## 4. EXIF And Histogram

Press `I` in normal culling view to show or hide the EXIF and RGB histogram
overlay. The overlay follows the current photo and hides automatically in
browse view, compare view, and busy progress states.

## 5. Clipping Warnings

Turn on `Show Clipping` from the top bar or press `J` to show highlight and
shadow clipping warnings. Red marks clipped highlights, and blue marks clipped
shadows.

The overlay may appear shortly after the photo because clipping analysis runs
in the background. Browse thumbnails do not show clipping warnings.

## 6. Visible-Region Minimap

While manually zoomed, the active strip thumbnail shows the visible region as a
red box with a darkened mask outside it. Click or drag inside that minimap to
recenter or pan the zoomed viewer.

In scene mode, the interactive minimap belongs on the horizontal scene strip
for the exact current photo. The left scene stack also shows it when the
current photo is the stack cover.
