"""
A new value runs the analyses that are already on screen.

Hand calculation for the divider: 10 V across 10k + 10k is 5 V and
0.5 mA. The bottom resistor at 30k is 10 * 30/40 = 7.5 V and
10/40k = 0.25 mA. The source at 8 V with that 30k is 6 V and 0.2 mA.

A 10k pot at position 0.5 is 5 V on the wiper. Position 0.25 is
10 * 0.25 = 2.5 V. A 1 Tohm resistor from the wiper to ground gives
that pin its second connection and does not move those readings.
A closed switch into 1k from 10 V is 10 V and 10 mA. Open, the
switch is 1 Gohm, so the load is about 0 V.

A 1 V sine across 1k becomes a 2 V sine when the source is set to 2.
The 1k /
159n low-pass at 1 kHz is about -3 dB. With 10k it is about -20 dB.
"""

import math
import time

import pytest
from PyQt5.QtWidgets import QApplication

from gui.main_window import MainWindow
from sim import runner
from sim.runner import OperatingPoint, sample_at_frequency
from tests.test_bode import build_lowpass, connect, place, point

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

_TEN_K_RC = 2.0 * math.pi * 1e3 * 10e3 * 159e-9
_TEN_K_GAIN = 1.0 / complex(1.0, _TEN_K_RC)
TEN_K_DB = 20.0 * math.log10(abs(_TEN_K_GAIN))
TEN_K_PHASE = math.degrees(math.atan2(_TEN_K_GAIN.imag, _TEN_K_GAIN.real))


def close_window(window):
    window.is_project_modified = False
    window.close()
    window.deleteLater()


def show_on_scene(window):
    scene = window.connection_grid_scene
    scene.rebuild_component_items()
    scene.rebuild_wire_items()


def select(window, reference):
    window.handle_component_selection(
        window.component_collection.get_component(reference)
    )


def volts_at(window, identifier):
    name = window._dc_name_by_point[identifier]
    return window._dc_volts_by_node[name]


def current_text(window, reference):
    item = window.connection_grid_scene.component_items_by_reference[reference]
    return item.dc_current_item.text()


def wait_until_idle(window):
    deadline = time.time() + 30

    while time.time() < deadline:
        QApplication.processEvents()

        if (window._dc_thread is None and window._tran_thread is None
                and window._ac_thread is None):
            return

        time.sleep(0.01)

    assert window._dc_thread is None
    assert window._tran_thread is None
    assert window._ac_thread is None


def build_divider(grid, parts, wires):
    place(parts, grid, "ground", 6, 2)
    place(parts, grid, "dc_source", 4, 2, "10")
    place(parts, grid, "resistor", 4, 3, "10k")
    place(parts, grid, "resistor", 4, 4, "10k")
    connect(wires, grid, (5, 2), (6, 2))
    connect(wires, grid, (4, 2), (4, 3))
    connect(wires, grid, (4, 5), (6, 5))
    connect(wires, grid, (6, 2), (6, 5))


def test_a_value_change_does_not_start_a_run_by_itself(qt_application):
    window = MainWindow()

    try:
        window.component_collection.add_component(
            "resistor", 4, 2, "1k", window.connection_grid
        )
        select(window, "R1")
        window.apply_component_value("2k")
        assert window._dc_thread is None
        assert window._tran_thread is None
        assert window._ac_thread is None
        assert window._dc_volts_by_node == {}
    finally:
        close_window(window)


def test_a_bad_value_leaves_the_numbers_alone(qt_application):
    window = MainWindow()
    recorded = []
    window.show_error_message = (
        lambda title, reason, resolution: recorded.append(title)
    )

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.show_dc_operating_point(OperatingPoint(
            {"N001": 10.0, "N002": 5.0, "0": 0.0},
            {"R1": 0.0005, "R2": 0.0005, "V1": -0.0005},
        ))
        select(window, "R2")
        window.apply_component_value("nope")
        assert recorded == ["Part Value Not Changed"]
        assert volts_at(window, point(4, 4)) == 5.0
        assert window._dc_thread is None
    finally:
        close_window(window)


def test_the_divider_updates_when_the_resistor_and_source_change(
        qt_application):
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(5.0)
        assert current_text(window, "R1") == "500 uA"

        select(window, "R2")
        window.apply_component_value("30k")
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(7.5)
        assert current_text(window, "R1") == "250 uA"

        select(window, "V1")
        window.apply_component_value("8")
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(6.0)
        assert current_text(window, "R1") == "200 uA"
    finally:
        close_window(window)


def test_a_second_edit_replaces_the_run_still_going(qt_application, monkeypatch):
    real_run = runner.run_operating_point

    def paced(components, wire_collection, connection_grid=None):
        for part in components.get_components():
            if part.reference == "R2" and part.value == 30000:
                time.sleep(0.3)

        return real_run(components, wire_collection, connection_grid)

    monkeypatch.setattr(runner, "run_operating_point", paced)
    window = MainWindow()

    try:
        build_divider(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        show_on_scene(window)
        window.run_dc_operating_point()
        wait_until_idle(window)
        select(window, "R2")
        window.apply_component_value("30k")
        window.apply_component_value("10k")
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(5.0)
    finally:
        close_window(window)


@needs_ngspice
def test_the_pot_and_the_switch_update(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        parts = window.component_collection
        wires = window.wire_collection
        place(parts, grid, "ground", 8, 2)
        place(parts, grid, "dc_source", 4, 2, "10")
        place(parts, grid, "potentiometer", 4, 3, "10k")
        place(parts, grid, "resistor", 5, 4, "1t")
        connect(wires, grid, (5, 2), (8, 2))
        connect(wires, grid, (4, 2), (4, 3))
        connect(wires, grid, (4, 5), (8, 5))
        connect(wires, grid, (8, 2), (8, 5))
        connect(wires, grid, (5, 5), (8, 5))
        show_on_scene(window)
        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(5, 4)) == pytest.approx(5.0)

        select(window, "RV1")
        window.apply_component_value("10k", {"position": "0.25"})
        wait_until_idle(window)
        assert volts_at(window, point(5, 4)) == pytest.approx(2.5)
    finally:
        close_window(window)

    window = MainWindow()

    try:
        grid = window.connection_grid
        parts = window.component_collection
        wires = window.wire_collection
        place(parts, grid, "ground", 6, 2)
        place(parts, grid, "dc_source", 4, 2, "10")
        place(
            parts, grid, "switch", 4, 3, "",
            parameter_texts={"state": "closed"},
        )
        place(parts, grid, "resistor", 4, 4, "1k")
        connect(wires, grid, (5, 2), (6, 2))
        connect(wires, grid, (4, 2), (4, 3))
        connect(wires, grid, (4, 5), (6, 5))
        connect(wires, grid, (6, 2), (6, 5))
        show_on_scene(window)
        window.run_dc_operating_point()
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(10.0, abs=1e-4)
        assert current_text(window, "R1") == "10 mA"

        select(window, "S1")
        window.apply_component_value("", {"state": "open"})
        wait_until_idle(window)
        assert volts_at(window, point(4, 4)) == pytest.approx(0.0, abs=1e-4)
    finally:
        close_window(window)


@needs_ngspice
def test_the_scope_and_the_spectrum_follow_the_source(qt_application):
    window = MainWindow()

    try:
        grid = window.connection_grid
        parts = window.component_collection
        wires = window.wire_collection
        place(parts, grid, "ground", 6, 2)
        place(
            parts, grid, "ac_source", 4, 2, "1",
            parameter_texts={"frequency": "1k"},
        )
        place(parts, grid, "resistor", 4, 2, "1k")
        connect(wires, grid, (5, 2), (6, 2))
        connect(wires, grid, (4, 3), (6, 3))
        connect(wires, grid, (6, 2), (6, 3))
        window.probe_collection.add_voltage(point(4, 2), grid)
        window.refresh_scope_channels()
        window.refresh_fft_channels()
        window.show()
        window.fft_dock.setFloating(True)
        window.fft_dock.show()
        QApplication.processEvents()
        window.run_transient()
        wait_until_idle(window)
        assert _peak(window) == pytest.approx(1.0, rel=0.01)
        assert _spectrum_at_1khz(window) == pytest.approx(1.0, rel=0.02)

        select(window, "V1")
        window.apply_component_value("2")
        wait_until_idle(window)
        assert _peak(window) == pytest.approx(2.0, rel=0.01)
        assert _spectrum_at_1khz(window) == pytest.approx(2.0, rel=0.02)
    finally:
        close_window(window)


@needs_ngspice
def test_bode_follows_the_resistor(qt_application):
    window = MainWindow()

    try:
        build_lowpass(
            window.connection_grid,
            window.component_collection,
            window.wire_collection,
        )
        window.probe_collection.add_voltage(point(4, 4), window.connection_grid)
        window.refresh_bode_channels()
        window.show()
        window.bode_dock.setFloating(True)
        window.bode_dock.show()
        QApplication.processEvents()
        window.bode_dock.start_edit.setText("100")
        window.bode_dock.stop_edit.setText("10k")
        window.bode_dock.points_edit.setText("5")
        window.run_frequency_sweep()
        wait_until_idle(window)
        assert _bode_at_1khz(window)[0] == pytest.approx(-3.01, abs=0.05)

        select(window, "R1")
        window.apply_component_value("10k")
        wait_until_idle(window)
        decibels, phase = _bode_at_1khz(window)
        assert decibels == pytest.approx(TEN_K_DB, abs=0.05)
        assert phase == pytest.approx(TEN_K_PHASE, abs=0.5)
        assert TEN_K_DB == pytest.approx(-20.0, abs=0.05)
    finally:
        close_window(window)


def _peak(window):
    _name, _time, values = window.oscilloscope_dock.plotted_series()[0]
    return max(values)


def _spectrum_at_1khz(window):
    _name, frequency, peaks = window.fft_dock.plotted_spectrum()[0]
    index = min(
        range(len(frequency)),
        key=lambda item: abs(frequency[item] - 1000.0),
    )
    return peaks[index]


def _bode_at_1khz(window):
    _name, frequency, decibels = window.bode_dock.plotted_magnitude()[0]
    _phase_name, phase_frequency, phase = (
        window.bode_dock.plotted_phase()[0]
    )
    return (
        sample_at_frequency(frequency, decibels, 1000),
        sample_at_frequency(phase_frequency, phase, 1000),
    )
