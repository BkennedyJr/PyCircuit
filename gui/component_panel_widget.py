"""
Components dock panel for the Circuit Workbench GUI.

The panel has two parts:

- "New Part": pick a discrete part, or an IC from the library
  (a family, then a device). Place uses whichever list you picked
  last. Edit the value, then place it at the selected grid point.
- "Selected Part": shows the selected part and lets the user rotate it,
  change its name or value, or delete it.

Kinds with extra settings (the AC source's frequency) get one more row in
each part; the row is hidden for every other kind.

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
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.components import (
    COMPONENT_DEFINITIONS,
    Component,
    follow_choice_model,
    get_panel_parameter_definitions,
)
from core.exceptions import ComponentError
from core.ic_library import IC_FAMILIES, kinds_in_family, part_kinds

NO_PART_SELECTED_TEXT = "No part selected"


def get_all_panel_parameters():
    """
    Return every panel setting of any kind, once each, in table order.

    :returns: Mapping of parameter name to its definition.
    :rtype: dict
    """
    parameters = {}

    for kind in COMPONENT_DEFINITIONS:
        for parameter in get_panel_parameter_definitions(kind):
            parameters.setdefault(parameter["name"], parameter)

    return parameters


def get_value_field_label(kind):
    """
    Return the label of the value row, for example "Peak amplitude (V):".

    :param kind: Component kind.
    :type kind: str
    :returns: Label text ending in a colon.
    :rtype: str
    """
    definition = COMPONENT_DEFINITIONS[kind]
    label_text = definition.get("value_label", "Value")
    unit_text = definition.get("value_unit", "")

    if unit_text:
        return f"{label_text} ({unit_text}):"

    return f"{label_text}:"


def get_parameter_field_label(parameter):
    """
    Return the label of a setting row, for example "Frequency (Hz):".

    :param parameter: Parameter definition.
    :type parameter: dict
    :returns: Label text ending in a colon.
    :rtype: str
    """
    if not parameter["unit"]:
        return f"{parameter['display_name']}:"

    return f"{parameter['display_name']} ({parameter['unit']}):"


def create_parameter_field(parameter):
    """
    Create the input for one setting: a dropdown for a choice (the LED
    color), otherwise a text box.

    :param parameter: Parameter definition.
    :type parameter: dict
    :returns: New QComboBox or QLineEdit.
    :rtype: QWidget
    """
    if parameter["value_kind"] != "choice":
        return QLineEdit()

    combo_box = QComboBox()

    for choice in parameter["choices"]:
        combo_box.addItem(choice.capitalize(), choice)

    return combo_box


def get_field_text(field):
    """
    Return the text of a setting field (a dropdown's choice, lower case).

    :param field: QComboBox or QLineEdit.
    :returns: Text to send to core.
    :rtype: str
    """
    if isinstance(field, QComboBox):
        return field.currentData() or ""

    return field.text()


def set_field_text(field, text):
    """
    Show a setting's text in its field.

    :param field: QComboBox or QLineEdit.
    :param text: Stored text, for example "1k" or "green".
    :type text: str
    :returns: None
    """
    if isinstance(field, QComboBox):
        field.setCurrentIndex(max(field.findData(text), 0))
    else:
        field.setText(text)


def clear_field(field):
    """
    Empty a text box; a dropdown goes back to its first choice.

    :returns: None
    """
    if isinstance(field, QComboBox):
        field.setCurrentIndex(0)
    else:
        field.clear()


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


def keep_combo_names_visible(combo, texts):
    """
    Keep every name in a dropdown fully visible.

    The IC library sits in a group box, so its lists are narrower than
    the Type list. Without a floor they clip, and a short dock can also
    squash the line so a "p" loses its tail.

    :param combo: Dropdown to size.
    :type combo: QComboBox
    :param texts: Names that must fit, including ones filled in later.
    :type texts: list
    :returns: None
    """
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    metrics = combo.fontMetrics()
    widest = max(metrics.horizontalAdvance(text) for text in texts)
    combo.setMinimumWidth(max(combo.sizeHint().width(), widest + 36))
    combo.setMinimumHeight(combo.sizeHint().height())


class ComponentPanelWidget(QWidget):
    """
    User controls for placing and editing parts.

    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    # (kind, value text, {setting name: text}) and (value text, settings).
    # The settings dictionary only holds the kind's panel settings.
    place_requested = pyqtSignal(str, str, dict)
    rotate_requested = pyqtSignal()
    value_change_requested = pyqtSignal(str, dict)
    delete_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        self.kind_combo_box = QComboBox()
        self.kind_combo_box.setToolTip(
            "Discrete parts, the follower, and the amplifier blocks."
        )
        self.ic_family_combo = QComboBox()
        self.ic_family_combo.setToolTip(
            "Groups of packaged ICs. Picking a family chooses its first "
            "device, and that is what Place uses."
        )
        self.ic_device_combo = QComboBox()
        self.ic_device_combo.setToolTip(
            "One device in the family above. Picking it is what Place uses."
        )
        self.place_source_label = QLabel("Placing from parts:")
        self.place_source_label.setWordWrap(True)
        # True while Place reads the IC library instead of the Type list.
        self.placing_from_library = False
        self.filling_devices = False
        self.value_label = QLabel("Value:")
        self.value_line_edit = QLineEdit()
        self.place_button = QPushButton("Place at Selected Point")
        self.place_button.setToolTip(
            "Shows the part at the selected point, cyan where it fits and "
            "red where it can't go. Arrow keys or W/A/S/D turn it, "
            "clicking another point moves it, Enter or a right-click "
            "places it, Esc cancels."
        )

        # Kind of the part shown in "Selected Part", or None.
        self.selected_component_kind = None
        # The part show_component last showed (a Selected Part choice is
        # only applied when it differs from this part's).
        self.selected_component = None
        self.selected_component_label = QLabel(NO_PART_SELECTED_TEXT)
        self.selected_name_line_edit = QLineEdit()
        self.selected_name_line_edit.setToolTip(
            "Schematic name, for example BATT. The netlist adds the part "
            "letter when the name does not already start with it, so a "
            "battery named BATT is VBATT."
        )
        self.selected_value_label = QLabel("Value:")
        self.selected_value_line_edit = QLineEdit()

        # One label and field per setting name, in both groups. The
        # fields are QLineEdits, or QComboBoxes for choices (LED color);
        # the dictionaries keep their old names.
        self.parameter_labels = {}
        self.parameter_line_edits = {}
        self.selected_parameter_labels = {}
        self.selected_parameter_line_edits = {}

        for name, parameter in get_all_panel_parameters().items():
            field_label = get_parameter_field_label(parameter)
            self.parameter_labels[name] = QLabel(field_label)
            self.parameter_line_edits[name] = create_parameter_field(
                parameter
            )
            self.selected_parameter_labels[name] = QLabel(field_label)
            self.selected_parameter_line_edits[name] = create_parameter_field(
                parameter
            )

        self.rotate_button = QPushButton("Rotate 90")
        self.apply_value_button = QPushButton("Apply")
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
        # Discrete parts and functional blocks, in definition order. The
        # kind is stored as item data so the display text can change.
        # Packaged ICs are in the library below, not in this list.
        for kind in part_kinds():
            definition = COMPONENT_DEFINITIONS[kind]
            self.kind_combo_box.addItem(definition["display_name"], kind)

        for family_id, label, _kinds in IC_FAMILIES:
            self.ic_family_combo.addItem(label, family_id)

        self.fill_device_combo(IC_FAMILIES[0][0])

        self.selected_component_label.setWordWrap(True)

        type_form = QFormLayout()
        type_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        type_form.addRow("Type:", self.kind_combo_box)

        library_form = QFormLayout()
        library_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        library_form.addRow("Family:", self.ic_family_combo)
        library_form.addRow("Device:", self.ic_device_combo)
        library_group = QGroupBox("IC Library")
        library_group.setLayout(library_form)

        new_part_form = QFormLayout()
        new_part_form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        new_part_form.addRow(self.value_label, self.value_line_edit)

        for name, line_edit in self.parameter_line_edits.items():
            new_part_form.addRow(self.parameter_labels[name], line_edit)

        new_part_layout = QVBoxLayout()
        new_part_layout.addLayout(type_form)
        new_part_layout.addWidget(library_group)
        new_part_layout.addWidget(self.place_source_label)
        new_part_layout.addLayout(new_part_form)
        new_part_layout.addWidget(self.place_button)

        new_part_group = QGroupBox("New Part")
        new_part_group.setLayout(new_part_layout)

        selected_part_form = QFormLayout()
        selected_part_form.setFieldGrowthPolicy(
            QFormLayout.AllNonFixedFieldsGrow
        )
        selected_part_form.addRow("Name:", self.selected_name_line_edit)
        selected_part_form.addRow(
            self.selected_value_label,
            self.selected_value_line_edit
        )

        for name, line_edit in self.selected_parameter_line_edits.items():
            selected_part_form.addRow(
                self.selected_parameter_labels[name],
                line_edit
            )

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
                "Click a grid point, choose a part or an IC, then place "
                "it. Click a part to rotate, edit or delete it."
            )
        )
        main_layout.itemAt(0).widget().setWordWrap(True)
        main_layout.addWidget(new_part_group)
        main_layout.addWidget(selected_part_group)
        main_layout.addStretch(1)

        self.setLayout(main_layout)
        # Stay at the size the names need. A short dock scrolls instead
        # of squashing the lists.
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        keep_combo_names_visible(
            self.kind_combo_box,
            [
                COMPONENT_DEFINITIONS[kind]["display_name"]
                for kind in part_kinds()
            ],
        )
        keep_combo_names_visible(
            self.ic_family_combo,
            [label for _family_id, label, _kinds in IC_FAMILIES],
        )
        keep_combo_names_visible(
            self.ic_device_combo,
            [
                COMPONENT_DEFINITIONS[kind]["display_name"]
                for _family_id, _label, kinds in IC_FAMILIES
                for kind in kinds
            ],
        )

    def connect_widget_signals(self):
        """
        Connect controls to the panel's request signals.

        :returns: None
        """
        self.kind_combo_box.currentIndexChanged.connect(
            self.handle_kind_change
        )
        # activated fires even when the user re-picks the current item,
        # so choosing the part that is already showing leaves the library.
        self.kind_combo_box.activated.connect(self.handle_kind_change)
        self.ic_family_combo.currentIndexChanged.connect(
            self.handle_family_change
        )
        self.ic_family_combo.activated.connect(self.handle_family_change)
        self.ic_device_combo.currentIndexChanged.connect(
            self.handle_device_change
        )
        self.ic_device_combo.activated.connect(self.handle_device_change)
        self.place_button.clicked.connect(self.emit_place_request)
        self.value_line_edit.returnPressed.connect(self.emit_place_request)

        self.rotate_button.clicked.connect(self.rotate_requested.emit)
        self.delete_button.clicked.connect(self.delete_requested.emit)
        self.apply_value_button.clicked.connect(
            self.emit_value_change_request
        )
        self.selected_name_line_edit.returnPressed.connect(
            self.emit_value_change_request
        )
        self.selected_value_line_edit.returnPressed.connect(
            self.emit_value_change_request
        )

        for name, field in self.parameter_line_edits.items():
            if isinstance(field, QComboBox):
                field.currentIndexChanged.connect(
                    lambda unused_index, setting=name:
                    self.handle_new_part_choice_change(setting)
                )
            else:
                field.returnPressed.connect(self.emit_place_request)

        for name, field in self.selected_parameter_line_edits.items():
            if isinstance(field, QComboBox):
                # Picking a color applies at once (with the value box).
                field.activated.connect(
                    lambda index, setting=name:
                    self.handle_selected_choice_activated(setting, index)
                )
            else:
                field.returnPressed.connect(self.emit_value_change_request)

    def handle_selected_choice_activated(self, name, index):
        """
        Apply a Selected Part choice (the LED color) when it changes.

        Re-picking the part's current choice sends nothing, so the project
        is not marked modified, unless the value box was also edited.

        :param name: Setting name, for example "color".
        :type name: str
        :param index: Index of the picked item.
        :type index: int
        :returns: None
        """
        component = self.selected_component

        if component is not None:
            picked = self.selected_parameter_line_edits[name].itemData(index)
            value_text = self.selected_value_line_edit.text().strip()

            name_text = self.selected_name_line_edit.text().strip()

            if (picked == component.parameter_texts.get(name) and
                    value_text == component.value_text and
                    name_text == component.reference):
                return

        self.emit_value_change_request()

    def handle_new_part_choice_change(self, name):
        """
        Let the New Part model box follow a choice (the LED color).

        If the box still holds the previous choice's default model, it
        shows the new choice's model; a model the user typed is kept.

        :param name: Setting name, for example "color".
        :type name: str
        :returns: None
        """
        kind = self.get_selected_kind()
        field = self.parameter_line_edits[name]
        previous_choice = field.property("previous_choice")
        new_choice = get_field_text(field)

        # No current item (setCurrentIndex(-1)): nothing to follow, and
        # the last real choice is kept for the next pick.
        if not new_choice:
            return

        field.setProperty("previous_choice", new_choice)

        if previous_choice is None or kind is None:
            return

        follow = COMPONENT_DEFINITIONS[kind].get("model_follows_choice")

        if follow is None or follow[0] != name:
            return

        self.value_line_edit.setText(
            follow_choice_model(
                kind, self.value_line_edit.text().strip(),
                {name: previous_choice}, {name: new_choice}
            )
        )

    def get_selected_kind(self):
        """
        Return the kind Place will use.

        That is the IC device when the library was picked last, and the
        Type list otherwise.

        :returns: Component kind, for example "resistor".
        :rtype: str
        """
        if self.placing_from_library:
            return self.ic_device_combo.currentData()

        return self.kind_combo_box.currentData()

    def fill_device_combo(self, family_id):
        """
        Show one family's devices. Does not change what Place uses.

        :param family_id: Family id, for example "opamps".
        :type family_id: str
        :returns: None
        """
        self.filling_devices = True
        self.ic_device_combo.blockSignals(True)
        self.ic_device_combo.clear()

        for kind in kinds_in_family(family_id):
            self.ic_device_combo.addItem(
                COMPONENT_DEFINITIONS[kind]["display_name"], kind
            )

        self.ic_device_combo.blockSignals(False)
        self.filling_devices = False

    def update_place_caption(self):
        """
        Say whether Place is using the Type list or the IC library.

        :returns: None
        """
        kind = self.get_selected_kind()
        name = COMPONENT_DEFINITIONS[kind]["display_name"]

        if self.placing_from_library:
            self.place_source_label.setText(
                f"Placing from IC library: {name}"
            )
        else:
            self.place_source_label.setText(f"Placing from parts: {name}")

    def handle_kind_change(self):
        """
        Use the Type list for Place and fill that part's default value.

        :returns: None
        """
        kind = self.kind_combo_box.currentData()

        if kind is None:
            return

        self.placing_from_library = False
        self.show_kind_fields(kind)

    def handle_family_change(self):
        """
        Show the picked family's devices and use the first one for Place.

        :returns: None
        """
        family_id = self.ic_family_combo.currentData()

        if family_id is None:
            return

        # Re-picking the family that is already showing keeps its device
        # and only switches Place over to the library.
        shown = tuple(
            self.ic_device_combo.itemData(index)
            for index in range(self.ic_device_combo.count())
        )

        if shown != kinds_in_family(family_id):
            self.fill_device_combo(family_id)

        self.placing_from_library = True
        self.show_kind_fields(self.ic_device_combo.currentData())

    def handle_device_change(self):
        """
        Use the picked IC for Place.

        :returns: None
        """
        if self.filling_devices:
            return

        kind = self.ic_device_combo.currentData()

        if kind is None:
            return

        self.placing_from_library = True
        self.show_kind_fields(kind)

    def show_kind_fields(self, kind):
        """
        Fill the value box with one kind's default value.

        Ground has no value, so its value box is emptied and disabled. Only
        the kind's own settings rows are shown, filled with defaults.

        :param kind: Component kind Place will use.
        :type kind: str
        :returns: None
        """
        definition = COMPONENT_DEFINITIONS[kind]

        self.value_label.setText(get_value_field_label(kind))
        self.value_line_edit.setText(definition["default_value_text"])
        self.value_line_edit.setEnabled(has_value(kind))

        kind_parameters = {
            parameter["name"]: parameter
            for parameter in get_panel_parameter_definitions(kind)
        }

        for name, line_edit in self.parameter_line_edits.items():
            is_shown = name in kind_parameters
            self.parameter_labels[name].setVisible(is_shown)
            line_edit.setVisible(is_shown)

            if is_shown:
                # Set the default first, without the model following it.
                line_edit.blockSignals(True)
                set_field_text(
                    line_edit, kind_parameters[name]["default_value_text"]
                )
                line_edit.blockSignals(False)
                line_edit.setProperty(
                    "previous_choice", get_field_text(line_edit)
                )

        self.update_place_caption()

    @staticmethod
    def collect_parameter_texts(kind, line_edits):
        """
        Read the settings boxes that belong to one kind.

        :param kind: Component kind.
        :type kind: str
        :param line_edits: Boxes keyed by setting name.
        :type line_edits: dict
        :returns: {setting name: text} for the kind's panel settings.
        :rtype: dict
        """
        return {
            parameter["name"]: get_field_text(line_edits[parameter["name"]])
            for parameter in get_panel_parameter_definitions(kind)
        }

    def emit_place_request(self):
        """
        Request a new part of the chosen kind, value and settings.

        :returns: None
        """
        kind = self.get_selected_kind()

        self.place_requested.emit(
            kind,
            self.value_line_edit.text(),
            self.collect_parameter_texts(kind, self.parameter_line_edits)
        )

    def emit_value_change_request(self):
        """
        Request a new value for the selected part.

        Does nothing when the button would be disabled (no part selected),
        so pressing Enter cannot bypass it. The name is read by the window
        from the name box when this request is applied.

        :returns: None
        """
        if self.apply_value_button.isEnabled():
            self.value_change_requested.emit(
                self.selected_value_line_edit.text(),
                self.collect_parameter_texts(
                    self.selected_component_kind,
                    self.selected_parameter_line_edits
                )
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

        shown_names = set()

        self.selected_component = component

        if component is None:
            self.selected_component_kind = None
            self.selected_component_label.setText(NO_PART_SELECTED_TEXT)
            self.selected_name_line_edit.clear()
            self.selected_value_label.setText("Value:")
            self.selected_value_line_edit.clear()
            part_has_value = False
        else:
            self.selected_component_kind = component.kind
            self.selected_component_label.setText(
                describe_component(component)
            )
            self.selected_name_line_edit.setText(component.reference)
            self.selected_value_label.setText(
                get_value_field_label(component.kind)
            )
            self.selected_value_line_edit.setText(component.value_text)
            part_has_value = has_value(component.kind)

            for parameter in get_panel_parameter_definitions(component.kind):
                name = parameter["name"]
                shown_names.add(name)
                set_field_text(
                    self.selected_parameter_line_edits[name],
                    component.parameter_texts[name]
                )

        for name, line_edit in self.selected_parameter_line_edits.items():
            is_shown = name in shown_names
            self.selected_parameter_labels[name].setVisible(is_shown)
            line_edit.setVisible(is_shown)

            if not is_shown:
                clear_field(line_edit)

        self.rotate_button.setEnabled(component is not None)
        self.delete_button.setEnabled(component is not None)
        self.selected_name_line_edit.setEnabled(component is not None)
        self.selected_value_line_edit.setEnabled(part_has_value)
        # Apply saves the name as well as the value, so ground can use it.
        self.apply_value_button.setEnabled(component is not None)
