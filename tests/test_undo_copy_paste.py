"""
Edit > Undo, Redo, Copy and Paste.

Place, move, wire, value and delete can be undone. Copy is not a
step. Paste is one step, and a refusal adds nothing. A net label and
the grid size stay put. Rotate is not its own step.
"""

import pytest
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QToolButton

from gui.grid_editor import grid_point_to_scene_position
from gui.main_window import MainWindow


@pytest.fixture
def window(qt_application, monkeypatch):
    """
    Return a MainWindow whose error dialogs are recorded, not shown.
    """
    main_window = MainWindow()
    main_window.recorded_errors = []

    def record_error(title, reason, resolution):
        main_window.recorded_errors.append((title, reason, resolution))

    monkeypatch.setattr(main_window, "show_error_message", record_error)
    yield main_window
    main_window.is_project_modified = False
    main_window.close()
    main_window.deleteLater()


def select_point(window, identifier):
    scene = window.connection_grid_scene
    scene.clearSelection()
    scene.connection_point_items_by_identifier[identifier].setSelected(True)


def place(window, identifier, kind, value_text):
    select_point(window, identifier)
    window.place_component(kind, value_text)


def references(window):
    return [
        component.reference
        for component in window.component_collection.get_components()
    ]


def test_edit_menu_has_undo_redo_copy_and_paste_off_the_toolbar(window):
    edit_menu = next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "&Edit"
    )
    assert [action.text() for action in edit_menu.actions()] == [
        "Undo",
        "Redo",
        "",
        "Copy",
        "Paste",
    ]
    assert window.undo_action.shortcut() == QKeySequence(QKeySequence.Undo)
    assert window.copy_action.shortcut() == QKeySequence(QKeySequence.Copy)
    assert window.paste_action.shortcut() == QKeySequence(QKeySequence.Paste)
    assert QKeySequence("Ctrl+Y") in window.redo_action.shortcuts()
    assert window.undo_action.isEnabled() is False
    assert window.paste_action.isEnabled() is False
    button_text = [
        button.text()
        for button in window.main_tool_bar.findChildren(QToolButton)
    ]
    assert "Undo" not in button_text
    assert "Copy" not in button_text


def test_place_move_wire_value_and_delete_undo_and_redo(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R04_C04", "capacitor", "100n")
    window.undo_edit()
    assert references(window) == ["R1"]
    window.undo_edit()
    assert references(window) == []
    assert window.undo_action.isEnabled() is False
    window.redo_edit()
    window.redo_edit()
    assert references(window) == ["C1", "R1"]

    window.connection_grid_scene.handle_component_drop(
        "R1", grid_point_to_scene_position(5, 3)
    )
    moved = window.component_collection.get_component("R1")
    assert (moved.row_number, moved.column_number) == (5, 3)
    window.undo_edit()
    moved = window.component_collection.get_component("R1")
    assert (moved.row_number, moved.column_number) == (2, 2)

    window.connection_grid_scene.add_drawn_wire(
        "NODE_R02_C03", "NODE_R02_C06"
    )
    assert [wire.reference for wire in window.wire_collection.get_wires()
            ] == ["W1"]
    window.undo_edit()
    assert window.wire_collection.get_wires() == []

    # Undo rebuilds the items and clears the selection.
    window.connection_grid_scene.component_items_by_reference[
        "R1"
    ].setSelected(True)
    window.apply_component_value("2k2")
    assert window.component_collection.get_component("R1").value_text == "2k2"
    window.undo_edit()
    assert window.component_collection.get_component("R1").value_text == "1k"
    window.redo_edit()
    assert window.component_collection.get_component("R1").value_text == "2k2"

    window.connection_grid_scene.component_items_by_reference[
        "R1"
    ].setSelected(True)
    window.delete_component_action.trigger()
    assert "R1" not in references(window)
    window.undo_edit()
    assert "R1" in references(window)
    assert window.statusBar().currentMessage() == "Undid the last change."


def test_undo_of_delete_puts_a_current_probe_back(window):
    place(window, "NODE_R03_C03", "resistor", "1k")
    resistor = window.component_collection.get_component("R1")
    window.probe_collection.add_current(resistor)
    window.delete_component_action.trigger()
    assert window.probe_collection.get_probes() == []
    window.undo_edit()
    assert window.probe_collection.get("P1").component_reference == "R1"
    assert references(window) == ["R1"]


def test_a_new_edit_clears_redo_and_undo_does_not_record_itself(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    window.undo_edit()
    assert window.redo_action.isEnabled() is True
    place(window, "NODE_R04_C04", "capacitor", "100n")
    assert window.redo_action.isEnabled() is False
    window.undo_edit()
    assert references(window) == []
    window.undo_edit()
    assert references(window) == []


def test_rotate_is_not_its_own_undo_step(window):
    place(window, "NODE_R04_C03", "resistor", "1k")
    window.rotate_selected_component()
    assert window.component_collection.get_component("R1").rotation == 90
    assert len(window._undo_snapshots) == 1
    window.undo_edit()
    assert references(window) == []


def test_a_refused_place_or_move_is_not_an_undo_step(window):
    select_point(window, "NODE_R04_C08")
    window.place_component("resistor", "1k")
    assert references(window) == []
    assert window.undo_action.isEnabled() is False
    assert window.recorded_errors[0][0] == "Part Not Placed"

    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R05_C04", "resistor", "2k")
    window.connection_grid_scene.handle_component_drop(
        "R1", grid_point_to_scene_position(5, 4)
    )
    assert window.component_collection.get_component("R1").row_number == 2
    assert len(window._undo_snapshots) == 2
    assert window._pending_snapshot is None


def test_undo_leaves_a_net_label_and_the_grid_size(window):
    window.connection_grid.set_net_label("NODE_R01_C01", "Vcc")
    place(window, "NODE_R03_C03", "resistor", "1k")
    window.undo_edit()
    assert window.connection_grid.get_net_labels()["NODE_R01_C01"] == "Vcc"
    assert window.connection_grid.row_count == 8
    assert window.connection_grid.column_count == 8
    assert references(window) == []


def test_copy_then_paste_uses_new_names_and_one_undo_step(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R02_C04", "resistor", "2k2")
    window.wire_collection.add_wire(
        "NODE_R02_C03", "NODE_R02_C04", window.connection_grid
    )
    window.wire_collection.add_wire(
        "NODE_R02_C03", "NODE_R06_C03", window.connection_grid
    )
    scene = window.connection_grid_scene
    scene.clearSelection()
    scene.component_items_by_reference["R1"].setSelected(True)
    scene.component_items_by_reference["R2"].setSelected(True)
    steps = len(window._undo_snapshots)
    window.copy_selection()
    assert len(window._undo_snapshots) == steps
    assert window.statusBar().currentMessage() == "Copied 2 parts."
    select_point(window, "NODE_R05_C02")
    window.paste_selection()
    assert references(window) == ["R1", "R2", "R3", "R4"]
    pasted = window.component_collection.get_component("R3")
    assert (pasted.row_number, pasted.column_number) == (5, 2)
    assert pasted.value_text == "1k"
    other = window.component_collection.get_component("R4")
    assert (other.row_number, other.column_number) == (5, 4)
    wires = {
        (wire.start_identifier, wire.end_identifier)
        for wire in window.wire_collection.get_wires()
    }
    assert ("NODE_R05_C03", "NODE_R05_C04") in wires
    assert ("NODE_R05_C03", "NODE_R09_C03") not in wires
    window.undo_edit()
    assert references(window) == ["R1", "R2"]


def test_a_refused_paste_adds_nothing_and_keeps_redo(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    scene = window.connection_grid_scene
    scene.component_items_by_reference["R1"].setSelected(True)
    window.copy_selection()
    window.undo_edit()
    assert window.redo_action.isEnabled() is True
    select_point(window, "NODE_R02_C08")
    window.paste_selection()
    assert references(window) == []
    assert window.recorded_errors[-1][0] == "Parts Not Pasted"
    assert window.redo_action.isEnabled() is True
    assert len(window._undo_snapshots) == 0
    window.redo_edit()
    assert references(window) == ["R1"]


def test_paste_needs_a_grid_point_and_copy_needs_a_part(window):
    window.copy_selection()
    assert window.statusBar().currentMessage() == (
        "Select one or more parts to copy."
    )
    place(window, "NODE_R02_C02", "resistor", "1k")
    window.copy_selection()
    window.connection_grid_scene.clearSelection()
    window.selected_connection_point_identifier = None
    window.paste_selection()
    assert window.recorded_errors[-1][0] == "No Connection Point Selected"
    assert references(window) == ["R1"]


def test_a_new_project_clears_undo_and_keeps_the_copy(window, monkeypatch):
    place(window, "NODE_R02_C02", "resistor", "4k7")
    window.copy_selection()
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)
    window.create_new_project()
    assert references(window) == []
    assert window.undo_action.isEnabled() is False
    select_point(window, "NODE_R04_C03")
    window.paste_selection()
    pasted = window.component_collection.get_component("R1")
    assert pasted.value_text == "4k7"
    assert (pasted.row_number, pasted.column_number) == (4, 3)
