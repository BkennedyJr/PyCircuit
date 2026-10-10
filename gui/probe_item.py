"""
The flag drawn for one probe.

The flag sits up and to the left of its grid point so it does not cover
the dot or a net name. A differential probe has a second flag on the
minus point. Dragging a flag snaps it to another point or, for a current
probe, another part.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPen
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from core.probes import PROBE_METHOD_LABELS

PROBE_Z_VALUE = 2
_FLAG_WIDTH = 46
_FLAG_HEIGHT = 16
_FLAG_GAP = 4


class ProbeItem(QGraphicsItem):
    """
    One end of a probe, drawn as a coloured flag.

    :param probe: Core probe to draw.
    :param role: ``"primary"`` or ``"second"``.
    :param slot: Stack index when several flags share a point.
    """

    def __init__(self, probe, role="primary", slot=0):
        super().__init__()

        self.probe = probe
        self.role = role
        self.slot = slot
        self._dragging = False
        self._press_scene_position = None

        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setZValue(PROBE_Z_VALUE)
        self.setToolTip(self._tool_tip_text())

    def boundingRect(self):
        """
        Return the flag rectangle, in item coordinates.

        The item origin is the grid point. The flag is above and to the left.

        :rtype: QRectF
        """
        top = -(_FLAG_HEIGHT + 18) - (self.slot * (_FLAG_HEIGHT + _FLAG_GAP))

        return QRectF(-_FLAG_WIDTH - 8, top, _FLAG_WIDTH, _FLAG_HEIGHT)

    def paint(self, painter, option, widget=None):
        """
        Draw the flag and its name.

        :returns: None
        """
        rectangle = self.boundingRect()
        color = QColor(self.probe.color)

        if self.isSelected():
            painter.setPen(QPen(QColor("#ffffff"), 2))
        else:
            painter.setPen(QPen(QColor("#102a43"), 1))

        painter.setBrush(color)
        painter.drawRoundedRect(rectangle, 3, 3)

        painter.setPen(QColor("#1f2933"))
        font = QFont()
        font.setPointSize(8)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(rectangle, Qt.AlignCenter, self._flag_text())

    def mousePressEvent(self, event):
        """
        Remember where a drag started.

        :returns: None
        """
        self._dragging = False
        self._press_scene_position = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Slide the flag with the cursor once the drag has started.

        :returns: None
        """
        if (self._press_scene_position is not None and
                event.buttons() & Qt.LeftButton):
            delta = event.scenePos() - self._press_scene_position

            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True

            if self._dragging:
                self.moveBy(delta.x(), delta.y())
                self._press_scene_position = event.scenePos()

        event.accept()

    def mouseReleaseEvent(self, event):
        """
        Snap the flag to the point or part under the cursor.

        :returns: None
        """
        if self._dragging and self.scene() is not None:
            self.scene().finish_probe_drag(self, event.scenePos())

        self._dragging = False
        self._press_scene_position = None
        super().mouseReleaseEvent(event)

    def _flag_text(self):
        """
        Return the short name drawn on the flag.

        :rtype: str
        """
        if self.role == "second":
            return f"{self.probe.reference}-"

        if self.probe.method == "current":
            return f"{self.probe.reference} I"

        if self.probe.method == "megohm":
            return f"{self.probe.reference} 1M"

        if self.probe.method == "scope_10x":
            return f"{self.probe.reference} 10x"

        if self.probe.method == "differential":
            return f"{self.probe.reference}+"

        return self.probe.reference

    def _tool_tip_text(self):
        """
        Return the hover text for this flag.

        :rtype: str
        """
        label = PROBE_METHOD_LABELS.get(self.probe.method, self.probe.method)
        lines = [f"{self.probe.reference} {label}"]

        if self.probe.method == "current":
            lines.append(self.probe.component_reference or "")
        elif self.role == "second":
            lines.append(self.probe.second_identifier or "")
        else:
            lines.append(self.probe.identifier or "")

            if self.probe.second_identifier:
                lines.append(f"minus {self.probe.second_identifier}")

        return "\n".join(line for line in lines if line)
