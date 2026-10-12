"""
The all-features sheet. The numbers are the hand calculation.

A 10 V source and two 10 kilohm resistors meet at 5 V. The same
divider with a 1 Mohm probe to ground is 1000/201 V (4.975 V). A 10x
probe is 10000/2001 V at DC (4.9975 V). The bridged divider is 6 V
from 12 V. The 1 mA source into 1 kilohm is 1 V. The regulator is 5 V.
The transformer secondary is 2 times 12 V.

The low-pass is 1 kilohm and 159 nF. At 1 kHz its gain is -3.01 dB
at -45 degrees. The follower is 0 dB. Gain 2 is +6.02 dB. The
inverting block is the same size with a 180 degree phase.
"""

import math

import pytest
from PyQt5.QtWidgets import QApplication

from core.components import COMPONENT_DEFINITIONS
from core.netlist import append_shunt_loads, build_netlist, spice_node_map
from core.node_formula import build_node_formulas
from core.probes import PROBE_METHODS, shunt_loads
from core.project_io import load_project_file
from examples.all_features import EXAMPLE_PATH, build_all_features
from gui.main_window import MainWindow
from sim import runner
from sim.runner import (
    _spellings,
    ac_source_peak,
    lit_led_references,
    probe_bode,
    run_ac,
    run_op,
    run_tran,
    sample_at_frequency,
    transient_step,
)

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

# 10 * (10k || 1M) / (10k + 10k || 1M)
MEGOHM_VOLTS = 1000 / 201
# 10 * (10k || 10M) / (10k + 10k || 10M), the 10 pF open at DC
SCOPE_VOLTS = 10000 / 2001
# 6 V behind 5k || 5k, loaded by 10 megohm
POT_VOLTS = 6.0 * 10e6 / (10e6 + 2500.0)
# 12 V, top 5k, bottom 10k || 1 megohm
_TIMER_BOTTOM = 1.0 / (1.0 / 10e3 + 1.0 / 1e6)
TIMER_VOLTS = 12.0 * _TIMER_BOTTOM / (5e3 + _TIMER_BOTTOM)

_W_RC = 2.0 * math.pi * 1e3 * 1e3 * 159e-9
_GAIN = 1.0 / complex(1.0, _W_RC)
LOWPASS_DB = 20.0 * math.log10(abs(_GAIN))
LOWPASS_PHASE = math.degrees(math.atan2(_GAIN.imag, _GAIN.real))
GAIN_2_DB = 20.0 * math.log10(2.0)


def netlist_of(workbook):
    return build_netlist(
        workbook.component_collection.get_components(),
        workbook.wire_collection,
        workbook.connection_grid,
    )


def voltage_at(op, names, marks, key):
    return op.voltages[names[marks[key]]]


@pytest.fixture(scope="module")
def example():
    return build_all_features()


def test_the_sheet_uses_every_part_and_every_probe(example):
    workbook, _marks = example
    kinds = {
        component.kind
        for component in workbook.component_collection.get_components()
    }
    methods = {
        probe.method for probe in workbook.probe_collection.get_probes()
    }
    bridges = [
        wire for wire in workbook.wire_collection.get_wires()
        if wire.bridged_points
    ]

    assert kinds == set(COMPONENT_DEFINITIONS)
    assert methods == set(PROBE_METHODS)
    assert len(bridges) == 1
    assert workbook.connection_grid.get_signal_pickoff_identifiers()
    labels = set(workbook.connection_grid.get_net_labels().values())
    assert {"Vcc", "Vee", "Vss", "V10", "IN"} <= labels
    references = {
        component.reference
        for component in workbook.component_collection.get_components()
    }
    assert "BATT" in references
    assert "VBATT" in netlist_of(workbook)


def test_a_model_port_does_not_clash_with_the_rail_name():
    spellings = _spellings(
        "VBATT Vcc 0 DC 12\n"
        "X1 0 Vcc NOT\n"
        ".subckt NOT a vcc\n"
        "BY a 0 V = V(vcc)\n"
        ".ends\n"
        ".subckt NE555 VCC GND\n"
        "R1 VCC GND 5k\n"
        ".ends\n"
    )

    assert spellings["vcc"] == {"Vcc"}


def test_there_is_no_single_s_domain_formula(example):
    workbook, marks = example
    formulas = build_node_formulas(
        workbook.component_collection.get_components(),
        workbook.wire_collection,
        workbook.connection_grid,
    )

    assert "no s-domain formula" in formulas.text_at(marks["divider"])


def test_the_saved_file_is_the_builder(example):
    workbook, _marks = example
    saved = load_project_file(EXAMPLE_PATH)

    assert netlist_of(saved) == netlist_of(workbook)
    assert saved.connection_grid.row_count == workbook.connection_grid.row_count
    assert [
        probe.method for probe in saved.probe_collection.get_probes()
    ] == [
        probe.method for probe in workbook.probe_collection.get_probes()
    ]


def test_the_hand_calculation_numbers():
    assert MEGOHM_VOLTS == pytest.approx(4.975124, abs=1e-6)
    assert SCOPE_VOLTS == pytest.approx(4.997501, abs=1e-6)
    assert LOWPASS_DB == pytest.approx(-3.01, abs=0.02)
    assert LOWPASS_PHASE == pytest.approx(-45.0, abs=0.2)
    assert GAIN_2_DB == pytest.approx(6.02, abs=0.01)
    assert TIMER_VOLTS == pytest.approx(7.97, abs=0.01)


@needs_ngspice
def test_the_dc_numbers_match_the_hand_calculation(example):
    workbook, marks = example
    parts = workbook.component_collection.get_components()
    names, _draw_at = spice_node_map(
        parts, workbook.wire_collection, workbook.connection_grid
    )
    op = run_op(netlist_of(workbook))

    def volts(key):
        return voltage_at(op, names, marks, key)

    assert volts("divider") == pytest.approx(5.0, abs=1e-6)
    assert volts("bridge") == pytest.approx(6.0, abs=1e-4)
    assert volts("pot") == pytest.approx(POT_VOLTS, abs=1e-3)
    assert volts("secondary") == pytest.approx(24.0, abs=1e-3)
    assert volts("current") == pytest.approx(1.0, abs=1e-4)
    assert volts("closed") == pytest.approx(12.0, abs=1e-3)
    assert abs(volts("open")) < 1e-3
    assert volts("regulator") == pytest.approx(5.0, abs=1e-3)
    assert volts("timer_control") == pytest.approx(TIMER_VOLTS, abs=0.02)
    assert volts("comparator") == pytest.approx(12.0, abs=1e-3)
    assert volts("gate_not") == pytest.approx(12.0, abs=1e-3)
    assert volts("gate_nand") == pytest.approx(0.0, abs=1e-3)
    assert volts("opamp_generic") == pytest.approx(0.0, abs=1e-3)
    assert volts("opamp_741") == pytest.approx(0.0, abs=1e-3)
    assert op.currents[marks["divider_resistor"]] == pytest.approx(
        0.5e-3, abs=1e-6
    )
    assert op.currents[marks["led_resistor"]] > 1e-3

    loaded = append_shunt_loads(
        netlist_of(workbook),
        shunt_loads(workbook.probe_collection.get_probes()),
        names,
    )
    loaded_op = run_op(loaded)

    assert voltage_at(loaded_op, names, marks, "divider") == pytest.approx(
        5.0, abs=1e-4
    )
    assert voltage_at(loaded_op, names, marks, "megohm") == pytest.approx(
        MEGOHM_VOLTS, abs=1e-3
    )
    assert voltage_at(loaded_op, names, marks, "scope_10x") == pytest.approx(
        SCOPE_VOLTS, abs=1e-3
    )


@needs_ngspice
def test_the_bode_numbers_match_the_hand_calculation(example):
    workbook, marks = example
    parts = workbook.component_collection.get_components()
    names, _draw_at = spice_node_map(
        parts, workbook.wire_collection, workbook.connection_grid
    )
    text = append_shunt_loads(
        netlist_of(workbook),
        shunt_loads(workbook.probe_collection.get_probes()),
        names,
    )
    sweep = run_ac(text, 100, 10e3, 5)
    peak = ac_source_peak(parts)

    def at_1khz(key):
        probe = next(
            item for item in workbook.probe_collection.get_probes()
            if item.identifier == marks[key]
        )
        frequency, decibels, phase = probe_bode(probe, sweep, names, peak)
        return (
            sample_at_frequency(frequency, decibels, 1000),
            sample_at_frequency(frequency, phase, 1000),
        )

    assert at_1khz("input")[0] == pytest.approx(0.0, abs=0.01)
    lowpass_db, lowpass_phase = at_1khz("lowpass")
    assert lowpass_db == pytest.approx(LOWPASS_DB, abs=0.05)
    assert lowpass_phase == pytest.approx(LOWPASS_PHASE, abs=0.5)
    assert at_1khz("opamp_generic")[0] == pytest.approx(0.0, abs=0.05)
    assert at_1khz("follower")[0] == pytest.approx(0.0, abs=0.05)
    noninv_db, noninv_phase = at_1khz("noninverting_amp")
    assert noninv_db == pytest.approx(GAIN_2_DB, abs=0.05)
    assert noninv_phase == pytest.approx(0.0, abs=1.0)
    inv_db, inv_phase = at_1khz("inverting_amp")
    assert inv_db == pytest.approx(GAIN_2_DB, abs=0.05)
    assert inv_phase == pytest.approx(180.0, abs=1.0)


@needs_ngspice
def test_a_transient_lights_the_led(example):
    workbook, marks = example
    parts = workbook.component_collection.get_components()
    result = run_tran(
        netlist_of(workbook), transient_step(0.005), 0.005
    )

    assert marks["led"] in lit_led_references(parts, result)


def test_the_window_opens_the_example(qt_application):
    window = MainWindow()

    try:
        window.show_workbook(load_project_file(EXAMPLE_PATH))
        QApplication.processEvents()
        kinds = {
            component.kind
            for component in window.component_collection.get_components()
        }
        assert kinds == set(COMPONENT_DEFINITIONS)
        assert window.connection_grid.row_count == 48
        window.selected_connection_point_identifier = (
            window.connection_grid.get_signal_pickoff_identifiers()[0]
        )
        window.refresh_selected_node_formula()
        assert "no s-domain formula" in (
            window.selected_node_formula_label.text()
        )
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()
