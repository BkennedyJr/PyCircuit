"""
FFT dock. The curves are the spectrum of the last oscilloscope run.

The height is the peak of that waveform. A whole number of cycles is
one line.
"""

import math

import pyqtgraph as pg
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.cursors import format_cursor_text, value_at
from gui.plot_cursors import CursorBox
from gui.plot_zoom import show_zoom_tip
from gui.update_mode import update_mode_combo


class FftPlot(pg.PlotWidget):
    """
    Spectrum beside the probe list.

    PlotWidget asks for 600 by 450. A shorter hint leaves the circuit
    on screen. The dock can still be dragged taller.
    """

    def sizeHint(self):
        return QSize(360, 180)

    def minimumSizeHint(self):
        return QSize(200, 90)


class FftDock(QDockWidget):
    """
    Dock that shows the spectrum of the last transient.

    :param parent: Owning window.
    """

    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("FFT", parent)
        self.setObjectName("fft")
        self._checks = []
        self._build()

    def _build(self):
        body = QWidget()
        row = QHBoxLayout()

        self.channel_layout = QVBoxLayout()
        self.note_label = QLabel("Run the oscilloscope to see a spectrum.")
        self.note_label.setWordWrap(True)

        self.plot = FftPlot()
        self.plot.setBackground("#1b1e23")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Frequency", units="Hz")
        self.plot.setLabel("left", "Peak")
        self.plot.addLegend()
        self.plot.setMinimumHeight(120)
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        show_zoom_tip(self.plot)

        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        mode_form = QFormLayout()
        self.update_mode_combo = update_mode_combo()
        mode_form.addRow("Update:", self.update_mode_combo)
        controls_layout.addLayout(mode_form)
        controls_layout.addLayout(self.channel_layout)
        controls_layout.addWidget(self.note_label)
        self.cursors = CursorBox((self.plot,), controls_layout)
        self.cursors.describe = _fft_cursor_text
        controls_layout.addStretch(1)
        controls = QWidget()
        controls.setLayout(controls_layout)
        controls.setMinimumWidth(220)
        controls.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        row.addWidget(controls)
        row.addWidget(self.plot, stretch=1)
        body.setLayout(row)
        self.setWidget(body)

    def set_channels(self, probes):
        """
        Rebuild the per-probe checkboxes. A new probe starts checked.

        :param probes: Probes on the circuit, in display order.
        :returns: None
        """
        previous = {
            box.property("reference"): box.isChecked() for box in self._checks
        }

        while self.channel_layout.count():
            item = self.channel_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        self._checks = []

        for probe in probes:
            row = QWidget()
            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            box = QCheckBox(probe.reference)
            box.setProperty("reference", probe.reference)
            box.setChecked(previous.get(probe.reference, True))
            box.setToolTip("Draw this probe on the spectrum")
            box.toggled.connect(self.channels_changed)
            swatch = QLabel()
            swatch.setFixedSize(14, 14)
            swatch.setStyleSheet(
                f"background: {probe.color}; border-radius: 2px;"
            )
            row_layout.addWidget(swatch)
            row_layout.addWidget(box)
            row_layout.addStretch(1)
            row.setLayout(row_layout)
            self.channel_layout.addWidget(row)
            self._checks.append(box)

    def enabled_references(self):
        """
        Return the probe names whose checkbox is on.

        :rtype: list
        """
        return [
            box.property("reference")
            for box in self._checks
            if box.isChecked()
        ]

    def show_traces(self, traces):
        """
        Draw traces. Each trace is ``(name, color, frequency, peak)``.

        :param traces: Series to draw.
        :returns: None
        """
        self._clear_plot()
        series = {}
        lowest = None
        highest = None

        for name, color, frequency, peak in traces:
            pen = pg.mkPen(color, width=2)
            finite = [
                (hertz, height)
                for hertz, height in zip(frequency, peak)
                if hertz >= 0 and math.isfinite(height)
            ]

            if not finite:
                continue

            hertz, height = zip(*finite)
            self.plot.plot(list(hertz), list(height), pen=pen, name=name)
            series[name] = (hertz, height)
            lowest = min(hertz) if lowest is None else min(lowest, min(hertz))
            highest = max(hertz) if highest is None else max(highest, max(hertz))

        if traces:
            self.note_label.setText(
                "Peak of the oscilloscope waveform. "
                "A whole number of cycles is one line."
            )
        else:
            self.note_label.setText(
                "Check a probe. This is the spectrum of the oscilloscope."
            )

        if lowest is None:
            self.cursors.show_series([], {}, 0, 1)
        else:
            self.cursors.show_series(list(series), series, lowest, highest)

    def clear_traces(self):
        """
        Remove the traces. The checkboxes stay.

        :returns: None
        """
        self._clear_plot()
        self.note_label.setText("Run the oscilloscope to see a spectrum.")
        self.cursors.clear()

    def plotted_spectrum(self):
        """
        Return ``(name, frequency, peak)`` for each curve.

        :rtype: list
        """
        series = []

        for item in self.plot.listDataItems():
            frequency, peak = item.getData()
            series.append((
                item.name(),
                tuple(float(value) for value in frequency),
                tuple(float(value) for value in peak),
            ))

        return series

    def set_cursors(self, first_hertz, second_hertz):
        """
        Put the cursors on two frequencies.

        :param first_hertz: Cursor A, in hertz.
        :param second_hertz: Cursor B, in hertz.
        :returns: None
        """
        self.cursors.set_positions(first_hertz, second_hertz)

    def _clear_plot(self):
        self.plot.plotItem.clearPlots()
        legend = self.plot.plotItem.legend

        if legend is not None:
            legend.clear()


def _fft_cursor_text(name, series, first, second):
    frequency, peak = series
    return format_cursor_text(
        name,
        first,
        second,
        "Hz",
        ((value_at(frequency, peak, first), value_at(frequency, peak, second), ""),),
    )
