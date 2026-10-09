"""
QGraphicsItem that draws one placed component on the connection grid.

The item reads everything from a core.components.Component: the symbol is
built in pitch units by gui.component_symbols, then rotated and scaled to
pixels with QTransform().rotate(rotation).scale(spacing, spacing). Qt's
rotate() turns clockwise on screen (y points down), the same direction as
core.components.rotate_offset(), so the drawn leads end on the grid points
the model reports for the pins.

The item itself is never rotated, so its label stays upright. The click
area (shape) is only the symbol body, so the grid points under the pins and
under the label stay clickable.

Stacking (z values): label patches at LABEL_Z_VALUE (-0.5) are below the
grid points (0), which are below the parts (1). So a label never hides a
pin or a selected grid point, and a transistor's body still hides the dot
under its centre. One-step parts have their body between two grid points.
The scene (ConnectionGridScene.layout_component_labels) may move a label to
another candidate spot to keep it off neighbouring parts and labels. A
child item always stacks with its parent, so the label is a separate
top-level scene item: ComponentItem adds it to, and removes it from, the
scene with itself and keeps it next to itself when moved.

This module must not import gui.grid_editor (the scene will import this
module). The scene sets the item position.

Drag to move: Qt's own ItemIsMovable is off, because a move must go through
the collection's checked move. Instead the item follows the mouse once a
left-button drag passes the platform drag distance, and on release asks the
scene (handle_component_drop) to snap it to the nearest grid point. The
scene moves the part through ComponentCollection.move_component, or puts it
back when the move is refused. A plain click still just selects.
"""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QColor,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QTransform,
)
from PyQt5.QtWidgets import (
    QApplication,
    QGraphicsItem,
    QGraphicsSimpleTextItem,
)

from core.components import (
    COMPONENT_DEFINITIONS,
    Component,
    get_panel_parameter_definitions,
)
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
# A part being dragged draws above the others.
DRAGGED_COMPONENT_Z_VALUE = 2
LABEL_Z_VALUE = -0.5
# The label may move this close to the body to keep its text off a dot.
MIN_LABEL_GAP = 2
# Half the grid dot (16 px) plus its 1 px outline; matches
# gui.grid_editor.CONNECTION_POINT_DIAMETER (not imported, see above).
LABEL_DOT_CLEARANCE = 9

# Sides tried for the label, in order. The first side that no pin points
# toward wins; if every side has a pin, the label goes above.
LABEL_SIDES = ("above", "right", "below", "left")

# Label candidates for the scene's collision-aware layout: the normal spot
# first, then moved along the side in half grid steps (up to 2 each way).
LABEL_NUDGES = (0, -1, 1, -2, 2)


def pin_direction(dx, dy):
    """
    Return the side a rotated pin offset points toward.

    A diagonal offset (|dx| == |dy|) counts as above or below. An offset of
    (0, 0), like the ground pin, points nowhere.

    :param dx: Column offset in grid steps (positive is right).
    :type dx: int or float
    :param dy: Row offset in grid steps (positive is down).
    :type dy: int or float
    :returns: "above", "right", "below", "left", or None.
    :rtype: str or None
    """
    if dx == 0 and dy == 0:
        return None

    if abs(dy) >= abs(dx):
        return "above" if dy < 0 else "below"

    return "right" if dx > 0 else "left"


def choose_label_side(pin_offsets, body_center=(0, 0)):
    """
    Pick the first side in LABEL_SIDES that no pin points toward.

    :param pin_offsets: Rotated pins as (pin_name, dx, dy).
    :type pin_offsets: list
    :param body_center: Rotated body centre (dx, dy) from the anchor.
    :type body_center: tuple
    :returns: "above", "right", "below", or "left".
    :rtype: str
    """
    return free_label_sides(pin_offsets, body_center)[0]


def free_label_sides(pin_offsets, body_center=(0, 0)):
    """
    Return the sides in LABEL_SIDES order that no pin points toward.

    Directions are taken from the body centre, not the anchor: a two-pin
    part's anchor is its first pin, so from the anchor that pin would
    point nowhere.

    :param pin_offsets: Rotated pins as (pin_name, dx, dy).
    :type pin_offsets: list
    :param body_center: Rotated body centre (dx, dy) from the anchor.
    :type body_center: tuple
    :returns: Free sides; ["above"] if every side has a pin.
    :rtype: list
    """
    center_dx, center_dy = body_center
    blocked_sides = {
        pin_direction(dx - center_dx, dy - center_dy)
        for unused_name, dx, dy in pin_offsets
    }
    free_sides = [side for side in LABEL_SIDES if side not in blocked_sides]

    return free_sides or [LABEL_SIDES[0]]


def snap_between_rows(center_y, grid_spacing):
    """
    Return the middle of the gap between grid rows nearest to center_y.

    Rows are at multiples of grid_spacing from the anchor, so the gap
    middles are at odd multiples of grid_spacing / 2. On a tie (center_y
    on a row) the upper gap wins.

    :param center_y: Label center relative to the anchor, in pixels.
    :type center_y: float
    :param grid_spacing: Pixels between grid rows.
    :type grid_spacing: float
    :returns: The middle of the nearest gap.
    :rtype: float
    """
    half_step = grid_spacing / 2.0
    upper_gap = (math.ceil((center_y - half_step) / grid_spacing)
                 * grid_spacing) - half_step

    if center_y - upper_gap <= half_step:
        return upper_gap

    return upper_gap + grid_spacing


def fit_between_rows(center_y, text_height, grid_spacing, low=None,
                     high=None):
    """
    Shift a label center so its text stays clear of the grid dot rows.

    The text is moved by the smallest amount that keeps it inside the
    dot-free band of the row gap that contains center_y. The move is not
    made if the result would leave [low, high] (too close to the body) or
    if the text is taller than the band; center_y is then returned.

    :param center_y: Preferred label center relative to the anchor.
    :type center_y: float
    :param text_height: Height of the text in pixels.
    :type text_height: float
    :param grid_spacing: Pixels between grid rows.
    :type grid_spacing: float
    :param low: Smallest allowed center, or None.
    :type low: float or None
    :param high: Largest allowed center, or None.
    :type high: float or None
    :returns: The adjusted center.
    :rtype: float
    """
    half_height = text_height / 2.0
    gap_index = math.floor(center_y / grid_spacing)
    band_top = (gap_index * grid_spacing) + LABEL_DOT_CLEARANCE
    band_bottom = ((gap_index + 1) * grid_spacing) - LABEL_DOT_CLEARANCE

    if text_height > band_bottom - band_top:
        return center_y

    fitted = min(max(center_y, band_top + half_height),
                 band_bottom - half_height)

    if (low is not None and fitted < low) or (high is not None and
                                                 fitted > high):
        return center_y

    return fitted


def text_touches_a_grid_dot(text_rect, grid_spacing):
    """
    Check whether a rectangle (relative to the anchor) overlaps a grid dot.

    The anchor is a grid point, so grid points are at whole multiples of
    grid_spacing in both directions.

    :param text_rect: Text rectangle in item coordinates.
    :type text_rect: QRectF
    :param grid_spacing: Pixels between grid points.
    :type grid_spacing: float
    :returns: True if any dot (with its outline) overlaps the rectangle.
    :rtype: bool
    """
    clearance = LABEL_DOT_CLEARANCE
    first_column = math.floor((text_rect.left() - clearance) / grid_spacing)
    last_column = math.ceil((text_rect.right() + clearance) / grid_spacing)
    first_row = math.floor((text_rect.top() - clearance) / grid_spacing)
    last_row = math.ceil((text_rect.bottom() + clearance) / grid_spacing)

    for column in range(first_column, last_column + 1):
        for row in range(first_row, last_row + 1):
            dot_rect = QRectF(
                column * grid_spacing - clearance,
                row * grid_spacing - clearance,
                2 * clearance,
                2 * clearance
            )

            if text_rect.intersects(dot_rect):
                return True

    return False


def _validate_grid_spacing(grid_spacing):
    """
    Check that the grid spacing is a positive number of pixels.

    :param grid_spacing: Pixels between neighboring grid points.
    :type grid_spacing: int or float
    :returns: None
    :raises ComponentError: If the spacing is not a positive, finite
        number (inf would make every path and rect infinite or NaN).
    """
    if (isinstance(grid_spacing, bool) or
            not isinstance(grid_spacing, (int, float)) or
            not math.isfinite(grid_spacing) or
            grid_spacing <= 0):
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
        self.setZValue(LABEL_Z_VALUE)

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
        # Everything this part draws, as an area: the label layout keeps
        # other labels' text off it.
        self.obstacle_path = QPainterPath()
        self.label_side = LABEL_SIDES[0]
        self.label_offset = QPointF()
        self._bounding_rect = QRectF()

        # Selectable for the property panel, but never dragged by Qt: a
        # move must go through the collection's checked move (see the
        # mouse handlers below).
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        # Needed for ItemPositionHasChanged, which moves the label along.
        self.setFlag(self.ItemSendsGeometryChanges, True)
        self.setZValue(COMPONENT_Z_VALUE)

        # Not a child (see the module docstring). This item keeps the only
        # Python reference and puts the label in its scene in itemChange().
        self.label_item = ComponentLabelItem()

        # Item position when the left button went down, and whether the
        # press has become a drag.
        self.drag_start_position = None
        self.is_dragging = False

        self.refresh_from_component()

    def mousePressEvent(self, event):
        """
        Select the part as usual and remember where a drag would start.

        :param event: Scene mouse event.
        :type event: QGraphicsSceneMouseEvent
        :returns: None
        """
        self.is_dragging = False
        self.drag_start_position = None

        if event.button() == Qt.LeftButton:
            self.drag_start_position = QPointF(self.pos())

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Follow the mouse once the press has moved past the drag distance.

        :param event: Scene mouse event.
        :type event: QGraphicsSceneMouseEvent
        :returns: None
        """
        if (self.drag_start_position is None or
                not event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return

        if not self.is_dragging:
            moved_distance = (
                event.screenPos() - event.buttonDownScreenPos(Qt.LeftButton)
            ).manhattanLength()

            if moved_distance < QApplication.startDragDistance():
                return

            self.is_dragging = True
            self.setZValue(DRAGGED_COMPONENT_Z_VALUE)

        self.setPos(
            self.drag_start_position +
            event.scenePos() -
            event.buttonDownScenePos(Qt.LeftButton)
        )

    def mouseReleaseEvent(self, event):
        """
        End a drag: the scene snaps the part to a grid point or puts it back.

        :param event: Scene mouse event.
        :type event: QGraphicsSceneMouseEvent
        :returns: None
        """
        if not (self.is_dragging and event.button() == Qt.LeftButton):
            self.drag_start_position = None
            self.is_dragging = False
            super().mouseReleaseEvent(event)
            return

        start_position = self.drag_start_position
        self.drag_start_position = None
        self.is_dragging = False
        self.setZValue(COMPONENT_Z_VALUE)
        event.accept()

        scene = self.scene()

        if scene is not None and hasattr(scene, "handle_component_drop"):
            scene.handle_component_drop(self.component.reference, self.pos())
        else:
            self.setPos(start_position)

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

        stroker = QPainterPathStroker()
        stroker.setWidth(SYMBOL_PEN_WIDTH)
        stroker.setCapStyle(Qt.RoundCap)
        self.obstacle_path = (
            stroker.createStroke(self.stroke_path)
            .united(self.fill_path)
            .united(self.body_path)
        )

        self._bounding_rect = (
            self.stroke_path.boundingRect()
            .united(self.fill_path.boundingRect())
            .united(self.body_path.boundingRect())
            .adjusted(
                -BOUNDING_MARGIN, -BOUNDING_MARGIN,
                BOUNDING_MARGIN, BOUNDING_MARGIN
            )
        )

        # prepareGeometryChange() above already schedules the repaint.
        self.refresh_label()
        self.setToolTip(self.build_tool_tip())

    def refresh_label(self):
        """
        Set the label text and put it beside the body.

        The side is the first one, in LABEL_SIDES order, that no pin points
        toward and where the text stays off every grid dot. If no free side
        keeps the text off the dots, the first free side is used. Grid dots
        draw above labels, so this keeps the text readable.

        Right and left labels are centered on the gap between grid rows
        nearest the body's center. Above and below labels sit LABEL_GAP
        from the body, moving to as little as MIN_LABEL_GAP to stay between
        the rows.

        :returns: None
        """
        label_text = self.component.label_text()
        self.label_item.setText(label_text)
        self.label_item.setVisible(bool(label_text))

        text_rect = self.label_item.text_rect()
        free_sides = free_label_sides(
            self.component.get_pin_offsets(),
            self.component.get_body_center_offset()
        )
        placements = [
            (side, self.get_label_top_left(side, text_rect))
            for side in free_sides
        ]

        self.label_side, top_left = placements[0]

        for side, candidate_top_left in placements:
            candidate_rect = QRectF(candidate_top_left, text_rect.size())

            if not text_touches_a_grid_dot(candidate_rect, self.grid_spacing):
                self.label_side, top_left = side, candidate_top_left
                break

        self.label_offset = top_left - text_rect.topLeft()
        self.place_label()

    def get_label_candidates(self):
        """
        Return every place the scene's label layout may put the text.

        Each free side (no pin points to it) at its normal spot, then moved
        along the side in half grid steps (LABEL_NUDGES): sideways for
        above and below labels, up and down for right and left labels.

        :returns: (side, nudge, top_left) tuples, with top_left in item
            coordinates and nudge in half steps.
        :rtype: list
        """
        text_rect = self.label_item.text_rect()
        half_step = self.grid_spacing / 2.0
        candidates = []

        for side in free_label_sides(
                self.component.get_pin_offsets(),
                self.component.get_body_center_offset()):
            normal_top_left = self.get_label_top_left(side, text_rect)

            for nudge in LABEL_NUDGES:
                if side in ("above", "below"):
                    shift = QPointF(nudge * half_step, 0.0)
                else:
                    shift = QPointF(0.0, nudge * half_step)

                candidates.append((side, nudge, normal_top_left + shift))

        return candidates

    def apply_label_placement(self, side, top_left):
        """
        Put the label text's top-left corner at a chosen spot.

        :param side: Side the spot belongs to.
        :type side: str
        :param top_left: Text top-left corner in item coordinates.
        :type top_left: QPointF
        :returns: None
        """
        self.label_side = side
        self.label_offset = top_left - self.label_item.text_rect().topLeft()
        self.place_label()

    def get_label_top_left(self, side, text_rect):
        """
        Return where the text's top-left corner goes for one side.

        :param side: "above", "right", "below" or "left".
        :type side: str
        :param text_rect: The label's text rectangle (for its size).
        :type text_rect: QRectF
        :returns: Top-left corner in item coordinates.
        :rtype: QPointF
        """
        body_rect = self.body_path.boundingRect()
        text_width = text_rect.width()
        text_height = text_rect.height()
        half_height = text_height / 2.0
        spacing = self.grid_spacing

        if side == "above":
            center_y = fit_between_rows(
                body_rect.top() - LABEL_GAP - half_height,
                text_height,
                spacing,
                high=body_rect.top() - MIN_LABEL_GAP - half_height
            )
            left_x = body_rect.center().x() - text_width / 2.0
        elif side == "below":
            center_y = fit_between_rows(
                body_rect.bottom() + LABEL_GAP + half_height,
                text_height,
                spacing,
                low=body_rect.bottom() + MIN_LABEL_GAP + half_height
            )
            left_x = body_rect.center().x() - text_width / 2.0
        else:
            center_y = snap_between_rows(body_rect.center().y(), spacing)

            if side == "right":
                left_x = body_rect.right() + LABEL_GAP
            else:
                left_x = body_rect.left() - LABEL_GAP - text_width

        return QPointF(left_x, center_y - half_height)

    def place_label(self):
        """
        Put the label at this item's position plus its offset.

        The label is a top-level item, so its position is in scene
        coordinates, the same as this (top-level) item's position.

        :returns: None
        """
        self.label_item.setPos(self.pos() + self.label_offset)

    def itemChange(self, change, value):
        """
        Keep the separate label in the same scene and next to this item.

        :param change: What is changing.
        :type change: QGraphicsItem.GraphicsItemChange
        :param value: The new value.
        :returns: The value Qt should use.
        """
        if change == self.ItemSceneChange:
            old_scene = self.scene()

            if old_scene is not None and self.label_item.scene() is old_scene:
                old_scene.removeItem(self.label_item)
        elif change == self.ItemSceneHasChanged:
            if value is not None and self.label_item.scene() is not value:
                value.addItem(self.label_item)
        elif change == self.ItemPositionHasChanged:
            self.place_label()

        return super().itemChange(change, value)

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
            value_label = definition.get("value_label", "Value")
            value_unit = definition.get("value_unit", "")
            lines.append(f"{value_label}: {component.value_text}{value_unit}")

        for parameter in get_panel_parameter_definitions(component.kind):
            lines.append(
                f"{parameter['display_name']}: "
                f"{component.parameter_texts[parameter['name']]}"
                f"{parameter['unit']}"
            )

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
