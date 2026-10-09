"""
A name such as Vcc on a grid point joins every point with that name.

The source is defined once: a DC source, ground, and a wire out to an
end point. Label that end Vcc. Another point labeled Vcc (or vcc) is the
same node, with no wire between them. Hand check: 10 V at that far
point, and 5 V at the middle of two 10k resistors from there to ground.
"""

import pytest
import sympy
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QApplication

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, GridConfigurationError
from core.node_formula import build_node_formulas
from core.wires import WireCollection, WireNets
from gui.main_window import MainWindow


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def same(expression, expected):
    assert expression is not None
    assert sympy.simplify(expression - expected) == 0


def supply(labels):
    """
    10 V from (2, 2) to ground, brought out on a wire to (2, 5).

    :param labels: (identifier, name) pairs to store on the grid.
    :returns: Solved formulas for that circuit.
    """
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(2, 2), point(2, 5), grid)

    for identifier, label in labels:
        grid.set_net_label(identifier, label)

    return build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
        ],
        wires,
        grid,
    )


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def press_key(window, widget, key):
    """Show the window, focus the widget, and press one key."""
    window.show()
    window.activateWindow()
    QTest.qWaitForWindowActive(window)
    widget.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    focus = QApplication.focusWidget()
    assert focus is widget or widget.isAncestorOf(focus)
    QTest.keyClick(focus, key)


# ----- the shared source ----------------------------------------------------

def test_a_far_point_with_the_same_label_is_the_source():
    book = supply([(point(2, 5), "Vcc"), (point(6, 6), "Vcc")])

    same(book.expression_at(point(2, 2)), 10)
    same(book.expression_at(point(2, 5)), 10)
    same(book.expression_at(point(6, 6)), 10)
    assert book.text_at(point(6, 6)) == "V(s) = 10 V"


def test_vcc_and_lowercase_vcc_are_one_name():
    book = supply([(point(2, 5), "Vcc"), (point(6, 6), "vcc")])

    same(book.expression_at(point(6, 6)), 10)


def test_a_divider_off_the_named_rail_is_5_volts():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(2, 2), point(2, 5), grid)
    grid.set_net_label(point(2, 5), "Vcc")
    grid.set_net_label(point(6, 6), "Vcc")
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
            Component("resistor", "R1", "10k", 6, 6),
            Component("resistor", "R2", "10k", 6, 7, 90),
            Component("ground", "GND2", "", 7, 7),
        ],
        wires,
        grid,
    )

    same(book.expression_at(point(6, 6)), 10)
    same(book.expression_at(point(6, 7)), 5)
    same(book.expression_at(point(7, 7)), 0)
    assert book.text_at(point(6, 7)) == "V(s) = 5 V"


def test_clearing_the_label_splits_the_point_off():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(2, 2), point(2, 5), grid)
    grid.set_net_label(point(2, 5), "Vcc")
    grid.set_net_label(point(6, 6), "Vcc")
    grid.set_net_label(point(6, 6), "")
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
        ],
        wires,
        grid,
    )

    assert book.text_at(point(6, 6)) == "Not connected."
    same(book.expression_at(point(2, 5)), 10)


def test_vcc_and_vss_stay_two_sources():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    grid.set_net_label(point(2, 2), "Vcc")
    grid.set_net_label(point(6, 2), "Vcc")
    grid.set_net_label(point(1, 6), "Vss")
    grid.set_net_label(point(6, 6), "Vss")
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
            Component("dc_source", "V2", "5", 1, 6),
            Component("ground", "GND2", "", 2, 6),
        ],
        wires,
        grid,
    )

    same(book.expression_at(point(6, 2)), 10)
    same(book.expression_at(point(6, 6)), 5)


def test_two_sources_on_one_name_have_no_single_formula():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    grid.set_net_label(point(2, 2), "Vcc")
    grid.set_net_label(point(1, 6), "Vcc")
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
            Component("dc_source", "V2", "5", 1, 6),
            Component("ground", "GND2", "", 2, 6),
        ],
        wires,
        grid,
    )

    assert book.text_at(point(2, 2)).startswith(
        "This circuit has no single formula."
    )
    assert book.text_at(point(1, 6)).startswith(
        "This circuit has no single formula."
    )


def test_a_bridge_stays_open_and_a_label_still_joins():
    grid = ConnectionGrid(8, 8)
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(2, 2), point(2, 6), grid, (point(2, 4),))
    wires.add_wire(point(2, 4), point(3, 4), grid)
    wires.add_wire(point(3, 4), point(3, 2), grid)
    grid.set_net_label(point(2, 6), "Vcc")
    grid.set_net_label(point(6, 6), "Vcc")
    book = build_node_formulas(
        [
            Component("ground", "GND1", "", 4, 2),
            Component("dc_source", "V1", "10", 2, 2),
            Component("dc_source", "V2", "5", 1, 4),
        ],
        wires,
        grid,
    )

    same(book.expression_at(point(2, 6)), 10)
    same(book.expression_at(point(6, 6)), 10)
    same(book.expression_at(point(2, 4)), 0)
    same(book.expression_at(point(1, 4)), 5)


def test_formulas_reject_a_grid_that_is_not_a_grid():
    with pytest.raises(ComponentError, match="ConnectionGrid"):
        build_node_formulas([], WireCollection(), "grid")


# ----- storing the name -----------------------------------------------------

def test_a_label_is_stripped_and_a_blank_clears_it():
    grid = ConnectionGrid(4, 4)

    assert grid.set_net_label(point(2, 2), "  Vcc  ") == "Vcc"
    assert grid.set_net_label(point(2, 2), "   ") == ""
    assert grid.get_net_labels() == {}


@pytest.mark.parametrize("label", [
    "1V", "V cc", "Vcc+", "_Vcc", "A" * 17, 5, None,
])
def test_a_bad_label_leaves_the_old_name(label):
    grid = ConnectionGrid(4, 4)
    grid.set_net_label(point(1, 1), "Vcc")

    with pytest.raises(GridConfigurationError):
        grid.set_net_label(point(1, 1), label)

    assert grid.get_connection_point(point(1, 1)).net_label == "Vcc"


def test_labels_survive_a_larger_grid_and_drop_off_a_smaller_one():
    grid = ConnectionGrid(8, 8)
    grid.set_net_label(point(2, 3), "Vss")
    grid.set_net_label(point(8, 8), "Vcc")

    grid.configure(10, 10)
    assert grid.get_connection_point(point(2, 3)).net_label == "Vss"
    assert grid.get_connection_point(point(8, 8)).net_label == "Vcc"

    grid.configure(4, 4)
    assert grid.get_connection_point(point(2, 3)).net_label == "Vss"
    assert grid.get_net_labels() == {point(2, 3): "Vss"}


def test_labels_round_trip_and_old_files_still_load():
    grid = ConnectionGrid(4, 4)
    grid.set_net_label(point(2, 3), "Vcc")
    restored = ConnectionGrid.from_dict(grid.to_dict())

    assert restored.get_net_labels() == {point(2, 3): "Vcc"}

    old = ConnectionGrid.from_dict({
        "row_count": 4,
        "column_count": 4,
        "signal_pickoff_identifiers": [],
    })

    assert old.get_net_labels() == {}


def test_a_saved_blank_label_is_refused():
    with pytest.raises(GridConfigurationError, match="blank"):
        ConnectionGrid.from_dict({
            "row_count": 2,
            "column_count": 2,
            "signal_pickoff_identifiers": [],
            "net_labels": {point(1, 1): ""},
        })


def test_same_label_connects_pins_with_no_wire():
    nets = WireNets(
        WireCollection(),
        pin_labels=[
            ("NODE_R02_C02", "V1.plus"),
            ("NODE_R06_C06", "R1.1"),
        ],
        net_labels=[
            ("NODE_R02_C02", "Vcc"),
            ("NODE_R06_C06", "vcc"),
        ],
    )

    assert nets.get_points("NODE_R06_C06") == (
        "NODE_R02_C02",
        "NODE_R06_C06",
    )
    assert nets.get_net_names("NODE_R06_C06") == ("Vcc",)
    assert nets.describe("NODE_R02_C02", "V1.plus") == "Vcc to R1.1"


def test_a_wire_between_two_names_lists_both():
    grid = ConnectionGrid(4, 4)
    wires = WireCollection()
    wires.add_wire("NODE_R02_C02", "NODE_R02_C04", grid)
    nets = WireNets(
        wires,
        net_labels=[
            ("NODE_R02_C02", "Vcc"),
            ("NODE_R02_C04", "Vss"),
        ],
    )

    assert nets.get_net_names("NODE_R02_C03") == ("Vcc", "Vss")
    assert nets.describe("NODE_R02_C02") == "Vcc, Vss via W1"


def test_a_bad_net_label_pair_is_refused():
    with pytest.raises(ComponentError, match="Vcc"):
        WireNets(WireCollection(), net_labels=[("NODE_R02_C02", "")])


# ----- the panel ------------------------------------------------------------

def test_apply_joins_the_far_point_to_the_source(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        window.component_collection.add_component(
            "ground", 4, 2, "", grid
        )
        window.component_collection.add_component(
            "dc_source", 2, 2, "10", grid
        )
        window.wire_collection.add_wire(point(3, 2), point(4, 2), grid)
        window.wire_collection.add_wire(point(2, 2), point(2, 5), grid)
        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()

        window.handle_connection_point_selection(
            grid.get_connection_point(point(2, 5))
        )
        window.net_label_line_edit.setText("Vcc")
        window.apply_selected_net_label()

        window.handle_connection_point_selection(
            grid.get_connection_point(point(6, 6))
        )
        window.net_label_line_edit.setText("Vcc")
        window.apply_selected_net_label()

        assert window.selected_node_formula_label.text() == "V(s) = 10 V"
        far_item = (
            window.connection_grid_scene
            .connection_point_items_by_identifier[point(6, 6)]
        )
        end_item = (
            window.connection_grid_scene
            .connection_point_items_by_identifier[point(2, 5)]
        )
        assert far_item.net_label_item.text() == "Vcc"
        assert far_item.net_label_item.isVisible()
        assert "Net: Vcc" in far_item.toolTip()
        assert end_item.net_label_item.text() == "Vcc"
        assert point(6, 6) not in (
            window.connection_grid_scene.junction_items_by_identifier
        )
        source_tip = (
            window.connection_grid_scene
            .component_items_by_reference["V1"].toolTip()
        )
        assert "net: Vcc via W2" in source_tip

        window.is_project_modified = False
        window.net_label_line_edit.setText("Vcc")
        window.apply_selected_net_label()
        assert window.is_project_modified is False

        window.net_label_line_edit.setText("   ")
        window.apply_selected_net_label()
        assert window.selected_node_formula_label.text() == "Not connected."
        assert far_item.net_label_item.text() == ""
        assert not far_item.net_label_item.isVisible()
    finally:
        close_window(window)


def test_a_bad_name_is_refused_in_the_panel(qt_application, monkeypatch):
    window = MainWindow()
    messages = []
    monkeypatch.setattr(
        window, "show_error_message", lambda *args: messages.append(args)
    )

    try:
        grid = window.connection_grid
        window.handle_connection_point_selection(
            grid.get_connection_point(point(2, 2))
        )
        window.net_label_line_edit.setText("Vcc")
        window.apply_selected_net_label()
        window.net_label_line_edit.setText("Vcc+")
        window.apply_selected_net_label()

        assert messages
        assert "not allowed" in messages[-1][1]
        assert grid.get_connection_point(point(2, 2)).net_label == "Vcc"
        assert window.net_label_line_edit.text() == "Vcc+"
    finally:
        close_window(window)


def test_enter_in_the_box_and_on_apply_stores_the_name(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        window.handle_connection_point_selection(
            grid.get_connection_point(point(3, 3))
        )
        window.net_label_line_edit.setText("Vss")
        press_key(window, window.net_label_line_edit, Qt.Key_Return)

        assert grid.get_connection_point(point(3, 3)).net_label == "Vss"

        window.net_label_line_edit.setText("Vdd")
        press_key(window, window.apply_net_label_button, Qt.Key_Enter)

        assert grid.get_connection_point(point(3, 3)).net_label == "Vdd"
        assert window.net_label_line_edit.text() == "Vdd"
    finally:
        close_window(window)


def test_shrinking_the_grid_reports_a_dropped_label(qt_application):
    window = MainWindow()

    try:
        window.connection_grid.set_net_label(point(2, 3), "Vss")
        window.connection_grid.set_net_label(point(8, 8), "Vcc")
        window.apply_grid_configuration(4, 4)

        assert window.connection_grid.get_net_labels() == {
            point(2, 3): "Vss",
        }
        assert "1 net label(s)" in window.statusBar().currentMessage()
        item = (
            window.connection_grid_scene
            .connection_point_items_by_identifier[point(2, 3)]
        )
        assert item.net_label_item.text() == "Vss"
    finally:
        close_window(window)
