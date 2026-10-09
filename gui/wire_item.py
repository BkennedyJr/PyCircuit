"""
QGraphicsLineItem that draws one wire on the connection grid.

Stacking (z values): the grid lines are the scene background, label
patches are at -0.5, wires at WIRE_Z_VALUE (-0.25), grid points at 0,
junction dots at 0.5 and parts at 1. So wires draw above the grid lines
and label patches but below the grid dots and the parts. A bridge is a
hop: the line leaves the straight path and arcs over that grid point, so
it does not land on the dot.

This module must not import gui.grid_editor (the scene imports this
module); the scene passes scene positions in.
"""

import math

from PyQt5.QtCore import QLineF, QPointF, Qt
from PyQt5.QtGui import QColor, QPainterPath, QPainterPathStroker, QPen
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsLineItem

from core.exceptions import ComponentError
from core.wires import Wire

WIRE_COLOR = "#7bd88f"
SELECTED_WIRE_COLOR = "#ffd166"
WIRE_PEN_WIDTH = 3
WIRE_Z_VALUE = -0.25
# The click area is wider than the drawn line, so a 3 px wire is easy to
# pick.
WIRE_PICK_WIDTH = 10
PREVIEW_WIRE_COLOR = "#ffd166"
# Semicircle radius of a bridge. A grid step is 60 px, so 16 px clears
# the dot and still reads as a hop, not a detour to the next point.
HOP_RADIUS = 16
# Cubic control-point factor for a quarter circle.
_HOP_KAPPA = 0.5522847498


class WireItem(QGraphicsLineItem):
    """
    Graphical representation of one wire.

    :param wire: Core-model wire to display.
    :type wire: core.wires.Wire
    :param start_position: Scene position of end A.
    :type start_position: QPointF
    :param end_position: Scene position of end B.
    :type end_position: QPointF
    :raises ComponentError: If wire is not a Wire.
    """

    def __init__(self, wire, start_position, end_position):
        if not isinstance(wire, Wire):
            raise ComponentError(f"WireItem needs a Wire, not {wire!r}.")

        super().__init__(QLineF(start_position, end_position))

        self.wire = wire

        # Selectable (Delete removes it), never dragged.
        self.setFlag(QGraphicsItem.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.setZValue(WIRE_Z_VALUE)
        self.setToolTip(wire.describe())
        self.update_pen()

    def update_pen(self):
        """
        Use the wire colour, or the highlight colour when selected.

        :returns: None
        """
        color = SELECTED_WIRE_COLOR if self.isSelected() else WIRE_COLOR
        pen = QPen(QColor(color), WIRE_PEN_WIDTH)
        pen.setCapStyle(Qt.RoundCap)
        self.setPen(pen)

    def itemChange(self, change, value):
        """
        Recolour on selection changes.
        """
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.update_pen()

        return super().itemChange(change, value)

    def wire_path(self):
        """
        Straight line from end A to end B, with a hop at each bridge.

        :rtype: QPainterPath
        """
        start = self.line().p1()
        end = self.line().p2()
        points = self.wire.get_points()
        bridged_points = self.wire.bridged_points
        step_count = len(points) - 1
        delta = end - start
        path = QPainterPath()
        path.moveTo(start)

        if step_count == 0:
            return path

        for index, grid_point in enumerate(points):
            if index == 0:
                continue

            at = start + delta * (index / step_count)

            if grid_point in bridged_points:
                self.add_hop(path, at, delta)
            else:
                path.lineTo(at)

        return path

    def add_hop(self, path, center, delta):
        """
        Arc over one grid point. The bulge is up for a left-to-right wire
        and to the right for a top-to-bottom wire.

        :param path: Path being built, already at the previous point.
        :type path: QPainterPath
        :param center: Scene position of the bridged grid point.
        :type center: QPointF
        :param delta: End minus start, the wire's direction.
        :type delta: QPointF
        :returns: None
        """
        length = math.hypot(delta.x(), delta.y())
        along = QPointF(delta.x() / length, delta.y() / length)
        # Rotate the direction a quarter turn toward the top of the screen.
        perp = QPointF(along.y(), -along.x())
        radius = HOP_RADIUS
        bow = _HOP_KAPPA * radius
        before = center - along * radius
        apex = center + perp * radius
        after = center + along * radius
        path.lineTo(before)
        path.cubicTo(
            before + perp * bow, apex - along * bow, apex
        )
        path.cubicTo(
            apex + along * bow, after + perp * bow, after
        )

    def shape(self):
        """
        Click area: the drawn path widened to WIRE_PICK_WIDTH.

        :rtype: QPainterPath
        """
        stroker = QPainterPathStroker()
        stroker.setWidth(WIRE_PICK_WIDTH)
        stroker.setCapStyle(Qt.RoundCap)

        return stroker.createStroke(self.wire_path())

    def boundingRect(self):
        """
        Bounding box that includes the wider click area and any hop.

        :rtype: QRectF
        """
        margin = WIRE_PICK_WIDTH / 2

        if self.wire.bridged_points:
            margin += HOP_RADIUS

        return super().boundingRect().adjusted(
            -margin, -margin, margin, margin
        )

    def paint(self, painter, option, widget=None):
        """
        Draw the wire without Qt's dashed selection rectangle.
        """
        painter.setPen(self.pen())
        painter.drawPath(self.wire_path())


def build_preview_pen():
    """
    Return the dashed pen of the rubber-band line shown while drawing.

    :rtype: QPen
    """
    pen = QPen(QColor(PREVIEW_WIRE_COLOR), 2, Qt.DashLine)
    pen.setCapStyle(Qt.RoundCap)

    return pen
