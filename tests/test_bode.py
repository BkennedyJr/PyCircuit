"""
Frequency sweep. The numbers are the hand calculation.

A 1 kilohm resistor and a 159 nF capacitor is a low-pass.
At 1 kHz, 2*pi*f*R*C is 0.999, so the gain is

    1 / (1 + j*0.999) = 0.707 at -45 degrees

which is -3.01 dB. The same gain comes back when the AC source is
2 V, because magnitude is relative to that source.
"""

import math
import time

import pytest
from PyQt5.QtWidgets import QApplication

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import ComponentError, SimulationError
from core.netlist import build_netlist, spice_node_map
from core.probes import ProbeCollection
from core.wires import WireCollection
from gui.bode_widget import BodeDock
from gui.main_window import MainWindow
from sim import runner
from sim.runner import (
    ac_source_peak,
    probe_bode,
    run_ac,
    sample_at_frequency,
)

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

# 1 / (1 + j*2*pi*1e3*1e3*159e-9)
_W_RC = 2.0 * math.pi * 1e3 * 1e3 * 159e-9
_GAIN = 1.0 / complex(1.0, _W_RC)
LOWPASS_DB = 20.0 * math.log10(abs(_GAIN))
LOWPASS_PHASE = math.degrees(math.atan2(_GAIN.imag, _GAIN.real))


def point(row, column):
    return ConnectionGrid.build_connection_point_identifier(row, column)


def place(parts, grid, kind, row, column, value="", parameter_texts=None):
    return parts.add_component(
        kind, row, column, value, grid, parameter_texts=parameter_texts
    )


def connect(wires, grid, start, end):
    wires.add_wire(point(*start), point(*end), grid)


def build_lowpass(grid, parts, wires, peak="1"):
    place(parts, grid, "ground", 6, 2)
    place(
        parts, grid, "ac_source", 4, 2, peak,
        parameter_texts={"frequency": "1k"},
    )
    place(parts, grid, "resistor", 4, 3, "1k")
    place(parts, grid, "capacitor", 4, 4, "159n")
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


def response_at_1khz(peak):
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    wires = WireCollection()
    build_lowpass(grid, parts, wires, peak)
    netlist = build_netlist(parts, wires, grid)
    sweep = run_ac(netlist, 100, 10e3, 5)
    probes = ProbeCollection()
    probe = probes.add_voltage(point(4, 4), grid)
    name_by_point, _draw_at = spice_node_map(parts, wires, grid)
    frequency, decibels, phase = probe_bode(
        probe, sweep, name_by_point, ac_source_peak(parts.get_components())
    )
    return (
        sample_at_frequency(frequency, decibels, 1000),
        sample_at_frequency(frequency, phase, 1000),
    )


def test_the_hand_calculation_is_minus_3_db_and_minus_45_degrees():
    assert LOWPASS_DB == pytest.approx(-3.01, abs=0.02)
    assert LOWPASS_PHASE == pytest.approx(-45.0, abs=0.2)


def test_a_missing_ac_source_is_refused():
    with pytest.raises(SimulationError, match="Add an AC source"):
        ac_source_peak([])


def test_two_ac_sources_are_refused():
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    place(parts, grid, "ac_source", 2, 2, "1", {"frequency": "1k"})
    place(parts, grid, "ac_source", 2, 4, "1", {"frequency": "2k"})

    with pytest.raises(SimulationError, match="one AC source"):
        ac_source_peak(parts.get_components())


def test_bad_sweep_settings_name_what_is_allowed():
    netlist = "* text\nR1 1 0 1k\n.end\n"

    with pytest.raises(SimulationError, match="stop must be higher"):
        run_ac(netlist, 10, 10, 20)

    with pytest.raises(SimulationError, match="Points per decade"):
        run_ac(netlist, 10, 1000, 0)


@needs_ngspice
@pytest.mark.parametrize("peak", ["1", "2"])
def test_the_low_pass_is_minus_3_db_at_1_khz(peak):
    decibels, phase = response_at_1khz(peak)

    assert decibels == pytest.approx(LOWPASS_DB, abs=0.15)
    assert phase == pytest.approx(LOWPASS_PHASE, abs=1.0)


def test_bode_settings_reject_bad_text(qt_application):
    dock = BodeDock()

    dock.start_edit.setText("0")

    with pytest.raises(ComponentError, match="Start frequency"):
        dock.start_hertz()

    dock.start_edit.setText("10")
    dock.stop_edit.setText("10")

    with pytest.raises(ComponentError, match="higher than the start"):
        dock.stop_hertz()

    dock.points_edit.setText("20.5")

    with pytest.raises(ComponentError, match="whole number"):
        dock.points_per_decade()

    dock.close()
    dock.deleteLater()


def test_start_with_no_ac_source_names_the_problem(qt_application):
    window = MainWindow()
    recorded = []
    window.show_error_message = (
        lambda title, reason, resolution: recorded.append((title, reason))
    )

    try:
        window.run_frequency_sweep()
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()

    assert recorded == [(
        "Bode",
        "Add an AC source before running a frequency sweep.",
    )]


def test_the_bode_dock_is_a_tab_on_the_oscilloscope(qt_application):
    window = MainWindow()

    try:
        assert window.bode_dock.windowTitle() == "Bode"
        assert window.bode_dock in window.tabifiedDockWidgets(
            window.oscilloscope_dock
        )
        view_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&View"
        )
        assert "Bode" in [action.text() for action in view_menu.actions()]
        window.bode_dock.setFloating(True)
        QApplication.processEvents()
        assert window.bode_dock.isFloating()
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()


@needs_ngspice
def test_the_dock_draws_the_low_pass(qt_application):
    window = MainWindow()

    try:
        build_lowpass(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        window.probe_collection.add_voltage(
            point(4, 4), window.connection_grid
        )
        window.refresh_bode_channels()
        window.bode_dock.start_edit.setText("100")
        window.bode_dock.stop_edit.setText("10k")
        window.bode_dock.points_edit.setText("5")
        window.run_frequency_sweep()
        deadline = time.time() + 30

        while window._ac_thread is not None and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert window._ac_thread is None
        curves = {
            name: (frequency, decibels)
            for name, frequency, decibels in (
                window.bode_dock.plotted_magnitude()
            )
        }
        assert "P1" in curves
        frequency, decibels = curves["P1"]
        assert sample_at_frequency(frequency, decibels, 1000) == (
            pytest.approx(LOWPASS_DB, abs=0.15)
        )
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()
