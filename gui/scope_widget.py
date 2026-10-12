"""
Oscilloscope dock. Start and Stop live here. The window runs ngspice.

Ten divisions across, and ten divisions from top to bottom. A blank
volts-per-division box means Auto.
"""

import pyqtgraph as pg
from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.exceptions import ComponentError
from core.units import format_spice_number, parse_value
from sim.runner import default_transient_stop

SCOPE_DIVISIONS = 10


class OscilloscopeDock(QDockWidget):
    """
    Dock that shows probe traces from the last transient.

    :param parent: Owning window.
    """

    start_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    channels_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("Oscilloscope", parent)
        self.setObjectName("oscilloscope")
        self._run_time_automatic = True
        self._time_div_automatic = True
        self._checks = []
        self._build()

    def _build(self):
        body = QWidget()
        layout = QVBoxLayout()
        form = QFormLayout()

        self.run_time_edit = QLineEdit("10m")
        self.run_time_edit.setToolTip(
            "How long to run. 10m is 10 milliseconds. "
            "A sine uses five periods of the slowest source."
        )
        self.run_time_edit.textEdited.connect(self._edited_run_time)
        self.time_div_edit = QLineEdit("1m")
        self.time_div_edit.setToolTip(
            "Time per division. The screen is 10 divisions wide."
        )
        self.time_div_edit.textEdited.connect(self._edited_time_div)
        self.volts_edit = QLineEdit()
        self.volts_edit.setPlaceholderText("Auto")
        self.volts_edit.setToolTip(
            "Volts per division, or blank for Auto. "
            "The screen is 10 divisions tall."
        )
        self.volts_edit.editingFinished.connect(self.channels_changed)

        form.addRow("Run time:", self.run_time_edit)
        form.addRow("Time / div:", self.time_div_edit)
        form.addRow("Volts / div:", self.volts_edit)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("Start")
        self.start_button.setToolTip("Run a transient and draw the probes")
        self.start_button.clicked.connect(self.start_requested)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setToolTip("Drop this run")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)

        self.channel_layout = QVBoxLayout()
        self.note_label = QLabel("Press Start.")
        self.note_label.setWordWrap(True)

        self.plot = pg.PlotWidget()
        self.plot.setBackground("#1b1e23")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setLabel("left", "Signal")
        self.plot.addLegend()
        self.plot.setMinimumHeight(220)

        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(self.channel_layout)
        layout.addWidget(self.note_label)
        layout.addWidget(self.plot, stretch=1)
        body.setLayout(layout)
        self.setWidget(body)

    def _edited_run_time(self):
        self._run_time_automatic = False

    def _edited_time_div(self):
        self._time_div_automatic = False
        self.channels_changed.emit()

    def refresh_automatic_times(self, components):
        """
        Fill the run time and the time scale when the user has not typed
        them. A sine gets five periods. Anything else gets 10 ms.

        :param components: Placed parts.
        :returns: None
        """
        stop = default_transient_stop(components)

        if self._run_time_automatic:
            self.run_time_edit.setText(format_spice_number(stop))

        if self._time_div_automatic:
            self.time_div_edit.setText(
                format_spice_number(stop / SCOPE_DIVISIONS)
            )

    def run_time_seconds(self):
        """
        Return the run time in seconds.

        :rtype: float
        :raises ComponentError: If the text is not a positive value.
        """
        return _positive_time(self.run_time_edit.text(), "Run time")

    def time_per_division_seconds(self):
        """
        Return the time per division in seconds.

        :rtype: float
        :raises ComponentError: If the text is not a positive value.
        """
        return _positive_time(self.time_div_edit.text(), "Time per division")

    def volts_per_division(self):
        """
        Return volts per division, or None for Auto.

        :rtype: float or None
        :raises ComponentError: If the text is not a positive value.
        """
        text = self.volts_edit.text().strip()

        if not text or text.lower() == "auto":
            return None

        try:
            value = parse_value(text)
        except ComponentError as error:
            raise ComponentError(
                "Volts per division must be a positive number, such as "
                "1 or 500m. Leave it blank for Auto."
            ) from error

        if value <= 0:
            raise ComponentError(
                "Volts per division must be a positive number, such as "
                "1 or 500m. Leave it blank for Auto."
            )

        return value

    def set_running(self, is_running):
        """
        Enable Start or Stop to match a run that is in progress.

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
            box.setToolTip("Draw this probe on the scope")
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

    def show_traces(self, traces, time_per_division, volts_per_division):
        """
        Draw traces. Each trace is ``(name, color, time, values)``.

        :param traces: Series to draw.
        :param time_per_division: Seconds across one division.
        :param volts_per_division: Volts across one division, or None.
        :returns: None
        """
        self.plot.clear()
        legend = self.plot.plotItem.legend

        if legend is not None:
            legend.clear()

        for name, color, time_seconds, values in traces:
            self.plot.plot(
                list(time_seconds),
                list(values),
                pen=pg.mkPen(color, width=2),
                name=name,
            )

        self.plot.setXRange(0, SCOPE_DIVISIONS * time_per_division, padding=0)

        if volts_per_division is None:
            self.plot.enableAutoRange(axis="y")
        else:
            half = (SCOPE_DIVISIONS / 2.0) * volts_per_division
            self.plot.setYRange(-half, half, padding=0)

        if traces:
            self.note_label.setText("Each checked probe is a trace.")
        else:
            self.note_label.setText("Check a probe, then press Start.")

    def clear_traces(self):
        """
        Remove the traces. The checkboxes stay.

        :returns: None
        """
        self.plot.clear()
        legend = self.plot.plotItem.legend

        if legend is not None:
            legend.clear()

        self.note_label.setText("Press Start.")

    def plotted_series(self):
        """
        Return ``(name, time, values)`` for each curve on the plot.

        :rtype: list
        """
        series = []

        for item in self.plot.listDataItems():
            time_seconds, values = item.getData()
            series.append((
                item.name(),
                tuple(float(value) for value in time_seconds),
                tuple(float(value) for value in values),
            ))

        return series


class TransientRunner(QObject):
    """
    Run one transient off the GUI thread.

    :param netlist: Text passed to ``run_tran``, including probe loads.
    :param step: Maximum time step, in seconds.
    :param stop: Run length, in seconds.
    :param cancel_event: Set this to drop the result.
    """

    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, netlist, step, stop, cancel_event):
        super().__init__()
        self._netlist = netlist
        self._step = step
        self._stop = stop
        self._cancel = cancel_event

    def run(self):
        """
        Emit the transient, or the plain-English reason it failed.

        :returns: None
        """
        from core.exceptions import SimulationError
        from sim.runner import run_tran

        try:
            result = run_tran(
                self._netlist,
                self._step,
                self._stop,
                cancel_event=self._cancel,
            )
        except SimulationError as error:
            self.failed.emit(str(error))
            return
        except Exception as error:  # noqa: BLE001
            self.failed.emit(str(error) or "The transient failed.")
            return

        self.succeeded.emit(result)


def _positive_time(text, label):
    try:
        value = parse_value(text)
    except ComponentError as error:
        raise ComponentError(
            f"{label} must be a positive number, such as 10m or 1u."
        ) from error

    if value <= 0:
        raise ComponentError(
            f"{label} must be a positive number, such as 10m or 1u."
        )

    return value
