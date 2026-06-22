"""Dialog helpers for organizer and XMP workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, cast

from PySide6.QtWidgets import (
    QAbstractButton,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from easy_loupe.operations.export import (
    ConflictPolicy,
    FlagFolderMode,
    FlagOrganizeFilesOptions,
    MetadataOrganizeFilesOptions,
    OrganizeAction,
    OrganizeCriterion,
    OrganizeFilesOptions,
)
from easy_loupe.operations.xmp import MergePolicy, WriteXmpOptions

if TYPE_CHECKING:
    from collections.abc import Sequence

OrganizerMode = Literal['reorganize', 'xmp']


@dataclass(slots=True, frozen=True)
class OrganizerDialogResult:
    """Selected organizer workflow and typed options."""

    mode: OrganizerMode
    organize_options: OrganizeFilesOptions | None = None
    xmp_options: WriteXmpOptions | None = None


class OrganizerDialog(QDialog):
    """Dialog for reorganizing files or writing shared XMP sidecars."""

    def __init__(
            self,
            parent: QWidget | None = None,
            *,
            current_folder: Path | None,
    ) -> None:
        super().__init__(parent)
        self._current_folder = current_folder
        self.setWindowTitle('Organize Photos')
        self.resize(680, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.mode_group = QButtonGroup(self)
        reorganize_section = self._build_reorganize_section()
        root.addWidget(reorganize_section)
        xmp_section = self._build_xmp_section()
        root.addWidget(xmp_section)
        root.addStretch(1)

        self.mode_group.buttonToggled.connect(self._handle_mode_toggled)
        self._sync_workflow_state()

        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            parent=self,
        )
        ok_button = self.button_box.button(QDialogButtonBox.Ok)
        if ok_button is not None:
            ok_button.setText('Start')
            ok_button.setDefault(True)

        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        root.addWidget(self.button_box)

    def selected_result(self) -> OrganizerDialogResult:
        """Build the typed workflow result from the current dialog state."""
        mode = self.current_mode()
        if mode == 'reorganize':
            output_parent_text = self.output_parent_edit.text().strip()
            output_parent = (
                Path(output_parent_text)
                if output_parent_text
                else self._current_folder
            )
            assert output_parent is not None
            criterion = cast(
                'OrganizeCriterion',
                self._selected_value(self.criterion_group),
            )
            action = cast(
                'OrganizeAction',
                self._selected_value(self.action_group),
            )
            conflict_policy = cast(
                'ConflictPolicy',
                self._selected_value(self.conflict_policy_group),
            )
            # Build the criterion-specific options here so disabled child
            # controls cannot leak stale, irrelevant values into the request.
            if criterion == 'flag':
                return OrganizerDialogResult(
                    mode='reorganize',
                    organize_options=FlagOrganizeFilesOptions(
                        criterion='flag',
                        action=action,
                        output_parent=output_parent,
                        flag_folder_mode=cast(
                            'FlagFolderMode',
                            self._selected_value(self.flag_folder_mode_group),
                        ),
                        conflict_policy=conflict_policy,
                        include_sidecars=True,
                    ),
                )

            return OrganizerDialogResult(
                mode='reorganize',
                organize_options=MetadataOrganizeFilesOptions(
                    criterion=criterion,
                    action=action,
                    output_parent=output_parent,
                    include_untagged=self._include_untagged_for(criterion),
                    conflict_policy=conflict_policy,
                    include_sidecars=True,
                ),
            )

        return OrganizerDialogResult(
            mode='xmp',
            xmp_options=WriteXmpOptions(
                merge_policy=cast(
                    'MergePolicy',
                    self._selected_value(self.merge_policy_group),
                )
            ),
        )

    def current_mode(self) -> OrganizerMode:
        """Return the selected organizer mode."""
        return cast('OrganizerMode', self._selected_value(self.mode_group))

    def accept(self) -> None:
        """Validate required fields before closing the dialog."""
        if self.current_mode() == 'reorganize':
            output_parent_text = self.output_parent_edit.text().strip()
            if not output_parent_text and self._current_folder is None:
                QMessageBox.warning(
                    self,
                    'Missing Output Folder',
                    'Choose an output parent folder before continuing.',
                )
                return

        super().accept()

    def _build_reorganize_section(self) -> QWidget:
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)

        reorganize_button = QRadioButton('Reorganize Files', section)
        reorganize_button.setProperty('option_value', 'reorganize')
        reorganize_button.setChecked(True)
        self.mode_group.addButton(reorganize_button, 0)
        section_layout.addWidget(reorganize_button)

        self.reorganize_box = QGroupBox(section)
        self.reorganize_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        box_layout = QVBoxLayout(self.reorganize_box)
        box_layout.setContentsMargins(12, 12, 12, 12)
        box_layout.setSpacing(10)

        criterion_box = self._build_criterion_group(self.reorganize_box)
        box_layout.addWidget(criterion_box)
        self.criterion_group.buttonToggled.connect(
            self._handle_criterion_toggled
        )

        action_box, self.action_group = self._build_boxed_radio_group(
            self.reorganize_box,
            (
                ('Copy Into Folders', 'copy'),
                ('Move Into Folders', 'move'),
            ),
            title='Action',
            orientation='horizontal',
        )
        box_layout.addWidget(action_box)

        output_parent_row = QWidget(self.reorganize_box)
        output_parent_layout = QHBoxLayout(output_parent_row)
        output_parent_layout.setContentsMargins(0, 0, 0, 0)
        output_parent_layout.setSpacing(8)
        self.output_parent_edit = QLineEdit(output_parent_row)
        self.output_parent_edit.setText(
            '' if self._current_folder is None else str(self._current_folder)
        )
        browse_button = QPushButton('Browse...', output_parent_row)
        browse_button.clicked.connect(self._browse_output_parent)
        output_parent_layout.addWidget(self.output_parent_edit, 1)
        output_parent_layout.addWidget(browse_button)

        output_box = QGroupBox('Output Parent Folder', self.reorganize_box)
        output_box_layout = QVBoxLayout(output_box)
        output_box_layout.setContentsMargins(12, 12, 12, 12)
        output_box_layout.setSpacing(8)
        output_box_layout.addWidget(output_parent_row)
        box_layout.addWidget(output_box)

        conflict_box, self.conflict_policy_group = (
            self._build_boxed_radio_group(
                self.reorganize_box,
                (
                    ('Fail Whole Run', 'fail'),
                    ('Skip Conflicts', 'skip'),
                    ('Overwrite Conflicts', 'overwrite'),
                ),
                title='Conflicts',
            )
        )
        box_layout.addWidget(conflict_box)
        section_layout.addWidget(self.reorganize_box)
        return section

    def _build_xmp_section(self) -> QWidget:
        section = QWidget(self)
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(0, 0, 0, 0)
        section_layout.setSpacing(6)

        xmp_button = QRadioButton('Write XMP', section)
        xmp_button.setProperty('option_value', 'xmp')
        self.mode_group.addButton(xmp_button, 1)
        section_layout.addWidget(xmp_button)

        self.xmp_box = QGroupBox(section)
        self.xmp_box.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        box_layout = QVBoxLayout(self.xmp_box)
        box_layout.setContentsMargins(12, 12, 12, 12)
        box_layout.setSpacing(10)

        merge_policy_box, self.merge_policy_group = (
            self._build_boxed_radio_group(
                self.xmp_box,
                (
                    ('Preserve and Update', 'preserve'),
                    ('Replace File', 'replace'),
                ),
                title='Merge Policy',
            )
        )
        box_layout.addWidget(merge_policy_box)

        summary_box = QGroupBox('XMP Fields', self.xmp_box)
        summary_box_layout = QVBoxLayout(summary_box)
        summary_box_layout.setContentsMargins(12, 12, 12, 12)
        summary_box_layout.setSpacing(8)
        summary = QLabel(
            'Writes shared PHOTO_ID.XMP sidecars with:\n'
            '- xmp:Rating\n'
            '- xmp:Label\n'
            '- xmpDM:good\n'
            '- xmpDM:pick\n'
            '- cap1:Flag',
            summary_box,
        )
        summary.setWordWrap(True)
        summary_box_layout.addWidget(summary)
        self.xmp_summary_label = summary
        box_layout.addWidget(summary_box)

        section_layout.addWidget(self.xmp_box)
        return section

    def _browse_output_parent(self) -> None:
        start_dir = self.output_parent_edit.text().strip()
        if not start_dir and self._current_folder is not None:
            start_dir = str(self._current_folder)

        selected = QFileDialog.getExistingDirectory(
            self, 'Choose Output Parent Folder', start_dir
        )
        if selected:
            self.output_parent_edit.setText(selected)

    def _build_criterion_group(self, parent: QWidget) -> QGroupBox:
        container = QGroupBox('Criterion', parent)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        self.criterion_group = QButtonGroup(container)
        flag_button = QRadioButton('By Picked/Rejected', container)
        flag_button.setProperty('option_value', 'flag')
        flag_button.setChecked(True)
        self.criterion_group.addButton(flag_button, 0)
        layout.addWidget(flag_button)

        self.flag_folder_mode_box = QWidget(container)
        flag_mode_layout = QVBoxLayout(self.flag_folder_mode_box)
        flag_mode_layout.setContentsMargins(20, 0, 0, 0)
        flag_mode_layout.setSpacing(4)
        self.flag_folder_mode_group = QButtonGroup(self.flag_folder_mode_box)
        flag_mode_options = (
            (
                '3 Folders: Picked / Rejected / Untagged',
                'picked_rejected_untagged',
            ),
            (
                (
                    '2 Folders: Picked / Rejected. '
                    '(Do nothing to untagged photos)'
                ),
                'picked_rejected',
            ),
            (
                '2 Folders: Picked / Others (including rejected and untagged)',
                'picked_others',
            ),
            (
                '2 Folders: Rejected / Others (including picked and untagged)',
                'rejected_others',
            ),
            (
                '1 Folder: Picked. (Do nothing to rejected and untagged)',
                'picked_only',
            ),
            (
                (
                    '1 Folder: Rejected. '
                    '(Do nothing to picked and untagged photos)'
                ),
                'rejected_only',
            ),
        )
        for index, (label, value) in enumerate(flag_mode_options):
            button = QRadioButton(label, self.flag_folder_mode_box)
            button.setProperty('option_value', value)
            self.flag_folder_mode_group.addButton(button, index)
            flag_mode_layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        layout.addWidget(self.flag_folder_mode_box)

        color_button = QRadioButton('By Color Label', container)
        color_button.setProperty('option_value', 'color_label')
        self.criterion_group.addButton(color_button, 1)
        layout.addWidget(color_button)
        self.color_include_untagged_box = QWidget(container)
        color_checkbox_layout = QVBoxLayout(self.color_include_untagged_box)
        color_checkbox_layout.setContentsMargins(20, 0, 0, 0)
        color_checkbox_layout.setSpacing(0)
        self.color_include_untagged_checkbox = QCheckBox(
            'Include untagged photos in "Untagged" folder',
            self.color_include_untagged_box,
        )
        color_checkbox_layout.addWidget(self.color_include_untagged_checkbox)
        layout.addWidget(self.color_include_untagged_box)

        rating_button = QRadioButton('By Rating', container)
        rating_button.setProperty('option_value', 'rating')
        self.criterion_group.addButton(rating_button, 2)
        layout.addWidget(rating_button)
        self.rating_include_untagged_box = QWidget(container)
        rating_checkbox_layout = QVBoxLayout(self.rating_include_untagged_box)
        rating_checkbox_layout.setContentsMargins(20, 0, 0, 0)
        rating_checkbox_layout.setSpacing(0)
        self.rating_include_untagged_checkbox = QCheckBox(
            'Include untagged photos in "Untagged" folder',
            self.rating_include_untagged_box,
        )
        rating_checkbox_layout.addWidget(self.rating_include_untagged_checkbox)
        layout.addWidget(self.rating_include_untagged_box)

        return container

    @staticmethod
    def _build_boxed_radio_group(
            parent: QWidget,
            options: Sequence[tuple[str, str]],
            *,
            title: str,
            orientation: Literal['vertical', 'horizontal'] = 'vertical',
    ) -> tuple[QGroupBox, QButtonGroup]:
        container = QGroupBox(title, parent)
        if orientation == 'horizontal':
            layout = QHBoxLayout(container)
        else:
            layout = QVBoxLayout(container)

        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)
        group = QButtonGroup(container)
        for index, (label, value) in enumerate(options):
            button = QRadioButton(label, container)
            button.setProperty('option_value', value)
            group.addButton(button, index)
            layout.addWidget(button)
            if index == 0:
                button.setChecked(True)

        return container, group

    @staticmethod
    def _selected_value(group: QButtonGroup) -> str:
        button = group.checkedButton()
        assert button is not None
        value = button.property('option_value')
        assert isinstance(value, str)
        return value

    @staticmethod
    def _button_with_value(group: QButtonGroup, value: str) -> QAbstractButton:
        for button in group.buttons():
            if button.property('option_value') == value:
                return button

        raise LookupError(f'No radio button registered for value {value!r}')

    def _handle_mode_toggled(
            self,
            _button: QAbstractButton,
            checked: bool,  # noqa: FBT001
    ) -> None:
        if checked:
            self._sync_workflow_state()

    def _handle_criterion_toggled(
            self,
            _button: QAbstractButton,
            checked: bool,  # noqa: FBT001
    ) -> None:
        if checked:
            self._sync_criterion_child_state()

    def _sync_workflow_state(self) -> None:
        is_reorganize = self.current_mode() == 'reorganize'
        self.reorganize_box.setEnabled(is_reorganize)
        self.xmp_box.setEnabled(not is_reorganize)
        # Reapply child state after parent mode toggles: Qt disables
        # descendants visually, but the selected criterion still controls
        # which child widgets become editable when re-enabled.
        self._sync_criterion_child_state()

    def _sync_criterion_child_state(self) -> None:
        is_reorganize = self.current_mode() == 'reorganize'
        criterion = self._selected_value(self.criterion_group)
        self.flag_folder_mode_box.setEnabled(
            is_reorganize and criterion == 'flag'
        )
        self.color_include_untagged_box.setEnabled(
            is_reorganize and criterion == 'color_label'
        )
        self.rating_include_untagged_box.setEnabled(
            is_reorganize and criterion == 'rating'
        )

    def _include_untagged_for(
            self,
            criterion: OrganizeCriterion,
    ) -> bool:
        """
        Return the criterion-scoped untagged option for file organization.

        Flag organizing now builds ``FlagOrganizeFilesOptions`` instead, so
        this helper only supplies the checkbox value for metadata criteria.
        """
        if criterion == 'color_label':
            return self.color_include_untagged_checkbox.isChecked()

        if criterion == 'rating':
            return self.rating_include_untagged_checkbox.isChecked()

        return False
