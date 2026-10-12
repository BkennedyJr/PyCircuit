"""
Spectrum of a transient. The numbers are the hand calculation.

200 samples across 5 ms, not counting the sample at the end, is a
1 kHz sine of exactly 5 cycles. That line is 1 V at 1000 Hz. An offset
of 0.25 V is the line at 0 Hz. A second sine of 0.5 V at 2 kHz is a
0.5 V line.

The same 1 kHz sine through a 1 kilohm resistor and a 159 nF capacitor
is 1 / sqrt(1 + (2*pi*1000*1000*159e-9)**2), about 0.707 V, at that
line. A 2 V source is twice that. The spectrum is the peak itself,
not a gain.
"""

import math
import time

import pytest
from PyQt5.QtWidgets import QApplication

from core.components import ComponentCollection
from core.connection_grid import ConnectionGrid
from core.exceptions import SimulationError
from core.netlist import build_netlist, spice_node_map
from core.probes import ProbeCollection
from core.wires import WireCollection
from gui.main_window import MainWindow
from sim import runner
from sim.runner import (
    Transient,
    amplitude_spectrum,
    probe_spectrum,
    run_tran,
    transient_step,
)
from tests.test_bode import build_lowpass, point

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

# 1 / sqrt(1 + (2*pi*1e3*1e3*159e-9)**2)
_W_RC = 2.0 * math.pi * 1e3 * 1e3 * 159e-9
LOWPASS_PEAK = 1.0 / math.sqrt(1.0 + _W_RC * _W_RC)
_XC = 1.0 / (2.0 * math.pi * 1e3 * 159e-9)
LOWPASS_CURRENT = 1.0 / math.hypot(1000.0, _XC)

_CYCLES = 5
_SAMPLES = 200
_DURATION = _CYCLES / 1000.0


def sine_record(amplitude, frequency, offset=0.0):
    times = tuple(
        index * _DURATION / _SAMPLES for index in range(_SAMPLES + 1)
    )
    values = tuple(
        offset + amplitude * math.sin(2.0 * math.pi * frequency * instant)
        for instant in times
    )
    return times, values


def line_at(frequency, peaks, target):
    index = min(
        range(len(frequency)),
        key=lambda item: abs(frequency[item] - target),
    )
    return frequency[index], peaks[index]


def test_the_hand_calculation_is_a_1_v_line_at_1_khz():
    times, values = sine_record(1.0, 1000.0)
    frequency, peaks = amplitude_spectrum(times, values)
    hertz, peak = line_at(frequency, peaks, 1000.0)

    assert hertz == pytest.approx(1000.0)
    assert peak == pytest.approx(1.0, abs=1e-9)
    assert peaks[0] == pytest.approx(0.0, abs=1e-9)


def test_an_offset_is_the_line_at_zero_hertz():
    times, values = sine_record(1.0, 1000.0, offset=0.25)
    frequency, peaks = amplitude_spectrum(times, values)

    assert peaks[0] == pytest.approx(0.25, abs=1e-9)
    assert line_at(frequency, peaks, 1000.0)[1] == pytest.approx(1.0, abs=1e-9)


def test_two_sines_are_two_lines():
    times = tuple(
        index * _DURATION / _SAMPLES for index in range(_SAMPLES + 1)
    )
    values = tuple(
        math.sin(2.0 * math.pi * 1000.0 * instant)
        + 0.5 * math.sin(2.0 * math.pi * 2000.0 * instant)
        for instant in times
    )
    frequency, peaks = amplitude_spectrum(times, values)

    assert line_at(frequency, peaks, 1000.0)[1] == pytest.approx(1.0, abs=1e-9)
    assert line_at(frequency, peaks, 2000.0)[1] == pytest.approx(0.5, abs=1e-9)


def test_a_2_v_sine_is_a_2_v_line():
    times, values = sine_record(2.0, 1000.0)
    frequency, peaks = amplitude_spectrum(times, values)

    assert line_at(frequency, peaks, 1000.0)[1] == pytest.approx(2.0, abs=1e-9)


def test_a_long_record_stays_a_1_v_line_without_a_long_wait():
    # 4 samples per cycle for 5000 cycles is 5 seconds. The line is
    # still 1 V at 1 kHz. The old sample-by-sample walk took seconds.
    cycles = 5000
    samples = cycles * 4
    duration = cycles / 1000.0
    times = tuple(
        index * duration / samples for index in range(samples + 1)
    )
    values = tuple(
        math.sin(2.0 * math.pi * 1000.0 * instant) for instant in times
    )
    started = time.perf_counter()
    frequency, peaks = amplitude_spectrum(times, values)
    elapsed = time.perf_counter() - started

    assert line_at(frequency, peaks, 1000.0)[1] == pytest.approx(1.0, abs=1e-6)
    assert elapsed < 1.0


def test_uneven_samples_keep_the_same_line():
    times, values = sine_record(1.0, 1000.0)
    times = list(times)
    values = list(values)
    times[10] += _DURATION / _SAMPLES * 0.25
    values[10] = math.sin(2.0 * math.pi * 1000.0 * times[10])
    frequency, peaks = amplitude_spectrum(times, values)

    assert line_at(frequency, peaks, 1000.0)[1] == pytest.approx(1.0, abs=0.01)


def test_bad_samples_name_what_is_allowed():
    with pytest.raises(SimulationError, match="at least 4"):
        amplitude_spectrum((0.0, 0.1, 0.2), (0.0, 0.0, 0.0))

    with pytest.raises(SimulationError, match="not usable"):
        amplitude_spectrum((0.0, 0.1, 0.2, 0.3), (0.0, 0.0, 0.0))

    with pytest.raises(SimulationError, match="move forward"):
        amplitude_spectrum((0.0, 0.2, 0.1, 0.3), (0.0, 0.0, 0.0, 0.0))

    with pytest.raises(SimulationError, match="not usable"):
        amplitude_spectrum((0.0, 0.1, 0.2, float("nan")), (0, 0, 0, 0))


def test_a_probe_with_no_sample_has_no_spectrum():
    grid = ConnectionGrid(8, 8)
    probe = ProbeCollection().add_voltage(point(1, 1), grid)
    transient = Transient((0.0, 0.1, 0.2, 0.3), {"0": (0, 0, 0, 0)}, {})

    assert probe_spectrum(probe, transient, {}) is None


def test_the_low_pass_hand_calculation_is_0_707_v():
    assert LOWPASS_PEAK == pytest.approx(0.707, abs=0.001)
    assert LOWPASS_CURRENT == pytest.approx(7.07e-4, abs=1e-5)


def test_the_fft_dock_is_a_tab_and_follows_the_scope(qt_application):
    window = MainWindow()

    try:
        assert window.fft_dock.windowTitle() == "FFT"
        assert window.fft_dock in window.tabifiedDockWidgets(
            window.oscilloscope_dock
        )
        view_menu = next(
            action.menu()
            for action in window.menuBar().actions()
            if action.text() == "&View"
        )
        assert "FFT" in [action.text() for action in view_menu.actions()]
        window.show()
        QApplication.processEvents()
        assert window.oscilloscope_dock.isVisible()
        window.fft_dock.setFloating(True)
        QApplication.processEvents()
        assert window.fft_dock.isFloating()
        window.fft_dock.show_traces([
            ("P1", "#4fc3f7", (0.0, 1000.0), (0.0, 1.0)),
        ])
        assert window.fft_dock.plotted_spectrum()[0][0] == "P1"
        window.clear_scope_run()
        assert window.fft_dock.plotted_spectrum() == []
        assert "oscilloscope" in window.fft_dock.note_label.text()
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()


@needs_ngspice
@pytest.mark.parametrize("peak", ["1", "2"])
def test_the_low_pass_spectrum_matches_the_hand_calculation(peak):
    grid = ConnectionGrid(8, 8)
    parts = ComponentCollection()
    wires = WireCollection()
    build_lowpass(grid, parts, wires, peak)
    components = parts.get_components()
    stop = 5.0 / 1000.0
    result = run_tran(
        build_netlist(components, wires, grid),
        transient_step(stop),
        stop,
    )
    name_by_point, _draw_at = spice_node_map(components, wires, grid)
    probes = ProbeCollection()
    source = probes.add_voltage(point(4, 2), grid)
    output = probes.add_voltage(point(4, 4), grid)
    current = probes.add_current(parts.get_component("R1"))
    scale = float(peak)
    source_line = line_at(
        *probe_spectrum(source, result, name_by_point), 1000.0
    )
    output_line = line_at(
        *probe_spectrum(output, result, name_by_point), 1000.0
    )
    current_line = line_at(
        *probe_spectrum(current, result, name_by_point), 1000.0
    )

    assert source_line[0] == pytest.approx(1000.0)
    assert source_line[1] == pytest.approx(scale, abs=0.01)
    assert output_line[1] == pytest.approx(scale * LOWPASS_PEAK, abs=0.01)
    # The capacitor starts at 0 V, so the first moments add a little
    # current that is not the steady sine. Five cycles still lands
    # near that sine.
    assert current_line[1] == pytest.approx(
        scale * LOWPASS_CURRENT, rel=0.05
    )


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
        window.refresh_scope_channels()
        window.refresh_fft_channels()
        window.show()
        window.fft_dock.setFloating(True)
        window.fft_dock.show()
        QApplication.processEvents()
        window.run_transient()
        deadline = time.time() + 30

        while window._tran_thread is not None and time.time() < deadline:
            QApplication.processEvents()
            time.sleep(0.01)

        assert window._tran_thread is None
        assert window.oscilloscope_dock.plotted_series()
        plotted = window.fft_dock.plotted_spectrum()
        assert len(plotted) == 1
        assert plotted[0][0] == "P1"
        hertz, height = line_at(plotted[0][1], plotted[0][2], 1000.0)
        assert hertz == pytest.approx(1000.0, rel=0.02)
        assert height == pytest.approx(LOWPASS_PEAK, abs=0.02)
    finally:
        window.is_project_modified = False
        window.close()
        window.deleteLater()
