from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from easy_loupe.ui.main_window.dialogs import OrganizerDialog

if TYPE_CHECKING:
    from pathlib import Path


def test_organizer_dialog_defaults_and_mode_switch(tmp_path: Path) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)

    assert dialog.current_mode() == 'reorganize'
    assert (
        dialog.button_box.button(QDialogButtonBox.StandardButton.Ok).text()
        == 'Start'
    )
    assert dialog.reorganize_box.isEnabled() is True
    assert dialog.xmp_box.isEnabled() is False
    assert (
        dialog._button_with_value(dialog.criterion_group, 'flag').text()
        == 'By Picked/Rejected'
    )
    assert dialog.output_parent_edit.text() == str(tmp_path)
    assert dialog._selected_value(dialog.conflict_policy_group) == 'fail'

    dialog._button_with_value(dialog.mode_group, 'xmp').setChecked(True)

    assert dialog.current_mode() == 'xmp'
    assert dialog.reorganize_box.isEnabled() is False
    assert dialog.xmp_box.isEnabled() is True
    assert dialog._selected_value(dialog.merge_policy_group) == 'preserve'
    assert dialog._button_with_value(
        dialog.merge_policy_group, 'preserve'
    ).isChecked()

    dialog.close()
    del app


def test_organizer_dialog_selected_result_builds_typed_options(
        tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)
    dialog._button_with_value(dialog.criterion_group, 'rating').setChecked(
        True
    )
    dialog._button_with_value(dialog.action_group, 'move').setChecked(True)
    dialog.include_untagged_checkbox.setChecked(True)
    dialog._button_with_value(
        dialog.conflict_policy_group, 'overwrite'
    ).setChecked(True)

    reorganize_result = dialog.selected_result()

    assert reorganize_result.mode == 'reorganize'
    assert reorganize_result.organize_options is not None
    assert reorganize_result.organize_options.criterion == 'rating'
    assert reorganize_result.organize_options.action == 'move'
    assert reorganize_result.organize_options.include_untagged is True
    assert reorganize_result.organize_options.conflict_policy == 'overwrite'
    assert reorganize_result.organize_options.output_parent == tmp_path

    dialog._button_with_value(dialog.mode_group, 'xmp').setChecked(True)
    xmp_result = dialog.selected_result()

    assert xmp_result.mode == 'xmp'
    assert xmp_result.xmp_options is not None
    assert xmp_result.xmp_options.merge_policy == 'preserve'

    dialog.close()
    del app


def test_organizer_dialog_groups_remain_mutually_exclusive(
        tmp_path: Path,
) -> None:
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)

    picked_button = dialog._button_with_value(dialog.criterion_group, 'flag')
    rating_button = dialog._button_with_value(dialog.criterion_group, 'rating')
    assert picked_button.isChecked() is True

    rating_button.setChecked(True)

    assert rating_button.isChecked() is True
    assert picked_button.isChecked() is False

    dialog.close()
    del app


def test_organizer_dialog_validates_missing_output_folder() -> None:
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=None)
    dialog.output_parent_edit.clear()
    warnings: list[tuple[str, str]] = []
    original_warning = QMessageBox.warning
    QMessageBox.warning = lambda _parent, title, text: warnings.append((
        title,
        text,
    ))
    try:
        dialog.accept()
    finally:
        QMessageBox.warning = original_warning

    assert warnings == [
        (
            'Missing Output Folder',
            'Choose an output parent folder before continuing.',
        )
    ]

    dialog.close()
    del app
