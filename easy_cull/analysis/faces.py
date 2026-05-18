"""
Face detection and auto-zoom focus hint.

Planned feature:
- Uses YOLO (or similar) to detect faces in photos.
- Returns bounding boxes as normalized (x, y, w, h) tuples.
- Provides a focus hint (centroid of detected faces) to override EXIF focus.
- Optional: auto-zoom the viewer to the primary face region.
"""
