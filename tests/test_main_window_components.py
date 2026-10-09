"""
Tests for the Step 9 main-window wiring of the Components dock.

Error dialogs are replaced with a recorder, so no modal box opens.
"""

import pytest
from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent, QKeySequence
from PyQt5.QtWidgets import QDockWidget, QPushButton

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


def test_component_menu_has_rotate_delete_and_wire_mode(window):
    menus = {
        action.text(): action.menu()
        for action in window.menuBar().actions()
    }
    assert "&Component" in menus
    assert [a.text() for a in menus["&Component"].actions()] == [
        "Rotate Part", "Delete", "", "Wire Mode"
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


def press_enter_on_the_grid(window):
    # Place shows a ghost first; Enter on the grid view places it.
    from PyQt5.QtTest import QTest

    QTest.keyClick(window.connection_grid_view, Qt.Key_Return)


def test_place_through_the_panel_button(window):
    select_point(window, "NODE_R03_C03")
    panel(window).kind_combo_box.setCurrentIndex(
        panel(window).kind_combo_box.findData("led")
    )
    panel(window).value_line_edit.setText("red")
    panel(window).place_button.click()
    assert window.component_collection.get_components() == []
    press_enter_on_the_grid(window)
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


# ----- QC PR #10 fixes -----

def focus_and_press(window, widget, key):
    """
    Give a widget real keyboard focus in the active window, then press a
    key on it, so shortcut contexts are checked the way Qt does for users.
    """
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication

    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    widget.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    assert QApplication.focusWidget() is widget
    QTest.keyClick(widget, key)


def references(window):
    return [c.reference for c in window.component_collection.get_components()]


def test_placing_twice_on_the_same_spot_is_refused(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    window.place_component("resistor", "1k")
    assert references(window) == ["R1"]
    assert [error[0] for error in window.recorded_errors] == [
        "Part Not Placed"
    ]
    assert window.recorded_errors[0][1].startswith(
        "R1 (Resistor) already connects exactly these grid points: "
        "NODE_R04_C04, NODE_R04_C05."
    )


def test_refused_duplicate_shows_a_status_message(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    window.place_component("resistor", "2k2")
    assert window.statusBar().currentMessage() == (
        "Part not placed: R1 (Resistor) already connects exactly these grid "
        "points: NODE_R04_C04, NODE_R04_C05. Pick other grid points or "
        "another rotation, or select R1 to edit it."
    )


def test_refused_duplicate_keeps_the_first_part_selected(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    panel(window).place_button.click()
    assert window.selected_component_reference == "R1"
    assert item(window, "R1").isSelected() is True
    assert list(
        window.connection_grid_scene.component_items_by_reference
    ) == ["R1"]


def test_enter_twice_in_the_value_box_places_once(window):
    from PyQt5.QtTest import QTest

    select_point(window, "NODE_R04_C04")
    line_edit = panel(window).value_line_edit
    line_edit.setText("1k")
    # Enter in the value box is Place: it shows (and refreshes) the ghost.
    QTest.keyClick(line_edit, Qt.Key_Return)
    QTest.keyClick(line_edit, Qt.Key_Return)
    assert references(window) == []
    press_enter_on_the_grid(window)
    press_enter_on_the_grid(window)
    assert references(window) == ["R1"]


def test_another_kind_on_the_same_point_is_refused(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    window.place_component("capacitor", "100n")
    assert references(window) == ["R1"]
    assert window.recorded_errors[-1][0] == "Part Not Placed"
    assert window.recorded_errors[-1][1].startswith(
        "R1 (Resistor) already connects exactly these grid points: "
        "NODE_R04_C04, NODE_R04_C05."
    )
    assert window.statusBar().currentMessage().startswith(
        "Part not placed: R1 (Resistor) already connects"
    )


def test_parts_sharing_a_pin_can_both_be_placed(window):
    # R1 runs C3 -> C4 and R2 runs C4 -> C5: they connect at C4.
    place(window, "NODE_R04_C03", "resistor", "1k")
    place(window, "NODE_R04_C04", "resistor", "2k2")
    assert references(window) == ["R1", "R2"]
    assert window.recorded_errors == []


def test_rotate_onto_an_identical_part_is_refused_in_the_gui(window):
    from core.components import Component

    place(window, "NODE_R04_C04", "resistor", "1k")
    window.rotate_selected_component()
    # add_component no longer allows a second part on R1's centre, so the
    # stacked twin is stored directly to keep testing the rotate guard.
    window.component_collection.components_by_reference["R2"] = Component(
        "resistor", "R2", "2k2", 4, 4, 0
    )
    window.connection_grid_scene.rebuild_component_items()
    window.connection_grid_scene.clearSelection()
    window.select_component_by_reference("R2")
    assert window.selected_component_reference == "R2"
    window.is_project_modified = False
    window.rotate_selected_component()
    assert window.component_collection.get_component("R2").rotation == 0
    assert window.recorded_errors[-1][0] == "Part Not Rotated"
    assert window.statusBar().currentMessage().startswith(
        "Part not rotated: R2 cannot be rotated to 90 deg: R1 "
    )
    assert window.is_project_modified is False


def test_part_shortcuts_are_scoped_to_the_grid_view(window):
    for action in (
            window.rotate_component_action,
            window.delete_component_action):
        assert action.shortcutContext() == Qt.WidgetWithChildrenShortcut
        assert action in window.connection_grid_view.actions()


@pytest.mark.parametrize(
    "widget_name",
    ["kind_combo_box", "place_button", "apply_value_button",
     "rotate_button", "delete_button"],
)
def test_r_does_not_rotate_from_the_dock(window, widget_name):
    place(window, "NODE_R04_C04", "resistor", "1k")
    focus_and_press(window, getattr(panel(window), widget_name), Qt.Key_R)
    assert window.component_collection.get_component("R1").rotation == 0


@pytest.mark.parametrize(
    "widget_name",
    ["kind_combo_box", "place_button", "apply_value_button",
     "rotate_button", "delete_button"],
)
def test_delete_does_not_delete_from_the_dock(window, widget_name):
    place(window, "NODE_R04_C04", "resistor", "1k")
    focus_and_press(
        window, getattr(panel(window), widget_name), Qt.Key_Delete
    )
    assert references(window) == ["R1"]


def test_delete_does_not_delete_from_the_grid_dock(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    focus_and_press(
        window,
        window.grid_configuration_widget.findChildren(QPushButton)[0],
        Qt.Key_Delete,
    )
    assert references(window) == ["R1"]


def test_r_and_delete_work_with_real_focus_on_the_grid(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    focus_and_press(window, window.connection_grid_view, Qt.Key_R)
    assert window.component_collection.get_component("R1").rotation == 90
    focus_and_press(window, window.connection_grid_view, Qt.Key_Delete)
    assert references(window) == []


def test_placing_from_the_panel_moves_focus_to_the_grid(window):
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication

    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    select_point(window, "NODE_R04_C04")
    panel(window).place_button.setFocus(Qt.OtherFocusReason)
    panel(window).place_button.click()
    QApplication.processEvents()
    assert QApplication.focusWidget() is window.connection_grid_view
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Return)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_R)
    assert window.component_collection.get_component("R1").rotation == 90


def test_menu_actions_still_work_without_grid_focus(window):
    place(window, "NODE_R04_C04", "resistor", "1k")
    panel(window).kind_combo_box.setFocus()
    window.rotate_component_action.trigger()
    window.delete_component_action.trigger()
    assert references(window) == []


def visible_scene_rect(window):
    view = window.connection_grid_view
    return view.mapToScene(view.viewport().rect()).boundingRect()


def label_rect(window, reference):
    return item(window, reference).label_item.sceneBoundingRect()


def shown_and_fitted(window):
    from PyQt5.QtTest import QTest

    window.resize(1360, 820)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.connection_grid_view.fit_grid_in_view()


def test_label_past_the_last_column_is_brought_into_view(window):
    shown_and_fitted(window)
    place(window, "NODE_R04_C07", "npn", "2N3904_LONG_MODEL_NAME")
    rect = label_rect(window, "Q1")
    assert rect.right() > window.connection_grid_scene.get_grid_rect().right()
    assert visible_scene_rect(window).contains(rect)
    # The whole grid was in view, so it is refitted rather than scrolled:
    # the first column must not be pushed out of view.
    assert visible_scene_rect(window).contains(
        window.connection_grid_scene.get_grid_rect()
    )


def test_fully_visible_part_does_not_change_the_view(window):
    shown_and_fitted(window)
    view = window.connection_grid_view
    transform = view.transform()
    place(window, "NODE_R04_C04", "resistor", "1k")
    assert view.transform() == transform


def test_zoomed_in_view_scrolls_without_changing_the_zoom(window):
    shown_and_fitted(window)
    view = window.connection_grid_view
    view.scale(3.0, 3.0)
    view.centerOn(
        window.connection_grid_scene.connection_point_items_by_identifier[
            "NODE_R01_C01"
        ]
    )
    zoom = view.transform().m11()
    place(window, "NODE_R08_C06", "resistor", "4k7")
    assert view.transform().m11() == zoom
    assert visible_scene_rect(window).contains(label_rect(window, "R1"))
    assert visible_scene_rect(window).contains(
        item(window, "R1").sceneBoundingRect()
    )


def test_rotate_brings_a_moved_label_into_view(window, monkeypatch):
    place(window, "NODE_R04_C04", "resistor", "1k")
    revealed = []
    monkeypatch.setattr(window, "reveal_component", revealed.append)
    window.rotate_selected_component()
    assert revealed == ["R1"]


def test_refused_rotate_does_not_move_the_view(window, monkeypatch):
    place(window, "NODE_R08_C04", "resistor", "1k")
    revealed = []
    monkeypatch.setattr(window, "reveal_component", revealed.append)
    window.rotate_selected_component()
    assert revealed == []


def test_rotated_label_past_the_grid_edge_is_visible(window):
    shown_and_fitted(window)
    # Q1's long label sits past the last column; each turn moves it to
    # another side, and it must stay in view after every turn.
    place(window, "NODE_R04_C07", "npn", "2N3904_LONG_MODEL_NAME")
    window.connection_grid_view.fit_grid_in_view()
    for _turn in range(3):
        window.rotate_selected_component()
        assert visible_scene_rect(window).contains(label_rect(window, "Q1"))


def test_one_step_resistor_lands_on_two_neighbouring_points(window):
    # Billie's example: R1 from R2 C2 to R2 C3.
    place(window, "NODE_R02_C02", "resistor", "1k")
    assert window.component_collection.get_component(
        "R1"
    ).get_pin_identifiers() == ["NODE_R02_C02", "NODE_R02_C03"]


def test_a_part_can_start_on_the_last_column_pointing_inward(window):
    place(window, "NODE_R04_C08", "resistor", "1k")
    assert window.recorded_errors[0][0] == "Part Not Placed"
    window.recorded_errors.clear()
    place(window, "NODE_R04_C07", "resistor", "1k")
    assert window.component_collection.get_component(
        "R1"
    ).get_pin_identifiers() == ["NODE_R04_C07", "NODE_R04_C08"]


# PR B: sources through the window and panel --------------------------------


def test_place_dc_and_ac_sources_from_the_panel(window):
    select_point(window, "NODE_R02_C02")
    combo = panel(window).kind_combo_box
    combo.setCurrentIndex(combo.findData("dc_source"))
    panel(window).value_line_edit.setText("9")
    panel(window).place_button.click()
    press_enter_on_the_grid(window)

    select_point(window, "NODE_R02_C04")
    combo.setCurrentIndex(combo.findData("ac_source"))
    panel(window).parameter_line_edits["frequency"].setText("50")
    panel(window).place_button.click()
    press_enter_on_the_grid(window)

    assert item(window, "V1").label_item.text() == "V1 9V"
    assert item(window, "V2").label_item.text() == "V2 1V 50Hz"
    assert window.statusBar().currentMessage() == (
        "Placed V2 1V 50Hz at NODE_R02_C04."
    )


def test_apply_a_new_frequency_to_the_selected_ac_source(window):
    place(window, "NODE_R02_C02", "ac_source", "1")
    assert not panel(window).selected_parameter_line_edits[
        "frequency"
    ].isHidden()

    panel(window).selected_parameter_line_edits["frequency"].setText("60")
    panel(window).apply_value_button.click()

    assert item(window, "V1").label_item.text() == "V1 1V 60Hz"
    assert window.statusBar().currentMessage() == "Set V1 to 1V 60Hz."


def test_bad_frequency_shows_an_error_and_restores_the_boxes(window):
    place(window, "NODE_R02_C02", "ac_source", "1")
    window.is_project_modified = False
    panel(window).selected_value_line_edit.setText("3")
    panel(window).selected_parameter_line_edits["frequency"].setText("-5")
    panel(window).apply_value_button.click()

    source = window.component_collection.get_component("V1")
    assert (source.value_text, source.parameter_texts["frequency"]) == (
        "1", "1k"
    )
    assert window.recorded_errors[0][0] == "Part Value Not Changed"
    assert panel(window).selected_value_line_edit.text() == "1"
    assert panel(window).selected_parameter_line_edits[
        "frequency"
    ].text() == "1k"
    assert window.is_project_modified is False


def test_clearing_the_selected_frequency_is_refused(window):
    # QC #12 item 1: an empty Frequency box no longer resets to 1k.
    select_point(window, "NODE_R02_C02")
    window.place_component("ac_source", "1", {"frequency": "60"})
    window.is_project_modified = False
    frequency_box = panel(window).selected_parameter_line_edits["frequency"]
    frequency_box.setText("")
    frequency_box.returnPressed.emit()

    source = window.component_collection.get_component("V1")
    assert source.parameter_texts["frequency"] == "60"
    assert window.recorded_errors[-1] == (
        "Part Value Not Changed",
        (
            "AC voltage source frequency is empty. Enter a number such as 50 "
            "or 1k."
        ),
        (
            "Enter a number with an optional prefix, for example 4k7, 100n, "
            "1m or 1k, or a model name for diodes, LEDs and transistors."
        ),
    )
    assert frequency_box.text() == "60"
    assert window.is_project_modified is False


def test_bad_frequency_on_place_places_nothing(window):
    select_point(window, "NODE_R02_C02")
    window.place_component("ac_source", "1", {"frequency": "0"})

    assert window.component_collection.get_components() == []
    assert window.recorded_errors[0][0] == "Part Not Placed"
    assert "frequency must be greater than zero" in (
        window.statusBar().currentMessage()
    )
