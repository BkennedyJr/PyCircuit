"""
Bode dock. Start and Stop live here. The window runs ngspice.

Magnitude is dB relative to the AC source. Phase is degrees. The
frequency axis is logarithmic.
"""

import pyqtgraph as pg
from PyQt5.QtCore import QObject, QSize, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import ComponentError
from core.units import parse_value


class BodePlot(pg.PlotWidget):
    """
    One Bode axis. Two of these stack beside the controls.

    PlotWidget asks for 600 by 450. A shorter hint leaves the circuit
    on screen. The dock can still be dragged taller.
    """

    def sizeHint(self):
        return QSize(360, 140)

    def minimumSizeHint(self):
        return QSize(200, 90)


class BodeDock(QDockWidget):
    """
    Dock that shows magnitude and phase from the last frequency sweep.

    :param parent: Owning window.
    """

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Bode", parent)
        self.setObjectName("bode")
        self._checks = []
        self._build()

    def _build(self):
        body = QWidget()
        row = QHBoxLayout()

        self.start_edit = QLineEdit("10")
        self.start_edit.setToolTip(
            "First frequency. 10 is 10 Hz. 1k is 1 kilohertz."
        )
        self.stop_edit = QLineEdit("100k")
        self.stop_edit.setToolTip("Last frequency. It must be higher than the start.")
        self.points_edit = QLineEdit("20")
        self.points_edit.setToolTip(
            "How many points to take in each decade. 20 is a smooth curve."
        )

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.addRow("Start:", self.start_edit)
        form.addRow("Stop:", self.stop_edit)
        form.addRow("Points / dec:", self.points_edit)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setToolTip("Run a frequency sweep and draw the probes")
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Drop this sweep")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)

        self.channel_layout = QVBoxLayout()
        self.note_label = QLabel(
            "Press Start. Magnitude is dB relative to the AC source."
        )
        self.note_label.setWordWrap(True)

        controls_layout = QVBoxLayout()
        controls_layout.setContentsMargins(0, 0, 0, 0)
        controls_layout.addLayout(form)
        controls_layout.addLayout(buttons)
        controls_layout.addLayout(self.channel_layout)
        controls_layout.addWidget(self.note_label)
        controls_layout.addStretch(1)
        controls = QWidget()
        controls.setLayout(controls_layout)
        controls.setMinimumWidth(220)
        controls.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        plots = QVBoxLayout()
        self.magnitude = _styled_plot("Magnitude", "dB")
        self.phase = _styled_plot("Phase", "deg")
        self.phase.setXLink(self.magnitude)
        plots.addWidget(self.magnitude, stretch=1)
        plots.addWidget(self.phase, stretch=1)

        row.addWidget(controls)
        row.addLayout(plots, stretch=1)
        body.setLayout(row)
        self.setWidget(body)

    def start_hertz(self):
        """
        Return the first frequency in hertz.

        :rtype: float
        :raises ComponentError: If the text is not a positive value.
        """
        return _positive_frequency(self.start_edit.text(), "Start frequency")

    def stop_hertz(self):
        """
        Return the last frequency in hertz.

        :rtype: float
        :raises ComponentError: If the text is not above the start.
        """
        stop = _positive_frequency(self.stop_edit.text(), "Stop frequency")
        start = self.start_hertz()

        if stop <= start:
            raise ComponentError(
                "Stop frequency must be higher than the start frequency."
            )

        return stop

    def points_per_decade(self):
        """
        Return how many points to take in each decade.

        :rtype: int
        :raises ComponentError: If the text is not a whole number from
            1 to 100.
        """
        text = self.points_edit.text().strip()

        if not text.isdigit():
            raise ComponentError(
                "Points per decade must be a whole number from 1 to 100, "
                "such as 20."
            )

        points = int(text)

        if points < 1 or points > 100:
            raise ComponentError(
                "Points per decade must be a whole number from 1 to 100, "
                "such as 20."
            )

        return points

    def set_running(self, is_running):
        """
        Enable Start or Stop to match a sweep that is in progress.

        :param is_running: True while ngspice is working.
        :type is_running: bool
        :returns: None
        """
        self.start_button.setEnabled(not is_running)
        self.stop_button.setEnabled(is_running)

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
            box.setToolTip("Draw this probe on the Bode plot")
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
        Draw traces. Each trace is ``(name, color, frequency, db, phase)``.

        :param traces: Series to draw.
        :returns: None
        """
        self._clear_plot(self.magnitude)
        self._clear_plot(self.phase)

        for name, color, frequency, decibels, phase in traces:
            pen = pg.mkPen(color, width=2)
            finite = [
                (hertz, db, degrees)
                for hertz, db, degrees in zip(frequency, decibels, phase)
                if hertz > 0 and db != float("-inf")
            ]

            if not finite:
                continue

            hertz, db, degrees = zip(*finite)
            self.magnitude.plot(list(hertz), list(db), pen=pen, name=name)
            self.phase.plot(list(hertz), list(degrees), pen=pen, name=name)

        if traces:
            self.note_label.setText(
                "Magnitude is dB relative to the AC source. "
                "Phase is degrees."
            )
        else:
            self.note_label.setText("Check a probe, then press Start.")

    def clear_traces(self):
        """
        Remove the traces. The checkboxes stay.

        :returns: None
        """
        self._clear_plot(self.magnitude)
        self._clear_plot(self.phase)
        self.note_label.setText(
            "Press Start. Magnitude is dB relative to the AC source."
        )

    def plotted_magnitude(self):
        """
        Return ``(name, frequency, decibels)`` for each magnitude curve.

        :rtype: list
        """
        return _curves(self.magnitude)

    @staticmethod
    def _clear_plot(plot):
        plot.clear()
        legend = plot.plotItem.legend

        if legend is not None:
            legend.clear()


class BodeRunner(QObject):
    """
    Run one frequency sweep off the GUI thread.

    :param netlist: Text passed to ``run_ac``, including probe loads.
    :param start: First frequency, in hertz.
    :param stop: Last frequency, in hertz.
    :param points_per_decade: Points in each decade.
    :param cancel_event: Set this to drop the result.
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, netlist, start, stop, points_per_decade, cancel_event):
        super().__init__()
        self._netlist = netlist
        self._start = start
        self._stop = stop
        self._points = points_per_decade
        self._cancel = cancel_event

    def run(self):
        """
        Emit the sweep, or the plain-English reason it failed.

        :returns: None
        """
        from core.exceptions import SimulationError
        from sim.runner import run_ac

        try:
            result = run_ac(
                self._netlist,
                self._start,
                self._stop,
                self._points,
                cancel_event=self._cancel,
            )
        except SimulationError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "The frequency sweep failed.")
            return

        self.succeeded.emit(result)


def _styled_plot(label, units):
    plot = BodePlot()
    plot.setBackground("#1b1e23")
    plot.showGrid(x=True, y=True, alpha=0.25)
    plot.setLabel("bottom", "Frequency", units="Hz")
    plot.setLabel("left", label, units=units)
    plot.setLogMode(x=True, y=False)
    plot.addLegend()
    plot.setMinimumHeight(100)
    return plot


def _curves(plot):
    series = []
    log_x = plot.plotItem.getViewBox().state["logMode"][0]

    for item in plot.listDataItems():
        frequency, values = item.getData()
        hertz = tuple(float(value) for value in frequency)

        if log_x:
            hertz = tuple(10.0 ** value for value in hertz)

        series.append((
            item.name(),
            hertz,
            tuple(float(value) for value in values),
        ))

    return series


def _positive_frequency(text, label):
    try:
        value = parse_value(text)
    except ComponentError as error:
        raise ComponentError(
            f"{label} must be a positive number, such as 10 or 1k."
        ) from error

    if value <= 0:
        raise ComponentError(
            f"{label} must be a positive number, such as 10 or 1k."
        )

    return value
