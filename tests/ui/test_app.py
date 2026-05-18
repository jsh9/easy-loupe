from __future__ import annotations

import easy_cull.ui as ui_package
import easy_cull.ui.main_window as ui_main_window_package
import easy_cull.ui.main_window.window as main_window_module
import easy_cull.ui.viewers as ui_viewers_package
import easy_cull.ui.viewers.exif_overlay as exif_overlay_module
import easy_cull.ui.viewers.main_photo_viewer as main_photo_viewer_module
import easy_cull.ui.viewers.photo_viewer as photo_viewer_module
import easy_cull.ui.widgets as widgets_module
import easy_cull.ui.workers as workers_module


def test_ui_packages_do_not_export_shortcuts() -> None:
    assert not hasattr(ui_package, 'MainWindow')
    assert not hasattr(ui_package, 'PhotoViewer')
    assert not hasattr(ui_package, 'ThumbnailPreviewWidget')
    assert not hasattr(ui_package, 'SceneDetectionWorker')
    assert not hasattr(ui_package, 'NO_METADATA_TEXT')
    assert not hasattr(ui_main_window_package, 'MainWindow')
    assert not hasattr(ui_viewers_package, 'PhotoViewer')
    assert not hasattr(ui_viewers_package, 'MainPhotoViewer')
    assert not hasattr(ui_viewers_package, 'ExifOverlayWidget')


def test_ui_modules_export_concrete_symbols() -> None:
    assert main_window_module.MainWindow.__name__ == 'MainWindow'
    assert photo_viewer_module.PhotoViewer.__name__ == 'PhotoViewer'
    assert (
        main_photo_viewer_module.MainPhotoViewer.__name__ == 'MainPhotoViewer'
    )
    assert (
        exif_overlay_module.ExifOverlayWidget.__name__ == 'ExifOverlayWidget'
    )
    assert (
        widgets_module.ThumbnailPreviewWidget.__name__
        == 'ThumbnailPreviewWidget'
    )
    assert (
        workers_module.SceneDetectionWorker.__name__ == 'SceneDetectionWorker'
    )
    assert workers_module.OperationWorker.__name__ == 'OperationWorker'
