"""
The probe drawn on the grid.

The probe is a small flag with its name, up and to the left of the point
it reads, so it does not cover the dot or a net name. A line and an
arrow run from the flag to that point. Dragging the flag moves the
readings and leaves the point alone. Dragging the arrow chooses a new
point. A probe that is not on a plot also draws a box of readings
(voltage, current, frequency, phase) to the left of that flag. A
differential probe has a second flag on the minus point.
"""

import math

from PyQt5.QtCore import QLineF, QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PyQt5.QtWidgets import QApplication, QGraphicsItem

from core.probes import PROBE_METHOD_LABELS

PROBE_Z_VALUE = 2
_FLAG_WIDTH = 46
_FLAG_HEIGHT = 16
_FLAG_GAP = 4
_LINE_HEIGHT = 14
_BOX_PAD = 4
# The arrow stops this far from the point so the grid dot stays visible.
_ARROW_CLEARANCE = 12
_ARROW_LENGTH = 9
_ARROW_HALF_WIDTH = 3.5
# The arrow head is the handle that chooses a new point.
_ARROW_GRAB = 12


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
        self._aiming = False
        self._press_scene_position = None
        # While the arrow is being dragged, the tip follows the cursor.
        # None means the arrow points at anchor_position.
        self._aim_scene_position = None
        # Scene position of the point this flag reads. The flag can sit
        # somewhere else; the arrow is drawn back to this point.
        self.anchor_position = QPointF(0, 0)

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

        The flag is above and to the left of the item origin. The box
        sits to the left of the flag. The arrow reaches the measured
        point, which is not always the item origin.

        :rtype: QRectF
        """
        flag = self._flag_rect()
        box = self._box_rect()
        rect = flag if box is None else flag.united(box)
        target = self.leader_target()
        reach = _ARROW_GRAB + 4
        rect = rect.united(
            QRectF(
                target.x() - reach,
                target.y() - reach,
                reach * 2,
                reach * 2,
            )
        )

        return rect.adjusted(-2, -2, 2, 2)

    def shape(self):
        """
        Return the flag, its readout, and the arrow head.

        The flag moves the readings. The arrow head chooses the point.
        The leader line is drawn but does not steal clicks from the grid.

        :rtype: QPainterPath
        """
        path = QPainterPath()
        path.addRoundedRect(self._flag_rect(), 3, 3)
        box = self._box_rect()

        if box is not None:
            path.addRoundedRect(box, 3, 3)

        tip = self._arrow_tip(self._leader_start(), self.leader_target())
        path.addEllipse(tip, _ARROW_GRAB, _ARROW_GRAB)

        return path

    def paint(self, painter, option, widget=None):
        """
        Draw the leader and arrow, the parameter box, then the flag.

        :returns: None
        """
        self._paint_leader(painter)

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
        self._paint_probe_head(painter)

    def leader_target(self):
        """
        Return the measured point, in item coordinates.

        :rtype: QPointF
        """
        if self._aim_scene_position is not None:
            return self.mapFromScene(self._aim_scene_position)

        return self.mapFromScene(self.anchor_position)

    def _paint_leader(self, painter):
        """
        Draw the line from the probe to the point it reads, with an arrow.

        :returns: None
        """
        start = self._leader_start()
        target = self.leader_target()
        tip = self._arrow_tip(start, target)
        color = QColor(self.probe.color)

        painter.setPen(QPen(color, 2))
        painter.setBrush(color)
        painter.drawLine(QLineF(start, tip))
        painter.setPen(QPen(QColor("#102a43"), 1))
        painter.drawPolygon(self._arrow_head(start, tip))

    def _paint_probe_head(self, painter):
        """
        Draw the probe tip where the lead leaves the flag.

        :returns: None
        """
        start = self._leader_start()
        painter.setPen(QPen(QColor("#102a43"), 1))
        painter.setBrush(QColor(self.probe.color))
        painter.drawEllipse(start, 4.5, 4.5)

    def _leader_start(self):
        """
        Return the point on the flag where the lead leaves.

        :rtype: QPointF
        """
        flag = self._flag_rect()
        target = self.leader_target()
        x_position = min(max(target.x(), flag.left()), flag.right())
        y_position = min(max(target.y(), flag.top()), flag.bottom())

        return QPointF(x_position, y_position)

    def _arrow_tip(self, start, target):
        """
        Return the arrow tip, held back from the grid dot.

        :rtype: QPointF
        """
        length = math.hypot(target.x() - start.x(), target.y() - start.y())

        # While aiming, the tip stays under the cursor.
        if self._aim_scene_position is not None or length <= _ARROW_CLEARANCE + 2:
            return target

        scale = (length - _ARROW_CLEARANCE) / length

        return QPointF(
            start.x() + (target.x() - start.x()) * scale,
            start.y() + (target.y() - start.y()) * scale,
        )

    def _arrow_head(self, start, tip):
        """
        Return the arrow head pointing from the probe toward the point.

        :rtype: QPolygonF
        """
        dx = tip.x() - start.x()
        dy = tip.y() - start.y()
        length = math.hypot(dx, dy)

        if length < 1:
            dx, dy, length = 1.0, 0.0, 1.0

        unit_x = dx / length
        unit_y = dy / length
        side_x = -unit_y
        side_y = unit_x
        back_x = tip.x() - (unit_x * _ARROW_LENGTH)
        back_y = tip.y() - (unit_y * _ARROW_LENGTH)

        return QPolygonF([
            tip,
            QPointF(
                back_x + (side_x * _ARROW_HALF_WIDTH),
                back_y + (side_y * _ARROW_HALF_WIDTH),
            ),
            QPointF(
                back_x - (side_x * _ARROW_HALF_WIDTH),
                back_y - (side_y * _ARROW_HALF_WIDTH),
            ),
        ])

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
        Remember where a drag started, and whether it grabbed the arrow.

        :returns: None
        """
        self._dragging = False
        self._aim_scene_position = None
        self._aiming = self._press_aims(event.pos())
        self._press_scene_position = event.scenePos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Slide the flag, or aim the arrow, once the drag has started.

        Dragging the flag moves the readings. Dragging the arrow leaves
        the flag where it is and points the tip at the cursor.

        :returns: None
        """
        if (self._press_scene_position is not None and
                event.buttons() & Qt.LeftButton):
            delta = event.scenePos() - self._press_scene_position

            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True

            if self._dragging and self._aiming:
                self.prepareGeometryChange()
                self._aim_scene_position = event.scenePos()
                self._press_scene_position = event.scenePos()
                self.update()

                if self.scene() is not None:
                    self.scene().preview_probe_aim(self, event.scenePos())
            elif self._dragging:
                self.prepareGeometryChange()
                self.moveBy(delta.x(), delta.y())
                self._press_scene_position = event.scenePos()

        event.accept()

    def mouseReleaseEvent(self, event):
        """
        Leave the flag where it was released.

        A flag drag does not change the point. An arrow drag does, when
        the release is on a grid point (or on a part, for current).

        :returns: None
        """
        aiming = self._aiming

        if self._dragging and self.scene() is not None:
            self.scene().finish_probe_drag(
                self, event.scenePos(), aiming=aiming
            )

        self._dragging = False
        self._aiming = False
        self._aim_scene_position = None
        self._press_scene_position = None
        super().mouseReleaseEvent(event)

    def _press_aims(self, local_position):
        """
        Return whether this press grabbed the arrow rather than the flag.

        :rtype: bool
        """
        if self._flag_rect().contains(local_position):
            return False

        box = self._box_rect()

        if box is not None and box.contains(local_position):
            return False

        tip = self._arrow_tip(self._leader_start(), self.leader_target())

        return QLineF(local_position, tip).length() <= _ARROW_GRAB

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
        lines = [
            f"{self.probe.reference} {label}",
            "Drag the flag to move the readings.",
            "Drag the arrow to choose the point.",
        ]

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
