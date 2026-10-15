"""
Wheel zoom. One notch is a factor of 1.02 ** -15.

pyqtgraph scales by 1.02 ** (wheel delta * -1/8). A notch is a delta
of 120, so the factor is 1.02 ** -15, about 0.743. The span of a
zoomed axis becomes the old span times that factor. Zooming in
shrinks the span. The other axis stays put when the wheel is on one
axis's numbers.

On the scope, that new span is ten divisions, so the division box
becomes the new span divided by 10. Drawing the trace again keeps
the zoom. Typing a division uses the box for that axis only.
"""

import pyqtgraph as pg
import pytest
from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QApplication

from gui.bode_widget import BodeDock
from gui.fft_widget import FftDock
from gui.plot_zoom import ZOOM_TIP
from gui.scope_widget import OscilloscopeDock

# 1.02 ** (120 * -1/8). One wheel notch zooming in.
WHEEL_FACTOR = 1.02 ** (120 * (-1.0 / 8.0))

_SCOPE = [("P1", "#3ec6ff", (0.0, 0.01), (0.0, 0.5))]


def _spans(plot):
    x_range, y_range = plot.viewRange()
    return (x_range[1] - x_range[0], y_range[1] - y_range[0])


def _show(widget):
    widget.resize(980, 640)
    widget.show()
    QApplication.processEvents()


def _close(widget):
    widget.close()
    widget.deleteLater()
    QApplication.processEvents()


def _axis_point(plot, name):
    """
    A point on the axis numbers, outside the trace.

    The axis rectangle also covers the trace. The numbers are the
    part that sticks out, and that is the part that zooms one axis.
    """
    axis = plot.plotItem.getAxis(name).sceneBoundingRect()
    view = plot.getViewBox().sceneBoundingRect()

    if name == "bottom":
        point = QPointF(view.center().x(), (view.bottom() + axis.bottom()) / 2.0)
    else:
        point = QPointF((axis.left() + view.left()) / 2.0, view.center().y())

    assert axis.contains(point)
    assert not view.contains(point)
    return point


def _roll(plot, scene_point):
    local = plot.mapFromScene(scene_point)
    event = QWheelEvent(
        QPointF(local),
        QPointF(plot.viewport().mapToGlobal(local)),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )
    QApplication.sendEvent(plot.viewport(), event)
    QApplication.processEvents()


def test_one_notch_is_the_hand_factor():
    # pyqtgraph: scale = 1.02 ** (delta * -1/8), and one notch is 120.
    assert WHEEL_FACTOR == pytest.approx(0.7430147299885189)
    assert WHEEL_FACTOR < 1


def test_the_scope_wheel_zooms_both_axes_and_keeps_them(qt_application):
    dock = OscilloscopeDock()

    try:
        dock.show_traces(_SCOPE, 0.001, 0.2)
        _show(dock)
        x_span, y_span = _spans(dock.plot)
        assert x_span == pytest.approx(0.01)
        assert y_span == pytest.approx(2.0)
        _roll(dock.plot, dock.plot.getViewBox().sceneBoundingRect().center())
        zoomed_x, zoomed_y = _spans(dock.plot)
        assert zoomed_x == pytest.approx(0.01 * WHEEL_FACTOR)
        assert zoomed_y == pytest.approx(2.0 * WHEEL_FACTOR)
        assert dock.time_per_division_seconds() == pytest.approx(
            zoomed_x / 10, rel=1e-5
        )
        assert dock.volts_per_division() == pytest.approx(zoomed_y / 10, rel=1e-5)
        assert dock.x_held
        assert dock.y_held
        assert dock._cursor_high == pytest.approx(0.01)
        dock.show_traces(_SCOPE, 0.001, 0.2)
        assert _spans(dock.plot) == pytest.approx((zoomed_x, zoomed_y))
        dock.time_div_edit.setText("2m")
        dock._edited_time_div()
        dock.show_traces(_SCOPE, 0.002, dock.volts_per_division())
        kept_y = _spans(dock.plot)[1]
        assert _spans(dock.plot)[0] == pytest.approx(0.02)
        assert kept_y == pytest.approx(zoomed_y)
        assert dock._cursor_high == pytest.approx(0.02)
        dock.volts_edit.clear()
        dock._edited_volts()
        dock.show_traces(_SCOPE, 0.002, None)
        assert _spans(dock.plot)[0] == pytest.approx(0.02)
        assert _spans(dock.plot)[1] != pytest.approx(zoomed_y)
        assert dock.volts_per_division() is None
    finally:
        _close(dock)


def test_scope_axis_numbers_zoom_one_axis(qt_application):
    dock = OscilloscopeDock()

    try:
        dock.show_traces(_SCOPE, 0.001, 0.2)
        _show(dock)
        _roll(dock.plot, _axis_point(dock.plot, "bottom"))
        x_span, y_span = _spans(dock.plot)
        assert x_span == pytest.approx(0.01 * WHEEL_FACTOR)
        assert y_span == pytest.approx(2.0)
        assert dock.x_held
        assert not dock.y_held
        assert dock.volts_edit.text() == ""
        assert dock.time_per_division_seconds() == pytest.approx(x_span / 10, rel=1e-5)
        dock.show_traces(_SCOPE, 0.001, 0.2)
        assert _spans(dock.plot)[0] == pytest.approx(x_span)
        assert _spans(dock.plot)[1] == pytest.approx(2.0)
        _roll(dock.plot, _axis_point(dock.plot, "left"))
        x_after, y_after = _spans(dock.plot)
        assert x_after == pytest.approx(x_span)
        assert y_after == pytest.approx(2.0 * WHEEL_FACTOR)
        assert dock.volts_per_division() == pytest.approx(y_after / 10, rel=1e-5)
        assert dock.time_per_division_seconds() == pytest.approx(x_span / 10, rel=1e-5)
    finally:
        _close(dock)


def test_a_scope_pan_keeps_the_division_boxes(qt_application):
    dock = OscilloscopeDock()

    try:
        dock.show_traces(_SCOPE, 0.001, 0.2)
        dock.plot.getViewBox().translateBy(x=0.001)
        dock.plot.sigRangeChangedManually.emit([True, True])
        assert dock.x_held
        assert not dock.y_held
        assert dock.time_div_edit.text() == "1m"
        assert dock.volts_edit.text() == ""
        x_range, y_range = dock.plot.viewRange()
        dock.show_traces(_SCOPE, 0.001, 0.2)
        assert dock.plot.viewRange()[0] == pytest.approx(tuple(x_range))
        assert dock.plot.viewRange()[1] == pytest.approx((-1.0, 1.0))
        assert y_range[1] - y_range[0] == pytest.approx(2.0)
    finally:
        _close(dock)


def test_bode_frequency_numbers_zoom_only_x(qt_application):
    dock = BodeDock()

    try:
        dock.show_traces([
            ("P1", "#3ec6ff", (100.0, 1000.0), (-1.0, -3.0), (0.0, -45.0)),
        ])
        _show(dock)
        x_span, y_span = _spans(dock.magnitude)
        phase_before = _spans(dock.phase)[0]
        _roll(dock.magnitude, _axis_point(dock.magnitude, "bottom"))
        zoomed_x, zoomed_y = _spans(dock.magnitude)
        phase_after = _spans(dock.phase)[0]
        assert zoomed_x == pytest.approx(x_span * WHEEL_FACTOR)
        assert zoomed_y == pytest.approx(y_span)
        # Phase follows the frequency axis. Its span is the same zoom
        # aside from the small shift pyqtgraph uses to line the axes up.
        assert phase_after < phase_before
        assert phase_after == pytest.approx(zoomed_x, rel=0.02)
        dock.show_traces([
            ("P1", "#3ec6ff", (100.0, 1000.0), (-1.0, -3.0), (0.0, -45.0)),
        ])
        assert _spans(dock.magnitude)[0] == pytest.approx(zoomed_x)
        assert _spans(dock.phase)[0] == pytest.approx(zoomed_x, rel=0.02)
    finally:
        _close(dock)


def test_the_fft_left_numbers_zoom_only_y(qt_application):
    dock = FftDock()

    try:
        dock.show_traces([
            ("P1", "#3ec6ff", (0.0, 1000.0), (0.0, 1.0)),
        ])
        _show(dock)
        x_span, y_span = _spans(dock.plot)
        _roll(dock.plot, _axis_point(dock.plot, "left"))
        zoomed_x, zoomed_y = _spans(dock.plot)
        assert zoomed_x == pytest.approx(x_span)
        assert zoomed_y == pytest.approx(y_span * WHEEL_FACTOR)
        dock.show_traces([
            ("P1", "#3ec6ff", (0.0, 1000.0), (0.0, 1.0)),
        ])
        assert _spans(dock.plot) == pytest.approx((zoomed_x, zoomed_y))
    finally:
        _close(dock)


class _Drag:
    """The pieces of a mouse drag that a view box reads."""

    def __init__(self, start, end, finish):
        self._start = start
        self._end = end
        self._finish = finish

    def accept(self):
        return None

    def pos(self):
        return self._end

    def lastPos(self):
        return self._start

    def button(self):
        return Qt.LeftButton

    def isFinish(self):
        return self._finish

    def buttonDownPos(self, button=None):
        return self._start


def _box_zoom(plot, x0, y0, x1, y1):
    view = plot.getViewBox()
    start = view.mapFromView(QPointF(x0, y0))
    end = view.mapFromView(QPointF(x1, y1))
    view.mouseDragEvent(_Drag(start, end, False))
    view.mouseDragEvent(_Drag(start, end, True))


def test_a_dragged_box_zooms_the_scope_to_that_box(qt_application):
    dock = OscilloscopeDock()

    try:
        dock.show_traces(_SCOPE, 0.001, 0.2)
        _show(dock)
        plot = dock.plot
        assert plot.getViewBox().state["mouseMode"] == pg.ViewBox.RectMode
        plot.setXRange(0, 0.01, padding=0)
        plot.setYRange(0, 1, padding=0)
        QApplication.processEvents()
        _box_zoom(plot, 0.002, 0.2, 0.004, 0.6)
        x_range, y_range = plot.viewRange()
        assert x_range[0] == pytest.approx(0.002, abs=0.0004)
        assert x_range[1] == pytest.approx(0.004, abs=0.0004)
        assert y_range[0] == pytest.approx(0.2, abs=0.08)
        assert y_range[1] == pytest.approx(0.6, abs=0.08)
        assert dock.time_per_division_seconds() == pytest.approx(
            (x_range[1] - x_range[0]) / 10, rel=1e-5
        )
        assert dock.volts_per_division() == pytest.approx(
            (y_range[1] - y_range[0]) / 10, rel=1e-5
        )
    finally:
        _close(dock)


def test_bode_and_fft_zoom_by_a_dragged_box(qt_application):
    bode = BodeDock()
    fft = FftDock()

    try:
        assert bode.magnitude.getViewBox().state["mouseMode"] == (
            pg.ViewBox.RectMode
        )
        assert bode.phase.getViewBox().state["mouseMode"] == (
            pg.ViewBox.RectMode
        )
        assert fft.plot.getViewBox().state["mouseMode"] == pg.ViewBox.RectMode
    finally:
        _close(bode)
        _close(fft)


def test_plot_tips_say_each_axis_zooms(qt_application):
    scope = OscilloscopeDock()
    bode = BodeDock()
    fft = FftDock()

    try:
        assert "both axes" in ZOOM_TIP
        assert ZOOM_TIP in scope.plot.toolTip()
        assert "Time per division" in scope.plot.toolTip()
        assert scope.plot.plotItem.getAxis("bottom").toolTip() == ZOOM_TIP
        assert scope.plot.plotItem.getAxis("left").toolTip() == ZOOM_TIP
        assert bode.magnitude.toolTip() == ZOOM_TIP
        assert bode.phase.toolTip() == ZOOM_TIP
        assert fft.plot.toolTip() == ZOOM_TIP
    finally:
        _close(scope)
        _close(bode)
        _close(fft)
