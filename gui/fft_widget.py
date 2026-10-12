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
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


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

        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addLayout(self.channel_layout)
        controls_layout.addWidget(self.note_label)
        controls_layout.addStretch(1)
        controls = QWidget()
        controls.setLayout(controls_layout)
        controls.setMinimumWidth(220)
        controls.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        self.plot = FftPlot()
        self.plot.setBackground("#1b1e23")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Frequency", units="Hz")
        self.plot.setLabel("left", "Peak")
        self.plot.addLegend()
        self.plot.setMinimumHeight(120)
        self.plot.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

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

        if traces:
            self.note_label.setText(
                "Peak of the oscilloscope waveform. "
                "A whole number of cycles is one line."
            )
        else:
            self.note_label.setText(
                "Check a probe. This is the spectrum of the oscilloscope."
            )

    def clear_traces(self):
        """
        Remove the traces. The checkboxes stay.

        :returns: None
        """
        self._clear_plot()
        self.note_label.setText("Run the oscilloscope to see a spectrum.")

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

    def _clear_plot(self):
        self.plot.clear()
        legend = self.plot.plotItem.legend

        if legend is not None:
            legend.clear()
