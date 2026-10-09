"""
QGraphicsLineItem that draws one wire on the connection grid.

Stacking (z values): the grid lines are the scene background, label
patches are at -0.5, wires at WIRE_Z_VALUE (-0.25), grid points at 0,
junction dots at 0.5 and parts at 1. So wires draw above the grid lines
and label patches but below the grid dots and the parts; a wire connects
every grid dot it covers.

This module must not import gui.grid_editor (the scene imports this
module); the scene passes scene positions in.
"""

from PyQt5.QtCore import QLineF, Qt
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

    def shape(self):
        """
        Click area: the line widened to WIRE_PICK_WIDTH.

        :rtype: QPainterPath
        """
        path = QPainterPath()
        path.moveTo(self.line().p1())
        path.lineTo(self.line().p2())

        stroker = QPainterPathStroker()
        stroker.setWidth(WIRE_PICK_WIDTH)
        stroker.setCapStyle(Qt.RoundCap)

        return stroker.createStroke(path)

    def boundingRect(self):
        """
        Bounding box that includes the wider click area.

        :rtype: QRectF
        """
        margin = WIRE_PICK_WIDTH / 2

        return super().boundingRect().adjusted(
            -margin, -margin, margin, margin
        )

    def paint(self, painter, option, widget=None):
        """
        Draw the line without Qt's dashed selection rectangle.
        """
        painter.setPen(self.pen())
        painter.drawLine(self.line())


def build_preview_pen():
    """
    Return the dashed pen of the rubber-band line shown while drawing.

    :rtype: QPen
    """
    pen = QPen(QColor(PREVIEW_WIRE_COLOR), 2, Qt.DashLine)
    pen.setCapStyle(Qt.RoundCap)

    return pen
