"""
Probes. Hand checks on a 10 V, 10k/10k divider:

The midpoint is 5 V with a Direct probe.
A 1 Mohm probe to ground makes it 1000/201 V (4.975 V).
A 10x probe (10 Mohm || 10 pF) is 10000/2001 V at DC (4.9975 V).
Current through the top resistor is 0.5 mA.
"""

import pytest
import sympy
from PyQt5.QtCore import QPointF
from PyQt5.QtWidgets import QApplication

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.node_formula import build_node_formulas
from core.probes import ProbeCollection, describe_reading, shunt_loads
from core.wires import WireCollection
from gui.grid_editor import grid_point_to_scene_position
from gui.main_window import MainWindow
from tests.view_mouse import click


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def same(expression, expected):
    assert expression is not None
    assert sympy.simplify(expression - expected) == 0


def divider_parts():
    return [
        Component("ground", "GND1", "", 4, 2),
        Component("dc_source", "V1", "10", 2, 2),
        Component("resistor", "R1", "10k", 2, 2),
        Component("resistor", "R2", "10k", 2, 3, 90),
    ]


def divider_wires(grid):
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(3, 3), point(3, 2), grid)
    return wires


def loaded(method):
    grid = ConnectionGrid(8, 8)
    parts = divider_parts()
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 3), grid)
    probes.set_method(probe.reference, method, parts)
    book = build_node_formulas(
        parts, divider_wires(grid), grid, shunt_loads(probes.get_probes())
    )
    return book, probe, parts


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


# ----- readings -------------------------------------------------------------

def test_direct_probe_does_not_load_the_divider():
    book, probe, _parts = loaded("direct")

    same(book.expression_at(point(2, 3)), 5)
    assert describe_reading(probe, book) == "V(s) = 5 V"


def test_one_megohm_probe_reads_4_975_volts():
    # 10k || 1M = 1000000/101
    # 10 * that / (10k + that) = 1000/201 = 4.975124...
    book, probe, _parts = loaded("megohm")

    same(book.expression_at(point(2, 3)), sympy.Rational(1000, 201))
    assert describe_reading(probe, book).startswith("V(s) = 4.975")


def test_10x_probe_reads_4_9975_volts_at_dc():
    # At s = 0 the 10 pF is open, leaving 10k || 10M.
    # 10 * (10000000/1001) / (10k + that) = 10000/2001 = 4.997501...
    book, probe, _parts = loaded("scope_10x")
    laplace = sympy.symbols("s")
    expression = book.expression_at(point(2, 3))

    same(expression.subs(laplace, 0), sympy.Rational(10000, 2001))
    assert "At DC: 4.9975" in describe_reading(probe, book)


def test_differential_is_the_midpoint_minus_ground():
    grid = ConnectionGrid(8, 8)
    parts = divider_parts()
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 3), grid)
    probes.set_method(probe.reference, "differential", parts)
    probes.set_second_point(probe.reference, point(4, 2), grid)
    book = build_node_formulas(
        parts, divider_wires(grid), grid, shunt_loads(probes.get_probes())
    )

    assert describe_reading(probe, book) == "V(s) = 5 V"
    assert shunt_loads(probes.get_probes()) == ()


def test_differential_waits_for_the_second_point():
    grid = ConnectionGrid(4, 4)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(1, 1), grid)
    probes.set_method(probe.reference, "differential")
    book = build_node_formulas([], WireCollection(), grid)

    assert describe_reading(probe, book) == (
        "Click the other point for this differential probe."
    )


def test_current_through_the_top_resistor_is_half_a_milliamp():
    # 10 V across 20k is 0.5 mA, from pin 1 of R1 toward pin 2.
    grid = ConnectionGrid(8, 8)
    parts = divider_parts()
    probes = ProbeCollection()
    probe = probes.add_current(parts[2])
    book = build_node_formulas(parts, divider_wires(grid), grid)

    same(book.current_expression(parts[2]), sympy.Rational(1, 2000))
    assert describe_reading(probe, book, parts[2]) == "I = 0.0005 A"
    same(book.current_expression(parts[1]), sympy.Rational(1, 2000))


def test_an_open_source_supplies_no_current():
    grid = ConnectionGrid(4, 4)
    parts = [
        Component("ground", "GND1", "", 3, 2),
        Component("dc_source", "V1", "10", 2, 2),
    ]
    book = build_node_formulas(parts, WireCollection(), grid)

    same(book.current_expression(parts[1]), 0)


def test_a_current_probe_on_a_diode_has_no_formula():
    grid = ConnectionGrid(4, 4)
    diode = Component("diode", "D1", "1N4148", 2, 2)
    parts = [Component("ground", "GND1", "", 3, 2), diode]
    probes = ProbeCollection()
    probe = probes.add_current(diode)
    book = build_node_formulas(parts, WireCollection(), grid)

    assert "no s-domain formula" in describe_reading(probe, book, diode)


# ----- collection -----------------------------------------------------------

def test_references_reuse_the_lowest_free_number():
    grid = ConnectionGrid(4, 4)
    probes = ProbeCollection()
    probes.add_voltage(point(1, 1), grid)
    second = probes.add_voltage(point(1, 2), grid)
    probes.remove("P1")

    assert second.reference == "P2"
    assert probes.add_voltage(point(1, 3), grid).reference == "P1"


def test_a_second_current_probe_on_the_same_part_is_refused():
    resistor = Component("resistor", "R1", "1k", 2, 2)
    probes = ProbeCollection()
    probes.add_current(resistor)

    with pytest.raises(ComponentError, match="already has current probe P1"):
        probes.add_current(resistor)

    assert len(probes.get_probes()) == 1


def test_current_needs_one_part_on_the_point():
    grid = ConnectionGrid(4, 4)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(1, 1), grid)

    with pytest.raises(ComponentError, match="Nothing is on this point"):
        probes.set_method(probe.reference, "current", [])

    assert probe.method == "direct"

    parts = divider_parts()
    # (2, 2) holds the source plus pin and R1 pin 1.
    shared = probes.add_voltage(point(2, 2), grid)

    with pytest.raises(ComponentError, match="More than one part"):
        probes.set_method(shared.reference, "current", parts)

    assert shared.method == "direct"


def test_switching_to_current_uses_the_only_part():
    grid = ConnectionGrid(8, 8)
    ground = Component("ground", "GND1", "", 4, 2)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(4, 2), grid)
    probes.set_method(probe.reference, "current", [ground])

    assert probe.method == "current"
    assert probe.component_reference == "GND1"
    assert probe.identifier is None


def test_a_bad_point_is_refused_and_nothing_is_stored():
    probes = ProbeCollection()

    with pytest.raises(ComponentError, match="grid point"):
        probes.add_voltage("NODE_R99_C99", ConnectionGrid(4, 4))

    assert probes.get_probes() == []


def test_differential_points_must_differ():
    grid = ConnectionGrid(4, 4)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(1, 1), grid)
    probes.set_method(probe.reference, "differential")

    with pytest.raises(ComponentError, match="must be different"):
        probes.set_second_point(probe.reference, point(1, 1), grid)


def test_shrinking_the_grid_drops_a_probe_outside_it():
    grid = ConnectionGrid(8, 8)
    probes = ProbeCollection()
    probes.add_voltage(point(2, 2), grid)
    probes.add_voltage(point(8, 8), grid)
    far = probes.add_voltage(point(2, 3), grid)
    probes.set_method(far.reference, "differential")
    probes.set_second_point(far.reference, point(8, 1), grid)

    removed = probes.remove_outside_grid(ConnectionGrid(4, 4))

    assert removed == ["P2"]
    assert probes.get("P1").identifier == point(2, 2)
    assert probes.get("P3").second_identifier is None


def test_a_bad_probe_load_is_refused():
    with pytest.raises(ComponentError, match="resistor or a capacitor"):
        build_node_formulas(
            [], WireCollection(), shunts=[(point(1, 1), "wire", 1)]
        )


# ----- the window -----------------------------------------------------------

def test_probe_mode_places_a_1_megohm_probe(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid

        for part in divider_parts():
            window.component_collection.components_by_reference[
                part.reference
            ] = part

        for start, end in (
                (point(3, 2), point(4, 2)),
                (point(3, 3), point(3, 2)),
        ):
            window.wire_collection.add_wire(start, end, grid)

        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()
        window.show()
        QApplication.processEvents()
        window.probe_mode_action.setChecked(True)
        click(
            window.connection_grid_view,
            grid_point_to_scene_position(2, 3),
        )

        probe = window.probe_collection.get("P1")
        assert probe.method == "direct"
        assert probe.identifier == point(2, 3)
        assert window.probe_reading_label.text() == "V(s) = 5 V"
        assert window.probe_name_label.text() == "P1"

        window.probe_method_combo.setCurrentIndex(
            window.probe_method_combo.findData("megohm")
        )

        assert probe.method == "megohm"
        assert window.probe_reading_label.text().startswith("V(s) = 4.975")
        assert any(
            item.probe.reference == "P1" and "1M" in item._flag_text()
            for item in window.connection_grid_scene.probe_items
        )

        window.probe_method_combo.setCurrentIndex(
            window.probe_method_combo.findData("differential")
        )
        click(
            window.connection_grid_view,
            grid_point_to_scene_position(4, 2),
        )

        assert probe.second_identifier == point(4, 2)
        # Differential adds no load, so the 1 Mohm is gone and the
        # midpoint is 5 V above ground again.
        assert window.probe_reading_label.text() == "V(s) = 5 V"

        window.delete_selection()
        assert window.probe_collection.get_probes() == []
    finally:
        close_window(window)


def test_clicking_a_part_places_a_current_probe(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        resistor = Component("resistor", "R1", "1k", 2, 2)
        window.component_collection.components_by_reference["R1"] = resistor
        window.component_collection.components_by_reference["GND1"] = (
            Component("ground", "GND1", "", 3, 2)
        )
        window.component_collection.components_by_reference["V1"] = (
            Component("dc_source", "V1", "10", 2, 2)
        )
        window.wire_collection.add_wire(point(2, 3), point(3, 3), grid)
        window.wire_collection.add_wire(point(3, 3), point(3, 2), grid)
        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()
        window.show()
        QApplication.processEvents()
        window.probe_mode_action.setChecked(True)
        # The body centre is half a step to the right of the anchor, away
        # from both pins, so the click is a current probe rather than a
        # voltage probe on a pin.
        anchor = grid_point_to_scene_position(2, 2)
        click(window.connection_grid_view, anchor + QPointF(30, 0))

        probe = window.probe_collection.get("P1")
        assert probe.method == "current"
        assert probe.component_reference == "R1"
        assert window.probe_reading_label.text() == "I = 0.01 A"
    finally:
        close_window(window)


def test_probe_mode_turns_wire_mode_off(qt_application):
    window = MainWindow()

    try:
        window.wire_mode_action.setChecked(True)
        window.probe_mode_action.setChecked(True)

        assert window.wire_mode_action.isChecked() is False
        assert window.connection_grid_scene.is_probe_mode is True

        window.wire_mode_action.setChecked(True)

        assert window.probe_mode_action.isChecked() is False
        assert window.connection_grid_scene.is_wire_mode is True
    finally:
        close_window(window)
