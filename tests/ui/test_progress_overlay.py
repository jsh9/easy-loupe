from __future__ import annotations

from PySide6.QtWidgets import QApplication, QLabel, QWidget

from easy_loupe.progress import ProgressSnapshot, ProgressStageSnapshot
from easy_loupe.ui.progress_overlay import (
    ProgressOverlayController,
    build_progress_overlay,
)


def test_progress_overlay_controller_switches_scalar_and_stage_rows() -> None:
    """
    Verify the shared controller owns scalar/snapshot overlay transitions.

    MainWindow and PhotoViewerWindow both rely on this behavior to keep
    structured rows visible after snapshots and to reset cleanly after hide.
    """
    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    parent.resize(640, 480)
    parent.show()
    widgets = build_progress_overlay(parent)
    geometry_updates: list[str] = []
    controller = ProgressOverlayController(
        widgets,
        update_geometry=lambda: geometry_updates.append('updated'),
    )

    controller.show_scalar('Loading', 42, max_value=100)
    app.processEvents()

    assert widgets.overlay.isVisible() is True
    assert widgets.progress_bar.isVisible() is True
    assert widgets.progress_bar.value() == 42
    assert widgets.stage_list.isHidden() is True

    snapshot = ProgressSnapshot(
        workflow_label='Loading folder',
        current_message='Preparing thumbnails',
        overall_progress=150,
        stages=(
            ProgressStageSnapshot(
                'thumbnails',
                'Preparing thumbnails',
                current=1,
                total=2,
                status='active',
            ),
        ),
    )
    controller.show_snapshot(snapshot)
    app.processEvents()

    label_texts = {
        label.text()
        for label in widgets.stage_list.findChildren(QLabel)
        if label.text()
    }
    assert widgets.progress_bar.isHidden() is True
    assert widgets.stage_list.isVisible() is True
    assert 'Preparing thumbnails' in label_texts
    assert '1 of 2' in label_texts
    assert controller.has_structured_rows() is True

    controller.set_message_preserving_rows('Done building rows')
    assert widgets.message_label.text() == 'Done building rows'
    assert widgets.stage_list.isVisible() is True

    controller.hide()
    assert widgets.overlay.isHidden() is True
    assert widgets.progress_bar.isHidden() is False
    assert widgets.progress_bar.maximum() == 100
    assert widgets.progress_bar.value() == 0
    assert widgets.message_label.text() == ''
    assert widgets.stage_list.isHidden() is True
    assert geometry_updates

    parent.close()
