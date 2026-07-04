from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from easy_loupe.operations.export import (
    FlagOrganizeFilesOptions,
    MetadataOrganizeFilesOptions,
)
from easy_loupe.ui.main_window.dialogs import OrganizerDialog

if TYPE_CHECKING:
    from pathlib import Path


def test_organizer_dialog_defaults_and_mode_switch(tmp_path: Path) -> None:
    """
    Verify organizer defaults match the user-facing folder-mode contract.

    The dialog is the only place that maps exact labels to backend option
    values, so this protects defaults, disabled child controls, and removal of
    the old global untagged checkbox from drifting apart.
    """
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
    assert (
        dialog._selected_value(dialog.flag_folder_mode_group)
        == 'picked_rejected_untagged'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'picked_rejected_untagged',
        ).text()
        == '3 Folders: Picked / Rejected / Untagged'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'picked_rejected',
        ).text()
        == '2 Folders: Picked / Rejected. '
        '(Do nothing to untagged photos)'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'picked_others',
        ).text()
        == '2 Folders: Picked / Not picked'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'rejected_others',
        ).text()
        == '2 Folders: Rejected / Not rejected'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'picked_only',
        ).text()
        == '1 Folder: Picked. '
        '(Do nothing to rejected and untagged)'
    )
    assert (
        dialog._button_with_value(
            dialog.flag_folder_mode_group,
            'rejected_only',
        ).text()
        == '1 Folder: Rejected. '
        '(Do nothing to picked and untagged photos)'
    )
    assert dialog.flag_folder_mode_box.isEnabled() is True
    assert dialog.color_include_untagged_checkbox.isEnabled() is False
    assert dialog.rating_include_untagged_checkbox.isEnabled() is False
    assert dialog.color_include_untagged_checkbox.isChecked() is False
    assert dialog.rating_include_untagged_checkbox.isChecked() is False
    assert hasattr(dialog, 'include_untagged_checkbox') is False
    assert dialog.output_parent_edit.text() == str(tmp_path)
    assert dialog._selected_value(dialog.conflict_policy_group) == 'fail'

    dialog._button_with_value(dialog.mode_group, 'xmp').setChecked(True)

    assert dialog.current_mode() == 'xmp'
    assert dialog.reorganize_box.isEnabled() is False
    assert dialog.xmp_box.isEnabled() is True
    assert dialog.flag_folder_mode_box.isEnabled() is False
    assert dialog.color_include_untagged_checkbox.isEnabled() is False
    assert dialog.rating_include_untagged_checkbox.isEnabled() is False
    assert dialog._selected_value(dialog.merge_policy_group) == 'preserve'
    assert dialog._button_with_value(
        dialog.merge_policy_group, 'preserve'
    ).isChecked()

    dialog.close()
    del app


def test_organizer_dialog_selected_result_builds_typed_options(
        tmp_path: Path,
) -> None:
    """
    Verify criterion-specific child controls map into typed options.

    Rating/color results must omit flag folder modes, and flag results must
    omit untagged checkboxes, so callers cannot observe stale disabled-control
    state from another criterion.
    """
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)
    dialog._button_with_value(dialog.criterion_group, 'rating').setChecked(
        True
    )
    dialog._button_with_value(dialog.action_group, 'move').setChecked(True)
    dialog.rating_include_untagged_checkbox.setChecked(True)
    dialog._button_with_value(
        dialog.conflict_policy_group, 'overwrite'
    ).setChecked(True)

    reorganize_result = dialog.selected_result()

    assert reorganize_result.mode == 'reorganize'
    assert reorganize_result.organize_options is not None
    assert isinstance(
        reorganize_result.organize_options,
        MetadataOrganizeFilesOptions,
    )
    assert reorganize_result.organize_options.criterion == 'rating'
    assert reorganize_result.organize_options.action == 'move'
    assert (
        hasattr(reorganize_result.organize_options, 'flag_folder_mode')
        is False
    )
    assert reorganize_result.organize_options.include_untagged is True
    assert reorganize_result.organize_options.conflict_policy == 'overwrite'
    assert reorganize_result.organize_options.output_parent == tmp_path

    dialog._button_with_value(dialog.criterion_group, 'flag').setChecked(True)
    dialog._button_with_value(
        dialog.flag_folder_mode_group, 'picked_others'
    ).setChecked(True)
    flag_result = dialog.selected_result()

    assert flag_result.organize_options is not None
    assert isinstance(
        flag_result.organize_options,
        FlagOrganizeFilesOptions,
    )
    assert flag_result.organize_options.criterion == 'flag'
    assert flag_result.organize_options.flag_folder_mode == 'picked_others'
    assert hasattr(flag_result.organize_options, 'include_untagged') is False

    dialog._button_with_value(dialog.mode_group, 'xmp').setChecked(True)
    xmp_result = dialog.selected_result()

    assert xmp_result.mode == 'xmp'
    assert xmp_result.xmp_options is not None
    assert xmp_result.xmp_options.merge_policy == 'preserve'

    dialog.close()
    del app


def test_organizer_dialog_criterion_children_follow_parent_selection(
        tmp_path: Path,
) -> None:
    """
    Verify only the selected criterion's child controls are editable.

    Disabled child controls can keep checked state in Qt, so this guards
    against users accidentally applying an option owned by another criterion.
    """
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)

    color_button = dialog._button_with_value(
        dialog.criterion_group, 'color_label'
    )
    rating_button = dialog._button_with_value(dialog.criterion_group, 'rating')

    color_button.setChecked(True)

    assert dialog.flag_folder_mode_box.isEnabled() is False
    assert dialog.color_include_untagged_checkbox.isEnabled() is True
    assert dialog.rating_include_untagged_checkbox.isEnabled() is False

    rating_button.setChecked(True)

    assert dialog.flag_folder_mode_box.isEnabled() is False
    assert dialog.color_include_untagged_checkbox.isEnabled() is False
    assert dialog.rating_include_untagged_checkbox.isEnabled() is True

    dialog.close()
    del app


def test_organizer_dialog_groups_remain_mutually_exclusive(
        tmp_path: Path,
) -> None:
    """
    Verify the custom criterion group keeps radio-button exclusivity.

    The criterion UI no longer comes from the shared boxed-group helper, so
    this preserves the original single-criterion selection contract.
    """
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
