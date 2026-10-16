"""
Cursors. The numbers are the hand calculation.

A 1 kHz sine is 0 at 0 s, 1 at 250 us, and 0 at 500 us. The cursor
reads those samples. Halfway between 0 and 250 us the straight line
is 0.5, which is the line the plot draws, not the sine itself.

On a log frequency axis the line from -1 dB at 100 Hz to -3 dB at
1 kHz is -2 dB at the geometric mean, 316.2 Hz.

The 1k / 159n low-pass is about -0.043 dB at 100 Hz and -3.01 dB at
1 kHz, so the difference between those two cursors is about -2.97 dB.
A 1 V, 1 kHz spectrum line is 1 V above the 0 Hz line.
"""

import math

import pytest
from PyQt5.QtWidgets import QApplication

from core.cursors import format_cursor_text, value_at, value_at_log_x
from core.exceptions import ComponentError
from gui.bode_widget import BodeDock
from gui.fft_widget import FftDock
from gui.scope_widget import OscilloscopeDock
from sim.runner import amplitude_spectrum
from tests.test_fft import sine_record

# 1 / (1 + j*2*pi*f*1e3*159e-9)
_R_C = 1e3 * 159e-9


def lowpass_db(hertz):
    gain = 1.0 / complex(1.0, 2.0 * math.pi * hertz * _R_C)
    return 20.0 * math.log10(abs(gain))


def test_the_straight_line_between_samples():
    times = (0.0, 250e-6, 500e-6)
    values = (0.0, 1.0, 0.0)

    assert value_at(times, values, 0.0) == 0.0
    assert value_at(times, values, 250e-6) == 1.0
    assert value_at(times, values, 125e-6) == 0.5
    assert value_at(times, values, -1.0) == 0.0
    assert value_at(times, values, 1.0) == 0.0

    text = format_cursor_text(
        "P1",
        0.0,
        250e-6,
        "s",
        ((value_at(times, values, 0.0), value_at(times, values, 250e-6), ""),),
    )
    assert text == (
        "A is 0 s, 0.\n"
        "B is 250u s, 1.\n"
        "Difference is 250u s, 1.\n"
        "Trace P1."
    )


def test_a_log_axis_follows_the_geometric_mean():
    frequency = (100.0, 1000.0)
    decibels = (-1.0, -3.0)
    middle = 10.0 ** 2.5

    assert value_at_log_x(frequency, decibels, middle) == pytest.approx(-2.0)
    assert value_at_log_x(frequency, decibels, 100.0) == -1.0
    assert value_at_log_x(frequency, decibels, 1000.0) == -3.0


def test_the_lowpass_difference_is_the_hand_calculation():
    at_100 = lowpass_db(100.0)
    at_1k = lowpass_db(1000.0)
    frequency = (100.0, 1000.0)
    decibels = (at_100, at_1k)

    assert at_100 == pytest.approx(-0.043, abs=0.001)
    assert at_1k == pytest.approx(-3.01, abs=0.01)
    assert value_at_log_x(frequency, decibels, 1000.0) - value_at_log_x(
        frequency, decibels, 100.0
    ) == pytest.approx(at_1k - at_100)


def test_the_spectrum_line_is_1_v_above_dc():
    times, values = sine_record(1.0, 1000.0)
    frequency, peaks = amplitude_spectrum(times, values)
    tone = min(range(len(frequency)), key=lambda item: abs(frequency[item] - 1000.0))

    assert frequency[0] == 0.0
    assert frequency[tone] == pytest.approx(1000.0)
    assert value_at(frequency, peaks, 0.0) == pytest.approx(0.0, abs=1e-9)
    assert value_at(frequency, peaks, frequency[tone]) == pytest.approx(1.0, abs=1e-9)
    assert value_at(frequency, peaks, frequency[tone]) - value_at(
        frequency, peaks, 0.0
    ) == pytest.approx(1.0, abs=1e-9)


def test_a_bad_trace_says_what_is_allowed():
    with pytest.raises(ComponentError, match="no trace"):
        value_at((), (), 0.0)

    with pytest.raises(ComponentError, match="positions and values"):
        value_at((0.0, 1.0), (0.0,), 0.0)

    with pytest.raises(ComponentError, match="finite"):
        value_at((0.0, 1.0), (0.0, float("nan")), 0.5)

    with pytest.raises(ComponentError, match="above 0"):
        value_at_log_x((100.0,), (-1.0,), 0.0)


def test_the_scope_reads_a_quarter_cycle(qt_application):
    dock = OscilloscopeDock()
    dock.show_traces(
        [("P1", "#3ec6ff", (0.0, 250e-6, 500e-6), (0.0, 1.0, 0.0))],
        100e-6,
        None,
    )

    try:
        assert [item[0] for item in dock.plotted_series()] == ["P1"]
        dock.set_cursors(0.0, 250e-6)
        assert dock.cursors.label.text() == (
            "A is 0 s, 0.\n"
            "B is 250u s, 1.\n"
            "Difference is 250u s, 1.\n"
            "Trace P1."
        )
        dock.cursors.lines.b[0].setValue(500e-6)
        assert "B is 500u s, 0." in dock.cursors.label.text()
        assert "Difference is 500u s, 0." in dock.cursors.label.text()
        dock.show_traces(
            [("P1", "#3ec6ff", (0.0, 250e-6, 500e-6), (0.0, 1.0, 0.0))],
            100e-6,
            None,
        )
        assert "B is 500u s, 0." in dock.cursors.label.text()
        dock.clear_traces()
        assert dock.cursors.label.text() == "Cursors appear when a trace is drawn."
        dock.show_traces(
            [("P1", "#3ec6ff", (0.0, 250e-6, 500e-6), (0.0, 1.0, 0.0))],
            100e-6,
            None,
        )
        assert dock.cursors.label.text().startswith("A is 250u s, 1.")
    finally:
        dock.close()
        dock.deleteLater()


def test_a_long_trace_keeps_the_spike_and_the_full_cursor(
    qt_application, monkeypatch
):
    monkeypatch.setattr("sim.runner.DISPLAY_SAMPLES", 4)
    dock = OscilloscopeDock()
    times = (0.0, 1.0, 2.0, 3.0, 4.0, 5.0)
    values = (0.0, 10.0, 0.0, 0.0, -5.0, 0.0)
    dock.show_traces([("P1", "#3ec6ff", times, values)], 1.0, None)

    try:
        _name, _time, plotted = dock.plotted_series()[0]
        assert 10.0 in plotted
        assert -5.0 in plotted
        assert len(plotted) <= 4
        assert dock.cursors.series["P1"][1] == values
        dock.set_cursors(1.0, 4.0)
        assert "A is 1 s, 10." in dock.cursors.label.text()
        assert "B is 4 s, -5." in dock.cursors.label.text()
    finally:
        dock.close()
        dock.deleteLater()


def test_the_scope_can_read_a_second_trace(qt_application):
    dock = OscilloscopeDock()
    dock.show_traces(
        [
            ("P1", "#3ec6ff", (0.0, 1.0), (0.0, 10.0)),
            ("P2", "#ffb000", (0.0, 1.0), (0.0, 4.0)),
        ],
        0.1,
        None,
    )

    try:
        dock.show()
        QApplication.processEvents()
        assert dock.cursors.combo.isVisible()
        assert dock.cursors.combo.currentText() == "P1"
        dock.cursors.combo.setCurrentText("P2")
        assert "Trace P2." in dock.cursors.label.text()
        assert "Difference is 500m s, 2." in dock.cursors.label.text()
    finally:
        dock.close()
        dock.deleteLater()


def test_bode_cursors_share_both_axes(qt_application):
    dock = BodeDock()
    dock.show_traces([
        ("P1", "#3ec6ff", (100.0, 1000.0), (-1.0, -3.0), (0.0, -45.0)),
    ])

    try:
        dock.set_cursors(100.0, 1000.0)
        assert dock.cursors.label.text() == (
            "A is 100 Hz, -1 dB, 0 deg.\n"
            "B is 1k Hz, -3 dB, -45 deg.\n"
            "Difference is 900 Hz, -2 dB, -45 deg.\n"
            "Trace P1."
        )
        dock.cursors.lines.a[0].setValue(math.log10(1000.0))
        assert dock.cursors.lines.a[1].value() == pytest.approx(math.log10(1000.0))
        assert "Difference is 0 Hz, 0 dB, 0 deg." in dock.cursors.label.text()
    finally:
        dock.close()
        dock.deleteLater()


def test_a_bode_cursor_at_zero_hertz_is_refused(qt_application):
    dock = BodeDock()
    dock.show_traces([
        ("P1", "#3ec6ff", (100.0, 1000.0), (-1.0, -3.0), (0.0, -45.0)),
    ])

    try:
        with pytest.raises(ComponentError, match="above 0"):
            dock.set_cursors(0.0, 1000.0)
    finally:
        dock.close()
        dock.deleteLater()


def test_the_fft_reads_the_1_v_line(qt_application):
    dock = FftDock()
    dock.show_traces([
        ("P1", "#3ec6ff", (0.0, 1000.0), (0.0, 1.0)),
    ])

    try:
        dock.set_cursors(0.0, 1000.0)
        assert dock.cursors.label.text() == (
            "A is 0 Hz, 0.\n"
            "B is 1k Hz, 1.\n"
            "Difference is 1k Hz, 1.\n"
            "Trace P1."
        )
        assert [item[0] for item in dock.plotted_spectrum()] == ["P1"]
    finally:
        dock.close()
        dock.deleteLater()
