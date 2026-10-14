"""
File > Examples. The numbers are the hand calculation.

Divider: 10 V across 10k + 10k is 5 V, and 10/20k = 0.5 mA.
The bottom resistor at 30k is 10 * 30/40 = 7.5 V.

RC: 1 V peak at 1 kHz into 1k and 159 nF.
w = 2*pi*1e3*1e3*159e-9. The capacitor is 1/sqrt(1+w*w) V peak
at -atan(w) degrees.

Buffer: a unity-gain follower copies a 1 V peak, 1 kHz sine.
The output is that same sine.

AND gate: both inputs at 5 V, so the output is 5 V.
"""

import math

import pytest
import sympy
from PyQt5.QtWidgets import QApplication

from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError
from core.netlist import build_netlist, spice_node_map
from core.node_formula import build_node_formulas
from core.probes import parameter_lines
from examples.samples import build_example, example_ids
from gui.main_window import MainWindow
from sim import runner
from sim.runner import run_op

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

_W_RC = 2.0 * math.pi * 1e3 * 1e3 * 159e-9
RC_PEAK = 1.0 / math.sqrt(1.0 + _W_RC * _W_RC)
RC_PHASE = -math.degrees(math.atan(_W_RC))


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def lines_at(workbook, identifier):
    parts = workbook.component_collection.get_components()
    formulas = build_node_formulas(
        parts, workbook.wire_collection, workbook.connection_grid
    )
    probe = next(
        item for item in workbook.probe_collection.get_probes()
        if item.identifier == identifier
    )
    return parameter_lines(probe, formulas, parts), formulas


def number_in(lines, label):
    text = dict(lines)[label]
    return float(text.split()[0])


def file_menu(window):
    return next(
        action.menu()
        for action in window.menuBar().actions()
        if action.text() == "&File"
    )


def examples_menu(window):
    return next(
        action.menu()
        for action in file_menu(window).actions()
        if action.menu() is not None and action.text() == "Examples"
    )


def test_the_four_examples_are_the_menu():
    assert example_ids() == ("divider", "rc", "buffer", "and")

    with pytest.raises(ComponentError, match="divider, rc, buffer, and"):
        build_example("nope")


def test_the_divider_is_5_volts_and_half_a_milliamp():
    workbook = build_example("divider")
    lines, formulas = lines_at(workbook, point(4, 4))
    parts = workbook.component_collection.get_components()
    top = next(part for part in parts if part.reference == "R1")

    assert lines == [
        ("Formula", "V(s) = 5 V"),
        ("Voltage", "5 V"),
        ("Frequency", "DC"),
    ]
    assert sympy.simplify(
        formulas.current_expression(top) - sympy.Rational(1, 2000)
    ) == 0


def test_the_rc_is_the_low_pass_at_1_kilohertz():
    lines, _formulas = lines_at(build_example("rc"), point(4, 4))

    assert number_in(lines, "Voltage") == pytest.approx(RC_PEAK, abs=1e-6)
    assert dict(lines)["Frequency"] == "1 kHz"
    assert number_in(lines, "Phase") == pytest.approx(RC_PHASE, abs=0.01)


def test_the_buffer_copies_the_1_volt_sine():
    workbook = build_example("buffer")
    incoming, formulas = lines_at(workbook, point(6, 2))
    outgoing, _same = lines_at(workbook, point(6, 7))

    assert incoming[0][0] == "Formula"
    assert incoming[0][1].startswith("V(s) = ")
    assert incoming[1:] == [
        ("Voltage", "1 V peak"),
        ("Frequency", "1 kHz"),
        ("Phase", "0 deg"),
    ]
    assert outgoing == incoming
    assert sympy.simplify(
        formulas.expression_at(point(6, 7))
        - formulas.expression_at(point(6, 2))
    ) == 0


@needs_ngspice
def test_the_and_gate_output_is_5_volts():
    workbook = build_example("and")
    parts = workbook.component_collection.get_components()
    names, _draw_at = spice_node_map(
        parts, workbook.wire_collection, workbook.connection_grid
    )
    operating_point = run_op(build_netlist(
        parts, workbook.wire_collection, workbook.connection_grid
    ))

    def volts(row, column):
        return operating_point.voltages[names[point(row, column)]]

    assert volts(5, 5) == pytest.approx(5.0)
    assert volts(7, 5) == pytest.approx(5.0)
    assert volts(6, 7) == pytest.approx(5.0)
    assert volts(7, 6) == pytest.approx(0.0)


def flag_lines(window, reference):
    flag = next(
        item for item in window.connection_grid_scene.probe_items
        if item.probe.reference == reference and item.role == "primary"
    )
    return flag.readout_lines


def test_examples_open_from_the_file_menu_and_can_be_edited(qt_application):
    window = MainWindow()

    try:
        labels = [
            action.text() for action in examples_menu(window).actions()
        ]
        assert labels == [
            "Voltage divider",
            "RC low-pass",
            "Unity-gain buffer",
            "AND gate",
        ]

        examples_menu(window).actions()[0].trigger()
        QApplication.processEvents()

        assert window.current_project_file_path is None
        assert window.is_project_modified is False
        assert flag_lines(window, "P1") == (
            ("Formula", "V(s) = 5 V"),
            ("Voltage", "5 V"),
            ("Frequency", "DC"),
        )
        assert {
            part.kind
            for part in window.component_collection.get_components()
        } == {"ground", "dc_source", "resistor"}

        window.handle_component_selection(
            window.component_collection.get_component("R2")
        )
        window.apply_component_value("30k")

        assert flag_lines(window, "P1") == (
            ("Formula", "V(s) = 7.5 V"),
            ("Voltage", "7.5 V"),
            ("Frequency", "DC"),
        )
        assert window.is_project_modified is True

        window.confirm_project_replacement = lambda: False
        window.open_example("buffer")

        assert window.component_collection.get_component("R2").value_text == (
            "30k"
        )
        assert ("Voltage", "7.5 V") in flag_lines(window, "P1")
    finally:
        close_window(window)


def test_a_bad_example_id_tells_the_user_what_is_allowed(qt_application):
    window = MainWindow()
    recorded = []
    window.show_error_message = (
        lambda title, reason, resolution: recorded.append((title, reason))
    )

    try:
        window.open_example("nope")
        assert recorded[0][0] == "Example Not Opened"
        assert "divider, rc, buffer, and" in recorded[0][1]
        assert window.component_collection.get_components() == []
    finally:
        close_window(window)
