"""
Components dock panel for the Circuit Workbench GUI.

The panel has two parts:

- "New Part": pick a type, edit its value, and place it at the selected
  grid point.
- "Selected Part": shows the selected part and lets the user rotate it,
  change its value or delete it.

The panel only emits requests. MainWindow applies them to the
ComponentCollection and reports errors.
"""

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.components import COMPONENT_DEFINITIONS, Component
from core.exceptions import ComponentError

NO_PART_SELECTED_TEXT = "No part selected"


def has_value(kind):
    """
    Return whether a part kind takes a value (ground does not).

    :param kind: Component kind.
    :type kind: str
    :returns: True if the kind has a value or model.
    :rtype: bool
    """
    return COMPONENT_DEFINITIONS[kind]["value_kind"] != "none"


def describe_component(component):
    """
    Return the panel text for a part, for example
    "R1 (Resistor) at R4 C4, 90 deg".

    :param component: Part to describe.
    :type component: core.components.Component
    :returns: One-line description.
    :rtype: str
    """
    display_name = COMPONENT_DEFINITIONS[component.kind]["display_name"]

    return (
        f"{component.reference} ({display_name}) at "
        f"R{component.row_number} C{component.column_number}, "
        f"{component.rotation} deg"
    )


class ComponentPanelWidget(QWidget):
    """
    User controls for placing and editing parts.

    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    place_requested = pyqtSignal(str, str)
    rotate_requested = pyqtSignal()
    value_change_requested = pyqtSignal(str)
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.kind_combo_box = QComboBox()
        self.value_line_edit = QLineEdit()
        self.place_button = QPushButton("Place at Selected Point")

        self.selected_component_label = QLabel(NO_PART_SELECTED_TEXT)
        self.selected_value_line_edit = QLineEdit()
        self.rotate_button = QPushButton("Rotate 90")
        self.apply_value_button = QPushButton("Apply Value")
        self.delete_button = QPushButton("Delete Part")

        self.create_widget_layout()
        self.connect_widget_signals()

        self.handle_kind_change()
        self.show_component(None)

    def create_widget_layout(self):
        """
        Create all panel controls programmatically.

        :returns: None
        """
        # One entry per kind, in COMPONENT_DEFINITIONS order. The kind is
        # stored as item data so the display text can change freely.
        for kind, definition in COMPONENT_DEFINITIONS.items():
            self.kind_combo_box.addItem(definition["display_name"], kind)

        self.selected_component_label.setWordWrap(True)

        new_part_form = QFormLayout()
        new_part_form.addRow("Type:", self.kind_combo_box)
        new_part_form.addRow("Value:", self.value_line_edit)

        new_part_layout = QVBoxLayout()
        new_part_layout.addLayout(new_part_form)
        new_part_layout.addWidget(self.place_button)

        new_part_group = QGroupBox("New Part")
        new_part_group.setLayout(new_part_layout)

        selected_part_form = QFormLayout()
        selected_part_form.addRow("Value:", self.selected_value_line_edit)

        selected_part_buttons = QHBoxLayout()
        selected_part_buttons.addWidget(self.rotate_button)
        selected_part_buttons.addWidget(self.delete_button)

        selected_part_layout = QVBoxLayout()
        selected_part_layout.addWidget(self.selected_component_label)
        selected_part_layout.addLayout(selected_part_form)
        selected_part_layout.addWidget(self.apply_value_button)
        selected_part_layout.addLayout(selected_part_buttons)

        selected_part_group = QGroupBox("Selected Part")
        selected_part_group.setLayout(selected_part_layout)

        main_layout = QVBoxLayout()
        main_layout.addWidget(
            QLabel(
                "Click a grid point, choose a part and its value, then "
                "place it. Click a part to rotate, edit or delete it."
            )
        )
        main_layout.itemAt(0).widget().setWordWrap(True)
        main_layout.addWidget(new_part_group)
        main_layout.addWidget(selected_part_group)
        main_layout.addStretch(1)

        self.setLayout(main_layout)

    def connect_widget_signals(self):
        """
        Connect controls to the panel's request signals.

        :returns: None
        """
        self.kind_combo_box.currentIndexChanged.connect(self.handle_kind_change)
        self.place_button.clicked.connect(self.emit_place_request)
        self.value_line_edit.returnPressed.connect(self.emit_place_request)

        self.rotate_button.clicked.connect(self.rotate_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.apply_value_button.clicked.connect(
            self.emit_value_change_request
        )
        self.selected_value_line_edit.returnPressed.connect(
            self.emit_value_change_request
        )

    def get_selected_kind(self):
        """
        Return the kind chosen in the type box.

        :returns: Component kind, for example "resistor".
        :rtype: str
        """
        return self.kind_combo_box.currentData()

    def handle_kind_change(self):
        """
        Fill the value box with the new kind's default value.

        Ground has no value, so its value box is emptied and disabled.

        :returns: None
        """
        kind = self.get_selected_kind()
        definition = COMPONENT_DEFINITIONS[kind]

        self.value_line_edit.setText(definition["default_value_text"])
        self.value_line_edit.setEnabled(has_value(kind))

    def emit_place_request(self):
        """
        Request a new part of the chosen kind and value.

        :returns: None
        """
        self.place_requested.emit(
            self.get_selected_kind(),
            self.value_line_edit.text()
        )

    def emit_value_change_request(self):
        """
        Request a new value for the selected part.

        Does nothing when the button would be disabled (no part, or a part
        without a value), so pressing Enter cannot bypass it.

        :returns: None
        """
        if self.apply_value_button.isEnabled():
            self.value_change_requested.emit(
                self.selected_value_line_edit.text()
            )

    def show_component(self, component):
        """
        Show the selected part, or none.

        :param component: Selected part, or None.
        :type component: core.components.Component or None
        :returns: None
        :raises ComponentError: If component is neither None nor a
            Component.
        """
        if component is not None and not isinstance(component, Component):
            raise ComponentError(
                f"show_component needs a Component or None, not "
                f"{component!r}."
            )

        if component is None:
            self.selected_component_label.setText(NO_PART_SELECTED_TEXT)
            self.selected_value_line_edit.clear()
            part_has_value = False
        else:
            self.selected_component_label.setText(
                describe_component(component)
            )
            self.selected_value_line_edit.setText(component.value_text)
            part_has_value = has_value(component.kind)

        self.rotate_button.setEnabled(component is not None)
        self.delete_button.setEnabled(component is not None)
        self.selected_value_line_edit.setEnabled(part_has_value)
        self.apply_value_button.setEnabled(part_has_value)
