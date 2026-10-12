"""
Two dashed cursor lines for a plot, and the box that reads them.

The lines share one position when a dock has more than one axis, so
Bode magnitude and phase stay together.
"""

import pyqtgraph as pg
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QComboBox, QLabel

from core.exceptions import ComponentError

_CURSOR_COLORS = (("A", "#3ec6ff"), ("B", "#ffb000"))


class CursorLines:
    """
    Vertical lines named A and B.

    :param plots: Plot widgets that show the same x position.
    """

    def __init__(self, plots):
        self.moved = None
        self._guard = False
        self.a = []
        self.b = []

        for plot in plots:
            pair = []

            for name, color in _CURSOR_COLORS:
                line = pg.InfiniteLine(
                    pos=0,
                    angle=90,
                    movable=True,
                    pen=pg.mkPen(color, width=1.5, style=Qt.DashLine),
                    hoverPen=pg.mkPen(color, width=3),
                    label=name,
                    labelOpts={
                        "position": 0.92,
                        "color": color,
                        "fill": (27, 30, 35, 210),
                    },
                )
                line.setZValue(20)
                line.sigPositionChanged.connect(self._line_moved)
                plot.plotItem.addItem(line, ignoreBounds=True)
                pair.append(line)

            self.a.append(pair[0])
            self.b.append(pair[1])

        self.hide()

    def hide(self):
        """
        Take both lines off the plot. Their positions stay put.

        :returns: None
        """
        for line in self.a + self.b:
            line.setVisible(False)

    def values(self):
        """
        Return the position of A and the position of B.

        :rtype: tuple
        """
        return self.a[0].value(), self.b[0].value()

    def place(self, first, second, low, high):
        """
        Show both lines inside ``low`` and ``high``.

        :param first: Position of A, in the plot's x units.
        :param second: Position of B.
        :param low: Left bound.
        :param high: Right bound.
        :returns: None
        """
        if high < low:
            low, high = high, low

        self._guard = True

        try:
            for line in self.a:
                line.setBounds((low, high))
                line.setValue(first)
                line.setVisible(True)

            for line in self.b:
                line.setBounds((low, high))
                line.setValue(second)
                line.setVisible(True)
        finally:
            self._guard = False

    def _line_moved(self, line):
        if self._guard:
            return

        if line in self.a:
            group = self.a
        elif line in self.b:
            group = self.b
        else:
            return

        value = line.value()
        self._guard = True

        try:
            for other in group:
                if other is not line:
                    other.setValue(value)
                    other.setVisible(True)
        finally:
            self._guard = False

        if self.moved is not None:
            self.moved()


class CursorBox:
    """
    The trace chooser, the two lines, and the difference text.

    :param plots: Plot widgets that share the cursors.
    :param layout: Controls column that holds the chooser and the text.
    """

    def __init__(self, plots, layout):
        self.lines = CursorLines(plots)
        self.lines.moved = self._dragged
        self.describe = None
        self.series = {}
        self.user_moved = False
        self._low = 0.0
        self._high = 1.0
        self.combo = QComboBox()
        self.combo.setToolTip("Which trace the cursors read")
        self.combo.currentTextChanged.connect(self._refresh)
        self.label = QLabel("Cursors appear when a trace is drawn.")
        self.label.setWordWrap(True)
        self.label.setToolTip("B minus A. Drag the dashed lines.")
        layout.addWidget(self.combo)
        layout.addWidget(self.label)
        self.combo.hide()

    def show_series(self, names, series, low, high):
        """
        Show the cursors for a new set of traces.

        A trace the user already chose stays chosen. Lines the user
        already dragged stay where they were, clamped to the new span.

        :param names: Trace names in plot order.
        :param series: Mapping of name to the data the text reads.
        :param low: Left end of the cursor span.
        :param high: Right end of the cursor span.
        :returns: None
        """
        self.series = dict(series)
        self._low = low
        self._high = high
        previous = self.combo.currentText()
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItems(list(names))

        if previous in names:
            self.combo.setCurrentText(previous)

        self.combo.setVisible(len(names) > 1)
        self.combo.blockSignals(False)

        if not names:
            self.lines.hide()
            self.label.setText("Check a trace to read the cursors.")
            return

        if self.user_moved:
            first, second = self.lines.values()
            first = min(high, max(low, first))
            second = min(high, max(low, second))
        else:
            first, second = _quarters(low, high)

        self.lines.place(first, second, low, high)
        self._refresh()

    def clear(self):
        """
        Hide the cursors and forget where the user dragged them.

        :returns: None
        """
        self.series = {}
        self.user_moved = False
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.blockSignals(False)
        self.combo.hide()
        self.lines.hide()
        self.label.setText("Cursors appear when a trace is drawn.")

    def set_positions(self, first, second):
        """
        Put A and B at two positions and read them.

        :param first: Position of A, in the plot's x units.
        :param second: Position of B.
        :returns: None
        """
        self.user_moved = True
        low = min(self._low, first, second)
        high = max(self._high, first, second)
        self._low = low
        self._high = high
        self.lines.place(first, second, low, high)
        self._refresh()

    def _dragged(self):
        self.user_moved = True
        self._refresh()

    def _refresh(self, *_unused):
        if not self.series or self.describe is None:
            return

        name = self.combo.currentText()

        if name not in self.series:
            name = next(iter(self.series))

        first, second = self.lines.values()

        try:
            text = self.describe(name, self.series[name], first, second)
        except ComponentError as error:
            self.label.setText(str(error))
            return

        self.label.setText(text)


def _quarters(low, high):
    if high < low:
        low, high = high, low

    if high == low:
        return low, low

    span = high - low
    return low + 0.25 * span, low + 0.75 * span
