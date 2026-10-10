"""
The flag drawn for one probe.

The flag sits up and to the left of its grid point so it does not cover
the dot or a net name. A probe that is not on a plot also draws a box of
readings (voltage, current, frequency, phase) to the left of that flag.
A differential probe has a second flag on the minus point. Dragging a
flag snaps it to another point or, for a current probe, another part.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPen
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from core.probes import PROBE_METHOD_LABELS

PROBE_Z_VALUE = 2
_FLAG_WIDTH = 46
_FLAG_HEIGHT = 16
_FLAG_GAP = 4
_LINE_HEIGHT = 14
_BOX_PAD = 4


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
        self.readout_lines = ()
        self._dragging = False
        self._press_scene_position = None

        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setZValue(PROBE_Z_VALUE)
        self.setToolTip(self._tool_tip_text())

    def set_readout(self, lines):
        """
        Store the parameter lines drawn in the box.

        An empty list hides the box. A probe on a plot passes an empty list.

        :param lines: ``(label, value)`` pairs.
        :returns: None
        """
        lines = tuple(tuple(line) for line in lines)

        if lines == self.readout_lines:
            return

        self.prepareGeometryChange()
        self.readout_lines = lines
        self.setToolTip(self._tool_tip_text())
        self.update()

    def boundingRect(self):
        """
        Return the flag and its parameter box, in item coordinates.

        The item origin is the grid point. The flag is above and to the
        left. The box sits to the left of the flag.

        :rtype: QRectF
        """
        flag = self._flag_rect()
        box = self._box_rect()

        if box is None:
            return flag

        return flag.united(box)

    def paint(self, painter, option, widget=None):
        """
        Draw the parameter box, then the flag and its name.

        :returns: None
        """
        box = self._box_rect()

        if box is not None:
            painter.setPen(QPen(QColor(self.probe.color), 1))
            painter.setBrush(QColor("#102a43"))
            painter.drawRoundedRect(box, 3, 3)
            painter.setPen(QColor("#f0f4f8"))
            painter.setFont(self._box_font())
            inner = box.adjusted(_BOX_PAD, _BOX_PAD, -_BOX_PAD, -_BOX_PAD)
            painter.drawText(
                inner,
                Qt.AlignLeft | Qt.AlignTop,
                "\n".join(self._readout_strings())
            )

        rectangle = self._flag_rect()
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

    def _flag_rect(self):
        """
        Return the flag rectangle, in item coordinates.

        :rtype: QRectF
        """
        top = -(_FLAG_HEIGHT + 18) - (self.slot * (_FLAG_HEIGHT + _FLAG_GAP))

        return QRectF(-_FLAG_WIDTH - 8, top, _FLAG_WIDTH, _FLAG_HEIGHT)

    def _box_font(self):
        """
        Return the font used for the parameter box.

        :rtype: QFont
        """
        font = QFont()
        font.setPointSize(8)

        return font

    def _readout_strings(self):
        """
        Return one ``"Voltage: 5 V"`` string per line.

        :rtype: list
        """
        return [f"{label}: {value}" for label, value in self.readout_lines]

    def _box_rect(self):
        """
        Return the parameter box, or None when this flag has no readout.

        :rtype: QRectF or None
        """
        if self.role != "primary" or not self.readout_lines:
            return None

        strings = self._readout_strings()
        metrics = QFontMetrics(self._box_font())
        text_width = max(metrics.horizontalAdvance(text) for text in strings)
        width = max(text_width + (2 * _BOX_PAD), 88)
        height = (2 * _BOX_PAD) + (_LINE_HEIGHT * len(strings))
        flag = self._flag_rect()
        right = flag.left() - 4

        return QRectF(right - width, flag.bottom() - height, width, height)

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

        if self.probe.has_plot:
            lines.append("On a plot.")
        else:
            lines.extend(self._readout_strings())

        if self.probe.method == "current":
            lines.append(self.probe.component_reference or "")
        elif self.role == "second":
            lines.append(self.probe.second_identifier or "")
        else:
            lines.append(self.probe.identifier or "")

            if self.probe.second_identifier:
                lines.append(f"minus {self.probe.second_identifier}")

        return "\n".join(line for line in lines if line)
