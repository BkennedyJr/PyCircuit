"""
s-domain voltage at a node. Hand-checked: a 10k/10k divider from 10 V is
5 V, an RC low-pass is 10/(1 + s/1000), and a bridged wire does not join.
"""

import pytest
import sympy

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.node_formula import build_node_formulas
from core.wires import WireCollection
from gui.main_window import MainWindow


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def formulas(*parts, wires=()):
    grid = ConnectionGrid(8, 8)
    collection = WireCollection()

    for start, end, bridged in wires:
        collection.add_wire(start, end, grid, bridged)

    return build_node_formulas(parts, collection)


def same(expression, expected):
    assert expression is not None
    assert sympy.simplify(expression - expected) == 0


def test_divider_midpoint_is_5_volts():
    book = formulas(
        Component("ground", "GND1", "", 4, 2),
        Component("dc_source", "V1", "10", 2, 2),
        Component("resistor", "R1", "10k", 2, 2),
        Component("resistor", "R2", "10k", 2, 3, 90),
        wires=[
            (point(3, 2), point(4, 2), ()),
            (point(3, 3), point(3, 2), ()),
        ],
    )

    same(book.expression_at(point(2, 2)), 10)
    same(book.expression_at(point(2, 3)), 5)
    same(book.expression_at(point(4, 2)), 0)
    assert book.text_at(point(2, 3)) == "V(s) = 5 V"
    assert book.text_at(point(8, 8)) == "Not connected."


def test_rc_lowpass_is_10_over_one_plus_s_over_1000():
    book = formulas(
        Component("ground", "GND1", "", 4, 2),
        Component("dc_source", "V1", "10", 2, 2),
        Component("resistor", "R1", "1k", 2, 2),
        Component("capacitor", "C1", "1u", 2, 3, 90),
        wires=[
            (point(3, 2), point(4, 2), ()),
            (point(3, 3), point(3, 2), ()),
        ],
    )
    s = sympy.symbols("s")

    same(book.expression_at(point(2, 3)), 10 / (1 + s / 1000))
    assert book.text_at(point(2, 3)).startswith("V(s) = ")
    assert "s" in book.text_at(point(2, 3))


def test_one_milliamp_through_1k_is_1_volt():
    book = formulas(
        Component("ground", "GND1", "", 3, 2),
        Component("current_source", "I1", "1m", 2, 2),
        Component("resistor", "R1", "1k", 2, 2, 90),
    )

    same(book.expression_at(point(2, 2)), 1)
    assert book.text_at(point(2, 2)) == "V(s) = 1 V"


def test_ac_divider_keeps_the_source_symbol():
    book = formulas(
        Component("ground", "GND1", "", 4, 2),
        Component("ac_source", "V1", "1", 2, 2),
        Component("resistor", "R1", "10k", 2, 2),
        Component("resistor", "R2", "10k", 2, 3, 90),
        wires=[
            (point(3, 2), point(4, 2), ()),
            (point(3, 3), point(3, 2), ()),
        ],
    )

    same(book.expression_at(point(2, 3)), sympy.Symbol("V1") / 2)


def test_a_bridge_does_not_mix_the_two_voltages():
    book = formulas(
        Component("ground", "GND1", "", 4, 2),
        Component("dc_source", "V1", "10", 2, 2),
        Component("dc_source", "V2", "5", 1, 4),
        wires=[
            (point(3, 2), point(4, 2), ()),
            (point(2, 2), point(2, 6), (point(2, 4),)),
            (point(2, 4), point(3, 4), ()),
            (point(3, 4), point(3, 2), ()),
        ],
    )

    same(book.expression_at(point(2, 2)), 10)
    same(book.expression_at(point(2, 6)), 10)
    same(book.expression_at(point(1, 4)), 5)
    same(book.expression_at(point(2, 4)), 0)


def test_ideal_opamp_buffer_copies_the_input():
    book = formulas(
        Component("opamp_741", "X1", "LM741", 4, 4),
        Component("dc_source", "V1", "1", 5, 3),
        Component("ground", "GND1", "", 6, 3),
        wires=[
            # Stay off row 3 column 4, which is the V+ pin.
            (point(4, 5), point(4, 6), ()),
            (point(4, 6), point(2, 6), ()),
            (point(2, 6), point(2, 3), ()),
            (point(2, 3), point(3, 3), ()),
        ],
    )

    same(book.expression_at(point(4, 5)), 1)
    same(book.expression_at(point(5, 3)), 1)
    assert "Ideal op-amp" in book.text_at(point(4, 5))
    assert book.text_at(point(3, 4)).startswith("No s-domain formula")


def test_a_diode_has_no_formula():
    book = formulas(
        Component("ground", "GND1", "", 3, 2),
        Component("diode", "D1", "1N4148", 2, 2),
    )

    assert book.text_at(point(2, 2)) == (
        "D1 is a diode, so there is no s-domain formula for this circuit."
    )


def test_a_floating_resistor_has_no_single_formula():
    book = formulas(
        Component("ground", "GND1", "", 6, 6),
        Component("resistor", "R1", "1k", 2, 2),
    )

    assert book.text_at(point(2, 2)).startswith(
        "This circuit has no single formula."
    )
    assert book.text_at(point(6, 6)) == "V(s) = 0 V"


def test_no_ground_explains_what_to_add():
    book = formulas(Component("resistor", "R1", "1k", 2, 2))

    assert book.text_at(point(2, 2)) == (
        "Add a ground part before a formula can be written."
    )


def test_formulas_need_a_wire_collection():
    with pytest.raises(ComponentError, match="WireCollection"):
        build_node_formulas([], "wires")


def test_the_selected_point_shows_the_formula(qt_application):
    window = MainWindow()
    grid = window.connection_grid
    parts = [
        Component("ground", "GND1", "", 4, 2),
        Component("dc_source", "V1", "10", 2, 2),
        Component("resistor", "R1", "10k", 2, 2),
        Component("resistor", "R2", "10k", 2, 3, 90),
    ]

    for part in parts:
        window.component_collection.components_by_reference[
            part.reference
        ] = part

    window.wire_collection.add_wire(point(3, 2), point(4, 2), grid)
    window.wire_collection.add_wire(point(3, 3), point(3, 2), grid)
    window.handle_connection_point_selection(
        grid.get_connection_point(point(2, 3))
    )

    assert window.selected_node_formula_label.text() == "V(s) = 5 V"

    window.component_collection.set_component_value("R2", "30k")
    window.mark_project_modified("Set R2.")

    assert window.selected_node_formula_label.text() == "V(s) = 7.5 V"
    window.is_project_modified = False
    window.close()
    window.deleteLater()
