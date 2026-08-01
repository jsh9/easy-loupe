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
    the old global untagged checkbox from drifting apart. It also locks the
    JPG/RAW split checkbox off by default so existing organizer runs keep their
    current output shape.
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
    assert dialog.split_jpg_raw_checkbox.text() == (
        'When applicable, put JPG and raw into separate folders'
    )
    assert dialog.split_jpg_raw_checkbox.isChecked() is False
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


def test_organizer_dialog_remembers_accepted_controls_not_output_parent(
        tmp_path: Path,
) -> None:
    """
    Verify every accepted control persists while the destination stays local.

    Organizer choices should survive new dialog instances and app restarts, but
    carrying an old output folder into another culling folder could route files
    to an unrelated destination. Inactive criterion controls are included so
    returning to a prior criterion also restores its last accepted choice.
    """
    app = QApplication.instance() or QApplication([])
    first_folder = tmp_path / 'first'
    second_folder = tmp_path / 'second'
    third_folder = tmp_path / 'third'
    first_folder.mkdir()
    second_folder.mkdir()
    third_folder.mkdir()

    dialog = OrganizerDialog(current_folder=first_folder)
    dialog._button_with_value(dialog.mode_group, 'xmp').setChecked(True)
    dialog._button_with_value(dialog.criterion_group, 'rating').setChecked(
        True
    )
    dialog._button_with_value(dialog.action_group, 'move').setChecked(True)
    dialog._button_with_value(
        dialog.flag_folder_mode_group, 'picked_only'
    ).setChecked(True)
    dialog.color_include_untagged_checkbox.setChecked(True)
    dialog.rating_include_untagged_checkbox.setChecked(True)
    dialog.split_jpg_raw_checkbox.setChecked(True)
    dialog._button_with_value(
        dialog.conflict_policy_group, 'overwrite'
    ).setChecked(True)
    dialog._button_with_value(dialog.merge_policy_group, 'replace').setChecked(
        True
    )
    dialog.output_parent_edit.setText(str(tmp_path / 'custom-output'))
    dialog.accept()

    restored = OrganizerDialog(current_folder=second_folder)

    assert restored.current_mode() == 'xmp'
    assert restored._selected_value(restored.criterion_group) == 'rating'
    assert restored._selected_value(restored.action_group) == 'move'
    assert (
        restored._selected_value(restored.flag_folder_mode_group)
        == 'picked_only'
    )
    assert restored.color_include_untagged_checkbox.isChecked() is True
    assert restored.rating_include_untagged_checkbox.isChecked() is True
    assert restored.split_jpg_raw_checkbox.isChecked() is True
    assert (
        restored._selected_value(restored.conflict_policy_group) == 'overwrite'
    )
    assert restored._selected_value(restored.merge_policy_group) == 'replace'
    assert restored.output_parent_edit.text() == str(second_folder)
    assert restored.reorganize_box.isEnabled() is False
    assert restored.xmp_box.isEnabled() is True

    restored._button_with_value(restored.mode_group, 'reorganize').setChecked(
        True
    )
    restored.accept()
    restored_again = OrganizerDialog(current_folder=third_folder)

    assert restored_again.current_mode() == 'reorganize'
    assert restored_again.flag_folder_mode_box.isEnabled() is False
    assert restored_again.color_include_untagged_box.isEnabled() is False
    assert restored_again.rating_include_untagged_box.isEnabled() is True
    assert restored_again.output_parent_edit.text() == str(third_folder)

    dialog.close()
    restored.close()
    restored_again.close()
    del app


def test_organizer_dialog_cancel_keeps_last_accepted_controls(
        tmp_path: Path,
) -> None:
    """
    Verify cancel discards control changes instead of persisting partial
    intent.

    Only pressing Start represents a configuration the user chose to run, so a
    later canceled dialog must not replace that last accepted configuration.
    """
    app = QApplication.instance() or QApplication([])
    accepted = OrganizerDialog(current_folder=tmp_path)
    accepted._button_with_value(accepted.action_group, 'move').setChecked(True)
    accepted.accept()

    canceled = OrganizerDialog(current_folder=tmp_path)
    canceled._button_with_value(canceled.action_group, 'copy').setChecked(True)
    canceled.reject()
    restored = OrganizerDialog(current_folder=tmp_path)

    assert restored._selected_value(restored.action_group) == 'move'

    accepted.close()
    canceled.close()
    restored.close()
    del app


def test_organizer_dialog_invalid_settings_fall_back_safely(
        tmp_path: Path,
) -> None:
    """
    Verify stale settings cannot select unsupported organizer configurations.

    Settings can outlive option changes or be edited outside EasyLoupe. Unknown
    radio values should preserve current defaults, while conventional boolean
    strings should normalize and invalid boolean values should become false.
    """
    app = QApplication.instance() or QApplication([])
    settings = OrganizerDialog._settings()
    for key in (
        'organizer/mode',
        'organizer/criterion',
        'organizer/action',
        'organizer/flag_folder_mode',
        'organizer/conflict_policy',
        'organizer/xmp_merge_policy',
    ):
        settings.setValue(key, 'unsupported')

    settings.setValue('organizer/color_include_untagged', 'yes')
    settings.setValue('organizer/rating_include_untagged', 'invalid')
    settings.setValue('organizer/split_jpg_raw', 'on')

    dialog = OrganizerDialog(current_folder=tmp_path)

    assert dialog.current_mode() == 'reorganize'
    assert dialog._selected_value(dialog.criterion_group) == 'flag'
    assert dialog._selected_value(dialog.action_group) == 'copy'
    assert (
        dialog._selected_value(dialog.flag_folder_mode_group)
        == 'picked_rejected_untagged'
    )
    assert dialog._selected_value(dialog.conflict_policy_group) == 'fail'
    assert dialog._selected_value(dialog.merge_policy_group) == 'preserve'
    assert dialog.color_include_untagged_checkbox.isChecked() is True
    assert dialog.rating_include_untagged_checkbox.isChecked() is False
    assert dialog.split_jpg_raw_checkbox.isChecked() is True
    assert dialog.flag_folder_mode_box.isEnabled() is True
    assert dialog.color_include_untagged_box.isEnabled() is False
    assert dialog.rating_include_untagged_box.isEnabled() is False

    dialog.close()
    del app


def test_organizer_dialog_selected_result_builds_typed_options(
        tmp_path: Path,
) -> None:
    """
    Verify criterion-specific child controls map into typed options.

    Rating/color results must omit flag folder modes, and flag results must
    omit untagged checkboxes, so callers cannot observe stale disabled-control
    state from another criterion. The JPG/RAW split option applies to every
    reorganize criterion, so this test verifies both typed request paths carry
    the shared checkbox state.
    """
    app = QApplication.instance() or QApplication([])
    dialog = OrganizerDialog(current_folder=tmp_path)
    dialog._button_with_value(dialog.criterion_group, 'rating').setChecked(
        True
    )
    dialog._button_with_value(dialog.action_group, 'move').setChecked(True)
    dialog.rating_include_untagged_checkbox.setChecked(True)
    dialog.split_jpg_raw_checkbox.setChecked(True)
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
    assert reorganize_result.organize_options.split_jpg_raw is True

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
    assert flag_result.organize_options.split_jpg_raw is True
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
    assert OrganizerDialog._settings().contains('organizer/mode') is False

    dialog.close()
    del app
