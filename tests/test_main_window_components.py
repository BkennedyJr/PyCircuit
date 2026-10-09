"""
Tests for the Step 9 main-window wiring of the Components dock.

Error dialogs are replaced with a recorder, so no modal box opens.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent, QKeySequence
from PyQt5.QtWidgets import QDockWidget

from core.components import ComponentCollection
from gui.component_panel_widget import NO_PART_SELECTED_TEXT
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


def panel(window):
    return window.component_panel_widget


def item(window, reference):
    return window.connection_grid_scene.component_items_by_reference[
        reference
    ]


# ----- dock, menu, and actions -----

def test_components_dock_is_on_the_left(window):
    assert window.component_dock.windowTitle() == "Components"
    assert window.component_dock.widget() is panel(window)
    assert window.dockWidgetArea(window.component_dock) == (
        Qt.LeftDockWidgetArea
    )


def test_both_left_docks_are_present(window):
    titles = [
        dock.windowTitle()
        for dock in window.findChildren(QDockWidget)
        if window.dockWidgetArea(dock) == Qt.LeftDockWidgetArea
    ]
    assert sorted(titles) == ["Components", "Grid Configuration"]


def test_component_menu_has_rotate_and_delete(window):
    menus = {
        action.text(): action.menu()
        for action in window.menuBar().actions()
    }
    assert "&Component" in menus
    assert [a.text() for a in menus["&Component"].actions()] == [
        "Rotate Part", "Delete Part"
    ]


def test_shortcuts_are_r_and_delete(window):
    assert window.rotate_component_action.shortcut() == QKeySequence("R")
    assert window.delete_component_action.shortcut() == (
        QKeySequence(QKeySequence.Delete)
    )


def test_part_actions_start_disabled(window):
    assert window.rotate_component_action.isEnabled() is False
    assert window.delete_component_action.isEnabled() is False
    assert window.selected_component_reference is None


def test_window_starts_with_an_empty_collection_on_the_scene(window):
    assert isinstance(window.component_collection, ComponentCollection)
    assert window.component_collection.get_components() == []
    assert window.connection_grid_scene.component_collection is (
        window.component_collection
    )


# ----- placing -----

def test_place_puts_the_anchor_on_the_selected_point(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    component = window.component_collection.get_component("R1")
    assert (component.row_number, component.column_number) == (4, 3)
    assert component.value_text == "4k7"
    assert component.rotation == 0
    assert "R1" in window.connection_grid_scene.component_items_by_reference


def test_place_selects_the_new_part_and_fills_the_panel(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    assert window.selected_component_reference == "R1"
    assert item(window, "R1").isSelected() is True
    assert panel(window).selected_component_label.text() == (
        "R1 (Resistor) at R4 C3, 0 deg"
    )
    assert panel(window).selected_value_line_edit.text() == "4k7"
    assert window.rotate_component_action.isEnabled() is True
    assert window.delete_component_action.isEnabled() is True


def test_place_keeps_the_grid_point_selected(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    assert window.selected_connection_point_identifier == "NODE_R04_C03"


def test_second_placement_reselects_after_the_rebuild(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R05_C05", "capacitor", "100n")
    assert window.selected_component_reference == "C1"
    assert panel(window).selected_component_label.text().startswith("C1 ")
    assert item(window, "C1").isSelected() is True
    assert item(window, "R1").isSelected() is False


def test_place_marks_modified_and_reports(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    assert window.is_project_modified is True
    assert window.windowTitle().endswith("*")
    assert window.statusBar().currentMessage() == (
        "Placed R1 4k7 at NODE_R04_C03."
    )


def test_place_ground_reports_its_reference(window):
    place(window, "NODE_R06_C02", "ground", "")
    assert window.statusBar().currentMessage() == (
        "Placed GND1 at NODE_R06_C02."
    )


def test_place_through_the_panel_button(window):
    select_point(window, "NODE_R03_C03")
    panel(window).kind_combo_box.setCurrentIndex(
        panel(window).kind_combo_box.findData("led")
    )
    panel(window).value_line_edit.setText("red")
    panel(window).place_button.click()
    component = window.component_collection.get_component("D1")
    assert component.kind == "led"
    assert window.selected_component_reference == "D1"


def test_place_without_a_selected_point_shows_an_error(window):
    window.connection_grid_scene.clearSelection()
    window.place_component("resistor", "4k7")
    assert window.component_collection.get_components() == []
    assert [error[0] for error in window.recorded_errors] == [
        "No Connection Point Selected"
    ]
    assert window.is_project_modified is False


def test_place_with_a_bad_value_shows_the_component_error(window):
    place(window, "NODE_R04_C03", "resistor", "abc")
    assert window.component_collection.get_components() == []
    assert len(window.recorded_errors) == 1
    assert window.recorded_errors[0][0] == "Part Not Placed"
    assert window.is_project_modified is False


def test_place_off_the_edge_shows_an_error(window):
    # A resistor's second pin is one column right; column 8 is the edge.
    place(window, "NODE_R04_C08", "resistor", "1k")
    assert window.component_collection.get_components() == []
    assert window.recorded_errors[0][0] == "Part Not Placed"


# ----- rotating -----

def test_rotate_turns_the_part_and_keeps_it_selected(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    window.rotate_component_action.trigger()
    assert window.component_collection.get_component("R1").rotation == 90
    assert item(window, "R1").isSelected() is True
    assert window.selected_component_reference == "R1"
    assert panel(window).selected_component_label.text() == (
        "R1 (Resistor) at R4 C3, 90 deg"
    )
    assert window.statusBar().currentMessage() == (
        "Rotated R1 to 90 degrees."
    )


def test_rotate_through_the_panel_button(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    panel(window).rotate_button.click()
    assert window.component_collection.get_component("R1").rotation == 90


def test_rotate_redraws_the_item(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    before = item(window, "R1")
    wide = before.boundingRect()
    assert wide.width() > wide.height()
    window.rotate_selected_component()
    assert item(window, "R1") is before
    tall = before.boundingRect()
    assert tall.height() > tall.width()


def test_rotate_off_the_edge_shows_an_error_and_keeps_rotation(window):
    # At row 8 a 90-degree turn would put the second pin on row 9.
    place(window, "NODE_R08_C03", "resistor", "1k")
    window.is_project_modified = False
    window.rotate_selected_component()
    assert window.component_collection.get_component("R1").rotation == 0
    assert window.recorded_errors[0][0] == "Part Not Rotated"
    assert window.is_project_modified is False


def test_rotate_with_nothing_selected_does_nothing(window):
    window.rotate_selected_component()
    assert window.recorded_errors == []
    assert window.is_project_modified is False


# ----- value -----

def test_apply_value_changes_the_part(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    panel(window).selected_value_line_edit.setText("2k2")
    panel(window).apply_value_button.click()
    assert window.component_collection.get_component("R1").value_text == "2k2"
    assert item(window, "R1").isSelected() is True
    assert panel(window).selected_value_line_edit.text() == "2k2"
    assert window.statusBar().currentMessage() == "Set R1 to 2k2."


def test_apply_value_updates_the_label(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    window.apply_component_value("2k2")
    assert item(window, "R1").label_item.text() == "R1 2k2"


def test_bad_value_shows_an_error_and_restores_the_box(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    window.is_project_modified = False
    panel(window).selected_value_line_edit.setText("abc")
    panel(window).apply_value_button.click()
    assert window.component_collection.get_component("R1").value_text == "4k7"
    assert window.recorded_errors[0][0] == "Part Value Not Changed"
    assert panel(window).selected_value_line_edit.text() == "4k7"
    assert window.is_project_modified is False


# ----- deleting -----

def test_delete_removes_the_part_and_clears_the_panel(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    window.delete_component_action.trigger()
    assert window.component_collection.get_components() == []
    assert window.connection_grid_scene.component_items_by_reference == {}
    assert window.selected_component_reference is None
    assert panel(window).selected_component_label.text() == (
        NO_PART_SELECTED_TEXT
    )
    assert window.delete_component_action.isEnabled() is False
    assert window.rotate_component_action.isEnabled() is False
    assert window.statusBar().currentMessage() == "Deleted R1."


def test_delete_through_the_panel_keeps_other_parts(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R05_C05", "capacitor", "100n")
    panel(window).delete_button.click()
    references = [
        c.reference for c in window.component_collection.get_components()
    ]
    assert references == ["R1"]
    assert list(
        window.connection_grid_scene.component_items_by_reference
    ) == ["R1"]


def test_delete_with_nothing_selected_does_nothing(window):
    window.delete_selected_component()
    assert window.is_project_modified is False


# ----- keyboard -----

def send_key_shortcut(window, widget, key):
    """
    Show the window, focus a widget, and click a key on it. Qt delivers
    ShortcutOverride first, then the shortcut map, then KeyPress.
    """
    from PyQt5.QtTest import QTest

    window.show()
    widget.setFocus()
    QTest.qWaitForWindowExposed(window)
    QTest.keyClick(widget, key)


def test_r_key_on_the_grid_rotates(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    send_key_shortcut(window, window.connection_grid_view, Qt.Key_R)
    assert window.component_collection.get_component("R1").rotation == 90


def test_delete_key_on_the_grid_deletes(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    send_key_shortcut(window, window.connection_grid_view, Qt.Key_Delete)
    assert window.component_collection.get_components() == []


def test_r_typed_in_a_value_box_does_not_rotate(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    line_edit = panel(window).value_line_edit
    line_edit.clear()
    send_key_shortcut(window, line_edit, Qt.Key_R)
    assert window.component_collection.get_component("R1").rotation == 0
    assert line_edit.text() == "r"


def test_delete_typed_in_a_value_box_does_not_delete(window):
    place(window, "NODE_R04_C03", "resistor", "4k7")
    line_edit = panel(window).selected_value_line_edit
    line_edit.setCursorPosition(0)
    send_key_shortcut(window, line_edit, Qt.Key_Delete)
    assert [
        c.reference for c in window.component_collection.get_components()
    ] == ["R1"]
    assert line_edit.text() == "k7"


def test_shortcut_override_is_accepted_by_line_edits(window):
    # The mechanism the two tests above rely on.
    event = QKeyEvent(QEvent.ShortcutOverride, Qt.Key_R, Qt.NoModifier, "r")
    event.ignore()
    panel(window).value_line_edit.event(event)
    assert event.isAccepted() is True


# ----- grid resize -----

def test_shrinking_the_grid_removes_parts_outside(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R07_C07", "capacitor", "100n")
    window.apply_grid_configuration(5, 5)
    assert [
        c.reference for c in window.component_collection.get_components()
    ] == ["R1"]
    assert list(
        window.connection_grid_scene.component_items_by_reference
    ) == ["R1"]
    assert window.statusBar().currentMessage() == (
        "Grid updated. Removed 1 part(s) (C1) outside the new grid boundary."
    )


def test_shrinking_reports_pickoffs_and_parts_together(window):
    select_point(window, "NODE_R08_C08")
    window.toggle_selected_signal_pickoff()
    place(window, "NODE_R07_C07", "capacitor", "100n")
    window.apply_grid_configuration(5, 5)
    assert window.statusBar().currentMessage() == (
        "Grid updated. Removed 1 signal pickoff(s) and 1 part(s) (C1) "
        "outside the new grid boundary."
    )


def test_resize_reselects_the_surviving_selected_part(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    window.apply_grid_configuration(6, 6)
    assert window.selected_component_reference == "R1"
    assert item(window, "R1").isSelected() is True
    assert panel(window).selected_component_label.text() == (
        "R1 (Resistor) at R2 C2, 0 deg"
    )
    assert window.rotate_component_action.isEnabled() is True


def test_resize_clears_the_panel_when_the_selected_part_is_removed(window):
    place(window, "NODE_R07_C07", "resistor", "1k")
    window.apply_grid_configuration(5, 5)
    assert window.selected_component_reference is None
    assert panel(window).selected_component_label.text() == (
        NO_PART_SELECTED_TEXT
    )
    assert window.delete_component_action.isEnabled() is False


def test_growing_the_grid_keeps_every_part(window):
    place(window, "NODE_R02_C02", "resistor", "1k")
    place(window, "NODE_R07_C07", "capacitor", "100n")
    window.apply_grid_configuration(10, 12)
    assert len(window.component_collection.get_components()) == 2
    assert window.statusBar().currentMessage().startswith("Grid ")
    assert "Removed" not in window.statusBar().currentMessage()


# ----- project reset -----

def test_new_project_clears_the_parts(window, monkeypatch):
    place(window, "NODE_R02_C02", "resistor", "1k")
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)
    window.create_new_project()
    assert window.component_collection.get_components() == []
    assert window.connection_grid_scene.component_items_by_reference == {}
    assert window.connection_grid_scene.component_collection is (
        window.component_collection
    )
    assert window.selected_component_reference is None
    assert panel(window).selected_component_label.text() == (
        NO_PART_SELECTED_TEXT
    )


def test_placing_after_new_project_uses_fresh_references(window, monkeypatch):
    place(window, "NODE_R02_C02", "resistor", "1k")
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)
    window.create_new_project()
    place(window, "NODE_R03_C03", "resistor", "2k2")
    assert [
        c.reference for c in window.component_collection.get_components()
    ] == ["R1"]


def test_open_project_clears_the_parts(window, monkeypatch, tmp_path):
    from PyQt5.QtWidgets import QFileDialog

    project_path = tmp_path / "saved.pycircuit"
    assert window.save_project_to_path(project_path) is True
    place(window, "NODE_R02_C02", "resistor", "1k")
    monkeypatch.setattr(window, "confirm_project_replacement", lambda: True)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        staticmethod(lambda *args, **kwargs: (str(project_path), ""))
    )
    window.open_project()
    assert window.component_collection.get_components() == []
    assert window.connection_grid_scene.component_items_by_reference == {}


def test_saving_with_parts_warns_they_are_not_stored(window, tmp_path):
    place(window, "NODE_R02_C02", "resistor", "1k")
    assert window.save_project_to_path(tmp_path / "a.pycircuit") is True
    assert window.statusBar().currentMessage() == (
        "Saved project 'a.pycircuit'. Note: parts are not saved to project "
        "files yet and will not be there when the project is opened again."
    )


def test_saving_without_parts_has_no_warning(window, tmp_path):
    assert window.save_project_to_path(tmp_path / "a.pycircuit") is True
    assert window.statusBar().currentMessage() == (
        "Saved project 'a.pycircuit'."
    )
