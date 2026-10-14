"""
Probes. Hand checks on a 10 V, 10k/10k divider:

The midpoint is 5 V with a Direct probe.
A 1 Mohm probe to ground makes it 1000/201 V (4.975 V).
A 10x probe (10 Mohm || 10 pF) is 10000/2001 V at DC (4.9975 V).
Current through the top resistor is 0.5 mA.
"""

import math

import pytest
import sympy
from PyQt5.QtCore import QEvent, QPointF, Qt
from PyQt5.QtWidgets import QApplication

from core.components import Component
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.node_formula import build_node_formulas
from core.probes import (
    ProbeCollection,
    describe_reading,
    flag_offset_from_saved,
    parameter_lines,
    point_for_text,
    shunt_loads,
)
from core.project_io import load_project_file, save_project_file
from core.wires import WireCollection
from gui.grid_editor import grid_point_to_scene_position
from gui.main_window import MainWindow
from tests.view_mouse import click, drag, send_mouse


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
    book, probe, parts = loaded("direct")

    same(book.expression_at(point(2, 3)), 5)
    assert describe_reading(probe, book) == "V(s) = 5 V"
    assert parameter_lines(probe, book, parts) == [
        ("Formula", "V(s) = 5 V"),
        ("Voltage", "5 V"),
        ("Frequency", "DC"),
    ]


def test_one_megohm_probe_reads_4_975_volts():
    # 10k || 1M = 1000000/101
    # 10 * that / (10k + that) = 1000/201 = 4.975124...
    book, probe, _parts = loaded("megohm")

    same(book.expression_at(point(2, 3)), sympy.Rational(1000, 201))
    assert describe_reading(probe, book).startswith("V(s) = 4.975")
    lines = dict(parameter_lines(probe, book, _parts))
    assert lines["Formula"].startswith("V(s) = 4.975")
    assert lines["Voltage"].startswith("4.975")
    assert lines["Frequency"] == "DC"


def test_10x_probe_reads_4_9975_volts_at_dc():
    # At s = 0 the 10 pF is open, leaving 10k || 10M.
    # 10 * (10000000/1001) / (10k + that) = 10000/2001 = 4.997501...
    book, probe, _parts = loaded("scope_10x")
    laplace = sympy.symbols("s")
    expression = book.expression_at(point(2, 3))

    same(expression.subs(laplace, 0), sympy.Rational(10000, 2001))
    assert "At DC: 4.9975" in describe_reading(probe, book)
    lines = dict(parameter_lines(probe, book, _parts))
    assert lines["Formula"].startswith("V(s) = ")
    assert "s" in lines["Formula"]
    assert lines["Voltage"].startswith("4.9975")
    assert lines["Frequency"] == "DC"


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
    assert parameter_lines(probe, book, parts, parts[2]) == [
        ("Formula", "I = 0.0005 A"),
        ("Current", "0.0005 A"),
        ("Voltage", "5 V"),
        ("Frequency", "DC"),
    ]


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
    assert parameter_lines(probe, book, parts, diode) == []


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


def test_an_ac_divider_shows_peak_voltage_and_frequency():
    # 10 V peak at 1 kHz across 10k/10k is 5 V peak, in phase.
    grid = ConnectionGrid(8, 8)
    parts = [
        Component("ground", "GND1", "", 4, 2),
        Component("ac_source", "V1", "10", 2, 2, parameter_texts={
            "frequency": "1k",
        }),
        Component("resistor", "R1", "10k", 2, 2),
        Component("resistor", "R2", "10k", 2, 3, 90),
    ]
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 3), grid)
    book = build_node_formulas(parts, divider_wires(grid), grid)

    assert parameter_lines(probe, book, parts) == [
        ("Formula", "V(s) = V1/2"),
        ("Voltage", "5 V peak"),
        ("Frequency", "1 kHz"),
        ("Phase", "0 deg"),
    ]


def test_a_lowpass_probe_shows_the_phase_lag():
    # 1 V peak at 1 kHz, 1k series, 1 uF to ground.
    # |H| = 1/sqrt(1+(2*pi)**2), angle = -atan(2*pi).
    grid = ConnectionGrid(8, 8)
    parts = [
        Component("ground", "GND1", "", 4, 2),
        Component("ac_source", "V1", "1", 2, 2),
        Component("resistor", "R1", "1k", 2, 2),
        Component("capacitor", "C1", "1u", 2, 3, 90),
    ]
    wires = WireCollection()
    wires.add_wire(point(3, 2), point(4, 2), grid)
    wires.add_wire(point(3, 3), point(3, 2), grid)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 3), grid)
    book = build_node_formulas(parts, wires, grid)
    magnitude = 1 / math.sqrt(1 + (2 * math.pi) ** 2)
    degrees = -math.degrees(math.atan(2 * math.pi))
    voltage = f"{magnitude:.6f}".rstrip("0").rstrip(".")
    phase = f"{degrees:.2f}".rstrip("0").rstrip(".")

    lines = parameter_lines(probe, book, parts)

    assert lines[0][0] == "Formula"
    assert lines[0][1].startswith("V(s) = ")
    assert "s" in lines[0][1]
    assert lines[1:] == [
        ("Voltage", f"{voltage} V peak"),
        ("Frequency", "1 kHz"),
        ("Phase", f"{phase} deg"),
    ]


def test_two_ac_frequencies_are_listed_separately():
    # V1 (10 V peak, 1 kHz) stacked on V2 (4 V peak, 2 kHz), both to ground.
    grid = ConnectionGrid(8, 8)
    parts = [
        Component("ground", "GND1", "", 4, 2),
        Component("ac_source", "V2", "4", 3, 2, parameter_texts={
            "frequency": "2k",
        }),
        Component("ac_source", "V1", "10", 2, 2, parameter_texts={
            "frequency": "1k",
        }),
    ]
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 2), grid)
    book = build_node_formulas(parts, WireCollection(), grid)

    assert parameter_lines(probe, book, parts) == [
        ("Formula", "V(s) = V1 + V2"),
        ("Voltage", "10 V peak at 1 kHz"),
        ("Voltage", "4 V peak at 2 kHz"),
        ("Phase", "0 deg at 1 kHz"),
        ("Phase", "0 deg at 2 kHz"),
    ]


def test_a_plotted_probe_still_has_its_meter_lines():
    # The scope trace does not replace the box. The midpoint stays 5 V.
    book, probe, parts = loaded("direct")

    probe.has_plot = True

    assert parameter_lines(probe, book, parts) == [
        ("Formula", "V(s) = 5 V"),
        ("Voltage", "5 V"),
        ("Frequency", "DC"),
    ]


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
        assert window.probe_parameter_label.text() == (
            "Formula: V(s) = 5 V\nVoltage: 5 V\nFrequency: DC"
        )
        flag = next(
            item for item in window.connection_grid_scene.probe_items
            if item.probe.reference == "P1"
        )
        assert flag.readout_lines == (
            ("Formula", "V(s) = 5 V"),
            ("Voltage", "5 V"),
            ("Frequency", "DC"),
        )
        assert flag.boundingRect().width() > flag._flag_rect().width()

        window.probe_method_combo.setCurrentIndex(
            window.probe_method_combo.findData("megohm")
        )

        assert probe.method == "megohm"
        assert window.probe_reading_label.text().startswith("V(s) = 4.975")
        assert window.probe_parameter_label.text().startswith(
            "Formula: V(s) = 4.975"
        )
        assert "Voltage: 4.975" in window.probe_parameter_label.text()
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
        assert window.probe_parameter_label.text() == (
            "Formula: I = 0.01 A\n"
            "Current: 0.01 A\nVoltage: 10 V\nFrequency: DC"
        )
    finally:
        close_window(window)


def test_a_plotted_probe_keeps_the_grid_box(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid

        for part in divider_parts():
            window.component_collection.components_by_reference[
                part.reference
            ] = part

        window.wire_collection.add_wire(point(3, 2), point(4, 2), grid)
        window.wire_collection.add_wire(point(3, 3), point(3, 2), grid)
        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()
        window.show()
        QApplication.processEvents()
        window.probe_mode_action.setChecked(True)
        click(
            window.connection_grid_view,
            grid_point_to_scene_position(2, 3),
        )
        window.probe_collection.set_has_plot("P1", True)
        window.refresh_probe_parameters()

        assert window.probe_parameter_label.text() == "On a plot."
        assert window.connection_grid_scene.probe_items[0].readout_lines == (
            ("Formula", "V(s) = 5 V"),
            ("Voltage", "5 V"),
            ("Frequency", "DC"),
        )
    finally:
        close_window(window)


def test_changing_a_pot_updates_boxes_on_plotted_probes(qt_application):
    # 10 V across a 10k pot. Position 0.5 is 5 V on the wiper.
    # Position 0.25 is 10 * 0.25 = 2.5 V. Pin 1 stays at 10 V.
    # A 1 Tohm from the wiper to ground is that pin's second
    # connection and does not move the reading. A 20k pot at the
    # same position is still 2.5 V.
    window = MainWindow()

    try:
        grid = window.connection_grid
        parts = window.component_collection
        parts.components_by_reference["GND1"] = Component(
            "ground", "GND1", "", 8, 2
        )
        parts.components_by_reference["V1"] = Component(
            "dc_source", "V1", "10", 4, 2
        )
        parts.components_by_reference["RV1"] = Component(
            "potentiometer", "RV1", "10k", 4, 3
        )
        parts.components_by_reference["R1"] = Component(
            "resistor", "R1", "1t", 5, 4
        )
        wires = window.wire_collection
        wires.add_wire(point(5, 2), point(8, 2), grid)
        wires.add_wire(point(4, 2), point(4, 3), grid)
        wires.add_wire(point(4, 5), point(8, 5), grid)
        wires.add_wire(point(8, 2), point(8, 5), grid)
        wires.add_wire(point(5, 5), point(8, 5), grid)
        window.connection_grid_scene.rebuild_component_items()
        window.connection_grid_scene.rebuild_wire_items()
        window.probe_collection.add_voltage(point(4, 3), grid)
        window.probe_collection.add_voltage(point(5, 4), grid)
        window.connection_grid_scene.rebuild_probe_items()
        window.refresh_probe_parameters()
        window.probe_collection.set_has_plot("P1", True)
        window.probe_collection.set_has_plot("P2", True)
        window.connection_grid_scene.rebuild_probe_items()

        assert flag_for(window, "P2").readout_lines == (
            ("Formula", "V(s) = 5 V"),
            ("Voltage", "5 V"),
            ("Frequency", "DC"),
        )

        window.handle_component_selection(parts.get_component("RV1"))
        window.apply_component_value("10k", {"position": "0.25"})

        assert flag_for(window, "P1").readout_lines == (
            ("Formula", "V(s) = 10 V"),
            ("Voltage", "10 V"),
            ("Frequency", "DC"),
        )
        assert flag_for(window, "P2").readout_lines == (
            ("Formula", "V(s) = 2.5 V"),
            ("Voltage", "2.5 V"),
            ("Frequency", "DC"),
        )

        window.apply_component_value("20k", {"position": "0.25"})

        assert flag_for(window, "P1").readout_lines == (
            ("Formula", "V(s) = 10 V"),
            ("Voltage", "10 V"),
            ("Frequency", "DC"),
        )
        assert flag_for(window, "P2").readout_lines == (
            ("Formula", "V(s) = 2.5 V"),
            ("Voltage", "2.5 V"),
            ("Frequency", "DC"),
        )
    finally:
        close_window(window)


def near(left, right, tolerance=1.5):
    return (
        abs(left.x() - right.x()) < tolerance
        and abs(left.y() - right.y()) < tolerance
    )


def flag_for(window, reference, role="primary"):
    return next(
        item for item in window.connection_grid_scene.probe_items
        if item.probe.reference == reference and item.role == role
    )


def show(window):
    window.show()
    QApplication.processEvents()


def test_the_usual_probe_place_is_not_saved():
    grid = ConnectionGrid(8, 8)
    probe = ProbeCollection().add_voltage(point(1, 1), grid)

    assert "flag_x" not in probe.to_dict()

    probe.set_flag_offset(0.2, -0.2)

    assert probe.flag_offset == (0.0, 0.0)
    assert probe.flag_is_moved() is False


def test_a_probe_position_must_be_two_finite_numbers():
    grid = ConnectionGrid(8, 8)
    probe = ProbeCollection().add_voltage(point(1, 1), grid)

    with pytest.raises(ComponentError, match="two numbers"):
        probe.set_flag_offset("left", 4)

    with pytest.raises(ComponentError, match="finite"):
        probe.set_flag_offset(float("nan"), 1)


def test_a_saved_probe_position_needs_both_numbers():
    with pytest.raises(ComponentError, match="both the across and down"):
        flag_offset_from_saved({"flag_x": 3}, "flag_x", "flag_y")


def test_a_second_flag_position_needs_a_second_point():
    grid = ConnectionGrid(8, 8)
    probes = ProbeCollection()

    with pytest.raises(ComponentError, match="only one point"):
        probes.place_saved(
            "P1", "direct", "#ff6b6b", grid,
            identifier=point(1, 1),
            second_flag_offset=(4, 5),
        )

    assert probes.get_probes() == []


def test_a_moved_probe_is_saved_and_loaded(tmp_path):
    grid = ConnectionGrid(8, 8)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(2, 3), grid)
    probes.set_method(probe.reference, "differential")
    probes.set_second_point(probe.reference, point(4, 2), grid)
    probe.set_flag_offset(40, -12)
    probe.set_flag_offset(8, 20, "second")
    path = tmp_path / "probes.json"
    save_project_file(path, grid, probe_collection=probes)

    again = load_project_file(path).probe_collection.get("P1")

    assert again.identifier == point(2, 3)
    assert again.second_identifier == point(4, 2)
    assert again.flag_offset == (40.0, -12.0)
    assert again.second_flag_offset == (8.0, 20.0)


def test_the_arrow_points_at_the_measured_point(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        anchor = grid_point_to_scene_position(2, 3)

        assert near(flag.mapToScene(flag.leader_target()), anchor)
        assert flag.boundingRect().contains(flag.leader_target())
        assert not window.reset_probe_position_button.isEnabled()
    finally:
        close_window(window)


def test_a_dragged_probe_stays_where_it_is_released(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        start = flag.mapToScene(flag._flag_rect().center())
        # Toward the point, but not onto it, and not onto a neighbour.
        released = start + QPointF(10, 10)
        drag(window.connection_grid_view, start, released)

        flag = flag_for(window, probe.reference)
        anchor = grid_point_to_scene_position(2, 3)

        assert probe.identifier == point(2, 3)
        assert near(flag.mapToScene(flag._flag_rect().center()), released)
        assert near(flag.mapToScene(flag.leader_target()), anchor)
        assert window.reset_probe_position_button.isEnabled()
        assert "Drop the probe" not in window.statusBar().currentMessage()

        window.reset_probe_position_button.click()
        flag = flag_for(window, probe.reference)

        assert probe.identifier == point(2, 3)
        assert near(flag.pos(), anchor)
        assert probe.flag_offset == (0.0, 0.0)
        assert window.reset_probe_position_button.isEnabled() is False
    finally:
        close_window(window)


def test_dragging_the_flag_onto_another_point_keeps_the_old_point(
        qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        start = flag.mapToScene(flag._flag_rect().center())
        target = grid_point_to_scene_position(2, 5)
        drag(window.connection_grid_view, start, target)

        flag = flag_for(window, probe.reference)

        assert probe.identifier == point(2, 3)
        assert near(flag.mapToScene(flag._flag_rect().center()), target)
        assert near(
            flag.mapToScene(flag.leader_target()),
            grid_point_to_scene_position(2, 3),
        )
    finally:
        close_window(window)


def arrow_tip(flag):
    return flag.mapToScene(
        flag._arrow_tip(flag._leader_start(), flag.leader_target())
    )


def test_dragging_the_arrow_reads_that_point(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        readings = flag.mapToScene(flag._flag_rect().center())
        target = grid_point_to_scene_position(2, 5)
        drag(window.connection_grid_view, arrow_tip(flag), target)

        flag = flag_for(window, probe.reference)

        assert probe.identifier == point(2, 5)
        assert near(flag.mapToScene(flag._flag_rect().center()), readings)
        assert near(flag.mapToScene(flag.leader_target()), target)
    finally:
        close_window(window)


def test_an_arrow_released_off_the_grid_keeps_the_point(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        drag(
            window.connection_grid_view,
            arrow_tip(flag),
            QPointF(-400, -400),
        )

        assert probe.identifier == point(2, 3)
        assert "off the grid" in window.statusBar().currentMessage()
        assert point(2, 3) in window.statusBar().currentMessage()
    finally:
        close_window(window)


def test_aiming_the_arrow_marks_the_point_it_would_choose(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        show(window)
        flag = flag_for(window, probe.reference)
        start = arrow_tip(flag)
        target = grid_point_to_scene_position(2, 5)
        view = window.connection_grid_view
        send_mouse(view, QEvent.MouseButtonPress, start)
        send_mouse(
            view, QEvent.MouseMove, target, Qt.NoButton, Qt.LeftButton
        )
        candidate = (
            window.connection_grid_scene
            .connection_point_items_by_identifier[point(2, 5)]
        )
        home = (
            window.connection_grid_scene
            .connection_point_items_by_identifier[point(2, 3)]
        )

        assert candidate.aim_candidate is True
        assert home.aim_candidate is False
        assert candidate.problem is False

        send_mouse(view, QEvent.MouseButtonRelease, target)

        assert candidate.aim_candidate is False
        assert probe.identifier == point(2, 5)
    finally:
        close_window(window)


def test_typing_a_point_moves_the_arrow_and_leaves_the_flag(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        probe.set_flag_offset(40, -12)
        window.connection_grid_scene.rebuild_probe_items()
        window.connection_grid_scene.select_probe(probe.reference)
        show(window)
        flag = flag_for(window, probe.reference)
        readings = flag.mapToScene(flag._flag_rect().center())
        window.probe_point_edit.setText("R2 C5")
        window.probe_point_edit.returnPressed.emit()

        flag = flag_for(window, probe.reference)

        assert probe.identifier == point(2, 5)
        assert near(flag.mapToScene(flag._flag_rect().center()), readings)
        assert near(
            flag.mapToScene(flag.leader_target()),
            grid_point_to_scene_position(2, 5),
        )
        assert window.probe_point_edit.text() == point(2, 5)
    finally:
        close_window(window)


def test_a_bad_point_tells_what_is_allowed(qt_application, monkeypatch):
    window = MainWindow()
    recorded = []
    monkeypatch.setattr(
        window,
        "show_error_message",
        lambda title, reason, resolution: recorded.append((title, reason)),
    )

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        window.connection_grid_scene.select_probe(probe.reference)
        show(window)
        window.probe_point_edit.setText("banana")
        window.probe_point_apply.click()

        assert probe.identifier == point(2, 3)
        assert recorded[0][0] == "Probe Point Not Changed"
        assert "NODE_R04_C03" in recorded[0][1]
        assert "Vcc" in recorded[0][1]
    finally:
        close_window(window)


def test_typing_the_minus_point_of_a_differential_probe(qt_application):
    window = MainWindow()

    try:
        probe = window.probe_collection.add_voltage(
            point(2, 3), window.connection_grid
        )
        window.probe_collection.set_method(probe.reference, "differential")
        window.probe_collection.set_second_point(
            probe.reference, point(4, 2), window.connection_grid
        )
        window.connection_grid_scene.rebuild_probe_items()
        window.connection_grid_scene.select_probe(probe.reference)
        show(window)

        assert window.probe_minus_row.isVisible()
        window.probe_minus_edit.setText("4, 5")
        window.probe_minus_edit.returnPressed.emit()

        assert probe.identifier == point(2, 3)
        assert probe.second_identifier == point(4, 5)
    finally:
        close_window(window)


def test_a_current_probe_has_no_point_box(qt_application):
    window = MainWindow()

    try:
        resistor = Component("resistor", "R1", "1k", 2, 2)
        window.component_collection.components_by_reference["R1"] = resistor
        window.component_collection.components_by_reference["R2"] = (
            Component("resistor", "R2", "1k", 2, 6)
        )
        window.connection_grid_scene.rebuild_component_items()
        probe = window.probe_collection.add_current(resistor)
        window.connection_grid_scene.rebuild_probe_items()
        window.connection_grid_scene.select_probe(probe.reference)
        show(window)

        assert window.probe_point_row.isVisible() is False

        flag = flag_for(window, probe.reference)
        body = grid_point_to_scene_position(2, 6) + QPointF(30, 0)
        drag(
            window.connection_grid_view,
            flag.mapToScene(flag._flag_rect().center()),
            body,
        )

        assert probe.component_reference == "R1"

        flag = flag_for(window, probe.reference)
        drag(window.connection_grid_view, arrow_tip(flag), body)

        assert probe.component_reference == "R2"
    finally:
        close_window(window)


def test_a_typed_point_accepts_a_node_a_row_and_a_net_name():
    grid = ConnectionGrid(8, 8)

    assert point_for_text("node_r04_c03", grid) == point(4, 3)
    assert point_for_text("4 3", grid) == point(4, 3)
    assert point_for_text("4,3", grid) == point(4, 3)
    assert point_for_text("R4 C3", grid) == point(4, 3)
    assert point_for_text("R4C3", grid) == point(4, 3)

    grid.set_net_label(point(4, 3), "Vcc")
    grid.set_net_label(point(2, 5), "vcc")

    # Same name, ignoring case, is one node. The arrow uses the
    # top-left point, which is the first identifier in row-column order.
    assert point_for_text("VCC", grid) == point(2, 5)

    with pytest.raises(ComponentError, match="NODE_R04_C03"):
        point_for_text("  ", grid)

    with pytest.raises(ComponentError, match="banana"):
        point_for_text("banana", grid)

    with pytest.raises(ComponentError, match="NODE_R02_C03"):
        point_for_text("99 99", grid)


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
