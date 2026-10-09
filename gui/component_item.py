"""
QGraphicsItem that draws one placed component on the connection grid.

The item reads everything from a core.components.Component: the symbol is
built in pitch units by gui.component_symbols, then rotated and scaled to
pixels with QTransform().rotate(rotation).scale(spacing, spacing). Qt's
rotate() turns clockwise on screen (y points down), the same direction as
core.components.rotate_offset(), so the drawn leads end on the grid points
the model reports for the pins.

The item itself is never rotated, so its child label stays upright. The
click area (shape) is only the symbol body, so the grid points under the
pins and under the label stay clickable.

This module must not import gui.grid_editor (the scene will import this
module). The scene sets the item position.
"""

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainterPath, QPen, QTransform
from PyQt5.QtWidgets import QGraphicsItem, QGraphicsSimpleTextItem

from core.components import COMPONENT_DEFINITIONS, Component
from core.exceptions import ComponentError
from gui.component_symbols import build_symbol_paths, get_body_rect

BACKGROUND_COLOR = "#1f2933"
SYMBOL_COLOR = "#d9e2ec"
SELECTED_COLOR = "#ffd166"
SYMBOL_PEN_WIDTH = 2
BOUNDING_MARGIN = 3
LABEL_GAP = 6
LABEL_PATCH_PADDING = 2
COMPONENT_Z_VALUE = 1

# Sides tried for the label, in order. The first side that no pin points
# toward wins; if every side has a pin, the label goes above.
LABEL_SIDES = ("above", "right", "below", "left")


def pin_direction(dx, dy):
    """
    Return the side a rotated pin offset points toward.

    A diagonal offset (|dx| == |dy|) counts as above or below. An offset of
    (0, 0), like the ground pin, points nowhere.

    :param dx: Column offset in grid steps (positive is right).
    :type dx: int
    :param dy: Row offset in grid steps (positive is down).
    :type dy: int
    :returns: "above", "right", "below", "left", or None.
    :rtype: str or None
    """
    if dx == 0 and dy == 0:
        return None

    if abs(dy) >= abs(dx):
        return "above" if dy < 0 else "below"

    return "right" if dx > 0 else "left"


def choose_label_side(pin_offsets):
    """
    Pick the first side in LABEL_SIDES that no pin points toward.

    :param pin_offsets: Rotated pins as (pin_name, dx, dy).
    :type pin_offsets: list
    :returns: "above", "right", "below", or "left".
    :rtype: str
    """
    blocked_sides = {
        pin_direction(dx, dy) for unused_name, dx, dy in pin_offsets
    }

    for side in LABEL_SIDES:
        if side not in blocked_sides:
            return side

    return LABEL_SIDES[0]


def _validate_grid_spacing(grid_spacing):
    """
    Check that the grid spacing is a positive number of pixels.

    :param grid_spacing: Pixels between neighboring grid points.
    :type grid_spacing: int or float
    :returns: None
    :raises ComponentError: If the spacing is not a positive number.
    """
    if (isinstance(grid_spacing, bool) or
            not isinstance(grid_spacing, (int, float)) or
            not grid_spacing > 0):
        raise ComponentError(
            f"Grid spacing must be a positive number of pixels, "
            f"not {grid_spacing!r}."
        )


class ComponentLabelItem(QGraphicsSimpleTextItem):
    """
    Upright text label drawn over a small background-colored patch.

    The patch hides the grid dots and guide lines behind the text. The
    label never takes mouse clicks, so whatever is under it (usually a grid
    point) still gets them.
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        self.setBrush(QColor(SYMBOL_COLOR))
        self.setAcceptedMouseButtons(Qt.NoButton)

    def text_rect(self):
        """
        Return the rectangle of the text alone, without the patch.

        :returns: Text rectangle in label coordinates.
        :rtype: QRectF
        """
        return super().boundingRect()

    def boundingRect(self):
        """
        Return the text rectangle grown by the patch padding.

        :returns: Patch rectangle in label coordinates.
        :rtype: QRectF
        """
        padding = LABEL_PATCH_PADDING

        return self.text_rect().adjusted(-padding, -padding, padding, padding)

    def shape(self):
        """
        Return the patch rectangle as the label's shape.

        :returns: Shape path in label coordinates.
        :rtype: QPainterPath
        """
        path = QPainterPath()
        path.addRect(self.boundingRect())

        return path

    def paint(self, painter, option, widget=None):
        """
        Fill the patch with the background color, then draw the text.

        :param painter: Painter used to draw this item.
        :type painter: QPainter
        :param option: Qt style option for the graphics item.
        :type option: QStyleOptionGraphicsItem
        :param widget: Optional containing widget.
        :type widget: QWidget or None
        :returns: None
        """
        if not self.text():
            return

        painter.fillRect(self.boundingRect(), QColor(BACKGROUND_COLOR))
        super().paint(painter, option, widget)


class ComponentItem(QGraphicsItem):
    """
    Graphical representation of one placed component.

    :param component: Core-model component to display.
    :type component: core.components.Component
    :param grid_spacing: Pixels between neighboring grid points.
    :type grid_spacing: int or float
    :raises ComponentError: If the component or spacing is invalid.
    """

    def __init__(self, component, grid_spacing):
        if not isinstance(component, Component):
            raise ComponentError(
                f"ComponentItem needs a Component, not {component!r}."
            )

        _validate_grid_spacing(grid_spacing)

        super().__init__()

        self.component = component
        self.grid_spacing = grid_spacing

        self.stroke_path = QPainterPath()
        self.fill_path = QPainterPath()
        self.body_path = QPainterPath()
        self.label_side = LABEL_SIDES[0]
        self._bounding_rect = QRectF()

        # Selectable for the property panel, but never dragged by Qt: a
        # move must go through the collection's checked move (M2).
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setZValue(COMPONENT_Z_VALUE)

        self.label_item = ComponentLabelItem(self)

        self.refresh_from_component()

    def refresh_from_component(self):
        """
        Rebuild the paths, label and tooltip from the component.

        Call this after the component's rotation or value changes. The
        position is set by the scene.

        :returns: None
        """
        self.prepareGeometryChange()

        component = self.component
        transform = QTransform().rotate(component.rotation).scale(
            self.grid_spacing, self.grid_spacing
        )

        stroke_path, fill_path = build_symbol_paths(component.kind)
        body_path = QPainterPath()
        body_path.addRect(get_body_rect(component.kind))

        self.stroke_path = transform.map(stroke_path)
        self.fill_path = transform.map(fill_path)
        self.body_path = transform.map(body_path)

        self._bounding_rect = (
            self.stroke_path.boundingRect()
            .united(self.fill_path.boundingRect())
            .united(self.body_path.boundingRect())
            .adjusted(
                -BOUNDING_MARGIN, -BOUNDING_MARGIN,
                BOUNDING_MARGIN, BOUNDING_MARGIN
            )
        )

        self.refresh_label()
        self.setToolTip(self.build_tool_tip())
        self.update()

    def refresh_label(self):
        """
        Set the label text and put it on the first free side of the body.

        :returns: None
        """
        label_text = self.component.label_text()
        self.label_item.setText(label_text)
        self.label_item.setVisible(bool(label_text))

        self.label_side = choose_label_side(self.component.get_pin_offsets())

        body_rect = self.body_path.boundingRect()
        text_rect = self.label_item.text_rect()
        text_width = text_rect.width()
        text_height = text_rect.height()

        if self.label_side == "above":
            top_left = QPointF(
                body_rect.center().x() - text_width / 2.0,
                body_rect.top() - LABEL_GAP - text_height
            )
        elif self.label_side == "below":
            top_left = QPointF(
                body_rect.center().x() - text_width / 2.0,
                body_rect.bottom() + LABEL_GAP
            )
        elif self.label_side == "right":
            top_left = QPointF(
                body_rect.right() + LABEL_GAP,
                body_rect.center().y() - text_height / 2.0
            )
        else:
            top_left = QPointF(
                body_rect.left() - LABEL_GAP - text_width,
                body_rect.center().y() - text_height / 2.0
            )

        # text_rect() starts at (0, 0), so its top-left is the item position.
        self.label_item.setPos(top_left - text_rect.topLeft())

    def build_tool_tip(self):
        """
        Describe the part: kind, reference, value and the node under each pin.

        :returns: Multi-line tooltip text.
        :rtype: str
        """
        component = self.component
        definition = COMPONENT_DEFINITIONS[component.kind]
        lines = [f"{component.reference} ({definition['display_name']})"]

        if definition["value_kind"] != "none":
            lines.append(f"Value: {component.value_text}")

        pin_names = [name for name, unused_dx, unused_dy in
                     component.get_pin_offsets()]
        pin_identifiers = component.get_pin_identifiers()

        for pin_name, identifier in zip(pin_names, pin_identifiers):
            lines.append(f"{pin_name}: {identifier}")

        return "\n".join(lines)

    def boundingRect(self):
        """
        Return the area this item paints (the label paints itself).

        :returns: Stroke, fill and body rectangles united, plus a margin.
        :rtype: QRectF
        """
        return QRectF(self._bounding_rect)

    def shape(self):
        """
        Return only the body as the click area.

        Pins and the label are outside it, so clicks there reach the grid
        points underneath.

        :returns: Body path in item coordinates.
        :rtype: QPainterPath
        """
        return QPainterPath(self.body_path)

    def paint(self, painter, option, widget=None):
        """
        Hide the grid under the body, then draw the symbol.

        :param painter: Painter used to draw this item.
        :type painter: QPainter
        :param option: Qt style option for the graphics item.
        :type option: QStyleOptionGraphicsItem
        :param widget: Optional containing widget.
        :type widget: QWidget or None
        :returns: None
        """
        painter.save()

        painter.fillPath(self.body_path, QColor(BACKGROUND_COLOR))

        if self.isSelected():
            color = QColor(SELECTED_COLOR)
        else:
            color = QColor(SYMBOL_COLOR)

        pen = QPen(color, SYMBOL_PEN_WIDTH)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(self.stroke_path)
        painter.fillPath(self.fill_path, color)

        painter.restore()
