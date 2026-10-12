"""
A closed plot is not calculated.

A 1 V, 1 kHz sine across 1k is a 1 V peak on the oscilloscope and a
1 V line at 1 kHz on the FFT. Setting the source to 2 V doubles both.
The 1k / 159n low-pass is about -3 dB at 1 kHz. At 10k it is about
-20 dB. Those sweeps run only while Bode is open.
"""

import math

import pytest
from PyQt5.QtWidgets import QApplication, QTabBar

from gui.main_window import MainWindow
from sim import runner
from sim.runner import probe_spectrum, sample_at_frequency
from tests.test_bode import build_lowpass, connect, place, point
from tests.test_refresh_on_edit import (
    TEN_K_DB,
    TEN_K_PHASE,
    close_window,
    select,
    wait_until_idle,
)

needs_ngspice = pytest.mark.skipif(
    not runner.ngspice_is_installed(),
    reason="ngspice is not installed",
)

_THREE_DB = 20.0 * math.log10(
    1.0 / abs(complex(1.0, 2.0 * math.pi * 1e3 * 1e3 * 159e-9))
)


def show_scope(window):
    window.show()
    QApplication.processEvents()


def select_plot_tab(window, title):
    window._watch_plot_tabs()
    chosen = None

    for bar in window.findChildren(QTabBar):
        if not bar.isVisible():
            continue

        for index in range(bar.count()):
            if bar.tabText(index) == title:
                chosen = (bar, index)

    assert chosen is not None
    bar, index = chosen

    if bar.currentIndex() != index:
        bar.setCurrentIndex(index)
    else:
        window._calculate_opened_plots()

    QApplication.processEvents()


def build_source(window):
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


def scope_peak(window):
    _name, _time, values = window.oscilloscope_dock.plotted_series()[0]
    return max(values)


def spectrum_at_1khz(window):
    _name, frequency, peaks = window.fft_dock.plotted_spectrum()[0]
    index = min(
        range(len(frequency)),
        key=lambda item: abs(frequency[item] - 1000.0),
    )
    return peaks[index]


def bode_at_1khz(window):
    _name, frequency, decibels = window.bode_dock.plotted_magnitude()[0]
    _phase_name, phase_frequency, phase = window.bode_dock.plotted_phase()[0]
    return (
        sample_at_frequency(frequency, decibels, 1000),
        sample_at_frequency(phase_frequency, phase, 1000),
    )


@needs_ngspice
def test_a_closed_fft_is_not_calculated_until_it_opens(qt_application, monkeypatch):
    calls = []
    real = probe_spectrum

    def counted(*arguments):
        calls.append(arguments[0].reference)
        return real(*arguments)

    monkeypatch.setattr("gui.main_window.probe_spectrum", counted)
    window = MainWindow()

    try:
        build_source(window)
        show_scope(window)
        assert window.plot_is_open(window.oscilloscope_dock)
        assert not window.plot_is_open(window.fft_dock)

        window.run_transient()
        wait_until_idle(window)
        assert scope_peak(window) == pytest.approx(1.0, rel=0.01)
        assert calls == []
        assert window.fft_dock.plotted_spectrum() == []

        select(window, "V1")
        window.apply_component_value("2")
        wait_until_idle(window)
        assert scope_peak(window) == pytest.approx(2.0, rel=0.01)
        assert calls == []

        select_plot_tab(window, "FFT")
        assert spectrum_at_1khz(window) == pytest.approx(2.0, rel=0.02)
        assert calls == ["P1"]
    finally:
        close_window(window)


@needs_ngspice
def test_opening_a_closed_scope_runs_the_new_value(qt_application):
    window = MainWindow()

    try:
        build_source(window)
        show_scope(window)
        window.run_transient()
        wait_until_idle(window)
        assert scope_peak(window) == pytest.approx(1.0, rel=0.01)

        window.oscilloscope_dock.hide()
        window.fft_dock.hide()
        QApplication.processEvents()
        select(window, "V1")
        window.apply_component_value("2")
        assert window._tran_thread is None
        assert window._tran_stale
        assert scope_peak(window) == pytest.approx(1.0, rel=0.01)

        window.oscilloscope_dock.show()
        select_plot_tab(window, "Oscilloscope")
        wait_until_idle(window)
        assert scope_peak(window) == pytest.approx(2.0, rel=0.01)
        assert window.fft_dock.plotted_spectrum() == []
    finally:
        close_window(window)


@needs_ngspice
def test_a_closed_bode_waits_until_it_opens(qt_application):
    window = MainWindow()
    sweeps = []
    real = window.run_frequency_sweep

    def counted():
        sweeps.append(1)
        return real()

    window.run_frequency_sweep = counted

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
        window.show()
        QApplication.processEvents()
        assert not window.plot_is_open(window.bode_dock)
        window.run_frequency_sweep()
        wait_until_idle(window)
        assert bode_at_1khz(window)[0] == pytest.approx(_THREE_DB, abs=0.05)
        assert len(sweeps) == 1

        select(window, "R1")
        window.apply_component_value("10k")
        assert len(sweeps) == 1
        assert window._ac_thread is None
        assert window._ac_stale
        assert bode_at_1khz(window)[0] == pytest.approx(_THREE_DB, abs=0.05)

        select_plot_tab(window, "Bode")
        wait_until_idle(window)
        decibels, phase = bode_at_1khz(window)
        assert decibels == pytest.approx(TEN_K_DB, abs=0.05)
        assert phase == pytest.approx(TEN_K_PHASE, abs=0.5)
        assert len(sweeps) == 2
    finally:
        close_window(window)
