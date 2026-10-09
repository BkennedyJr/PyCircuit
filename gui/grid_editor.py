"""
PyQt5 graphics-scene classes for the connection-grid editor.

This module draws and manages selectable connection points, the placed
parts and the wires. In Wire mode a left press on a grid point starts a
wire: a dashed rubber-band line follows the mouse, and releasing on another
grid point adds a straight wire between the two points (Esc cancels). Out
of Wire mode, presses behave as before (select, rubber-band select, drag a
part). It remains separate from the core data model so future command-line or test workflows
can use the connection-grid model without importing PyQt5.
"""

import math

from PyQt5 import sip
from PyQt5.QtCore import QPointF
from PyQt5.QtCore import QRectF
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from PyQt5.QtGui import QPainter
from PyQt5.QtGui import QPen
from PyQt5.QtCore import QLineF
from PyQt5.QtWidgets import QGraphicsEllipseItem
from PyQt5.QtWidgets import QGraphicsLineItem
from PyQt5.QtWidgets import QGraphicsScene
from PyQt5.QtWidgets import QGraphicsSimpleTextItem
from PyQt5.QtWidgets import QGraphicsView

from core.exceptions import ComponentError
from core.wires import find_junction_identifiers
from gui.component_item import (
    LABEL_PATCH_PADDING,
    LABEL_SIDES,
    ComponentItem,
    text_touches_a_grid_dot,
)
from gui.wire_item import WIRE_COLOR, WireItem, build_preview_pen

GRID_POINT_SPACING = 60
GRID_ORIGIN_X = 90
GRID_ORIGIN_Y = 80
CONNECTION_POINT_DIAMETER = 16
# Grid points stack above component labels (-0.5) and below parts (1).
CONNECTION_POINT_Z_VALUE = 0
# Default header positions: column headers at this y, row headers at this x.
HEADER_POSITION = 25
# Space kept between the headers and any part or label.
HEADER_GAP = 8
# Extra room around everything when the scene grows to fit the parts.
SCENE_MARGIN = 20
# In Wire mode a press or release counts as "on" a grid point within this
# distance of its centre (a third of a step: generous, never ambiguous).
WIRE_SNAP_DISTANCE = 20
# The rubber-band line draws above everything while a wire is drawn.
WIRE_PREVIEW_Z_VALUE = 3
# Junction dots (core.wires.find_junction_identifiers) sit on top of the
# grid dot, in the wire color, below the parts.
JUNCTION_DIAMETER = 14
JUNCTION_Z_VALUE = 0.5


def grid_point_to_scene_position(row_number, column_number):
    """
    Return the scene position of a grid point (1-based row and column).

    Same formula as ConnectionGridScene.rebuild_connection_point_items.

    :param row_number: Row of the grid point.
    :type row_number: int
    :param column_number: Column of the grid point.
    :type column_number: int
    :returns: Scene position of the point's center.
    :rtype: QPointF
    """
    return QPointF(
        GRID_ORIGIN_X + ((column_number - 1) * GRID_POINT_SPACING),
        GRID_ORIGIN_Y + ((row_number - 1) * GRID_POINT_SPACING)
    )


def scene_position_to_grid_point(scene_position):
    """
    Return the (row, column) of the grid point nearest a scene position.

    The result may lie outside the grid (for example row 0); callers check.
    Halves round up, so the result does not depend on banker's rounding.

    :param scene_position: Position in scene coordinates.
    :type scene_position: QPointF
    :returns: One-based (row, column).
    :rtype: tuple
    """
    column_number = math.floor(
        (scene_position.x() - GRID_ORIGIN_X) / GRID_POINT_SPACING + 0.5
    ) + 1
    row_number = math.floor(
        (scene_position.y() - GRID_ORIGIN_Y) / GRID_POINT_SPACING + 0.5
    ) + 1

    return (row_number, column_number)


class ConnectionPointItem(QGraphicsEllipseItem):
    """
    Graphical representation of one selectable connection point.

    :param connection_point: Core-model connection point to display.
    :type connection_point: core.connection_grid.ConnectionPoint
    """

    def __init__(self, connection_point):
        radius = CONNECTION_POINT_DIAMETER / 2.0

        super(ConnectionPointItem, self).__init__(
            -radius,
            -radius,
            CONNECTION_POINT_DIAMETER,
            CONNECTION_POINT_DIAMETER
        )

        self.connection_point = connection_point

        # Enable normal Qt selection behavior while preventing accidental
        # movement of fixed grid points.
        self.setFlag(self.ItemIsSelectable, True)
        self.setFlag(self.ItemIsMovable, False)
        self.setZValue(CONNECTION_POINT_Z_VALUE)

        self.setToolTip(
            "{}\nRow: {}\nColumn: {}".format(
                connection_point.identifier,
                connection_point.row_number,
                connection_point.column_number
            )
        )

    def paint(self, painter, option, widget=None):
        """
        Draw the connection point according to its selection state.

        Blue points are available grid nodes. Green points are selected as
        signal pickoffs. Yellow outlines indicate the actively selected node.

        :param painter: Painter used to draw this item.
        :type painter: QPainter
        :param option: Qt style option for the graphics item.
        :type option: QStyleOptionGraphicsItem
        :param widget: Optional containing widget.
        :type widget: QWidget or None
        :returns: None
        """
        painter.save()

        # Highlight a selected point without changing its underlying pickoff
        # status. This distinguishes inspection from analysis selection.
        if self.isSelected():
            painter.setPen(QPen(QColor("#ffd166"), 3))
        else:
            painter.setPen(QPen(QColor("#102a43"), 2))

        # Use green to indicate that simulation output should later be
        # collected from this connection point.
        if self.connection_point.is_signal_pickoff:
            painter.setBrush(QColor("#4caf50"))
        else:
            painter.setBrush(QColor("#4f9ee3"))

        painter.drawEllipse(self.rect())
        painter.restore()


class ConnectionGridScene(QGraphicsScene):
    """
    Graphics scene that displays the configurable connection-point grid.

    :param connection_grid: Core-model grid to display.
    :type connection_grid: core.connection_grid.ConnectionGrid
    :param parent: Optional Qt parent object.
    :type parent: QObject or None
    """

    connection_point_selected = pyqtSignal(object)
    component_selected = pyqtSignal(object)
    # A dragged part was moved (reference), or its move was refused
    # (reference, reason); in both cases it is already drawn in place.
    component_moved = pyqtSignal(str)
    component_move_refused = pyqtSignal(str, str)
    # A wire was drawn (reference) or refused (reason). wires_selected
    # carries the references of the selected wires (possibly empty).
    wire_added = pyqtSignal(str)
    wire_refused = pyqtSignal(str)
    wires_selected = pyqtSignal(object)

    def __init__(self, connection_grid, parent=None):
        super(ConnectionGridScene, self).__init__(parent)

        self.connection_grid = None
        self.connection_point_items_by_identifier = {}
        self.component_collection = None
        self.component_items_by_reference = {}
        self.wire_collection = None
        self.wire_items_by_reference = {}
        self.junction_items_by_identifier = {}
        self.column_header_items = []
        self.row_header_items = []

        # Wire drawing: the mode flag, the grid point where the current
        # drag started (None when not drawing) and the rubber-band line.
        self.is_wire_mode = False
        self.wire_start_identifier = None
        self.wire_preview_item = None

        # Report selection changes to the main window so it can update the
        # selected-node panel and signal-pickoff controls.
        self.selectionChanged.connect(
            self.handle_connection_point_selection_change
        )

        self.set_connection_grid(connection_grid)

    def set_connection_grid(self, connection_grid):
        """
        Replace the displayed connection grid with a validated model.

        :param connection_grid: New grid model to display.
        :type connection_grid: core.connection_grid.ConnectionGrid
        :returns: None
        """
        self.connection_grid = connection_grid
        self.rebuild_connection_point_items()

    def rebuild_connection_point_items(self):
        """
        Rebuild graphical labels and points from the active grid model.

        The previous graphical items are cleared only after the core model
        has already been validated by the caller.

        :returns: None
        """
        self.clear()
        self.connection_point_items_by_identifier = {}
        self.column_header_items = []
        self.row_header_items = []

        row_count = self.connection_grid.row_count
        column_count = self.connection_grid.column_count

        grid_width = (column_count - 1) * GRID_POINT_SPACING
        grid_height = (row_count - 1) * GRID_POINT_SPACING

        # Define a scene rectangle large enough for labels, points, and
        # future components that will be placed adjacent to the grid.
        self.setSceneRect(
            0,
            0,
            GRID_ORIGIN_X + grid_width + 100,
            GRID_ORIGIN_Y + grid_height + 100
        )

        # Add column labels to make the point-coordinate system readable.
        for column_number in range(1, column_count + 1):
            column_label = QGraphicsSimpleTextItem(
                "C{}".format(column_number)
            )
            column_label.setBrush(QColor("#d9e2ec"))
            column_label.setPos(
                GRID_ORIGIN_X +
                ((column_number - 1) * GRID_POINT_SPACING) - 10,
                25
            )
            self.addItem(column_label)
            self.column_header_items.append(column_label)

        # Add row labels to make point selection understandable without
        # requiring users to infer grid coordinates from visual location.
        for row_number in range(1, row_count + 1):
            row_label = QGraphicsSimpleTextItem(
                "R{}".format(row_number)
            )
            row_label.setBrush(QColor("#d9e2ec"))
            row_label.setPos(
                25,
                GRID_ORIGIN_Y +
                ((row_number - 1) * GRID_POINT_SPACING) - 10
            )
            self.addItem(row_label)
            self.row_header_items.append(row_label)

        # Create one visible selectable item for every core-model point.
        for connection_point in (
                self.connection_grid.connection_points_by_identifier.values()):
            point_x_position = (
                GRID_ORIGIN_X +
                ((connection_point.column_number - 1) * GRID_POINT_SPACING)
            )
            point_y_position = (
                GRID_ORIGIN_Y +
                ((connection_point.row_number - 1) * GRID_POINT_SPACING)
            )

            connection_point_item = ConnectionPointItem(connection_point)
            connection_point_item.setPos(
                QPointF(point_x_position, point_y_position)
            )

            self.addItem(connection_point_item)

            self.connection_point_items_by_identifier[
                connection_point.identifier
            ] = connection_point_item

        # clear() above already deleted the old component items, labels,
        # wires and any rubber-band line.
        self.component_items_by_reference = {}
        self.wire_items_by_reference = {}
        self.junction_items_by_identifier = {}
        self.wire_start_identifier = None
        self.wire_preview_item = None
        self.rebuild_wire_items()
        self.rebuild_component_items()

        # Clear the selected-node display after a rebuild because old item
        # references are no longer valid once the scene has been cleared.
        self.connection_point_selected.emit(None)

    def set_component_collection(self, component_collection):
        """
        Show the parts of a component collection on the grid.

        :param component_collection: Parts to display, or None for none.
        :type component_collection: core.components.ComponentCollection
        :returns: None
        """
        self.component_collection = component_collection
        self.rebuild_component_items()

    def rebuild_component_items(self):
        """
        Replace every component item with fresh ones from the collection.

        :returns: None
        """
        for component_item in self.component_items_by_reference.values():
            # Skip items Qt already deleted (for example by clear()).
            if (not sip.isdeleted(component_item) and
                    component_item.scene() is self):
                self.removeItem(component_item)

        self.component_items_by_reference = {}

        if self.component_collection is not None:
            for component in self.component_collection.get_components():
                component_item = ComponentItem(component, GRID_POINT_SPACING)
                component_item.setPos(
                    grid_point_to_scene_position(
                        component.row_number,
                        component.column_number
                    )
                )
                self.addItem(component_item)

                self.component_items_by_reference[
                    component.reference
                ] = component_item

        self.layout_component_labels()
        self.rebuild_junction_items()
        self.update_scene_extent()

    def refresh_component(self, reference):
        """
        Redraw one part after its rotation, value or position changed.

        :param reference: Reference of the part, for example "R1".
        :type reference: str
        :returns: None
        """
        component_item = self.component_items_by_reference.get(reference)

        if component_item is None:
            return

        component_item.refresh_from_component()
        component_item.setPos(
            grid_point_to_scene_position(
                component_item.component.row_number,
                component_item.component.column_number
            )
        )
        # A turn or a longer value can change the best spot for the
        # neighbours' labels too, so lay out every label again.
        self.layout_component_labels()
        # A moved or turned pin can start or stop meeting a wire.
        self.rebuild_junction_items()
        self.update_scene_extent()

    def set_wire_collection(self, wire_collection):
        """
        Show the wires of a wire collection on the grid.

        :param wire_collection: Wires to display, or None for none.
        :type wire_collection: core.wires.WireCollection
        :returns: None
        """
        self.wire_collection = wire_collection
        self.rebuild_wire_items()

    def rebuild_wire_items(self):
        """
        Replace every wire item with fresh ones from the collection.

        :returns: None
        """
        for wire_item in self.wire_items_by_reference.values():
            if not sip.isdeleted(wire_item) and wire_item.scene() is self:
                self.removeItem(wire_item)

        self.wire_items_by_reference = {}

        if self.wire_collection is not None:
            for wire in self.wire_collection.get_wires():
                wire_item = WireItem(
                    wire,
                    grid_point_to_scene_position(*wire.start_point),
                    grid_point_to_scene_position(*wire.end_point)
                )
                self.addItem(wire_item)
                self.wire_items_by_reference[wire.reference] = wire_item

        self.rebuild_junction_items()

    def rebuild_junction_items(self):
        """
        Draw a junction dot wherever three or more connections meet.

        Wires connect every point they cover (breadboard strips), so a dot
        shows where a wire passes a part pin or meets another wire
        mid-span. The dots ignore the mouse: a click reaches the grid
        point underneath.

        :returns: None
        """
        for junction_item in self.junction_items_by_identifier.values():
            if (not sip.isdeleted(junction_item) and
                    junction_item.scene() is self):
                self.removeItem(junction_item)

        self.junction_items_by_identifier = {}

        if self.wire_collection is None:
            return

        pin_identifiers = []

        if self.component_collection is not None:
            for component in self.component_collection.get_components():
                pin_identifiers.extend(component.get_pin_identifiers())

        # Junctions are always on a wire, so the wires give their points.
        point_by_identifier = {}

        for wire in self.wire_collection.get_wires():
            point_by_identifier.update(
                zip(wire.get_point_identifiers(), wire.get_points())
            )

        for identifier in find_junction_identifiers(
                self.wire_collection, pin_identifiers):
            center = grid_point_to_scene_position(
                *point_by_identifier[identifier]
            )
            radius = JUNCTION_DIAMETER / 2
            junction_item = QGraphicsEllipseItem(
                center.x() - radius, center.y() - radius,
                JUNCTION_DIAMETER, JUNCTION_DIAMETER
            )
            junction_item.setBrush(QColor(WIRE_COLOR))
            junction_item.setPen(QPen(Qt.NoPen))
            junction_item.setZValue(JUNCTION_Z_VALUE)
            junction_item.setAcceptedMouseButtons(Qt.NoButton)
            self.addItem(junction_item)
            self.junction_items_by_identifier[identifier] = junction_item

    def set_wire_mode(self, is_wire_mode):
        """
        Switch Wire mode on or off; switching off cancels a wire in progress.

        :param is_wire_mode: True to draw wires on press-drag.
        :type is_wire_mode: bool
        :returns: None
        """
        self.is_wire_mode = bool(is_wire_mode)

        if not self.is_wire_mode:
            self.cancel_wire_drawing()

    def find_grid_point_near(self, scene_position):
        """
        Return the identifier of the grid point within WIRE_SNAP_DISTANCE.

        :param scene_position: Position in scene coordinates.
        :type scene_position: QPointF
        :returns: Identifier such as "NODE_R02_C03", or None when no grid
            point of the current grid is that close.
        :rtype: str or None
        """
        row_number, column_number = scene_position_to_grid_point(
            scene_position
        )

        if not (1 <= row_number <= self.connection_grid.row_count and
                1 <= column_number <= self.connection_grid.column_count):
            return None

        center = grid_point_to_scene_position(row_number, column_number)

        if QLineF(center, scene_position).length() > WIRE_SNAP_DISTANCE:
            return None

        return self.connection_grid.build_connection_point_identifier(
            row_number,
            column_number
        )

    def get_connection_point_position(self, identifier):
        """
        Return the scene position of a grid point by identifier.

        :rtype: QPointF
        """
        connection_point = self.connection_grid.get_connection_point(
            identifier
        )

        return grid_point_to_scene_position(
            connection_point.row_number,
            connection_point.column_number
        )

    def start_wire_drawing(self, identifier):
        """
        Begin a wire at a grid point and show the rubber-band line.

        :param identifier: Start grid point.
        :type identifier: str
        :returns: None
        """
        self.cancel_wire_drawing()
        start_position = self.get_connection_point_position(identifier)

        self.wire_start_identifier = identifier
        self.wire_preview_item = QGraphicsLineItem(
            QLineF(start_position, start_position)
        )
        self.wire_preview_item.setPen(build_preview_pen())
        self.wire_preview_item.setZValue(WIRE_PREVIEW_Z_VALUE)
        # The preview never takes clicks.
        self.wire_preview_item.setAcceptedMouseButtons(Qt.NoButton)
        self.addItem(self.wire_preview_item)

    def update_wire_drawing(self, scene_position):
        """
        Stretch the rubber-band line to the mouse.

        :param scene_position: Mouse position in scene coordinates.
        :type scene_position: QPointF
        :returns: None
        """
        if self.wire_preview_item is None:
            return

        line = self.wire_preview_item.line()
        self.wire_preview_item.setLine(QLineF(line.p1(), scene_position))

    def cancel_wire_drawing(self):
        """
        Stop drawing and remove the rubber-band line, if any.

        :returns: None
        """
        if (self.wire_preview_item is not None and
                not sip.isdeleted(self.wire_preview_item) and
                self.wire_preview_item.scene() is self):
            self.removeItem(self.wire_preview_item)

        self.wire_preview_item = None
        self.wire_start_identifier = None

    def finish_wire_drawing(self, scene_position):
        """
        Add a wire from the start point to the grid point under the mouse.

        Releasing on the start point (a click) cancels quietly. Releasing
        away from any grid point, or a wire the collection refuses, emits
        wire_refused with the reason.

        :param scene_position: Release position in scene coordinates.
        :type scene_position: QPointF
        :returns: None
        """
        start_identifier = self.wire_start_identifier
        self.cancel_wire_drawing()

        if start_identifier is None or self.wire_collection is None:
            return

        end_identifier = self.find_grid_point_near(scene_position)

        if end_identifier == start_identifier:
            return

        if end_identifier is None:
            self.wire_refused.emit(
                f"release on a grid point to finish the wire from "
                f"{start_identifier}."
            )
            return

        try:
            wire = self.wire_collection.add_wire(
                start_identifier,
                end_identifier,
                self.connection_grid
            )
        except ComponentError as error:
            self.wire_refused.emit(str(error))
            return

        self.rebuild_wire_items()
        self.wire_added.emit(wire.reference)

    def mousePressEvent(self, event):
        """
        In Wire mode, a left press on a grid point starts a wire.

        Every other press (and any press out of Wire mode) goes to the
        items as usual: select, rubber-band select or drag a part.

        :param event: Scene mouse event.
        :type event: QGraphicsSceneMouseEvent
        :returns: None
        """
        if self.is_wire_mode and event.button() == Qt.LeftButton:
            identifier = self.find_grid_point_near(event.scenePos())

            if identifier is not None:
                self.start_wire_drawing(identifier)
                event.accept()
                return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Stretch the rubber-band line while a wire is being drawn.
        """
        if self.wire_start_identifier is not None:
            self.update_wire_drawing(event.scenePos())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """
        Finish a wire on left release.
        """
        if (self.wire_start_identifier is not None and
                event.button() == Qt.LeftButton):
            self.finish_wire_drawing(event.scenePos())
            event.accept()
            return

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        """
        Esc cancels a wire being drawn.
        """
        if (event.key() == Qt.Key_Escape and
                self.wire_start_identifier is not None):
            self.cancel_wire_drawing()
            event.accept()
            return

        super().keyPressEvent(event)

    def handle_component_drop(self, reference, anchor_position):
        """
        Finish a part drag: snap to the nearest grid point, or put it back.

        The move goes through ComponentCollection.move_component, which
        refuses off-grid and overlapping moves. Dropping on the part's own
        grid point just puts it back, with no signal.

        :param reference: Part that was dragged.
        :type reference: str
        :param anchor_position: Where the part's anchor was dropped, in
            scene coordinates.
        :type anchor_position: QPointF
        :returns: None
        """
        if self.component_collection is None:
            return

        row_number, column_number = scene_position_to_grid_point(
            anchor_position
        )
        component = self.component_collection.get_component(reference)

        if (row_number, column_number) == (
                component.row_number, component.column_number):
            self.refresh_component(reference)
            return

        try:
            self.component_collection.move_component(
                reference,
                row_number,
                column_number,
                self.connection_grid
            )
        except ComponentError as error:
            # refresh_component puts the item back at the model position.
            self.refresh_component(reference)
            self.component_move_refused.emit(reference, str(error))
            return

        self.refresh_component(reference)
        self.component_moved.emit(reference)

    def layout_component_labels(self):
        """
        Place every part's label where it is easiest to read.

        One-step parts sit side by side, so a label wider than a grid step
        would run into its neighbour's label or symbol. Each label (in
        reference order) takes the lowest-scoring candidate from
        ComponentItem.get_label_candidates(), compared worst problem first:

        1. the text crosses a part's symbol or body (unreadable, because
           parts draw above labels);
        2. the text, with its patch, overlaps a label placed before it;
        3. the text touches a grid dot (a few letters under a dot);
        4. how far it was moved from the side's normal spot;
        5. side order: above, right, below, left.

        With no neighbours this gives the single-part rule of
        ComponentItem.refresh_label().

        :returns: None
        """
        component_items = [
            component_item
            for component_item in self.component_items_by_reference.values()
            if component_item.scene() is self
        ]
        obstacles = [
            component_item.obstacle_path.translated(component_item.pos())
            for component_item in component_items
        ]
        obstacle_rects = [path.boundingRect() for path in obstacles]
        placed_label_rects = []

        for component_item in component_items:
            if not component_item.label_item.isVisible():
                continue

            text_size = component_item.label_item.text_rect().size()
            best_score = None
            best_placement = None

            for side, nudge, top_left in (
                    component_item.get_label_candidates()):
                item_rect = QRectF(top_left, text_size)
                scene_rect = item_rect.translated(component_item.pos())
                patch_rect = scene_rect.adjusted(
                    -LABEL_PATCH_PADDING, -LABEL_PATCH_PADDING,
                    LABEL_PATCH_PADDING, LABEL_PATCH_PADDING
                )

                crosses_a_part = any(
                    obstacle_rect.intersects(scene_rect) and
                    obstacle.intersects(scene_rect)
                    for obstacle, obstacle_rect in zip(
                        obstacles, obstacle_rects
                    )
                )
                overlaps_a_label = any(
                    patch_rect.intersects(placed_rect)
                    for placed_rect in placed_label_rects
                )
                touches_a_dot = text_touches_a_grid_dot(
                    item_rect, component_item.grid_spacing
                )
                score = (
                    crosses_a_part,
                    overlaps_a_label,
                    touches_a_dot,
                    abs(nudge),
                    LABEL_SIDES.index(side),
                )

                if best_score is None or score < best_score:
                    best_score = score
                    best_placement = (side, top_left, patch_rect)

            side, top_left, patch_rect = best_placement
            component_item.apply_label_placement(side, top_left)
            placed_label_rects.append(patch_rect)

    def get_grid_rect(self):
        """
        Return the scene area covered by the grid points.

        :returns: Rectangle around every grid point.
        :rtype: QRectF
        """
        radius = CONNECTION_POINT_DIAMETER / 2.0
        grid_width = (self.connection_grid.column_count - 1) * GRID_POINT_SPACING
        grid_height = (self.connection_grid.row_count - 1) * GRID_POINT_SPACING

        return QRectF(
            GRID_ORIGIN_X - radius,
            GRID_ORIGIN_Y - radius,
            grid_width + CONNECTION_POINT_DIAMETER,
            grid_height + CONNECTION_POINT_DIAMETER
        )

    def get_components_rect(self):
        """
        Return the scene area painted by the parts and their labels.

        :returns: United rectangle; empty when there are no parts.
        :rtype: QRectF
        """
        components_rect = QRectF()

        for component_item in self.component_items_by_reference.values():
            components_rect = components_rect.united(
                component_item.mapRectToScene(component_item.boundingRect())
            )

            label_item = component_item.label_item

            if label_item.isVisible():
                components_rect = components_rect.united(
                    label_item.mapRectToScene(label_item.boundingRect())
                )

        return components_rect

    def update_scene_extent(self):
        """
        Keep the headers clear of the parts and the scene big enough.

        Column headers move up and row headers move left when a part or
        label reaches past the grid edge, so they are never covered. Then
        the sceneRect grows to hold everything plus SCENE_MARGIN, so a view
        can scroll to labels outside the grid. It never shrinks below the
        default rectangle set in rebuild_connection_point_items().

        :returns: None
        """
        content_rect = self.get_grid_rect().united(self.get_components_rect())

        for column_header in self.column_header_items:
            header_height = column_header.boundingRect().height()
            column_header.setY(min(
                HEADER_POSITION,
                content_rect.top() - HEADER_GAP - header_height
            ))

        for row_header in self.row_header_items:
            header_width = row_header.boundingRect().width()
            row_header.setX(min(
                HEADER_POSITION,
                content_rect.left() - HEADER_GAP - header_width
            ))

        grid_width = (self.connection_grid.column_count - 1) * GRID_POINT_SPACING
        grid_height = (self.connection_grid.row_count - 1) * GRID_POINT_SPACING
        default_rect = QRectF(
            0,
            0,
            GRID_ORIGIN_X + grid_width + 100,
            GRID_ORIGIN_Y + grid_height + 100
        )

        scene_rect = default_rect.united(
            self.itemsBoundingRect().adjusted(
                -SCENE_MARGIN, -SCENE_MARGIN, SCENE_MARGIN, SCENE_MARGIN
            )
        )
        self.setSceneRect(scene_rect)

    def refresh_connection_point(self, connection_point_identifier):
        """
        Redraw one point after a model-state change.

        :param connection_point_identifier: Point whose appearance changed.
        :type connection_point_identifier: str
        :returns: None
        """
        connection_point_item = self.connection_point_items_by_identifier.get(
            connection_point_identifier
        )

        if connection_point_item is not None:
            connection_point_item.update()

    def handle_connection_point_selection_change(self):
        """
        Report the selected connection point and selected part.

        Both signals fire on every selection change, with None when nothing
        of that type is selected.

        :returns: None
        """
        selected_connection_point = None
        selected_component = None
        selected_wire_references = [
            selected_item.wire.reference
            for selected_item in self.selectedItems()
            if isinstance(selected_item, WireItem)
        ]

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ConnectionPointItem):
                selected_connection_point = (
                    selected_item.connection_point
                )
                break

        for selected_item in self.selectedItems():
            if isinstance(selected_item, ComponentItem):
                selected_component = selected_item.component
                break

        self.connection_point_selected.emit(selected_connection_point)
        self.component_selected.emit(selected_component)
        self.wires_selected.emit(selected_wire_references)

    def drawBackground(self, painter, rectangle):
        """
        Draw the editor background and visible grid guide lines.

        :param painter: Painter used to draw the scene background.
        :type painter: QPainter
        :param rectangle: Updated portion of the scene.
        :type rectangle: QRectF
        :returns: None
        """
        painter.fillRect(rectangle, QColor("#1f2933"))

        painter.save()
        painter.setPen(QPen(QColor("#334e68"), 1))

        row_count = self.connection_grid.row_count
        column_count = self.connection_grid.column_count

        grid_width = (column_count - 1) * GRID_POINT_SPACING
        grid_height = (row_count - 1) * GRID_POINT_SPACING

        # Draw horizontal guides to show the future wire-routing geometry.
        for row_number in range(row_count):
            y_position = GRID_ORIGIN_Y + (row_number * GRID_POINT_SPACING)

            painter.drawLine(
                GRID_ORIGIN_X,
                y_position,
                GRID_ORIGIN_X + grid_width,
                y_position
            )

        # Draw vertical guides to complete the visual connection-point grid.
        for column_number in range(column_count):
            x_position = (
                GRID_ORIGIN_X +
                (column_number * GRID_POINT_SPACING)
            )

            painter.drawLine(
                x_position,
                GRID_ORIGIN_Y,
                x_position,
                GRID_ORIGIN_Y + grid_height
            )

        painter.restore()


class ConnectionGridView(QGraphicsView):
    """
    Interactive view for the connection-grid scene.

    Ctrl+mouse-wheel zoom is available for large grids. Standard scrollbars
    allow navigation without introducing platform-specific mouse handling.

    :param connection_grid_scene: Scene shown by the view.
    :type connection_grid_scene: ConnectionGridScene
    :param parent: Optional Qt parent object.
    :type parent: QWidget or None
    """

    def __init__(self, connection_grid_scene, parent=None):
        super(ConnectionGridView, self).__init__(
            connection_grid_scene,
            parent
        )

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(self.RubberBandDrag)
        self.setTransformationAnchor(self.AnchorUnderMouse)

    def fit_grid_in_view(self):
        """
        Fit the complete connection grid into the visible editor area.

        :returns: None
        """
        scene_rectangle = self.scene().itemsBoundingRect()

        if not scene_rectangle.isNull():
            self.fitInView(
                scene_rectangle.adjusted(-25, -25, 25, 25),
                Qt.KeepAspectRatio
            )

    def wheelEvent(self, event):
        """
        Zoom when Ctrl is held; otherwise preserve normal scrolling.

        :param event: Mouse-wheel event.
        :type event: QWheelEvent
        :returns: None
        """
        if event.modifiers() & Qt.ControlModifier:
            if event.angleDelta().y() > 0:
                self.scale(1.15, 1.15)
            else:
                self.scale(1.0 / 1.15, 1.0 / 1.15)

            event.accept()
            return

        super(ConnectionGridView, self).wheelEvent(event)